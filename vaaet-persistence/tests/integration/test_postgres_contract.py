# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Consumidor independiente contra el contrato PostgreSQL real."""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import text
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.settings import FEATURE_COLS, TELEMETRY_SCHEMA_VERSION

from vaaet_persistence.connection import database_engine, inspect_database
from vaaet_persistence.persistence import persist_classified_telemetry, persist_raw_telemetry
from vaaet_persistence.pipeline_runs import PipelineRunMetadata, PipelineWorkflow, pipeline_run
from vaaet_persistence.queries import load_telemetry_window
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
