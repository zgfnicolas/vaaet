# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Consumidor independiente contra el contrato PostgreSQL real."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd
import pytest
from sqlalchemy import text
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.settings import FEATURE_COLS, TELEMETRY_SCHEMA_VERSION

import vaaet_persistence.pipeline_runs as pipeline_run_module
from vaaet_persistence.connection import database_engine, inspect_database
from vaaet_persistence.exceptions import (
    PersistenceConflictError,
    PipelineAuditIncompleteError,
)
from vaaet_persistence.persistence import (
    persist_classified_telemetry,
    persist_raw_telemetry,
    reconcile_raw_telemetry,
)
from vaaet_persistence.pipeline_runs import PipelineRunMetadata, PipelineWorkflow, pipeline_run
from vaaet_persistence.queries import load_telemetry_window
from vaaet_persistence.receipts import read_pipeline_run_audit_state
from vaaet_persistence.review_domain import HumanValidation
from vaaet_persistence.review_persistence import persist_human_validation_record
from vaaet_persistence.settings import DatabaseProfile, load_database_settings

pytestmark = pytest.mark.postgres


def _settings(profile: DatabaseProfile = DatabaseProfile.COLLECTION):
    try:
        return load_database_settings(
            profile,
            application_name="independent-backend-consumer-test",
            application_version="0.1.0",
        )
    except RuntimeError:
        if os.environ.get("VAAET_REQUIRE_POSTGRES_INTEGRATION") == "1":
            pytest.fail("Required PostgreSQL integration profile is not configured")
        pytest.skip("PostgreSQL integration profile is not configured")


def test_installed_component_inspects_migrated_schema_without_ml() -> None:
    settings = _settings()
    with database_engine(settings) as engine:
        health = inspect_database(engine, DatabaseProfile.COLLECTION)
    assert "vaaet_raw" in health.available_schemas


@pytest.mark.parametrize(
    ("profile", "workflow", "allowed", "forbidden"),
    [
        (
            DatabaseProfile.COLLECTION,
            PipelineWorkflow.COLLECTION,
            ("vaaet_raw.traffic_data", "INSERT"),
            ("vaaet_ml.telemetry_features", "INSERT"),
        ),
        (
            DatabaseProfile.INFERENCE,
            PipelineWorkflow.INFERENCE,
            ("vaaet_ml.telemetry_features", "INSERT"),
            ("vaaet_raw.traffic_data", "INSERT"),
        ),
        (
            DatabaseProfile.TRAINING,
            PipelineWorkflow.TRAINING,
            ("vaaet_raw.traffic_data", "SELECT"),
            ("vaaet_raw.traffic_data", "INSERT"),
        ),
        (
            DatabaseProfile.REVIEW,
            PipelineWorkflow.REVIEW,
            ("vaaet_feedback.human_validations", "INSERT"),
            ("vaaet_ml.traffic_predictions", "INSERT"),
        ),
    ],
)
def test_each_login_uses_only_its_workflow_role(
    profile: DatabaseProfile,
    workflow: PipelineWorkflow,
    allowed: tuple[str, str],
    forbidden: tuple[str, str],
) -> None:
    settings = _settings(profile)
    metadata = PipelineRunMetadata(
        workflow=workflow,
        application_name="independent-backend-consumer-test",
        application_version="0.1.0",
        source_kind="integration-test",
        input_rows=0,
    )
    with database_engine(settings) as engine:
        assert inspect_database(engine, profile).current_role == settings.username
        with pipeline_run(metadata, engine=engine) as run:
            run.set_output_rows(0)
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT has_table_privilege(current_user, :table, :privilege)"),
                {"table": allowed[0], "privilege": allowed[1]},
            ).scalar()
            assert not connection.execute(
                text("SELECT has_table_privilege(current_user, :table, :privilege)"),
                {"table": forbidden[0], "privilege": forbidden[1]},
            ).scalar()


