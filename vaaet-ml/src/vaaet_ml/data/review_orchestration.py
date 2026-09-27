# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Orquestación de revisión sin depender de widgets ni imprimir diagnósticos."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from numbers import Integral
from typing import cast
from uuid import UUID

import pandas as pd
from vaaet.logging import get_logger

from vaaet_ml.data.artifact_serialization import (
    canonical_contract_value,
    typed_frames_fingerprint,
)
from vaaet_ml.data.database import DatabaseSettings
from vaaet_ml.data.review_domain import HumanValidation, InferenceReviewSession, select_review_queue
from vaaet_ml.data.review_persistence import (
    PersistedHumanValidation,
    load_human_validation_record,
    load_review_queue,
    persist_human_validation_record,
    reconcile_human_validation,
)
from vaaet_ml.exceptions import ReviewSessionIntegrityError
from vaaet_ml.settings import FEATURE_COLS
from vaaet_ml.workflow_state import StaleInferenceExecutionError

# Conserva el canal 4.x para no romper filtros de logs configurados en notebooks.
logger = get_logger("vaaet_ml.data.review")

class ReviewSubmissionStatus(str, Enum):
    """Diferencia una decisión confirmada de una escritura pendiente de auditoría."""

    PREPARED = "prepared"
    SENDING = "sending"
    CONFIRMED = "confirmed"
    AUDIT_PENDING = "audit-pending"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ReviewSessionContext:
    """Fija la procedencia y las observaciones revisables de una sesión."""

    origin: str
    inference_pipeline_run_id: str | None
    model_revision: str | None
    observations: tuple[tuple[object, ...], ...]
    feature_contracts: tuple[tuple[object, ...], ...] = ()
    export_fingerprint: str | None = None
    model_version: str | None = None
    attempt_id: UUID | None = None


@dataclass
class ManagedReviewSession(InferenceReviewSession):
    """Mantiene el intento vigente y decisiones todavía no resueltas."""

    context: ReviewSessionContext | None = None
    unresolved: dict[UUID, HumanValidation] = field(default_factory=dict[UUID, HumanValidation])
    current_guard: ReviewGuard | None = None
    submissions: dict[UUID, ReviewSubmissionResult] = field(default_factory=dict)
    integrity_invalidated: bool = False
    _sealed_context: ReviewSessionContext | None = field(default=None, init=False, repr=False)
    _listeners: list[Callable[[ReviewSubmissionResult], None]] = field(
        default_factory=list, repr=False
    )

    def __post_init__(self) -> None:
        if (
            self.context is not None
            and self.context.export_fingerprint is None
            and self.export_frame is not None
        ):
            self.context = replace(
                self.context,
                export_fingerprint=typed_frames_fingerprint({"export": self.export_frame}),
            )
        self._sealed_context = self.context

    def seal_context(self, context: ReviewSessionContext) -> None:
        """Fija una sola fotografía de procedencia al preparar la sesión."""

        if self._sealed_context is not None:
            raise ReviewSessionIntegrityError("The review session context is already sealed.")
        self.context = context
        self._sealed_context = context

    def require_current(self) -> None:
        if self.current_guard is not None and not self.current_guard():
            raise StaleInferenceExecutionError(
                "This review action belongs to an earlier inference attempt."
            )

    def require_integrity(self) -> None:
        """Bloquea definitivamente una sesión cuyo frame exportable fue alterado."""

        self.require_current()
        if self.integrity_invalidated:
            raise ReviewSessionIntegrityError(
                "The review session changed; prepare a new session before continuing."
            )
        context = self.context
        if context is None:
            if self._sealed_context is not None:
                self.integrity_invalidated = True
                raise ReviewSessionIntegrityError(
                    "The review session changed; prepare a new session before continuing."
                )
            return
        if context is not self._sealed_context:
            self.integrity_invalidated = True
            raise ReviewSessionIntegrityError(
                "The review session changed; prepare a new session before continuing."
            )
        frame = self.export_frame
        try:
            consistent = frame is not None and (
                (context.export_fingerprint is None or
                 typed_frames_fingerprint({"export": frame}) == context.export_fingerprint)
                and (not context.feature_contracts or
                     _session_feature_contracts(frame) == context.feature_contracts)
            )
        except (TypeError, ValueError, KeyError, OverflowError, AttributeError):
            consistent = False
        if not consistent:
            self.integrity_invalidated = True
            raise ReviewSessionIntegrityError(
                "The review session changed; prepare a new session before continuing."
            )

    def record_submission(self, result: ReviewSubmissionResult) -> None:
        """Publica un único estado de decisión para formulario y recuperación."""

        existing = self.submissions.get(result.decision.validation_id)
        if existing is not None and existing.decision != result.decision:
            raise ValueError("The review decision changed under its immutable UUID.")
        if existing is not None and existing.confirmed and not result.confirmed:
            return
        if existing == result:
            return
        self.submissions[result.decision.validation_id] = result
        if result.confirmed:
            self.unresolved.pop(result.decision.validation_id, None)
        else:
            self.unresolved[result.decision.validation_id] = result.decision
        for listener in tuple(self._listeners):
            try:
                listener(result)
            except Exception:
                logger.warning("Review presentation update failed after authoritative state change.")

    def subscribe(self, listener: Callable[[ReviewSubmissionResult], None]) -> Callable[[], None]:
        """Notifica cambios locales sin permitir que la UI gobierne la decisión."""

        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def detach_presentations(self) -> None:
        """Desvincula widgets anteriores sin modificar decisiones confirmadas."""

        self._listeners.clear()

    def require_finalizable(self) -> None:
        self.require_integrity()
        if self.unresolved or self.pending_validations:
            raise RuntimeError("Resolve uncertain or pending human decisions before finalization.")
        if self.context is not None:
            confirmed = {
                identifier: result.decision
                for identifier, result in self.submissions.items() if result.confirmed
            }
            actual = {_validation_identity(entry): entry for entry in self.validations}
            if set(actual) != set(confirmed) or len(actual) != len(self.validations):
                raise ReviewSessionIntegrityError(
                    "The review decisions changed; prepare a new session before finalization."
                )
            if any(
                _decision_contract(actual[identifier]) != _decision_contract(decision)
                for identifier, decision in confirmed.items()
            ):
                raise ReviewSessionIntegrityError(
                    "The review decisions changed; prepare a new session before finalization."
                )


