# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""PostgreSQL 17 integration checks for vaaet-db-v3."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.settings import FEATURE_COLS, TELEMETRY_SCHEMA_VERSION

from vaaet_ml.data.database_connection import create_admin_engine, dispose_engine
from vaaet_ml.data.database_settings import (
    cleanup_temporary_root_certificate,
    load_database_admin_settings,
)
from vaaet_ml.data.ingestion import (
    PostgresBackupSource,
    TrainingIngestionPlan,
    load_training_inputs,
)
from vaaet_ml.data.persistence import persist_classified_telemetry
from vaaet_ml.data.review import HumanValidation, persist_human_validation
from vaaet_ml.training.lifecycle import TrainingMode

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def engine():
    try:
        settings = load_database_admin_settings(allow_legacy=False)
    except RuntimeError:
        pytest.skip("Typed PostgreSQL administrator settings are not configured")
    active = create_admin_engine(settings)
    try:
        yield active
    finally:
        dispose_engine(active)
        cleanup_temporary_root_certificate(settings)


@pytest.mark.parametrize(
    ("path_variable", "expected_table", "expected_layout"),
    [
        ("VAAET_LEGACY_BACKUP_PATH", "public.traffic_data", "legacy"),
        ("VAAET_MODERN_BACKUP_PATH", "vaaet_raw.traffic_data", "modern"),
    ],
)
def test_real_pg17_custom_backups_are_ingested_exactly(
    path_variable: str, expected_table: str, expected_layout: str
) -> None:
    backup_value = os.getenv(path_variable)
    pg_restore_value = os.getenv("VAAET_PG_RESTORE_PATH")
    if not backup_value or not pg_restore_value:
        pytest.skip("PostgreSQL 17 backup fixtures are not configured")

    result = load_training_inputs(
        TrainingIngestionPlan(
            mode=TrainingMode.SEED_BOOTSTRAP,
            raw_sources=(
                PostgresBackupSource(Path(backup_value), Path(pg_restore_value)),
            )
        )
    )

    assert len(result.raw) >= 1
    assert "legacy-clip" in set(result.raw["clip_id"])
    assert result.provenance.iloc[0]["archive_table"] == expected_table
    assert result.provenance.iloc[0]["backup_layout"] == expected_layout
    assert str(result.provenance.iloc[0]["reader_version"]).startswith(
        "pg_restore (PostgreSQL) 17"
    )


def test_migrated_schemas_tables_and_views_exist(engine) -> None:
    expected = {
        "vaaet_raw.traffic_data",
        "vaaet_ml.telemetry_features",
        "vaaet_ml.traffic_predictions",
        "vaaet_feedback.human_validations",
        "vaaet_feedback.review_queue",
        "vaaet_feedback.effective_human_labels",
        "vaaet_ops.pipeline_runs",
        "public.traffic_data",
        "public.telemetry_raw",
        "public.traffic_classifications",
    }
    with engine.connect() as connection:
        existing = {
            name
            for name in expected
            if connection.execute(text("SELECT to_regclass(:name)"), {"name": name}).scalar()
        }
    assert existing == expected


def test_legacy_hitl_and_buenos_aires_timestamps_are_migrated(engine) -> None:
    if os.getenv("VAAET_EXPECT_LEGACY_FIXTURE") != "1":
        pytest.skip("Legacy fixture is not expected in this database")
    with engine.connect() as connection:
        raw_time = connection.execute(
            text(
                "SELECT record_time FROM vaaet_raw.traffic_data "
                "WHERE clip_id='legacy-clip'"
            )
        ).scalar_one()
        validation = connection.execute(
            text(
                "SELECT validated_state, incident_context_reviewed, notes, reviewed_at "
                "FROM vaaet_feedback.human_validations "
                "WHERE reviewer_id='legacy-migration'"
            )
        ).one()
        automatic_state = connection.execute(
            text(
                "SELECT traffic_state FROM vaaet_ml.traffic_predictions "
                "WHERE model_version='mlp-v1.1'"
            )
        ).scalar_one()
    assert raw_time.hour == 11
    assert validation.validated_state == 3
    assert validation.incident_context_reviewed
    assert validation.notes
    assert validation.reviewed_at.hour == 11
    assert automatic_state == 2


