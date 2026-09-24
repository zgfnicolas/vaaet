# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Orquestación de revisión sin depender de widgets ni imprimir diagnósticos."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
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
from vaaet_ml.workflow_state import StaleInferenceExecutionError

# Conserva el canal 4.x para no romper filtros de logs configurados en notebooks.
logger = get_logger("vaaet_ml.data.review")

class ReviewSubmissionStatus(str, Enum):
    """Diferencia una decisión confirmada de una escritura pendiente de auditoría."""

    CONFIRMED = "confirmed"
    AUDIT_PENDING = "audit-pending"


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


ReviewSubmitter = Callable[[HumanValidation], ReviewSubmissionResult]
ReviewGuard = Callable[[], bool]


@dataclass(frozen=True)
class PreparedReview:
    """Plan de revisión que separa la decisión de su presentación en notebook."""

    session: InferenceReviewSession
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

    session = InferenceReviewSession(export_frame=None, validations=[])
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

    persisted = load_human_validation_record(validation_id, settings=settings)
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
    return ReviewSubmissionResult(
        persisted.decision,
        ReviewSubmissionStatus.CONFIRMED,
        persisted.pipeline_run_id,
    )


def _guard_prepared_review(
    prepared: PreparedReview, is_current: ReviewGuard | None
) -> PreparedReview:
    if is_current is None:
        return prepared

    def guarded_submit(decision: HumanValidation) -> ReviewSubmissionResult:
        if not is_current():
            raise StaleInferenceExecutionError(
                "This review action belongs to an earlier inference attempt."
            )
        return prepared.submit(decision)

    return PreparedReview(prepared.session, prepared.queue, guarded_submit)


def _prepare_database_review(
    session: InferenceReviewSession,
    *,
    classified: pd.DataFrame | None,
    settings: DatabaseSettings | Mapping[str, str],
    pipeline_run_id: str,
    mode: str,
) -> PreparedReview:
    if classified is None:
        raise ValueError("Classified telemetry is required when review uses PostgreSQL.")
    full_queue = load_review_queue(settings=settings, pipeline_run_id=pipeline_run_id, mode="all")
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
    session: InferenceReviewSession,
    classified: pd.DataFrame,
    pipeline_run_id: str | None,
    mode: str,
) -> PreparedReview:
    session.export_frame = classified.copy().reset_index(drop=True)
    session.export_frame["prediction_id"] = session.export_frame.index + 1
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


__all__ = [
    "PreparedReview",
    "ReviewGuard",
    "ReviewSubmissionResult",
    "ReviewSubmissionStatus",
    "ReviewSubmitter",
    "prepare_review_session",
    "recover_pending_review_validation",
]