@dataclass(frozen=True)
class ReviewSubmissionResult:
    """Resultado visible del envío de una decisión humana inmutable."""

    decision: HumanValidation
    status: ReviewSubmissionStatus
    pipeline_run_id: UUID | None = None
    audit_error_category: str | None = None

    @property
    def confirmed(self) -> bool:
        return self.status is ReviewSubmissionStatus.CONFIRMED


class ReviewSubmissionController:
    """Retiene identidad y contenido aun cuando se pierde la respuesta del envío."""

    def __init__(
        self,
        decision: HumanValidation | None = None,
        status: ReviewSubmissionStatus | None = None,
        session: ManagedReviewSession | None = None,
    ) -> None:
        self.decision = decision
        self._status = status
        self.session = session
        if decision is not None and session is not None:
            session.require_integrity()
            session.record_submission(
                ReviewSubmissionResult(decision, status or ReviewSubmissionStatus.PREPARED)
            )

    @property
    def status(self) -> ReviewSubmissionStatus | None:
        if self.decision is not None and self.session is not None:
            result = self.session.submissions.get(self.decision.validation_id)
            if result is not None:
                return result.status
        return self._status

    def prepare(self, factory: Callable[[], HumanValidation]) -> HumanValidation:
        if self.session is not None:
            self.session.require_integrity()
        if self.decision is None:
            self.decision = factory()
            if self.session is not None:
                self.session.record_submission(
                    ReviewSubmissionResult(self.decision, ReviewSubmissionStatus.PREPARED)
                )
        return self.decision

    def submit(
        self, submitter: Callable[[HumanValidation], ReviewSubmissionResult | None]
    ) -> ReviewSubmissionResult | None:
        if self.decision is None:
            raise RuntimeError("Prepare the review decision before submitting it.")
        if self.session is not None:
            self.session.require_integrity()
            previous = self.session.submissions.get(self.decision.validation_id)
            if previous is not None and previous.confirmed:
                return previous
            self.session.record_submission(
                ReviewSubmissionResult(self.decision, ReviewSubmissionStatus.SENDING)
            )
        try:
            result = submitter(self.decision)
        except Exception:
            self._status = ReviewSubmissionStatus.UNKNOWN
            if self.session is not None:
                self.session.record_submission(
                    ReviewSubmissionResult(self.decision, ReviewSubmissionStatus.UNKNOWN)
                )
            raise
        if result is not None and result.decision != self.decision:
            raise ValueError("Review submission changed the prepared decision content.")
        self._status = (
            ReviewSubmissionStatus.CONFIRMED
            if result is None or result.confirmed
            else ReviewSubmissionStatus.AUDIT_PENDING
        )
        if self.session is not None:
            self.session.record_submission(
                result or ReviewSubmissionResult(self.decision, self._status)
            )
        return result

    def reset(self) -> None:
        if self.decision is not None and self.status is not ReviewSubmissionStatus.CONFIRMED:
            raise RuntimeError("Resolve the current review decision before advancing.")
        self.decision = None
        self._status = None


