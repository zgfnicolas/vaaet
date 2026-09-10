# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Acceso PostgreSQL append-only para colas y decisiones de revisión."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from vaaet_persistence.connection import dispose_engine, get_engine, require_database_revision
from vaaet_persistence.exceptions import (
    DatabaseOperationError,
    PersistenceConflictError,
    PersistenceError,
)
from vaaet_persistence.pipeline_runs import PipelineRunMetadata, PipelineWorkflow, pipeline_run
from vaaet_persistence.review_domain import HumanValidation, select_review_queue
from vaaet_persistence.settings import DatabaseSettings

REVIEW_QUEUE_QUERY = """
SELECT prediction_id, pipeline_run_id, clip_id, continuity_id, record_time, traffic_state,
       state_label, confidence, model_version, model_revision, probability_margin,
       decision_abstained, measurement_reliable, accident_rule_triggered,
       accident_alert_started, accident_evidence_score, latest_validation_id,
       current_validated_state, current_reviewer_id, current_reviewed_at,
       validation_conflict
FROM vaaet_feedback.review_queue
WHERE (:pipeline_run_id IS NULL OR pipeline_run_id = CAST(:pipeline_run_id AS UUID))
  AND (
    :after_record_time IS NULL OR
    (record_time, prediction_id) >
      (CAST(:after_record_time AS TIMESTAMPTZ), CAST(:after_prediction_id AS BIGINT))
  )
ORDER BY record_time, prediction_id
LIMIT :page_size
"""

DEFAULT_REVIEW_PAGE_SIZE = 500

INSERT_VALIDATION_QUERY = """
INSERT INTO vaaet_feedback.human_validations (
    id, prediction_id, validated_state, reviewer_id, reviewed_at, notes,
    review_source, incident_context_reviewed, supersedes_validation_id,
    pipeline_run_id
) VALUES (
    :id, :prediction_id, :validated_state, :reviewer_id, :reviewed_at, :notes,
    :review_source, :incident_context_reviewed, :supersedes_validation_id,
    CAST(:pipeline_run_id AS UUID)
)
ON CONFLICT (id) DO NOTHING
RETURNING id, prediction_id, validated_state, reviewer_id, reviewed_at, notes,
          review_source, incident_context_reviewed, supersedes_validation_id,
          pipeline_run_id
"""

SELECT_VALIDATION_QUERY = """
SELECT id, prediction_id, validated_state, reviewer_id, reviewed_at, notes,
       review_source, incident_context_reviewed, supersedes_validation_id,
       pipeline_run_id
FROM vaaet_feedback.human_validations
WHERE id = CAST(:id AS UUID)
"""


@dataclass(frozen=True)
class PersistedHumanValidation:
    """Representa la identidad compartida por PostgreSQL y el paquete portable."""

    decision: HumanValidation
    pipeline_run_id: UUID

    @property
    def validation_id(self) -> UUID:
        return self.decision.validation_id

    @property
    def reviewed_at(self) -> datetime:
        return self.decision.reviewed_at


def load_review_queue(
    *,
    settings: DatabaseSettings | None = None,
    engine: Engine | None = None,
    pipeline_run_id: UUID | str | None = None,
    mode: str = "priority",
) -> pd.DataFrame:
    """Carga una cola read-only y aplica la selección de prioridad en memoria."""

    owns_engine = engine is None
    if engine is not None:
        active_engine = engine
    elif settings is not None:
        active_engine = get_engine(settings)
    else:
        raise ValueError("PostgreSQL reads require explicit settings or an engine.")
    try:
        try:
            with active_engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as connection:
                with connection.begin():
                    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                    frame = _load_queue_pages(connection, pipeline_run_id=pipeline_run_id)
        except SQLAlchemyError as exc:
            raise DatabaseOperationError(
                "PostgreSQL review queue read failed.",
                operation="load-review-queue",
                sqlstate=getattr(getattr(exc, "orig", None), "pgcode", None),
                run_id=str(pipeline_run_id) if pipeline_run_id else None,
            ) from None
    finally:
        if owns_engine:
            dispose_engine(active_engine)
    return select_review_queue(frame, mode=mode)


def _load_queue_pages(
    connection: Connection,
    *,
    pipeline_run_id: UUID | str | None,
) -> pd.DataFrame:
    """Recupera páginas por clave estable dentro de una única fotografía PostgreSQL."""

    pages: list[pd.DataFrame] = []
    after_record_time: object = None
    after_prediction_id: object = None
    while True:
        frame = pd.read_sql(
            text(REVIEW_QUEUE_QUERY),
            connection,
            params=cast(
                Mapping[str, object],
                {
                    "pipeline_run_id": str(pipeline_run_id) if pipeline_run_id else None,
                    "after_record_time": after_record_time,
                    "after_prediction_id": after_prediction_id,
                    "page_size": DEFAULT_REVIEW_PAGE_SIZE,
                },
            ),
        )
        pages.append(frame)
        if len(frame) < DEFAULT_REVIEW_PAGE_SIZE:
            break
        last = frame.iloc[-1]
        after_record_time = last["record_time"]
        after_prediction_id = last["prediction_id"]
    return pd.concat(pages, ignore_index=True) if pages else pd.DataFrame()


