# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for schema-qualified PostgreSQL persistence payloads."""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.features.engineering import engineer_features
from vaaet.settings import FEATURE_COLS, TELEMETRY_SCHEMA_VERSION

from vaaet_persistence.exceptions import (
    PersistenceConflictError,
    PipelineAuditIncompleteError,
)
from vaaet_persistence.persistence import (
    INSERT_FEATURE_SQL,
    INSERT_PREDICTION_SQL,
    INSERT_RAW_SQL,
    SELECT_RAW_SQL,
    _assert_idempotent,
    _assert_reconciliation_state,
    _batch_count,
    _batches,
    _database_values_equal,
    _feature_payload,
    _multi_values_parameters,
    _multi_values_statement,
    _prediction_payload,
    _raw_payload,
    _rows_by_key,
    _strict_boolean,
    _strict_float,
    _strict_integer,
    _validate_classified_row,
    _validated_pipeline_run_id,
    persist_classified_telemetry,
    persist_raw_telemetry,
)
from vaaet_persistence.pipeline_runs import PipelineWorkflow
from vaaet_persistence.receipts import PipelineRunAuditState, build_persistence_receipt
from vaaet_persistence.settings import DatabaseProfile, DatabaseSettings


@pytest.mark.parametrize(
    ("rows", "expected"),
    [(0, 0), (1, 1), (500, 1), (501, 2), (1_000, 2), (1_001, 3)],
)
def test_batch_count_has_stable_boundaries(rows: int, expected: int) -> None:
    assert _batch_count(rows) == expected


def test_batch_count_rejects_negative_rows() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        _batch_count(-1)


@pytest.mark.parametrize(("rows", "batches"), [(1, 1), (500, 1), (501, 2), (1_200, 3)])
def test_multi_values_batches_are_bounded(rows: int, batches: int) -> None:
    payloads = [
        {
            "pipeline_run_id": "00000000-0000-0000-0000-000000000001",
            "clip_id": f"clip-{index}",
            "continuity_id": f"clip-{index}:continuity-0001",
            "record_time": pd.Timestamp("2026-09-08T00:00:00Z") + pd.Timedelta(minutes=index),
            "avg_speed": 10.0,
            "count_car": 1,
            "count_truck": 0,
            "count_bus": 0,
            "count_motorcycle": 0,
            "count_bicycle": 0,
            "total_vehicles": 1,
            "near_zero_motion_count": None,
            "stationary_confirmed_count": None,
            "rejected_speed_count": None,
            "recovered_track_count": None,
            "speed_sample_count": None,
            "speed_measurement_quality": None,
            "optical_flow_tracking_ratio": None,
            "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
            "numeric_representation": "float64",
        }
        for index in range(rows)
    ]

    chunks = _batches(payloads)
    assert len(chunks) == batches
    assert max(map(len, chunks)) <= 500
    statement = _multi_values_statement(INSERT_RAW_SQL, chunks[0])
    parameters = _multi_values_parameters(chunks[0])
    assert statement.count("ON CONFLICT") == 1
    assert ":clip_id_0" in statement
    assert parameters["clip_id_0"] == "clip-0"


def test_pipeline_run_id_is_validated_before_database_access() -> None:
    with pytest.raises(ValueError, match="must be a UUID"):
        _validated_pipeline_run_id("not-a-uuid")


def test_batch_indexes_preserve_large_integer_identity() -> None:
    first = 2**53
    second = first + 1

    indexed = _rows_by_key([{"id": first}, {"id": second}], ("id",))

    assert len(indexed) == 2


def test_queries_use_versioned_schemas() -> None:
    assert "vaaet_raw.traffic_data" in INSERT_RAW_SQL
    assert "RETURNING id" in INSERT_RAW_SQL
    assert "vaaet_raw.traffic_data" in SELECT_RAW_SQL
    assert "vaaet_ml.telemetry_features" in INSERT_FEATURE_SQL
    assert "vaaet_ml.traffic_predictions" in INSERT_PREDICTION_SQL
    assert "is_human_validated" not in INSERT_PREDICTION_SQL
    assert "human_override_state" not in INSERT_PREDICTION_SQL
    assert "DO UPDATE" not in INSERT_FEATURE_SQL
    assert "DO UPDATE" not in INSERT_PREDICTION_SQL


def test_raw_payload_localizes_historical_buenos_aires_time() -> None:
    row = pd.Series(
        {
            "clip_id": "bridge_test",
            "record_time": pd.Timestamp("2025-05-01 08:01:00"),
            "avg_speed": 12.5,
            "count_car": 1,
            "count_truck": 0,
            "count_bus": 0,
            "count_motorcycle": 0,
            "count_bicycle": 0,
            "total_vehicles": 1,
        }
    )
    payload = _raw_payload(row, "00000000-0000-0000-0000-000000000001")
    assert payload["record_time"].tzinfo is not None
    assert payload["record_time"].hour == 11


