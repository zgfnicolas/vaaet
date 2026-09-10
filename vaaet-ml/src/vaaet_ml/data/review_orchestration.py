# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Orquestación de revisión sin depender de widgets ni imprimir diagnósticos."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass

import pandas as pd
from vaaet.logging import get_logger

from vaaet_ml.data.database import DatabaseSettings
from vaaet_ml.data.review_domain import HumanValidation, InferenceReviewSession, select_review_queue
from vaaet_ml.data.review_persistence import (
    load_review_queue,
    persist_human_validation_record,
)

# Conserva el canal 4.x para no romper filtros de logs configurados en notebooks.
logger = get_logger("vaaet_ml.data.review")
ReviewSubmitter = Callable[[HumanValidation], None]


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
) -> PreparedReview:
    """Prepara selección y persistencia opt-in sin crear UI ni modificar notebooks."""

    session = InferenceReviewSession(export_frame=None, validations=[])
    if not enabled:
        logger.info("Revisión humana desactivada; activala explícitamente para el próximo video.")
        return PreparedReview(session, pd.DataFrame(), session.validations.append)
    if reviewer_id is None:
        raise ValueError("A stable reviewer identifier is required for human review.")
    if settings is not None and inference_pipeline_run_id is not None:
        return _prepare_database_review(
            session,
            classified=classified,
            settings=settings,
            pipeline_run_id=inference_pipeline_run_id,
            mode=mode,
        )
    if classified is None or classified.empty:
        logger.info("Revisión HITL omitida porque no hay minutos clasificados.")
        return PreparedReview(session, pd.DataFrame(), session.validations.append)
    return _prepare_portable_review(session, classified, inference_pipeline_run_id, mode)


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
    session.export_frame["record_time"] = pd.to_datetime(session.export_frame["record_time"], utc=True)
    session.export_frame = session.export_frame.merge(
        prediction_keys,
        on=["clip_id", "record_time"],
        how="left",
        validate="one_to_one",
    )
    if session.export_frame["prediction_id"].isna().any():
        raise RuntimeError("La cola de revisión PostgreSQL no cubre todas las filas inferidas.")

    def persist_and_accumulate(decision: HumanValidation) -> None:
        persisted = persist_human_validation_record(decision, settings=settings)
        session.validations.append(
            {
                **asdict(persisted.decision),
                "pipeline_run_id": str(persisted.pipeline_run_id),
            }
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
    reason = "inference was not persisted" if pipeline_run_id is None else "review profile is unavailable"
    logger.info(
        "Portable review prepared: reason=%s selected_rows=%s total_rows=%s mode=%s",
        reason,
        len(queue),
        len(session.export_frame),
        mode,
    )
    return PreparedReview(session, queue, session.validations.append)


__all__ = ["PreparedReview", "ReviewSubmitter", "prepare_review_session"]
