# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Orquestación de revisión sin depender de widgets ni imprimir diagnósticos."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import cast
from uuid import UUID

import pandas as pd
from vaaet.logging import get_logger

from vaaet_ml.data.database import DatabaseSettings
from vaaet_ml.data.review_domain import HumanValidation, InferenceReviewSession, select_review_queue
from vaaet_ml.data.review_persistence import (
    PersistedHumanValidation,
    load_human_validation_record,
    load_review_queue,
    persist_human_validation_record,
    reconcile_human_validation,
)
from vaaet_ml.settings import FEATURE_COLS
from vaaet_ml.workflow_state import StaleInferenceExecutionError

# Conserva el canal 4.x para no romper filtros de logs configurados en notebooks.
logger = get_logger("vaaet_ml.data.review")

class ReviewSubmissionStatus(str, Enum):
    """Diferencia una decisión confirmada de una escritura pendiente de auditoría."""

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


@dataclass
class ManagedReviewSession(InferenceReviewSession):
    """Mantiene el intento vigente y decisiones todavía no resueltas."""

    context: ReviewSessionContext | None = None
    unresolved: dict[UUID, HumanValidation] = field(default_factory=dict[UUID, HumanValidation])
    current_guard: ReviewGuard | None = None

    def require_current(self) -> None:
        if self.current_guard is not None and not self.current_guard():
            raise StaleInferenceExecutionError(
                "This review action belongs to an earlier inference attempt."
            )

    def require_finalizable(self) -> None:
        self.require_current()
        if self.unresolved or self.pending_validations:
            raise RuntimeError("Resolve uncertain or pending human decisions before finalization.")


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


@dataclass
class ReviewSubmissionController:
    """Retiene identidad y contenido aun cuando se pierde la respuesta del envío."""

    decision: HumanValidation | None = None
    status: ReviewSubmissionStatus | None = None
    session: ManagedReviewSession | None = None

    def prepare(self, factory: Callable[[], HumanValidation]) -> HumanValidation:
        if self.decision is None:
            self.decision = factory()
            if self.session is not None:
                self.session.unresolved[self.decision.validation_id] = self.decision
        return self.decision

    def submit(
        self, submitter: Callable[[HumanValidation], ReviewSubmissionResult | None]
    ) -> ReviewSubmissionResult | None:
        if self.decision is None:
            raise RuntimeError("Prepare the review decision before submitting it.")
        try:
            result = submitter(self.decision)
        except Exception:
            self.status = ReviewSubmissionStatus.UNKNOWN
            raise
        if result is not None and result.decision != self.decision:
            raise ValueError("Review submission changed the prepared decision content.")
        self.status = (
            ReviewSubmissionStatus.CONFIRMED
            if result is None or result.confirmed
            else ReviewSubmissionStatus.AUDIT_PENDING
        )
        if self.session is not None and self.status is ReviewSubmissionStatus.CONFIRMED:
            self.session.unresolved.pop(self.decision.validation_id, None)
        return result

    def reset(self) -> None:
        if self.decision is not None and self.status is not ReviewSubmissionStatus.CONFIRMED:
            raise RuntimeError("Resolve the current review decision before advancing.")
        self.decision = None
        self.status = None


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
        )
        return _guard_prepared_review(prepared, is_current)
    if classified is None or classified.empty:
        logger.info("Revisión HITL omitida porque no hay minutos clasificados.")
        return PreparedReview(session, pd.DataFrame(), _portable_submitter(session))
    prepared = _prepare_portable_review(session, classified, inference_pipeline_run_id, mode)
    return _guard_prepared_review(prepared, is_current)


def recover_pending_review_validation(
    session: InferenceReviewSession,
    validation_id: UUID | str,
    *,
    settings: DatabaseSettings | Mapping[str, str],
) -> ReviewSubmissionResult:
    """Recupera la misma decisión y actualiza la sesión sin repetir su escritura."""

    if not isinstance(session, ManagedReviewSession):
        raise ValueError("Recovery requires the original managed review session.")
    session.require_current()
    context = session.context
    if context is None or context.origin != "postgresql" or context.inference_pipeline_run_id is None:
        raise ValueError("PostgreSQL recovery requires its original inference session.")
    if (
        session.export_frame is None
        or not context.feature_contracts
        or _session_feature_contracts(session.export_frame) != context.feature_contracts
    ):
        raise ValueError("The review features contradict the original inference session.")
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
    session.require_current()
    if not persisted.audit_complete:
        persisted = reconcile_human_validation(
            persisted.decision,
            pipeline_run_id=persisted.pipeline_run_id,
            settings=settings,
        )
    entry = _persisted_validation_entry(persisted)
    if not persisted.audit_complete:
        _replace_validation_entry(session.pending_validations, entry)
        return ReviewSubmissionResult(
            persisted.decision,
            ReviewSubmissionStatus.AUDIT_PENDING,
            persisted.pipeline_run_id,
            persisted.audit_error_category,
        )
    session.pending_validations[:] = [
        item
        for item in session.pending_validations
        if str(_validation_identity(item)) != str(persisted.decision.validation_id)
    ]
    _replace_validation_entry(session.validations, entry)
    session.unresolved.pop(identifier, None)
    return ReviewSubmissionResult(
        persisted.decision,
        ReviewSubmissionStatus.CONFIRMED,
        persisted.pipeline_run_id,
    )


def _guard_prepared_review(
    prepared: PreparedReview, is_current: ReviewGuard | None
) -> PreparedReview:
    def guarded_submit(decision: HumanValidation) -> ReviewSubmissionResult:
        if is_current is not None and not is_current():
            raise StaleInferenceExecutionError(
                "This review action belongs to an earlier inference attempt."
            )
        prepared.session.unresolved[decision.validation_id] = decision
        result = prepared.submit(decision)
        if result.confirmed:
            prepared.session.unresolved.pop(decision.validation_id, None)
        return result

    return PreparedReview(prepared.session, prepared.queue, guarded_submit)


def _prepare_database_review(
    session: ManagedReviewSession,
    *,
    classified: pd.DataFrame | None,
    settings: DatabaseSettings | Mapping[str, str],
    pipeline_run_id: str,
    mode: str,
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
    session.context = _review_context(
        "postgresql", pipeline_run_id, full_queue, export_frame=session.export_frame
    )

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
) -> PreparedReview:
    session.export_frame = classified.copy().reset_index(drop=True)
    session.export_frame["prediction_id"] = session.export_frame.index + 1
    session.context = _review_context("portable", pipeline_run_id, session.export_frame)
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


def _review_context(
    origin: str,
    run_id: str | None,
    frame: pd.DataFrame,
    *,
    export_frame: pd.DataFrame | None = None,
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
            _session_feature_contracts(export_frame) if export_frame is not None else ()
        ),
    )


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