def persist_human_validation(
    decision: HumanValidation,
    *,
    settings: DatabaseSettings | None = None,
    engine: Engine | None = None,
    pipeline_run_id: UUID | str | None = None,
    application_name: str | None = None,
    application_version: str | None = None,
) -> UUID:
    """Fachada compatible que devuelve el UUID de una decisión persistida."""

    return persist_human_validation_record(
        decision,
        settings=settings,
        engine=engine,
        pipeline_run_id=pipeline_run_id,
        application_name=application_name,
        application_version=application_version,
    ).validation_id


def persist_human_validation_record(  # noqa: C901 - protege la escritura HITL idempotente.
    decision: HumanValidation,
    *,
    settings: DatabaseSettings | None = None,
    engine: Engine | None = None,
    pipeline_run_id: UUID | str | None = None,
    application_name: str | None = None,
    application_version: str | None = None,
) -> PersistedHumanValidation:
    """Persiste una decisión idempotente y devuelve su identidad completa."""

    if pipeline_run_id is None and (not application_name or not application_version):
        raise ValueError(
            "Automatic pipeline lineage requires application_name and application_version."
        )
    owns_engine = engine is None
    if engine is not None:
        active_engine = engine
    elif settings is not None:
        active_engine = get_engine(settings)
    else:
        raise ValueError("PostgreSQL writes require explicit settings or an engine.")
    if pipeline_run_id is None:
        try:
            metadata = PipelineRunMetadata(
                workflow=PipelineWorkflow.REVIEW,
                application_name=application_name,
                application_version=application_version,
                source_kind=decision.review_source,
                input_rows=1,
                telemetry_schema_version=None,
                feature_schema_version=None,
                model_version=None,
            )
            with pipeline_run(metadata, engine=active_engine) as run:
                persisted = persist_human_validation_record(
                    decision,
                    engine=active_engine,
                    pipeline_run_id=run.id,
                )
                run.set_output_rows(1)
            return persisted
        finally:
            if owns_engine:
                dispose_engine(active_engine)

    try:
        run_uuid = UUID(str(pipeline_run_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("pipeline_run_id must be a UUID.") from exc
    payload = {
        "id": str(decision.validation_id),
        "prediction_id": decision.prediction_id,
        "validated_state": decision.validated_state,
        "reviewer_id": decision.reviewer_id,
        "reviewed_at": decision.reviewed_at,
        "notes": decision.notes,
        "review_source": decision.review_source,
        "incident_context_reviewed": decision.incident_context_reviewed,
        "supersedes_validation_id": (
            str(decision.supersedes_validation_id) if decision.supersedes_validation_id else None
        ),
        "pipeline_run_id": str(run_uuid),
    }
    try:
        with active_engine.begin() as connection:
            require_database_revision(connection)
            inserted = connection.execute(text(INSERT_VALIDATION_QUERY), payload).mappings().one_or_none()
            existing = inserted or connection.execute(
                text(SELECT_VALIDATION_QUERY), {"id": str(decision.validation_id)}
            ).mappings().one()
            _assert_same_validation(existing, payload)
    except PersistenceError:
        raise
    except Exception as exc:
        sqlstate = getattr(getattr(exc, "orig", None), "pgcode", None)
        if sqlstate in {"23505", "23514"}:
            raise PersistenceConflictError(
                "Immutable human validation lineage conflicts with stored history."
            ) from None
        raise DatabaseOperationError(
            "PostgreSQL human validation persistence failed.",
            operation="persist-human-validation",
            sqlstate=sqlstate,
            run_id=str(run_uuid),
        ) from None
    finally:
        if owns_engine:
            dispose_engine(active_engine)
    return PersistedHumanValidation(decision=decision, pipeline_run_id=run_uuid)


def _assert_same_validation(existing: Mapping[str, object], payload: Mapping[str, object]) -> None:
    fields = (
        "prediction_id",
        "validated_state",
        "reviewer_id",
        "notes",
        "review_source",
        "incident_context_reviewed",
        "supersedes_validation_id",
        "pipeline_run_id",
    )
    different = [field for field in fields if str(existing.get(field)) != str(payload.get(field))]
    existing_time = pd.Timestamp(existing.get("reviewed_at"))
    requested_time = pd.Timestamp(payload.get("reviewed_at"))
    if existing_time.tzinfo is None:
        existing_time = existing_time.tz_localize("UTC")
    else:
        existing_time = existing_time.tz_convert("UTC")
    if requested_time.tzinfo is None:
        requested_time = requested_time.tz_localize("UTC")
    else:
        requested_time = requested_time.tz_convert("UTC")
    if existing_time != requested_time:
        different.append("reviewed_at")
    if different:
        raise PersistenceConflictError(
            f"Immutable human validation idempotency conflict in fields: {different}"
        )


__all__ = [
    "DEFAULT_REVIEW_PAGE_SIZE",
    "PersistedHumanValidation",
    "load_review_queue",
    "persist_human_validation",
    "persist_human_validation_record",
]