def test_feature_payload_uses_source_id_and_schema_version() -> None:
    row = pd.Series(
        {
            "id": 7,
            "clip_id": "clip",
            "record_time": pd.Timestamp("2025-05-01 08:00:00", tz="UTC"),
            "feature_schema_version": "traffic-features-v3",
            "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
        }
    )
    payload = _feature_payload(row, "00000000-0000-0000-0000-000000000001")
    assert payload["source_record_id"] == 7
    assert payload["feature_schema_version"] == "traffic-features-v3"
    assert payload["telemetry_schema_version"] == TELEMETRY_SCHEMA_VERSION


def test_prediction_rejects_automatic_accident() -> None:
    row = pd.Series(
        {
            "traffic_state": 3,
            "model_traffic_state": 2,
            "state_label": "Accident",
            "confidence": 0.91,
        }
    )
    with pytest.raises(ValueError, match="exclusively"):
        _prediction_payload(
            row,
            feature_id=10,
            pipeline_run_id="00000000-0000-0000-0000-000000000001",
            model_version="mlp-v3.0",
            model_revision="a" * 64,
        )


def test_prediction_preserves_incident_candidate_as_congested() -> None:
    row = pd.Series(
        {
            "traffic_state": 2,
            "state_label": "Congested",
            "confidence": 0.91,
            "model_traffic_state": 2,
            "accident_rule_triggered": True,
            "accident_alert_started": True,
            "accident_evidence_score": 0.88,
        }
    )
    payload = _prediction_payload(
        row,
        feature_id=10,
        pipeline_run_id="00000000-0000-0000-0000-000000000001",
        model_version="mlp-v3.0",
        model_revision="a" * 64,
    )
    assert payload["traffic_state"] == 2
    assert payload["accident_rule_triggered"] is True


def test_prediction_rejects_contradictory_model_version() -> None:
    row = pd.Series(
        {
            "traffic_state": 0,
            "state_label": "Normal",
            "confidence": 0.91,
            "model_version": "mlp-v2.1",
        }
    )
    with pytest.raises(ValueError, match="contradicts"):
        _prediction_payload(
            row,
            feature_id=10,
            pipeline_run_id="00000000-0000-0000-0000-000000000001",
            model_version="mlp-v3.0",
            model_revision="a" * 64,
        )