def test_independent_consumer_can_persist_and_read_raw_telemetry() -> None:
    settings = _settings()
    record_time = pd.Timestamp("2026-09-08T12:34:00Z")
    frame = pd.DataFrame(
        [
            {
                "clip_id": "persistence-consumer-contract",
                "record_time": record_time,
                "avg_speed": 20.123456789012345,
                "count_car": 1,
                "count_truck": 0,
                "count_bus": 0,
                "count_motorcycle": 0,
                "count_bicycle": 0,
                "total_vehicles": 1,
                "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
            }
        ]
    )
    inserted = persist_raw_telemetry(
        frame,
        settings=settings,
        application_name="independent-backend-consumer-test",
        application_version="0.1.0",
    )
    loaded = load_telemetry_window(
        start=record_time,
        end=record_time + pd.Timedelta(minutes=1),
        clip_ids=("persistence-consumer-contract",),
        settings=settings,
    )

    assert inserted in {0, 1}
    assert len(loaded) == 1
    assert loaded.iloc[0]["avg_speed"] == frame.iloc[0]["avg_speed"]
    assert loaded.iloc[0]["numeric_representation"] == "float64"

    repeated = persist_raw_telemetry(
        frame,
        settings=settings,
        application_name="independent-backend-consumer-test",
        application_version="0.1.0",
    )
    assert repeated == 0

    with pytest.raises(ValueError, match="idempotency conflict"):
        persist_raw_telemetry(
            frame.assign(avg_speed=21.0),
            settings=settings,
            application_name="independent-backend-consumer-test",
            application_version="0.1.0",
        )


def test_confirmed_write_is_reconciled_without_reinserting_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    frame = pd.DataFrame(
        [
            {
                "clip_id": f"audit-reconciliation-{uuid4()}",
                "record_time": pd.Timestamp("2026-09-15T12:00:00Z"),
                "avg_speed": 18.125,
                "count_car": 1,
                "count_truck": 0,
                "count_bus": 0,
                "count_motorcycle": 0,
                "count_bicycle": 0,
                "total_vehicles": 1,
                "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
            }
        ]
    )
    original_finish = pipeline_run_module.finish_pipeline_run

    def fail_audit_close(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated audit close failure")

    monkeypatch.setattr(pipeline_run_module, "finish_pipeline_run", fail_audit_close)
    with pytest.raises(PipelineAuditIncompleteError) as captured:
        persist_raw_telemetry(
            frame,
            settings=settings,
            application_name="independent-backend-consumer-test",
            application_version="0.1.0",
        )

    assert captured.value.confirmed_result == 1
    with database_engine(settings) as engine, engine.connect() as connection:
        receipt_before = read_pipeline_run_audit_state(connection, captured.value.run_id).receipt
    assert receipt_before is not None
    assert receipt_before.operation == "raw-telemetry"
    assert receipt_before.processed_counts == {"raw_telemetry": 1}
    assert receipt_before.inserted_counts == {"raw_telemetry": 1}
    monkeypatch.setattr(pipeline_run_module, "finish_pipeline_run", original_finish)
    with pytest.raises(PersistenceConflictError):
        reconcile_raw_telemetry(
            frame.assign(clip_id="different-clip"),
            pipeline_run_id=captured.value.run_id,
            settings=settings,
        )
    outcome = reconcile_raw_telemetry(
        frame,
        pipeline_run_id=captured.value.run_id,
        settings=settings,
    )

    assert outcome.work_succeeded
    assert outcome.audit_complete
    assert outcome.reconciliation_run_id is not None
    repeated_outcome = reconcile_raw_telemetry(
        frame,
        pipeline_run_id=captured.value.run_id,
        settings=settings,
    )
    assert repeated_outcome.audit_complete
    assert repeated_outcome.reconciliation_run_id == outcome.reconciliation_run_id
    assert persist_raw_telemetry(
        frame,
        settings=settings,
        application_name="independent-backend-consumer-test",
        application_version="0.1.0",
    ) == 0


def test_independent_consumer_preserves_feature_and_probability_float64() -> None:
    settings = _settings(DatabaseProfile.INFERENCE)
    high_precision_speed = 20.123456789012345
    high_precision_probability = 0.8123456789012345
    row = {column: 0.0 for column in FEATURE_COLS}
    row.update(
        {
            "clip_id": "persistence-float64-classification",
            "continuity_id": "persistence-float64-classification:continuity-0001",
            "record_time": pd.Timestamp("2026-09-08T12:35:00Z"),
            "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "avg_speed": high_precision_speed,
            "speed_measurement_quality": 0.9876543210987654,
            "traffic_state": 0,
            "state_label": "Normal",
            "confidence": high_precision_probability,
            "model_confidence": high_precision_probability,
            "probability_margin": 0.6123456789012345,
            "measurement_reliable": True,
        }
    )
    result = persist_classified_telemetry(
        pd.DataFrame([row]),
        settings=settings,
        model_version="mlp-v3.0-integration",
        model_revision="d" * 64,
        application_name="independent-backend-consumer-test",
        application_version="0.1.0",
    )
    assert result.telemetry_rows == 1
    assert result.classification_rows == 1
    assert result.inserted_telemetry_rows in {0, 1}
    assert result.inserted_classification_rows in {0, 1}
    assert result.receipt is not None
    assert result.receipt.operation == "classified-telemetry"

    with database_engine(settings) as engine, engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT f.avg_speed, f.speed_measurement_quality, p.confidence, "
                "p.probability_margin, f.numeric_representation "
                "FROM vaaet_ml.telemetry_features f "
                "JOIN vaaet_ml.traffic_predictions p ON p.telemetry_feature_id=f.id "
                "WHERE p.pipeline_run_id=CAST(:run_id AS UUID)"
            ),
            {"run_id": result.pipeline_run_id},
        ).one()

    assert stored.avg_speed == high_precision_speed
    assert stored.speed_measurement_quality == row["speed_measurement_quality"]
    assert stored.confidence == high_precision_probability
    assert stored.probability_margin == row["probability_margin"]
    assert stored.numeric_representation == "float64"