ReviewSubmitter = Callable[[HumanValidation], ReviewSubmissionResult]
ReviewGuard = Callable[[], bool]


@dataclass(frozen=True)
class PreparedReview:
    """Plan de revisión que separa la decisión de su presentación en notebook."""

    session: ManagedReviewSession
    queue: pd.DataFrame
    submit: ReviewSubmitter


def prepare_review_session(
    *,
    enabled: bool,
    classified: pd.DataFrame | None,
    inference_pipeline_run_id: str | None,
    reviewer_id: str | None,
    settings: DatabaseSettings | Mapping[str, str] | None,
    mode: str,
    is_current: ReviewGuard | None = None,
    attempt_id: UUID | None = None,
) -> PreparedReview:
    """Prepara selección y persistencia opt-in sin crear UI ni modificar notebooks."""

    session = ManagedReviewSession(export_frame=None, validations=[], current_guard=is_current)
    if not enabled:
        logger.info("Revisión humana desactivada; activala explícitamente para el próximo video.")
        return PreparedReview(session, pd.DataFrame(), _portable_submitter(session))
    if reviewer_id is None:
        raise ValueError("A stable reviewer identifier is required for human review.")
    if settings is not None and inference_pipeline_run_id is not None:
        prepared = _prepare_database_review(
            session,
            classified=classified,
            settings=settings,
            pipeline_run_id=inference_pipeline_run_id,
            mode=mode,
            attempt_id=attempt_id,
        )
        return _guard_prepared_review(prepared)
    if classified is None or classified.empty:
        logger.info("Revisión HITL omitida porque no hay minutos clasificados.")
        return PreparedReview(session, pd.DataFrame(), _portable_submitter(session))
    prepared = _prepare_portable_review(
        session, classified, inference_pipeline_run_id, mode, attempt_id=attempt_id
    )
    return _guard_prepared_review(prepared)


