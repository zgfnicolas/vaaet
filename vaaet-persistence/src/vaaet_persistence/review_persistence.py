# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Acceso PostgreSQL append-only para colas y decisiones de revisión."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from vaaet.logging import get_logger

from vaaet_persistence.connection import dispose_engine, get_engine, require_database_revision
from vaaet_persistence.exceptions import (
    DatabaseOperationError,
    PersistenceConflictError,
    PersistenceError,
    PipelineAuditIncompleteError,
    safe_sqlstate,
)
from vaaet_persistence.pipeline_runs import (
    PipelineRunMetadata,
    PipelineWorkflow,
    complete_reconciled_pipeline_run,
    pipeline_run,
)
from vaaet_persistence.receipts import (
    PersistenceReceipt,
    build_persistence_receipt,
    read_pipeline_run_audit_state,
    receipts_match,
    record_persistence_receipt,
)
from vaaet_persistence.review_domain import HumanValidation, select_review_queue
from vaaet_persistence.settings import DatabaseSettings

logger = get_logger(__name__)

REVIEW_QUEUE_QUERY = """
SELECT q.prediction_id, q.pipeline_run_id, q.clip_id, q.continuity_id, q.record_time, q.traffic_state,
       state_label, confidence, model_version, model_revision, probability_margin,
       decision_abstained, measurement_reliable, accident_rule_triggered,
       accident_alert_started, accident_evidence_score, latest_validation_id,
       current_validated_state, current_reviewer_id, current_reviewed_at,
       validation_conflict,
       (SELECT c.telemetry_id FROM public.traffic_classifications c
        WHERE c.id = q.prediction_id) AS operational_feature_id
FROM vaaet_feedback.review_queue q
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

SELECT_PREDICTION_CONTEXT_QUERY = """
SELECT q.prediction_id, q.pipeline_run_id, q.clip_id, q.continuity_id,
       q.record_time, q.model_revision, c.telemetry_id AS operational_feature_id