def test_automatic_accident_is_rejected_by_database(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO vaaet_ops.pipeline_runs
                  (id, workflow, status, completed_at, application_name, application_version)
                VALUES
                  ('00000000-0000-0000-0000-000000000001', 'inference',
                   'succeeded', CURRENT_TIMESTAMP, 'vaaet-integration', 'integration-test')
                ON CONFLICT (id) DO NOTHING
                """
            )
        )
        feature_id = connection.execute(
            text(
                """
                INSERT INTO vaaet_ml.telemetry_features
                  (pipeline_run_id, clip_id, continuity_id, record_time,
                   feature_schema_version)
                VALUES
                  ('00000000-0000-0000-0000-000000000001', 'constraint-test',
                   'constraint-test:continuity-0001', '2026-08-04T12:00:00Z',
                   'traffic-features-v3')
                ON CONFLICT (pipeline_run_id, clip_id, record_time,
                             feature_schema_version)
                DO UPDATE SET clip_id=EXCLUDED.clip_id RETURNING id
                """
            )
        ).scalar_one()
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO vaaet_ml.traffic_predictions
                      (telemetry_feature_id, pipeline_run_id, traffic_state, state_label,
                       confidence, model_version, model_revision)
                    VALUES (:feature_id, '00000000-0000-0000-0000-000000000001',
                            3, 'Accident', 1, 'constraint-test', :model_revision)
                    """
                ),
                {"feature_id": feature_id, "model_revision": "a" * 64},
            )


def test_group_roles_follow_least_privilege(engine) -> None:
    checks = {
        "vaaet_collection_role": {
            "vaaet_raw.traffic_data": ("INSERT",),
        },
        "vaaet_inference_role": {
            "vaaet_ml.telemetry_features": ("SELECT", "INSERT"),
            "vaaet_ml.traffic_predictions": ("SELECT", "INSERT"),
        },
        "vaaet_training_role": {
            "vaaet_raw.traffic_data": ("SELECT",),
            "vaaet_ml.traffic_predictions": ("SELECT",),
            "vaaet_feedback.human_validations": ("SELECT",),
            "vaaet_ops.pipeline_runs": ("SELECT",),
        },
        "vaaet_reviewer_role": {
            "vaaet_ml.traffic_predictions": ("SELECT",),
            "vaaet_feedback.human_validations": ("SELECT", "INSERT"),
        },
    }
    with engine.connect() as connection:
        for role, tables in checks.items():
            for table, privileges in tables.items():
                for privilege in privileges:
                    assert connection.execute(
                        text("SELECT has_table_privilege(:role, :table, :privilege)"),
                        {"role": role, "table": table, "privilege": privilege},
                    ).scalar()
        assert not connection.execute(
            text(
                "SELECT has_table_privilege('vaaet_reviewer_role', "
                "'vaaet_feedback.human_validations', 'UPDATE')"
            )
        ).scalar()
        for table in (
            "vaaet_ml.telemetry_features",
            "vaaet_ml.traffic_predictions",
        ):
            assert not connection.execute(
                text(
                    "SELECT has_table_privilege('vaaet_inference_role', "
                    ":table, 'UPDATE')"
                ),
                {"table": table},
            ).scalar()
        assert connection.execute(
            text(
                "SELECT has_table_privilege('vaaet_collection_role', "
                "'vaaet_raw.traffic_data', 'SELECT')"
            )
        ).scalar()
        assert not connection.execute(
            text(
                "SELECT has_table_privilege('vaaet_training_role', "
                "'vaaet_raw.traffic_data', 'INSERT')"
            )
        ).scalar()
        for role in (
            "vaaet_collection_role",
            "vaaet_inference_role",
            "vaaet_training_role",
            "vaaet_reviewer_role",
        ):
            assert connection.execute(
                text(
                    "SELECT has_table_privilege(:role, "
                    "'public.alembic_version', 'SELECT')"
                ),
                {"role": role},
            ).scalar()
            assert connection.execute(
                text(
                    "SELECT has_function_privilege(:role, "
                    "'vaaet_ops.start_pipeline_run(uuid,text,text,text,text,text,text,text,text,text,text,bigint)', "
                    "'EXECUTE')"
                ),
                {"role": role},
            ).scalar()
            assert connection.execute(
                text(
                    "SELECT has_function_privilege(:role, "
                    "'vaaet_ops.finish_pipeline_run(uuid,text,bigint,text,text)', "
                    "'EXECUTE')"
                ),
                {"role": role},
            ).scalar()
            assert not connection.execute(
                text(
                    "SELECT has_table_privilege(:role, 'vaaet_ops.pipeline_runs', 'INSERT')"
                ),
                {"role": role},
            ).scalar()


def test_hardening_constraints_comments_and_indexes(engine) -> None:
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM public.alembic_version")
        ).scalar_one()
        undocumented = connection.execute(
            text(
                """
                SELECT count(*) FROM pg_attribute a
                JOIN pg_class c ON c.oid=a.attrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                LEFT JOIN pg_description d ON d.objoid=c.oid AND d.objsubid=a.attnum
                WHERE n.nspname LIKE 'vaaet_%' AND c.relkind='r'
                  AND a.attnum > 0 AND NOT a.attisdropped AND d.description IS NULL
                """
            )
        ).scalar_one()
        indexes = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE schemaname LIKE 'vaaet_%'"
                )
            )
        }
        raw_total_validated = connection.execute(
            text(
                "SELECT convalidated FROM pg_constraint "
                "WHERE conname='ck_raw_total_matches_types'"
            )
        ).scalar_one()
    assert revision == "20260909_0004"
    assert undocumented == 0
    assert "idx_raw_clip_time" not in indexes
    assert "idx_features_clip_time" not in indexes
    assert "idx_validations_prediction_time_id" in indexes
    assert "idx_predictions_model_revision" in indexes
    assert raw_total_validated is False