def recover_pending_review_validation(
    session: InferenceReviewSession,
    validation_id: UUID | str,
    *,
    settings: DatabaseSettings | Mapping[str, str],
) -> ReviewSubmissionResult:
    """Recupera la misma decisión y actualiza la sesión sin repetir su escritura."""

    if not isinstance(session, ManagedReviewSession):
        raise ValueError("Recovery requires the original managed review session.")
    session.require_integrity()
    context = session.context
    if context is None or context.origin != "postgresql" or context.inference_pipeline_run_id is None:
        raise ValueError("PostgreSQL recovery requires its original inference session.")
    identifier = UUID(str(validation_id))
    persisted = load_human_validation_record(identifier, settings=settings)
    prepared = session.unresolved.get(identifier)
    if prepared is not None and prepared != persisted.decision:
        raise ValueError("The stored decision contradicts the prepared review decision.")
    binding = next(
        (item for item in context.observations if item[0] == persisted.decision.prediction_id),
        None,
    )
    if binding is None:
        raise ValueError("The stored decision belongs to a different prediction.")
    stored_context = persisted.prediction_context
    if stored_context is None or (
        stored_context.prediction_id,
        stored_context.clip_id,
        pd.Timestamp(stored_context.record_time).tz_convert("UTC").isoformat(),
        stored_context.continuity_id,
        stored_context.model_revision,
        str(stored_context.pipeline_run_id),
        str(stored_context.operational_feature_id),
    ) != binding:
        raise ValueError("The stored decision contradicts the original prediction context.")
    current = load_review_queue(
        settings=settings, pipeline_run_id=context.inference_pipeline_run_id, mode="all"
    )
    matched = current.loc[current["prediction_id"].eq(persisted.decision.prediction_id)]
    if len(matched) != 1 or _observation_key(matched.iloc[0]) != binding:
        raise ValueError("The stored prediction contradicts the original review session.")
    session.require_integrity()
    if not persisted.audit_complete:
        persisted = reconcile_human_validation(
            persisted.decision,
            pipeline_run_id=persisted.pipeline_run_id,
            settings=settings,
        )
    entry = _persisted_validation_entry(persisted)
    if not persisted.audit_complete:
        _replace_validation_entry(session.pending_validations, entry)
        result = ReviewSubmissionResult(
            persisted.decision,
            ReviewSubmissionStatus.AUDIT_PENDING,
            persisted.pipeline_run_id,
            persisted.audit_error_category,
        )
        session.record_submission(result)
        return result
    session.pending_validations[:] = [
        item
        for item in session.pending_validations
        if str(_validation_identity(item)) != str(persisted.decision.validation_id)
    ]
    _replace_validation_entry(session.validations, entry)
    session.unresolved.pop(identifier, None)
    result = ReviewSubmissionResult(
        persisted.decision,
        ReviewSubmissionStatus.CONFIRMED,
        persisted.pipeline_run_id,
    )
    session.record_submission(result)
    return result


def _guard_prepared_review(prepared: PreparedReview) -> PreparedReview:
    def guarded_submit(decision: HumanValidation) -> ReviewSubmissionResult:
        prepared.session.require_integrity()
        prior = prepared.session.submissions.get(decision.validation_id)
        if prior is not None and prior.confirmed:
            if prior.decision != decision:
                raise ValueError("The review decision changed under its immutable UUID.")
            return prior
        prepared.session.unresolved[decision.validation_id] = decision
        result = prepared.submit(decision)
        prepared.session.record_submission(result)
        return result

    return PreparedReview(prepared.session, prepared.queue, guarded_submit)


def _prepare_database_review(
    session: ManagedReviewSession,
    *,
    classified: pd.DataFrame | None,
    settings: DatabaseSettings | Mapping[str, str],
    pipeline_run_id: str,
    mode: str,
    attempt_id: UUID | None,
) -> PreparedReview:
    if classified is None:
        raise ValueError("Classified telemetry is required when review uses PostgreSQL.")
    full_queue = load_review_queue(settings=settings, pipeline_run_id=pipeline_run_id, mode="all")
    _check_queue_parity(classified, full_queue)
    queue = select_review_queue(full_queue, mode=mode)
    prediction_keys = full_queue[["clip_id", "record_time", "prediction_id"]].copy()
    prediction_keys["record_time"] = pd.to_datetime(prediction_keys["record_time"], utc=True)
    session.export_frame = classified.copy()
    session.export_frame["record_time"] = pd.to_datetime(
        session.export_frame["record_time"], utc=True
    )
    session.export_frame = session.export_frame.merge(
        prediction_keys,
        on=["clip_id", "record_time"],
        how="left",
        validate="one_to_one",
    )
    if session.export_frame["prediction_id"].isna().any():
        raise RuntimeError("La cola de revisión PostgreSQL no cubre todas las filas inferidas.")
    session.seal_context(_review_context(
        "postgresql", pipeline_run_id, full_queue,
        export_frame=session.export_frame, attempt_id=attempt_id,
    ))

    pending_by_id: dict[UUID, PersistedHumanValidation] = {}

    def persist_and_accumulate(decision: HumanValidation) -> ReviewSubmissionResult:
        pending = pending_by_id.get(decision.validation_id)
        if pending is None:
            persisted = persist_human_validation_record(decision, settings=settings)
        else:
            persisted = reconcile_human_validation(
                decision,
                pipeline_run_id=pending.pipeline_run_id,
                settings=settings,
            )
        entry = _persisted_validation_entry(persisted)
        if not persisted.audit_complete:
            pending_by_id[decision.validation_id] = persisted
            _replace_validation_entry(session.pending_validations, entry)
            return ReviewSubmissionResult(
                persisted.decision,
                ReviewSubmissionStatus.AUDIT_PENDING,
                persisted.pipeline_run_id,
                persisted.audit_error_category,
            )
        pending_by_id.pop(decision.validation_id, None)
        session.pending_validations[:] = [
            item
            for item in session.pending_validations
            if str(_validation_identity(item)) != str(decision.validation_id)
        ]
        _replace_validation_entry(session.validations, entry)
        return ReviewSubmissionResult(
            persisted.decision,
            ReviewSubmissionStatus.CONFIRMED,
            persisted.pipeline_run_id,
        )

    logger.info(
        "PostgreSQL review queue prepared: selected_rows=%s total_rows=%s mode=%s",
        len(queue),
        len(full_queue),
        mode,
    )
    return PreparedReview(session, queue, persist_and_accumulate)