def test_reviewer_can_append_and_correct_without_update_privilege() -> None:
    inference_settings = _settings(DatabaseProfile.INFERENCE)
    review_settings = _settings(DatabaseProfile.REVIEW)
    row = {column: 0.0 for column in FEATURE_COLS}
    row.update(
        {
            "clip_id": "reviewer-least-privilege-contract",
            "continuity_id": "reviewer-least-privilege-contract:continuity-0001",
            "record_time": pd.Timestamp("2026-09-11T12:00:00Z"),
            "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "traffic_state": 1,
            "state_label": "Reduced",
            "confidence": 0.8,
            "model_confidence": 0.8,
            "probability_margin": 0.4,
            "measurement_reliable": True,
        }
    )
    persisted = persist_classified_telemetry(
        pd.DataFrame([row]),
        settings=inference_settings,
        model_version="mlp-v3.0-review-integration",
        model_revision="e" * 64,
        application_name="independent-backend-consumer-test",
        application_version="0.1.0",
    )
    with database_engine(inference_settings) as engine, engine.connect() as connection:
        prediction_id = connection.execute(
            text(
                "SELECT id FROM vaaet_ml.traffic_predictions "
                "WHERE pipeline_run_id=CAST(:run_id AS UUID)"
            ),
            {"run_id": persisted.pipeline_run_id},
        ).scalar_one()

    root = HumanValidation(
        prediction_id=prediction_id,
        validated_state=1,
        reviewer_id="integration-reviewer",
        validation_id=uuid4(),
        reviewed_at=datetime(2026, 9, 11, 12, 5, tzinfo=timezone.utc),
        review_source="postgres-integration",
    )
    first = persist_human_validation_record(
        root,
        settings=review_settings,
        application_name="independent-backend-consumer-test",
        application_version="0.1.0",
    )
    correction = HumanValidation(
        prediction_id=prediction_id,
        validated_state=0,
        reviewer_id="integration-reviewer",
        validation_id=uuid4(),
        supersedes_validation_id=first.validation_id,
        reviewed_at=datetime(2026, 9, 11, 12, 6, tzinfo=timezone.utc),
        review_source="postgres-integration",
    )
    corrected = persist_human_validation_record(
        correction,
        settings=review_settings,
        application_name="independent-backend-consumer-test",
        application_version="0.1.0",
    )
    repeated = persist_human_validation_record(
        correction,
        settings=review_settings,
        application_name="independent-backend-consumer-test",
        application_version="0.1.0",
    )

    assert repeated == corrected
    assert first.audit_complete
    assert first.receipt is not None
    assert corrected.audit_complete
    assert corrected.receipt is not None
    assert corrected.pipeline_run_id == repeated.pipeline_run_id
    with database_engine(review_settings) as engine, engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT count(*) FROM vaaet_feedback.human_validations "
                "WHERE prediction_id=:prediction_id"
            ),
            {"prediction_id": prediction_id},
        ).scalar_one() == 2
        for privilege in ("UPDATE", "DELETE"):
            assert not connection.execute(
                text(
                    "SELECT has_table_privilege(current_user, "
                    "'vaaet_feedback.human_validations', :privilege)"
                ),
                {"privilege": privilege},
            ).scalar_one()