def test_missing_lineage_identity_fails_before_creating_an_engine(monkeypatch) -> None:
    frame = pd.DataFrame(
        [
            {
                "clip_id": "clip",
                "record_time": pd.Timestamp("2026-09-08T00:00:00Z"),
                "avg_speed": 10.0,
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
    settings = DatabaseSettings(
        DatabaseProfile.COLLECTION,
        "localhost",
        5432,
        "vaaet",
        "collection",
        "secret",
        "disable",
    )
    created = False

    def unexpected_engine(_settings):
        nonlocal created
        created = True
        return object()

    monkeypatch.setattr("vaaet_persistence.persistence.get_engine", unexpected_engine)

    with pytest.raises(ValueError, match="application_name"):
        persist_raw_telemetry(frame, settings=settings)

    assert not created


def test_raw_scalar_facade_exposes_confirmed_result_when_audit_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame(
        [
            {
                "clip_id": "audit-incomplete",
                "record_time": pd.Timestamp("2026-09-15T00:00:00Z"),
                "avg_speed": 10.0,
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
    run_id = uuid4()
    run = SimpleNamespace(
        id=run_id,
        outcome=SimpleNamespace(
            run_id=run_id,
            audit_complete=False,
            audit_error_category="DatabaseOperationError",
        ),
        set_output_rows=lambda _rows: None,
    )

    @contextmanager
    def fake_pipeline_run(*_args: object, **_kwargs: object):
        yield run

    monkeypatch.setattr("vaaet_persistence.persistence.pipeline_run", fake_pipeline_run)
    monkeypatch.setattr(
        "vaaet_persistence.persistence.persist_raw_telemetry",
        lambda *_args, **_kwargs: 1,
    )

    with pytest.raises(PipelineAuditIncompleteError) as captured:
        persist_raw_telemetry(
            frame,
            engine=object(),  # type: ignore[arg-type]
            application_name="test-consumer",
            application_version="1.0.0",
        )

    assert captured.value.confirmed_result == 1
    assert captured.value.run_id == str(run_id)


def test_classified_persistence_requires_declared_telemetry_schema() -> None:
    row = {column: 0.0 for column in FEATURE_COLS}
    row.update(
        {
            "clip_id": "clip",
            "continuity_id": "clip:continuity-0001",
            "record_time": pd.Timestamp("2026-09-08T00:00:00Z"),
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "traffic_state": 0,
        }
    )

    with pytest.raises(ValueError, match="telemetry_schema_version"):
        persist_classified_telemetry(pd.DataFrame([row]))


def test_core_engineered_low_speed_persistence_is_accepted() -> None:
    raw = pd.DataFrame(
        [
            {
                "clip_id": "clip",
                "record_time": pd.Timestamp("2026-09-08T00:00:00Z")
                + pd.Timedelta(minutes=index),
                "avg_speed": 1.0,
                "count_car": 1,
                "count_truck": 0,
                "count_bus": 0,
                "count_motorcycle": 0,
                "count_bicycle": 0,
                "total_vehicles": 1,
                "speed_sample_count": 1,
                "rejected_speed_count": 0,
                "near_zero_motion_count": 1,
                "stationary_confirmed_count": 1,
                "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
            }
            for index in range(3)
        ]
    )
    engineered = engineer_features(raw)
    assert engineered["low_speed_persistence"].max() == 2
    row = engineered.iloc[-1].copy()
    row["traffic_state"] = 2
    row["state_label"] = "Congested"
    row["confidence"] = 0.9

    _validate_classified_row(row, model_revision="a" * 64)


def test_raw_idempotency_ignores_lineage_but_rejects_changed_measurements() -> None:
    existing = {
        "id": 1,
        "pipeline_run_id": "first-run",
        "clip_id": "clip",
        "record_time": pd.Timestamp("2026-09-08T00:00:00Z"),
        "avg_speed": 10.0,
    }
    retry = {
        "pipeline_run_id": "second-run",
        "clip_id": "clip",
        "record_time": pd.Timestamp("2026-09-08T00:00:00Z"),
        "avg_speed": 10.0,
    }

    _assert_idempotent(
        existing,
        retry,
        "raw telemetry",
        ignored_fields={"pipeline_run_id"},
    )

    with pytest.raises(ValueError, match="avg_speed"):
        _assert_idempotent(
            existing,
            {**retry, "avg_speed": 11.0},
            "raw telemetry",
            ignored_fields={"pipeline_run_id"},
        )


def test_reconciliation_rejects_receipt_from_another_run_or_clip() -> None:
    requested_run = uuid4()
    other_run = uuid4()
    frame = pd.DataFrame(
        [
            {
                "clip_id": "clip-requested",
                "record_time": pd.Timestamp("2026-09-20T12:00:00Z"),
                "avg_speed": 10.0,
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
    expected = build_persistence_receipt(
        pipeline_run_id=requested_run,
        operation="raw-telemetry",
        observations=[_raw_payload(frame.iloc[0], str(requested_run))],
        processed_counts={"raw_telemetry": 1},
        inserted_counts={"raw_telemetry": 0},
        telemetry_schema_version=TELEMETRY_SCHEMA_VERSION,
    )
    wrong_receipt = build_persistence_receipt(
        pipeline_run_id=other_run,
        operation="raw-telemetry",
        observations=[_raw_payload(frame.iloc[0], str(other_run))],
        processed_counts={"raw_telemetry": 1},
        inserted_counts={"raw_telemetry": 1},
        telemetry_schema_version=TELEMETRY_SCHEMA_VERSION,
    )
    state = PipelineRunAuditState(
        pipeline_run_id=other_run,
        workflow="collection",
        application_name="test-consumer",
        application_version="1.0.0",
        database_user="collection",
        status="running",
        source_kind="dataframe",
        clip_id="clip-other",
        input_rows=1,
        output_rows=None,
        telemetry_schema_version=TELEMETRY_SCHEMA_VERSION,
        feature_schema_version=None,
        model_version=None,
        model_revision=None,
        receipt=wrong_receipt,
    )

    with pytest.raises(PersistenceConflictError, match="clip_id.*persistence_receipt"):
        _assert_reconciliation_state(
            state,
            expected,
            workflow=PipelineWorkflow.COLLECTION,
            frame=frame,
        )


@pytest.mark.parametrize("value", [True, "1", 1.5, np.float64(2.5)])
def test_integer_contract_rejects_coerced_or_fractional_values(value: object) -> None:
    with pytest.raises(ValueError, match="integer"):
        _strict_integer(value, label="count")


@pytest.mark.parametrize("value", [True, "0.5", float("nan"), float("inf")])
def test_float_contract_rejects_boolean_text_and_nonfinite_values(value: object) -> None:
    with pytest.raises(ValueError, match="numeric|finite"):
        _strict_float(value, label="confidence")


@pytest.mark.parametrize("value", [1, 0, "true", "false"])
def test_boolean_contract_accepts_only_real_booleans(value: object) -> None:
    with pytest.raises(ValueError, match="boolean"):
        _strict_boolean(value, label="confirmed")


def test_decimal_and_float_are_compared_as_the_persisted_float64_value() -> None:
    value = 0.12345678901234566

    assert _database_values_equal(Decimal.from_float(value), np.float64(value))
    assert not _database_values_equal(Decimal("0.1234567890123457"), value)