def _prepare_portable_review(
    session: ManagedReviewSession,
    classified: pd.DataFrame,
    pipeline_run_id: str | None,
    mode: str,
    *,
    attempt_id: UUID | None,
) -> PreparedReview:
    session.export_frame = classified.copy().reset_index(drop=True)
    session.export_frame["prediction_id"] = session.export_frame.index + 1
    session.seal_context(_review_context(
        "portable", pipeline_run_id, session.export_frame,
        export_frame=session.export_frame, attempt_id=attempt_id,
    ))
    queue = select_review_queue(session.export_frame, mode=mode)
    reason = (
        "inference was not persisted"
        if pipeline_run_id is None
        else "review profile is unavailable"
    )
    logger.info(
        "Portable review prepared: reason=%s selected_rows=%s total_rows=%s mode=%s",
        reason,
        len(queue),
        len(session.export_frame),
        mode,
    )
    return PreparedReview(session, queue, _portable_submitter(session))


def _portable_submitter(session: InferenceReviewSession) -> ReviewSubmitter:
    def submit(decision: HumanValidation) -> ReviewSubmissionResult:
        _replace_validation_entry(session.validations, decision)
        return ReviewSubmissionResult(decision, ReviewSubmissionStatus.CONFIRMED)

    return submit


def _persisted_validation_entry(persisted: PersistedHumanValidation) -> dict[str, object]:
    return {
        **asdict(persisted.decision),
        "pipeline_run_id": str(persisted.pipeline_run_id),
        "audit_complete": persisted.audit_complete,
        "review_audit_origin": "postgresql",
        "persistence_receipt_fingerprint": (
            persisted.receipt.content_fingerprint if persisted.receipt is not None else None
        ),
    }


def _replace_validation_entry(
    items: list[HumanValidation | Mapping[str, object]],
    item: HumanValidation | Mapping[str, object],
) -> None:
    identity = _validation_identity(item)
    items[:] = [existing for existing in items if _validation_identity(existing) != identity]
    items.append(item)


def _validation_identity(value: object) -> object:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value).get("validation_id")
    return getattr(value, "validation_id", None)


def _decision_contract(value: HumanValidation | Mapping[str, object]) -> tuple[object, ...]:
    fields = asdict(value) if isinstance(value, HumanValidation) else value
    columns = (
        "validation_id", "prediction_id", "validated_state", "reviewer_id",
        "notes", "incident_context_reviewed", "supersedes_validation_id",
        "reviewed_at", "review_source",
    )
    return tuple(_decision_field_value(column, fields.get(column)) for column in columns)


def _decision_field_value(column: str, value: object) -> object:
    if column in {"validation_id", "supersedes_validation_id"} and value is not None:
        return UUID(str(value))
    if (
        column in {"prediction_id", "validated_state"}
        and type(value) is not bool
        and isinstance(value, Integral)
    ):
        return ("integer", int(value))
    return canonical_contract_value(column, value)


