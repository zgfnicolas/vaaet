# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Acceso PostgreSQL append-only para colas y decisiones de revisión."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast
from uuid import UUID, uuid4

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from vaaet_persistence.connection import get_engine
from vaaet_persistence.pipeline_runs import PipelineRunMetadata, PipelineWorkflow, pipeline_run
from vaaet_persistence.review_domain import HumanValidation, select_review_queue
from vaaet_persistence.settings import DatabaseSettings

REVIEW_QUEUE_QUERY = """
SELECT prediction_id, pipeline_run_id, clip_id, continuity_id, record_time, traffic_state,
       state_label, confidence, model_version, model_revision, probability_margin,
       decision_abstained, measurement_reliable, accident_rule_triggered,
       accident_alert_started, accident_evidence_score, latest_validation_id,
       current_validated_state, current_reviewer_id, current_reviewed_at
FROM vaaet_feedback.review_queue
WHERE (:pipeline_run_id IS NULL OR pipeline_run_id = CAST(:pipeline_run_id AS UUID))
ORDER BY record_time
"""

INSERT_VALIDATION_QUERY = """
INSERT INTO vaaet_feedback.human_validations (
    id, prediction_id, validated_state, reviewer_id, reviewed_at, notes,
    review_source, incident_context_reviewed, supersedes_validation_id,
    pipeline_run_id
) VALUES (
    :id, :prediction_id, :validated_state, :reviewer_id, CURRENT_TIMESTAMP, :notes,
    :review_source, :incident_context_reviewed, :supersedes_validation_id,
    CAST(:pipeline_run_id AS UUID)
)
"""


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
        frame = pd.read_sql(
            text(REVIEW_QUEUE_QUERY),
            active_engine,
            params=cast(
                Mapping[str, object],
                {"pipeline_run_id": str(pipeline_run_id) if pipeline_run_id else None},
            ),
        )
    finally:
        if owns_engine:
            active_engine.dispose()
    return select_review_queue(frame, mode=mode)


def persist_human_validation(
    decision: HumanValidation,
    *,
    settings: DatabaseSettings | None = None,
    engine: Engine | None = None,
    pipeline_run_id: UUID | str | None = None,
    application_name: str | None = None,
    application_version: str | None = None,
) -> UUID:
    """Guarda una decisión append-only y crea linaje de revisión si es necesario."""

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
                validation_id = persist_human_validation(
                    decision,
                    engine=active_engine,
                    pipeline_run_id=run.id,
                )
                run.set_output_rows(1)
            return validation_id
        finally:
            if owns_engine:
                active_engine.dispose()

    validation_id = decision.validation_id or uuid4()
    payload = {
        "id": str(validation_id),
        "prediction_id": decision.prediction_id,
        "validated_state": decision.validated_state,
        "reviewer_id": decision.reviewer_id,
        "notes": decision.notes,
        "review_source": decision.review_source,
        "incident_context_reviewed": decision.incident_context_reviewed,
        "supersedes_validation_id": (
            str(decision.supersedes_validation_id) if decision.supersedes_validation_id else None
        ),
        "pipeline_run_id": str(pipeline_run_id),
    }
    try:
        with active_engine.begin() as connection:
            connection.execute(text(INSERT_VALIDATION_QUERY), payload)
    finally:
        if owns_engine:
            active_engine.dispose()
    return validation_id


__all__ = ["load_review_queue", "persist_human_validation"]