FROM vaaet_feedback.review_queue q
JOIN public.traffic_classifications c ON c.id = q.prediction_id
WHERE q.prediction_id = :prediction_id
"""

LOCK_VALIDATION_ID_QUERY = """
SELECT pg_advisory_xact_lock(hashtextextended(CAST(:id AS TEXT), 0))
"""


@dataclass(frozen=True)
class PersistedPredictionContext:
    """Identifica la observación PostgreSQL de una decisión recuperada."""

    prediction_id: int
    pipeline_run_id: UUID
    clip_id: str
    record_time: datetime
    continuity_id: str
    model_revision: str
    operational_feature_id: int


@dataclass(frozen=True)
class PersistedHumanValidation:
    """Representa la identidad compartida por PostgreSQL y el paquete portable."""

    decision: HumanValidation
    pipeline_run_id: UUID
    audit_complete: bool = True
    audit_error_category: str | None = None
    receipt: PersistenceReceipt | None = None
    prediction_context: PersistedPredictionContext | None = None

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
                sqlstate=safe_sqlstate(exc),
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

    persisted = persist_human_validation_record(
        decision,
        settings=settings,
        engine=engine,
        pipeline_run_id=pipeline_run_id,
        application_name=application_name,
        application_version=application_version,
    )
    if not persisted.audit_complete:
        raise PipelineAuditIncompleteError(
            "The human validation was stored, but its pipeline audit is incomplete.",
            confirmed_result=persisted.validation_id,
            run_id=str(persisted.pipeline_run_id),
            audit_error_category=persisted.audit_error_category,
        )
    return persisted.validation_id


def load_human_validation_record(
    validation_id: UUID | str,
    *,
    settings: DatabaseSettings | None = None,
    engine: Engine | None = None,
) -> PersistedHumanValidation:
    """Recupera una decisión y su auditoría real para reanudar un runtime."""

    try:
        identifier = UUID(str(validation_id))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("validation_id must be a UUID.") from None
    owns_engine = engine is None
    if engine is not None:
        active_engine = engine
    elif settings is not None:
        active_engine = get_engine(settings)
    else:
        raise ValueError("PostgreSQL reads require explicit settings or an engine.")
    try:
        existing = _load_existing_validation(active_engine, identifier)
        if existing is None:
            raise PersistenceConflictError("The human validation does not exist.")
        run_id = UUID(str(existing["pipeline_run_id"]))
        state = _load_audit_state(active_engine, run_id)
        prediction_context = _load_prediction_context(
            active_engine, int(existing["prediction_id"])
        )
        return PersistedHumanValidation(
            decision=_stored_decision(existing),
            pipeline_run_id=run_id,
            audit_complete=state.audit_complete,
            audit_error_category=(
                None if state.audit_complete else "PipelineAuditIncomplete"
            ),
            receipt=state.receipt,
            prediction_context=prediction_context,
        )
    finally:
        if owns_engine:
            dispose_engine(active_engine)


def reconcile_human_validation(  # noqa: C901 - protege verificación y recursos del borde público.
    decision: HumanValidation,
    *,
    pipeline_run_id: UUID | str,
    settings: DatabaseSettings | None = None,
    engine: Engine | None = None,
) -> PersistedHumanValidation:
    """Verifica una decisión almacenada y completa únicamente su auditoría pendiente."""

    try:
        run_uuid = UUID(str(pipeline_run_id))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("pipeline_run_id must be a UUID.") from None
    owns_engine = engine is None
    try:
        if engine is not None:
            active_engine = engine
        elif settings is not None:
            active_engine = get_engine(settings)
        else:
            raise ValueError("PostgreSQL reconciliation requires explicit settings or an engine.")
    except (PersistenceError, ValueError):
        raise
    except Exception as exc:
        raise DatabaseOperationError(
            "PostgreSQL human validation reconciliation failed.",
            operation="reconcile-human-validation",
            sqlstate=safe_sqlstate(exc),
            run_id=str(run_uuid),
        ) from None
    try:
        with active_engine.begin() as connection:
            require_database_revision(connection)
            existing = (
                connection.execute(
                    text(SELECT_VALIDATION_QUERY), {"id": str(decision.validation_id)}
                )
                .mappings()
                .one_or_none()
            )
            if existing is None:
                raise PersistenceConflictError(
                    "The human validation cannot be reconciled because it is not stored."
                )
            payload = _validation_payload(decision, run_uuid)
            _assert_same_validation(existing, payload)
            state = read_pipeline_run_audit_state(connection, run_uuid)
            expected_receipt = build_persistence_receipt(
                pipeline_run_id=run_uuid,
                operation="human-validation",
                observations=[payload],
                processed_counts={"human_validations": 1},
                inserted_counts={"human_validations": 0},
            )
            if (
                state.workflow != PipelineWorkflow.REVIEW.value
                or state.input_rows != 1
                or state.receipt is None
                or not receipts_match(
                    state.receipt,
                    expected_receipt,
                    include_inserted_counts=False,
                )
            ):
                raise PersistenceConflictError(
                    "The human validation does not match its immutable persistence receipt."
                )
            outcome = complete_reconciled_pipeline_run(
                run_id=run_uuid,
                output_rows=1,
                engine=active_engine,
                connection=connection,
                workflow=PipelineWorkflow.REVIEW,
                application_version="0.3.2",
                operation=expected_receipt.operation,
                content_fingerprint=expected_receipt.content_fingerprint,
            )
        return PersistedHumanValidation(
            decision=_stored_decision(existing),
            pipeline_run_id=run_uuid,
            audit_complete=outcome.audit_complete,
            audit_error_category=outcome.audit_error_category,
            receipt=state.receipt,
        )
    except PersistenceError:
        raise
    except Exception as exc:
        raise DatabaseOperationError(
            "PostgreSQL human validation reconciliation failed.",
            operation="reconcile-human-validation",
            sqlstate=safe_sqlstate(exc),
            run_id=str(run_uuid),
        ) from None
    finally:
        if owns_engine:
            try:
                dispose_engine(active_engine)
            except Exception:
                logger.warning("PostgreSQL reconciliation resource cleanup failed.")


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
    run_uuid: UUID | None = None
    if pipeline_run_id is not None:
        try:
            run_uuid = UUID(str(pipeline_run_id))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("pipeline_run_id must be a UUID.") from None
    owns_engine = engine is None
    if engine is not None:
        active_engine = engine
    elif settings is not None:
        active_engine = get_engine(settings)
    else:
        raise ValueError("PostgreSQL writes require explicit settings or an engine.")
    if pipeline_run_id is None:
        try:
            existing = _load_existing_validation(active_engine, decision.validation_id)
            if existing is not None:
                original_run = UUID(str(existing["pipeline_run_id"]))
                _assert_same_validation(
                    existing,
                    _validation_payload(decision, original_run),
                )
                audit_state = _load_audit_state(active_engine, original_run)
                return PersistedHumanValidation(
                    decision=_stored_decision(existing),
                    pipeline_run_id=original_run,
                    audit_complete=audit_state.audit_complete,
                    audit_error_category=(
                        None if audit_state.audit_complete else "PipelineAuditIncomplete"
                    ),
                    receipt=audit_state.receipt,
                )
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
            # Una decisión posee una corrida determinista: el mismo reintento no
            # fabrica otra identidad operacional ni altera su lineage.
            with pipeline_run(
                metadata,
                engine=active_engine,
                run_id=decision.validation_id,
            ) as run:
                persisted = persist_human_validation_record(
                    decision,
                    engine=active_engine,
                    pipeline_run_id=run.id,
                )
                run.set_output_rows(1)
            outcome = run.outcome
            if outcome is None:
                raise RuntimeError("Pipeline run did not publish an outcome.")
            return PersistedHumanValidation(
                decision=persisted.decision,
                pipeline_run_id=persisted.pipeline_run_id,
                audit_complete=outcome.audit_complete,
                audit_error_category=outcome.audit_error_category,
                receipt=persisted.receipt,
            )
        finally:
            if owns_engine:
                dispose_engine(active_engine)

    assert run_uuid is not None
    payload = _validation_payload(decision, run_uuid)
    try:
        with active_engine.begin() as connection:
            require_database_revision(connection)
            # Serializa dos creaciones simultáneas del mismo UUID sin ampliar
            # privilegios sobre la tabla append-only.
            connection.execute(text(LOCK_VALIDATION_ID_QUERY), {"id": str(decision.validation_id)})
            inserted = (
                connection.execute(text(INSERT_VALIDATION_QUERY), payload).mappings().one_or_none()
            )
            existing = (
                inserted
                or connection.execute(
                    text(SELECT_VALIDATION_QUERY), {"id": str(decision.validation_id)}
                )
                .mappings()
                .one()
            )
            _assert_same_validation(existing, payload)
            receipt = record_persistence_receipt(
                connection,
                build_persistence_receipt(
                    pipeline_run_id=run_uuid,
                    operation="human-validation",
                    observations=[payload],
                    processed_counts={"human_validations": 1},
                    inserted_counts={"human_validations": 1 if inserted is not None else 0},
                ),
            )
            audit_state = read_pipeline_run_audit_state(connection, run_uuid)
    except PersistenceError:
        raise
    except Exception as exc:
        sqlstate = safe_sqlstate(exc)
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
    return PersistedHumanValidation(
        decision=_stored_decision(existing),
        pipeline_run_id=run_uuid,
        audit_complete=audit_state.audit_complete,
        audit_error_category=(
            None if audit_state.audit_complete else "PipelineAuditIncomplete"
        ),
        receipt=receipt,
    )


def _validation_payload(decision: HumanValidation, run_uuid: UUID) -> dict[str, object]:
    return {
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


def _load_existing_validation(
    engine: Engine,
    validation_id: UUID,
) -> Mapping[Any, Any] | None:
    """Busca una decisión antes de fabricar una corrida operacional nueva."""

    try:
        with engine.begin() as connection:
            require_database_revision(connection)
            return (
                connection.execute(text(SELECT_VALIDATION_QUERY), {"id": str(validation_id)})
                .mappings()
                .one_or_none()
            )
    except PersistenceError:
        raise
    except Exception as exc:
        sqlstate = safe_sqlstate(exc)
        raise DatabaseOperationError(
            "PostgreSQL human validation lookup failed.",
            operation="load-human-validation",
            sqlstate=sqlstate,
        ) from None


def _load_prediction_context(engine: Engine, prediction_id: int) -> PersistedPredictionContext:
    """Lee la relación predicción-feature con los permisos vigentes del reviewer."""

    try:
        with engine.begin() as connection:
            require_database_revision(connection)
            row = (
                connection.execute(
                    text(SELECT_PREDICTION_CONTEXT_QUERY),
                    {"prediction_id": prediction_id},
                )
                .mappings()
                .one_or_none()
            )
    except PersistenceError:
        raise
    except Exception as exc:
        raise DatabaseOperationError(
            "PostgreSQL prediction context lookup failed.",
            operation="load-review-prediction-context",
            sqlstate=safe_sqlstate(exc),
        ) from None
    if row is None:
        raise PersistenceConflictError("The reviewed prediction context is unavailable.")
    timestamp = pd.Timestamp(row["record_time"])
    if timestamp.tzinfo is None:
        raise PersistenceConflictError("The reviewed prediction timestamp is invalid.")
    return PersistedPredictionContext(
        prediction_id=int(row["prediction_id"]),
        pipeline_run_id=UUID(str(row["pipeline_run_id"])),
        clip_id=str(row["clip_id"]),
        record_time=timestamp.tz_convert("UTC").to_pydatetime(),
        continuity_id=str(row["continuity_id"]),
        model_revision=str(row["model_revision"]),
        operational_feature_id=int(row["operational_feature_id"]),
    )


def _load_audit_state(engine: Engine, run_id: UUID):
    """Consulta la conclusión autoritativa sin inferirla desde la validación."""

    try:
        with engine.begin() as connection:
            require_database_revision(connection)
            return read_pipeline_run_audit_state(connection, run_id)
    except PersistenceError:
        raise
    except Exception as exc:
        raise DatabaseOperationError(
            "PostgreSQL review audit lookup failed.",
            operation="load-review-audit-state",
            sqlstate=safe_sqlstate(exc),
            run_id=str(run_id),
        ) from None


def _stored_decision(row: Mapping[Any, Any]) -> HumanValidation:
    """Reconstruye la decisión autoritativa sin alterar identidad ni fecha."""

    supersedes = row.get("supersedes_validation_id")
    return HumanValidation(
        prediction_id=int(row["prediction_id"]),
        validated_state=int(row["validated_state"]),
        reviewer_id=str(row["reviewer_id"]),
        notes=cast(str | None, row.get("notes")),
        incident_context_reviewed=bool(row["incident_context_reviewed"]),
        supersedes_validation_id=UUID(str(supersedes)) if supersedes else None,
        validation_id=UUID(str(row["id"])),
        reviewed_at=pd.Timestamp(row["reviewed_at"]).to_pydatetime(),
        review_source=str(row["review_source"]),
    )


def _assert_same_validation(existing: Mapping[Any, Any], payload: Mapping[str, object]) -> None:
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
    "PersistedPredictionContext",
    "load_review_queue",
    "load_human_validation_record",
    "persist_human_validation",
    "persist_human_validation_record",
    "reconcile_human_validation",
]