def _review_context(
    origin: str,
    run_id: str | None,
    frame: pd.DataFrame,
    *,
    export_frame: pd.DataFrame | None = None,
    attempt_id: UUID | None = None,
) -> ReviewSessionContext:
    revisions = frame.get("model_revision", pd.Series(dtype=str)).dropna().astype(str).unique()
    revision = str(revisions[0]) if len(revisions) == 1 else None
    required = {"prediction_id", "clip_id", "record_time"}
    observations = (
        tuple(_observation_key(row) for _, row in frame.iterrows())
        if required.issubset(frame.columns)
        else ()
    )
    if len({item[0] for item in observations}) != len(observations):
        raise ValueError("The review queue repeats a prediction identity.")
    return ReviewSessionContext(
        origin=origin,
        inference_pipeline_run_id=run_id,
        model_revision=revision,
        observations=observations,
        feature_contracts=(
            _session_feature_contracts(export_frame)
            if export_frame is not None
            and {"prediction_id", "feature_schema_version", *FEATURE_COLS}.issubset(export_frame.columns)
            else ()
        ),
        export_fingerprint=(
            typed_frames_fingerprint({"export": export_frame})
            if export_frame is not None else None
        ),
        model_version=(
            _single_model_version(export_frame) if export_frame is not None else None
        ),
        attempt_id=attempt_id,
    )


def _single_model_version(frame: pd.DataFrame) -> str | None:
    if "model_version" not in frame or frame.empty:
        return None
    versions = frame["model_version"].dropna().astype(str).unique()
    if len(versions) != 1:
        raise ValueError("The review session must refer to one model version.")
    return str(versions[0])


def _session_feature_contracts(frame: pd.DataFrame) -> tuple[tuple[object, ...], ...]:
    """Fija schema y 19 valores de cada predicción, sin depender del orden de filas."""

    required = {"prediction_id", "feature_schema_version", *FEATURE_COLS}
    if not required.issubset(frame.columns):
        raise ValueError("The original review frame lacks contractual features.")
    contracts = tuple(
        sorted(
            (
                int(row["prediction_id"]),
                str(row["feature_schema_version"]),
                *(float(row[feature]) for feature in FEATURE_COLS),
            )
            for _, row in frame.iterrows()
        )
    )
    if len({contract[0] for contract in contracts}) != len(contracts):
        raise ValueError("The original review frame repeats a prediction identity.")
    return contracts


def _check_queue_parity(classified: pd.DataFrame, queue: pd.DataFrame) -> None:
    """Impide asociar una predicción DB a otro contexto ya clasificado."""

    common = [column for column in ("continuity_id", "model_revision") if column in classified and column in queue]
    if not common or classified.empty:
        return
    keys = ["clip_id", "record_time"]
    expected = classified[[*keys, *common]].copy()
    actual = queue[[*keys, *common]].copy()
    for frame in (expected, actual):
        frame["record_time"] = pd.to_datetime(frame["record_time"], utc=True)
    joined = expected.merge(actual, on=keys, how="left", validate="one_to_one", suffixes=("", "_db"))
    for column in common:
        if joined[f"{column}_db"].isna().any() or not joined[column].astype(str).eq(joined[f"{column}_db"].astype(str)).all():
            raise ValueError(f"PostgreSQL review queue contradicts classified {column}.")


def _observation_key(row: pd.Series) -> tuple[object, ...]:
    timestamp = pd.Timestamp(row["record_time"])
    if timestamp.tzinfo is None:
        raise ValueError("Review observation timestamps must be timezone-aware.")
    return (
        int(row["prediction_id"]),
        str(row["clip_id"]),
        timestamp.tz_convert("UTC").isoformat(),
        str(row.get("continuity_id", "")),
        str(row.get("model_revision", "")),
        str(row.get("pipeline_run_id", "")),
        str(row.get("operational_feature_id", "")),
    )


__all__ = [
    "PreparedReview",
    "ReviewGuard",
    "ReviewSubmissionResult",
    "ReviewSubmissionController",
    "ReviewSubmissionStatus",
    "ReviewSubmitter",
    "prepare_review_session",
    "recover_pending_review_validation",
]