def test_new_raw_rows_require_consistent_vehicle_total(engine) -> None:
    run_id = "00000000-0000-0000-0000-000000000099"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO vaaet_ops.pipeline_runs "
                "(id, workflow, status, completed_at, application_name, application_version) "
                "VALUES (:id, 'collection', 'succeeded', CURRENT_TIMESTAMP, "
                "'vaaet-integration', 'test') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": run_id},
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO vaaet_raw.traffic_data
                      (pipeline_run_id, clip_id, record_time, avg_speed, count_car,
                       count_truck, count_bus, count_motorcycle, count_bicycle,
                       total_vehicles)
                    VALUES
                      (:run_id, 'invalid-total', '2026-08-06T12:00:00Z', 10,
                       1, 0, 0, 0, 0, 2)
                    """
                ),
                {"run_id": run_id},
            )


def test_reinference_preserves_append_only_human_validation(engine) -> None:
    base = {column: 0.0 for column in FEATURE_COLS}
    base.update(
        {
            "clip_id": "reinference-test",
            "continuity_id": "reinference-test:continuity-0001",
            "record_time": "2026-08-04T13:00:00Z",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
            "traffic_state": 2,
            "state_label": "Congested",
            "confidence": 0.81,
            "model_version": "mlp-v3.0-test",
            "model_revision": "a" * 64,
        }
    )
    frame = pd.DataFrame([base])
    persist_classified_telemetry(
        frame,
        engine=engine,
        model_version="mlp-v3.0-test",
        model_revision="a" * 64,
        application_name="vaaet-ml-integration",
        application_version="4.8.0",
    )
    with engine.connect() as connection:
        prediction_id = connection.execute(
            text(
                """
                SELECT p.id FROM vaaet_ml.traffic_predictions p
                JOIN vaaet_ml.telemetry_features f ON f.id=p.telemetry_feature_id
                WHERE f.clip_id='reinference-test' AND p.model_revision=:model_revision
                """
            ),
            {"model_revision": "a" * 64},
        ).scalar_one()
    first_validation_id = persist_human_validation(
        HumanValidation(prediction_id, 1, "integration-reviewer"),
        engine=engine,
        application_name="vaaet-ml-integration",
        application_version="4.8.0",
    )
    frame.loc[0, "confidence"] = 0.92
    frame.loc[0, "model_revision"] = "b" * 64
    persist_classified_telemetry(
        frame,
        engine=engine,
        model_version="mlp-v3.0-test",
        model_revision="b" * 64,
        application_name="vaaet-ml-integration",
        application_version="4.8.0",
    )
    with engine.connect() as connection:
        feature_count, prediction_count = connection.execute(
            text(
                "SELECT count(DISTINCT f.id), count(DISTINCT p.id) "
                "FROM vaaet_ml.telemetry_features f "
                "JOIN vaaet_ml.traffic_predictions p ON p.telemetry_feature_id=f.id "
                "WHERE f.clip_id='reinference-test' AND p.model_version='mlp-v3.0-test'"
            )
        ).one()
        count = connection.execute(
            text(
                "SELECT count(*) FROM vaaet_feedback.human_validations "
                "WHERE prediction_id=:prediction_id"
            ),
            {"prediction_id": prediction_id},
        ).scalar_one()
        effective = connection.execute(
            text(
                "SELECT traffic_state FROM vaaet_feedback.effective_human_labels "
                "WHERE prediction_id=:prediction_id"
            ),
            {"prediction_id": prediction_id},
        ).scalar_one()
    assert feature_count == 2
    assert prediction_count == 2
    assert count == 1
    assert effective == 1
    persist_human_validation(
        HumanValidation(
            prediction_id,
            0,
            "integration-reviewer",
            notes="Correction after reviewing adjacent minutes.",
            supersedes_validation_id=first_validation_id,
        ),
        engine=engine,
        application_name="vaaet-ml-integration",
        application_version="4.8.0",
    )
    with engine.connect() as connection:
        count, effective = connection.execute(
            text(
                "SELECT count(*), max(e.traffic_state) FROM vaaet_feedback.human_validations v "
                "JOIN vaaet_feedback.effective_human_labels e ON e.prediction_id=v.prediction_id "
                "WHERE v.prediction_id=:prediction_id GROUP BY e.traffic_state"
            ),
            {"prediction_id": prediction_id},
        ).one()
    assert count == 2
    assert effective == 0
