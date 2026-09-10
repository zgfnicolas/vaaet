# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Escrituras idempotentes sobre los schemas PostgreSQL migrados de VAAET."""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from numbers import Integral, Real
from typing import TypeVar
from uuid import UUID, uuid4

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.continuity import normalize_continuity_frame
from vaaet.logging import get_logger
from vaaet.settings import (
    DATA_ORIGINS,
    FEATURE_COLS,
    MODEL_VERSION,
    STATE_LABELS,
    SYNTHETIC_SCENARIOS,
    TELEMETRY_SCHEMA_VERSION,
)
from vaaet.timestamps import normalize_timestamp

from vaaet_persistence.connection import dispose_engine, get_engine, require_database_revision
from vaaet_persistence.exceptions import (
    DatabaseOperationError,
    DatabaseSchemaVersionError,
    PersistenceConflictError,
)
from vaaet_persistence.pipeline_runs import PipelineRunMetadata, PipelineWorkflow, pipeline_run
from vaaet_persistence.settings import DatabaseSettings

logger = get_logger(__name__)

RAW_TABLE = "vaaet_raw.traffic_data"
FEATURE_TABLE = "vaaet_ml.telemetry_features"
PREDICTION_TABLE = "vaaet_ml.traffic_predictions"
NUMERIC_REPRESENTATION = "float64"
DEFAULT_BATCH_SIZE = 500
T = TypeVar("T")


@dataclass(frozen=True)
class PersistResult:
    """Resume las filas persistidas y la corrida que conserva su lineage."""

    telemetry_rows: int
    classification_rows: int
    pipeline_run_id: str


def _log_write_metrics(
    *, operation: str, rows: int, batches: int, queries: int, started_at: float
) -> None:
    """Registra capacidad observada sin incluir payloads ni prometer latencias."""

    duration = max(time.perf_counter() - started_at, 0.0)
    throughput = rows / duration if duration > 0 else 0.0
    logger.info(
        "%s completed: rows=%s batches=%s data_queries=%s transaction_connections=1 "
        "duration_seconds=%.6f rows_per_second=%.3f",
        operation,
        rows,
        batches,
        queries,
        duration,
        throughput,
    )


def _batch_count(row_count: int) -> int:
    """Calcula los lotes SQL requeridos sin materializar una colección auxiliar."""

    if row_count < 0:
        raise ValueError("Batch row count cannot be negative.")
    return (row_count + DEFAULT_BATCH_SIZE - 1) // DEFAULT_BATCH_SIZE


def _operation_engine(
    settings: DatabaseSettings | None, engine: Engine | None
) -> tuple[Engine, bool]:
    """Resuelve el engine y conserva explícitamente quién debe liberarlo."""

    if engine is not None:
        return engine, False
    if settings is None:
        raise ValueError("PostgreSQL writes require explicit settings or an engine.")
    return get_engine(settings), True


def _validated_pipeline_run_id(value: UUID | str | None) -> str:
    """Normaliza la FK de corrida antes de adquirir recursos PostgreSQL."""

    try:
        return str(UUID(str(value))) if value is not None else str(uuid4())
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("pipeline_run_id must be a UUID.") from exc


def _utc_timestamp(value: object) -> object:
    if value is None or bool(pd.isna(value)):
        raise ValueError("record_time is required and must be a valid timestamp.")
    return normalize_timestamp(value).to_pydatetime()


def _nullable_int(value: object) -> int | None:
    return _strict_integer(value, label="integer value", nullable=True)


def _nullable_float(value: object) -> float | None:
    return _strict_float(value, label="floating-point value", nullable=True)


def _nullable_str(value: object) -> str | None:
    return None if value is None or pd.isna(value) else str(value)


def _is_missing(value: object) -> bool:
    return value is None or value is pd.NA or value is pd.NaT


def _is_boolean(value: object) -> bool:
    return isinstance(value, bool) or type(value).__name__ == "bool_"


def _strict_integer(
    value: object,
    *,
    label: str,
    nullable: bool = False,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    if _is_missing(value):
        if nullable:
            return None
        raise ValueError(f"{label} is required.")
    if _is_boolean(value) or isinstance(value, str) or not isinstance(value, (Integral, Real, Decimal)):
        raise ValueError(f"{label} must be an integer, not a coerced value.")
    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise ValueError(f"{label} must be a finite integer.")
        result = int(value)
    elif isinstance(value, Integral):
        result = int(value)
    else:
        rendered = float(value)
        if not isfinite(rendered) or not rendered.is_integer():
            raise ValueError(f"{label} must be a finite integer.")
        result = int(rendered)
    if minimum is not None and result < minimum:
        raise ValueError(f"{label} must be at least {minimum}.")
    if maximum is not None and result > maximum:
        raise ValueError(f"{label} must be at most {maximum}.")
    return result


def _strict_float(
    value: object,
    *,
    label: str,
    nullable: bool = False,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    if _is_missing(value):
        if nullable:
            return None
        raise ValueError(f"{label} is required.")
    if _is_boolean(value) or isinstance(value, str) or not isinstance(value, (Real, Decimal)):
        raise ValueError(f"{label} must be numeric, not a coerced value.")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{label} must be finite.")
    if minimum is not None and result < minimum:
        raise ValueError(f"{label} must be at least {minimum}.")
    if maximum is not None and result > maximum:
        raise ValueError(f"{label} must be at most {maximum}.")
    return result


def _strict_boolean(value: object, *, label: str, nullable: bool = False) -> bool | None:
    if _is_missing(value):
        if nullable:
            return None
        raise ValueError(f"{label} is required.")
    if not _is_boolean(value):
        raise ValueError(f"{label} must be a boolean value.")
    return bool(value)


def _strict_identifier(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value


def _strict_choice(value: object, *, label: str, choices: tuple[str, ...]) -> str:
    result = _strict_identifier(value, label=label)
    if result not in choices:
        raise ValueError(f"{label} must be one of {choices}.")
    return result


def _validate_raw_row(row: pd.Series) -> None:
    _strict_identifier(row["clip_id"], label="clip_id")
    _strict_identifier(row.get("continuity_id", f"{row['clip_id']}:continuity-0001"), label="continuity_id")
    _utc_timestamp(row["record_time"])
    if row["telemetry_schema_version"] != TELEMETRY_SCHEMA_VERSION:
        raise ValueError("Operational raw persistence requires the current telemetry schema.")
    _strict_float(row["avg_speed"], label="avg_speed", minimum=0)
    counts = {
        column: _strict_integer(row[column], label=column, minimum=0)
        for column in (
            "count_car",
            "count_truck",
            "count_bus",
            "count_motorcycle",
            "count_bicycle",
        )
    }
    total = _strict_integer(row["total_vehicles"], label="total_vehicles", minimum=0)
    if total != sum(int(value) for value in counts.values() if value is not None):
        raise ValueError("total_vehicles must equal the sum of vehicle counts.")
    for column in (
        "near_zero_motion_count",
        "stationary_confirmed_count",
        "rejected_speed_count",
        "recovered_track_count",
        "speed_sample_count",
    ):
        _strict_integer(row.get(column), label=column, nullable=True, minimum=0)
    for column in ("speed_measurement_quality", "optical_flow_tracking_ratio"):
        _strict_float(row.get(column), label=column, nullable=True, minimum=0, maximum=1)


def _validate_classified_row(  # noqa: C901 - valida el contrato tabular externo completo.
    row: pd.Series, *, model_revision: str
) -> None:
    _strict_identifier(row["clip_id"], label="clip_id")
    _strict_identifier(row["continuity_id"], label="continuity_id")
    _utc_timestamp(row["record_time"])
    if row["feature_schema_version"] != FEATURE_SCHEMA_VERSION:
        raise ValueError("Operational prediction persistence requires the current feature schema.")
    if row["telemetry_schema_version"] != TELEMETRY_SCHEMA_VERSION:
        raise ValueError("Operational prediction persistence requires the current telemetry schema.")
    for column in FEATURE_COLS:
        if column in {
            "total_vehicles",
            "count_car",
            "count_truck",
            "count_bus",
            "count_motorcycle",
            "count_bicycle",
            "delta_count",
            "transition_flag",
            "hour_of_day",
            "weather_condition",
        }:
            minimum = 0 if column.startswith("count_") or column == "total_vehicles" else None
            maximum = 1 if column == "transition_flag" else None
            if column == "hour_of_day":
                minimum, maximum = 0, 23
            elif column == "weather_condition":
                minimum, maximum = 0, 1
            _strict_integer(
                row[column], label=column, nullable=False, minimum=minimum, maximum=maximum
            )
        else:
            minimum = 0 if column in {
                "avg_speed",
                "heavy_vehicle_ratio",
                "speed_variance",
                "low_speed_persistence",
                "speed_measurement_quality",
                "near_zero_motion_ratio",
                "stationary_confirmed_ratio",
            } else None
            maximum = 1 if column in {
                "heavy_vehicle_ratio",
                "low_speed_persistence",
                "speed_measurement_quality",
                "near_zero_motion_ratio",
                "stationary_confirmed_ratio",
            } else None
            _strict_float(
                row[column], label=column, nullable=False, minimum=minimum, maximum=maximum
            )
    counts = [
        _strict_integer(row[column], label=column, minimum=0)
        for column in (
            "count_car",
            "count_truck",
            "count_bus",
            "count_motorcycle",
            "count_bicycle",
        )
    ]
    total = _strict_integer(row["total_vehicles"], label="total_vehicles", minimum=0)
    if total != sum(int(value) for value in counts if value is not None):
        raise ValueError("total_vehicles must equal the sum of vehicle counts.")
    for column in (
        "near_zero_motion_count",
        "stationary_confirmed_count",
        "rejected_speed_count",
        "recovered_track_count",
        "speed_sample_count",
    ):
        _strict_integer(row.get(column), label=column, nullable=True, minimum=0)
    _strict_float(
        row.get("optical_flow_tracking_ratio"),
        label="optical_flow_tracking_ratio",
        nullable=True,
        minimum=0,
        maximum=1,
    )
    _strict_choice(
        row.get("data_origin", "real"), label="data_origin", choices=DATA_ORIGINS
    )
    _strict_choice(
        row.get("synthetic_scenario", "observed"),
        label="synthetic_scenario",
        choices=SYNTHETIC_SCENARIOS,
    )
    state = _strict_integer(row["traffic_state"], label="traffic_state", minimum=0, maximum=2)
    model_state = _strict_integer(
        row.get("model_traffic_state", state),
        label="model_traffic_state",
        minimum=0,
        maximum=2,
    )
    if row.get("state_label", STATE_LABELS[int(state)]) != STATE_LABELS[int(state)]:
        raise ValueError("traffic_state and state_label must describe the same state.")
    if row.get("model_state_label", STATE_LABELS[int(model_state)]) != STATE_LABELS[int(model_state)]:
        raise ValueError("model_traffic_state and model_state_label must describe the same state.")
    confidence = row.get("confidence", 0.0)
    _strict_float(confidence, label="confidence", minimum=0, maximum=1)
    _strict_float(
        row.get("model_confidence", confidence),
        label="model_confidence",
        minimum=0,
        maximum=1,
    )
    _strict_float(
        row.get("probability_margin"),
        label="probability_margin",
        nullable=True,
        minimum=0,
        maximum=1,
    )
    _strict_float(
        row.get("accident_evidence_score", 0.0),
        label="accident_evidence_score",
        minimum=0,
        maximum=1,
    )
    for column in ("decision_abstained", "accident_rule_triggered", "accident_alert_started"):
        _strict_boolean(row.get(column, False), label=column)
    _strict_boolean(row.get("measurement_reliable"), label="measurement_reliable", nullable=True)
    if not re.fullmatch(r"[0-9a-f]{64}", model_revision):
        raise ValueError("model_revision must be a lowercase SHA-256 value.")


def _require_migrated_schema(_exc: Exception) -> DatabaseSchemaVersionError:
    return DatabaseSchemaVersionError(
        "The VAAET PostgreSQL schema is unavailable. Apply `alembic upgrade head` "
        "with the administrator profile before running a notebook."
    )


INSERT_RAW_SQL = f"""
INSERT INTO {RAW_TABLE} (
    pipeline_run_id, clip_id, continuity_id, record_time, avg_speed, count_car, count_truck,
    count_bus, count_motorcycle, count_bicycle, total_vehicles,
    near_zero_motion_count, stationary_confirmed_count, rejected_speed_count,
    recovered_track_count, speed_sample_count, speed_measurement_quality,
    optical_flow_tracking_ratio, telemetry_schema_version, numeric_representation
) VALUES (
    :pipeline_run_id, :clip_id, :continuity_id, :record_time, :avg_speed, :count_car, :count_truck,
    :count_bus, :count_motorcycle, :count_bicycle, :total_vehicles,
    :near_zero_motion_count, :stationary_confirmed_count, :rejected_speed_count,
    :recovered_track_count, :speed_sample_count, :speed_measurement_quality,
    :optical_flow_tracking_ratio, :telemetry_schema_version, :numeric_representation
)
ON CONFLICT (clip_id, record_time) DO NOTHING
RETURNING id, clip_id, record_time
"""

SELECT_RAW_SQL = f"""
SELECT id, pipeline_run_id, clip_id, continuity_id, record_time, avg_speed,
       count_car, count_truck, count_bus, count_motorcycle, count_bicycle,
       total_vehicles, near_zero_motion_count, stationary_confirmed_count,
       rejected_speed_count, recovered_track_count, speed_sample_count,
       speed_measurement_quality, optical_flow_tracking_ratio,
       telemetry_schema_version, numeric_representation
FROM {RAW_TABLE}
WHERE clip_id = :clip_id AND record_time = :record_time
"""


INSERT_FEATURE_SQL = f"""
INSERT INTO {FEATURE_TABLE} (
    source_record_id, pipeline_run_id, clip_id, continuity_id, record_time, feature_schema_version,
    avg_speed, total_vehicles, count_car, count_truck, count_bus,
    count_motorcycle, count_bicycle, heavy_vehicle_ratio, delta_speed, delta_count,
    transition_flag, speed_variance, cumulative_delta_speed, low_speed_persistence,
    speed_measurement_quality, optical_flow_tracking_ratio, near_zero_motion_ratio,
    stationary_confirmed_ratio, near_zero_motion_count, stationary_confirmed_count,
    rejected_speed_count, recovered_track_count, speed_sample_count,
    telemetry_schema_version, data_origin, synthetic_scenario, hour_of_day,
    weather_condition, numeric_representation
) VALUES (
    :source_record_id, :pipeline_run_id, :clip_id, :continuity_id, :record_time, :feature_schema_version,
    :avg_speed, :total_vehicles, :count_car, :count_truck, :count_bus,
    :count_motorcycle, :count_bicycle, :heavy_vehicle_ratio, :delta_speed, :delta_count,
    :transition_flag, :speed_variance, :cumulative_delta_speed, :low_speed_persistence,
    :speed_measurement_quality, :optical_flow_tracking_ratio, :near_zero_motion_ratio,
    :stationary_confirmed_ratio, :near_zero_motion_count, :stationary_confirmed_count,
    :rejected_speed_count, :recovered_track_count, :speed_sample_count,
    :telemetry_schema_version, :data_origin, :synthetic_scenario, :hour_of_day,
    :weather_condition, :numeric_representation
)
ON CONFLICT (pipeline_run_id, clip_id, record_time, feature_schema_version) DO NOTHING
RETURNING id, pipeline_run_id, clip_id, record_time, feature_schema_version
"""


INSERT_PREDICTION_SQL = f"""
INSERT INTO {PREDICTION_TABLE} (
    telemetry_feature_id, pipeline_run_id, classified_at, traffic_state, state_label,
    confidence, model_version, model_revision, model_traffic_state, model_state_label,
    model_confidence, probability_margin, decision_abstained, measurement_reliable,
    accident_rule_triggered, accident_alert_started, accident_evidence_score,
    numeric_representation
) VALUES (
    :telemetry_feature_id, :pipeline_run_id, CURRENT_TIMESTAMP, :traffic_state, :state_label,
    :confidence, :model_version, :model_revision, :model_traffic_state, :model_state_label,
    :model_confidence, :probability_margin, :decision_abstained, :measurement_reliable,
    :accident_rule_triggered, :accident_alert_started, :accident_evidence_score,
    :numeric_representation
)
ON CONFLICT (telemetry_feature_id, model_revision) DO NOTHING
RETURNING id, telemetry_feature_id, model_revision
"""

SELECT_FEATURE_SQL = f"""
SELECT id, source_record_id, pipeline_run_id, clip_id, continuity_id, record_time,
       feature_schema_version, avg_speed, total_vehicles, count_car, count_truck,
       count_bus, count_motorcycle, count_bicycle, heavy_vehicle_ratio,
       delta_speed, delta_count, transition_flag, speed_variance,
       cumulative_delta_speed, low_speed_persistence, speed_measurement_quality,
       optical_flow_tracking_ratio, near_zero_motion_ratio,
       stationary_confirmed_ratio, near_zero_motion_count,
       stationary_confirmed_count, rejected_speed_count, recovered_track_count,
       speed_sample_count, telemetry_schema_version, data_origin,
       synthetic_scenario, hour_of_day, weather_condition, numeric_representation
FROM {FEATURE_TABLE}
WHERE pipeline_run_id = CAST(:pipeline_run_id AS UUID)
  AND clip_id = :clip_id AND record_time = :record_time
  AND feature_schema_version = :feature_schema_version
"""

SELECT_PREDICTION_SQL = f"""
SELECT id, telemetry_feature_id, pipeline_run_id, traffic_state, state_label,
       confidence, model_version, model_revision, model_traffic_state,
       model_state_label, model_confidence, probability_margin,
       decision_abstained, measurement_reliable, accident_rule_triggered,
       accident_alert_started, accident_evidence_score, numeric_representation
FROM {PREDICTION_TABLE}
WHERE telemetry_feature_id = :telemetry_feature_id
  AND model_revision = :model_revision
"""


def _raw_payload(row: pd.Series, pipeline_run_id: str) -> dict[str, object]:
    return {
        "pipeline_run_id": pipeline_run_id,
        "clip_id": _strict_identifier(row["clip_id"], label="clip_id"),
        "continuity_id": _strict_identifier(
            row.get("continuity_id", f"{row['clip_id']}:continuity-0001"),
            label="continuity_id",
        ),
        "record_time": _utc_timestamp(row["record_time"]),
        "avg_speed": _strict_float(row["avg_speed"], label="avg_speed", minimum=0),
        "count_car": _strict_integer(row["count_car"], label="count_car", minimum=0),
        "count_truck": _strict_integer(row["count_truck"], label="count_truck", minimum=0),
        "count_bus": _strict_integer(row["count_bus"], label="count_bus", minimum=0),
        "count_motorcycle": _strict_integer(
            row["count_motorcycle"], label="count_motorcycle", minimum=0
        ),
        "count_bicycle": _strict_integer(row["count_bicycle"], label="count_bicycle", minimum=0),
        "total_vehicles": _strict_integer(
            row["total_vehicles"], label="total_vehicles", minimum=0
        ),
        "near_zero_motion_count": _nullable_int(row.get("near_zero_motion_count")),
        "stationary_confirmed_count": _nullable_int(row.get("stationary_confirmed_count")),
        "rejected_speed_count": _nullable_int(row.get("rejected_speed_count")),
        "recovered_track_count": _nullable_int(row.get("recovered_track_count")),
        "speed_sample_count": _nullable_int(row.get("speed_sample_count")),
        "speed_measurement_quality": _nullable_float(row.get("speed_measurement_quality")),
        "optical_flow_tracking_ratio": _nullable_float(row.get("optical_flow_tracking_ratio")),
        "telemetry_schema_version": _nullable_str(
            row.get("telemetry_schema_version", TELEMETRY_SCHEMA_VERSION)
        ),
        "numeric_representation": NUMERIC_REPRESENTATION,
    }


def _feature_payload(row: pd.Series, pipeline_run_id: str) -> dict[str, object]:
    source_id = row.get("source_record_id", row.get("id"))
    return {
        "source_record_id": _nullable_int(source_id),
        "pipeline_run_id": pipeline_run_id,
        "clip_id": _strict_identifier(row["clip_id"], label="clip_id"),
        "continuity_id": _strict_identifier(
            row.get("continuity_id", f"{row['clip_id']}:continuity-0001"),
            label="continuity_id",
        ),
        "record_time": _utc_timestamp(row["record_time"]),
        "feature_schema_version": _strict_identifier(
            row["feature_schema_version"],
            label="feature_schema_version",
        ),
        "avg_speed": _nullable_float(row.get("avg_speed")),
        "total_vehicles": _nullable_int(row.get("total_vehicles")),
        "count_car": _nullable_int(row.get("count_car")),
        "count_truck": _nullable_int(row.get("count_truck")),
        "count_bus": _nullable_int(row.get("count_bus")),
        "count_motorcycle": _nullable_int(row.get("count_motorcycle")),
        "count_bicycle": _nullable_int(row.get("count_bicycle")),
        "heavy_vehicle_ratio": _nullable_float(row.get("heavy_vehicle_ratio")),
        "delta_speed": _nullable_float(row.get("delta_speed")),
        "delta_count": _nullable_int(row.get("delta_count")),
        "transition_flag": _nullable_int(row.get("transition_flag")) or 0,
        "speed_variance": _nullable_float(row.get("speed_variance")),
        "cumulative_delta_speed": _nullable_float(row.get("cumulative_delta_speed")),
        "low_speed_persistence": _nullable_float(row.get("low_speed_persistence")),
        "speed_measurement_quality": _nullable_float(row.get("speed_measurement_quality")),
        "optical_flow_tracking_ratio": _nullable_float(row.get("optical_flow_tracking_ratio")),
        "near_zero_motion_ratio": _nullable_float(row.get("near_zero_motion_ratio")),
        "stationary_confirmed_ratio": _nullable_float(row.get("stationary_confirmed_ratio")),
        "near_zero_motion_count": _nullable_int(row.get("near_zero_motion_count")),
        "stationary_confirmed_count": _nullable_int(row.get("stationary_confirmed_count")),
        "rejected_speed_count": _nullable_int(row.get("rejected_speed_count")),
        "recovered_track_count": _nullable_int(row.get("recovered_track_count")),
        "speed_sample_count": _nullable_int(row.get("speed_sample_count")),
        "telemetry_schema_version": _strict_identifier(
            row["telemetry_schema_version"], label="telemetry_schema_version"
        ),
        "data_origin": _strict_choice(
            row.get("data_origin", "real"), label="data_origin", choices=DATA_ORIGINS
        ),
        "synthetic_scenario": _strict_choice(
            row.get("synthetic_scenario", "observed"),
            label="synthetic_scenario",
            choices=SYNTHETIC_SCENARIOS,
        ),
        "hour_of_day": _nullable_int(row.get("hour_of_day")),
        "weather_condition": _nullable_int(row.get("weather_condition")),
        "numeric_representation": NUMERIC_REPRESENTATION,
    }


def _prediction_payload(
    row: pd.Series,
    *,
    feature_id: int,
    pipeline_run_id: str,
    model_version: str,
    model_revision: str,
) -> dict[str, object]:
    if row.get("traffic_state") == 3:
        raise ValueError(
            "Accident belongs exclusively to vaaet_feedback.human_validations."
        )
    state = _strict_integer(
        row.get("traffic_state", 0), label="traffic_state", minimum=0, maximum=2
    )
    model_state = _strict_integer(
        row.get("model_traffic_state", state),
        label="model_traffic_state",
        minimum=0,
        maximum=2,
    )
    assert state is not None and model_state is not None
    if state not in (0, 1, 2) or model_state not in (0, 1, 2):
        raise ValueError(
            "Automatic predictions may contain only Normal, Reduced, or Congested; "
            "Accident belongs exclusively to vaaet_feedback.human_validations."
        )
    if _strict_boolean(row.get("accident_gate_applied", False), label="accident_gate_applied"):
        raise ValueError("The bundle forbids an automatic Accident gate override.")
    row_revision = row.get("model_revision")
    exact_revision = model_revision if row_revision is None or pd.isna(row_revision) else str(row_revision)
    row_version = row.get("model_version")
    semantic_version = (
        model_version
        if row_version is None or pd.isna(row_version)
        else _strict_identifier(row_version, label="model_version")
    )
    if semantic_version != model_version:
        raise ValueError("Classified telemetry contradicts the requested model_version.")
    return {
        "telemetry_feature_id": feature_id,
        "pipeline_run_id": pipeline_run_id,
        "traffic_state": state,
        "state_label": str(row.get("state_label", STATE_LABELS[state])),
        "confidence": _strict_float(
            row.get("confidence", 0.0), label="confidence", minimum=0, maximum=1
        ),
        "model_version": semantic_version,
        "model_revision": exact_revision,
        "model_traffic_state": model_state,
        "model_state_label": str(row.get("model_state_label", STATE_LABELS[model_state])),
        "model_confidence": _strict_float(
            row.get("model_confidence", row.get("confidence", 0.0)),
            label="model_confidence",
            minimum=0,
            maximum=1,
        ),
        "probability_margin": _nullable_float(row.get("probability_margin")),
        "decision_abstained": _strict_boolean(
            row.get("decision_abstained", False), label="decision_abstained"
        ),
        "measurement_reliable": (
            _strict_boolean(
                row.get("measurement_reliable"), label="measurement_reliable", nullable=True
            )
        ),
        "accident_rule_triggered": _strict_boolean(
            row.get("accident_rule_triggered", False), label="accident_rule_triggered"
        ),
        "accident_alert_started": _strict_boolean(
            row.get("accident_alert_started", False), label="accident_alert_started"
        ),
        "accident_evidence_score": _strict_float(
            row.get("accident_evidence_score", 0.0),
            label="accident_evidence_score",
            minimum=0,
            maximum=1,
        ),
        "numeric_representation": NUMERIC_REPRESENTATION,
    }


def persist_raw_telemetry(  # noqa: C901 - valida y registra lineage opcional en un borde público.
    df: pd.DataFrame,
    *,
    settings: DatabaseSettings | None = None,
    engine: Engine | None = None,
    pipeline_run_id: UUID | str | None = None,
    application_name: str | None = None,
    application_version: str | None = None,
) -> int:
    """Persiste telemetría cruda de forma idempotente dentro de una corrida."""

    started_at = time.perf_counter()
    if df.empty:
        return 0
    required = {
        "clip_id",
        "record_time",
        "avg_speed",
        "count_car",
        "count_truck",
        "count_bus",
        "count_motorcycle",
        "count_bicycle",
        "total_vehicles",
        "telemetry_schema_version",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Raw telemetry is missing required columns: {sorted(missing)}")
    if pipeline_run_id is None and (not application_name or not application_version):
        raise ValueError(
            "Automatic pipeline lineage requires application_name and application_version."
        )
    run_id = _validated_pipeline_run_id(pipeline_run_id)
    active_engine, owns_engine = _operation_engine(settings, engine)
    if pipeline_run_id is None:
        try:
            clip_ids = df["clip_id"].dropna().astype(str).unique()
            metadata = PipelineRunMetadata(
                workflow=PipelineWorkflow.COLLECTION,
                application_name=application_name,
                application_version=application_version,
                source_kind="dataframe",
                clip_id=str(clip_ids[0]) if len(clip_ids) == 1 else None,
                input_rows=len(df),
                model_version=None,
                feature_schema_version=None,
            )
            with pipeline_run(metadata, engine=active_engine) as run:
                inserted = persist_raw_telemetry(
                    df,
                    engine=active_engine,
                    pipeline_run_id=run.id,
                )
                run.set_output_rows(inserted)
            return inserted
        except ProgrammingError as exc:
            raise _require_migrated_schema(exc) from None
        finally:
            if owns_engine:
                dispose_engine(active_engine)
    normalized = normalize_continuity_frame(df)
    for _, row in normalized.iterrows():
        _validate_raw_row(row)
    try:
        with active_engine.begin() as connection:
            require_database_revision(connection)
            inserted = _persist_raw_rows(connection, normalized, run_id)
    except ProgrammingError as exc:
        raise _require_migrated_schema(exc) from None
    except SQLAlchemyError as exc:
        raise DatabaseOperationError(
            "PostgreSQL raw telemetry persistence failed.",
            operation="persist-raw-telemetry",
            sqlstate=getattr(getattr(exc, "orig", None), "pgcode", None),
            run_id=run_id,
        ) from None
    finally:
        if owns_engine:
            dispose_engine(active_engine)
    batch_count = _batch_count(len(normalized))
    _log_write_metrics(
        operation="persist-raw-telemetry",
        rows=len(normalized),
        batches=batch_count,
        queries=1 + (3 * batch_count),
        started_at=started_at,
    )
    return inserted


def _persist_raw_rows(
    connection: Connection,
    frame: pd.DataFrame,
    run_id: str,
) -> int:
    """Inserta filas nuevas y comprueba el contenido de colisiones naturales."""

    payloads = [_raw_payload(row, run_id) for _, row in frame.iterrows()]
    inserted = 0
    for batch in _batches(payloads):
        existing_before = _select_batch(
            connection,
            SELECT_RAW_SQL,
            batch,
            key_fields=("clip_id", "record_time"),
        )
        for payload in batch:
            matches = _matching_rows(existing_before, payload, ("clip_id", "record_time"))
            if matches:
                _assert_idempotent(
                    matches[0], payload, "raw telemetry", ignored_fields={"pipeline_run_id"}
                )
        inserted += len(batch) - len(existing_before)
        connection.execute(text(_without_returning(INSERT_RAW_SQL)), batch)
        stored = _select_batch(connection, SELECT_RAW_SQL, batch, key_fields=("clip_id", "record_time"))
        _assert_batch_idempotent(
            stored, batch, kind="raw telemetry", key_fields=("clip_id", "record_time"),
            ignored_fields={"pipeline_run_id"},
        )
    return inserted


def persist_classified_telemetry(  # noqa: C901 - valida y registra lineage opcional en un borde público.
    df: pd.DataFrame,
    *,
    settings: DatabaseSettings | None = None,
    engine: Engine | None = None,
    model_version: str = MODEL_VERSION,
    model_revision: str | None = None,
    pipeline_run_id: UUID | str | None = None,
    application_name: str | None = None,
    application_version: str | None = None,
) -> PersistResult:
    """Persiste features y predicciones asociadas en una única transacción."""

    started_at = time.perf_counter()
    run_id = _validated_pipeline_run_id(pipeline_run_id)
    if df.empty:
        return PersistResult(0, 0, run_id)
    required = {
        "clip_id",
        "continuity_id",
        "record_time",
        "feature_schema_version",
        "telemetry_schema_version",
        "traffic_state",
        *FEATURE_COLS,
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Classified telemetry is missing required columns: {sorted(missing)}")
    normalized = normalize_continuity_frame(df)
    schema_versions = normalized["feature_schema_version"].dropna().astype(str).unique()
    if len(schema_versions) != 1 or schema_versions[0] != FEATURE_SCHEMA_VERSION:
        raise ValueError(
            "Operational prediction persistence requires the current feature schema."
        )
    resolved_revision = _resolve_model_revision(normalized, model_revision)
    for _, row in normalized.iterrows():
        _validate_classified_row(row, model_revision=resolved_revision)
    if pipeline_run_id is None and (not application_name or not application_version):
        raise ValueError(
            "Automatic pipeline lineage requires application_name and application_version."
        )
    active_engine, owns_engine = _operation_engine(settings, engine)
    if pipeline_run_id is None:
        try:
            clip_ids = normalized["clip_id"].dropna().astype(str).unique()
            metadata = PipelineRunMetadata(
                workflow=PipelineWorkflow.INFERENCE,
                application_name=application_name,
                application_version=application_version,
                source_kind="dataframe",
                clip_id=str(clip_ids[0]) if len(clip_ids) == 1 else None,
                input_rows=len(normalized),
                telemetry_schema_version=TELEMETRY_SCHEMA_VERSION,
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                model_version=model_version,
                model_revision=resolved_revision,
            )
            with pipeline_run(metadata, engine=active_engine) as run:
                persisted = persist_classified_telemetry(
                    normalized,
                    engine=active_engine,
                    model_version=model_version,
                    model_revision=resolved_revision,
                    pipeline_run_id=run.id,
                )
                run.set_output_rows(persisted.classification_rows)
            return persisted
        except ProgrammingError as exc:
            raise _require_migrated_schema(exc) from None
        finally:
            if owns_engine:
                dispose_engine(active_engine)
    try:
        with active_engine.begin() as connection:
            require_database_revision(connection)
            telemetry_rows, prediction_rows = _persist_classified_rows(
                connection, normalized, run_id, model_version, resolved_revision
            )
    except ProgrammingError as exc:
        raise _require_migrated_schema(exc) from None
    except SQLAlchemyError as exc:
        raise DatabaseOperationError(
            "PostgreSQL classified telemetry persistence failed.",
            operation="persist-classified-telemetry",
            sqlstate=getattr(getattr(exc, "orig", None), "pgcode", None),
            run_id=run_id,
        ) from None
    finally:
        if owns_engine:
            dispose_engine(active_engine)
    batch_count = _batch_count(len(normalized))
    _log_write_metrics(
        operation="persist-classified-telemetry",
        rows=len(normalized),
        batches=batch_count,
        queries=1 + (6 * batch_count),
        started_at=started_at,
    )
    return PersistResult(telemetry_rows, prediction_rows, run_id)


def _resolve_model_revision(frame: pd.DataFrame, requested: str | None) -> str:
    revisions = (
        frame.get("model_revision", pd.Series(dtype="string"))
        .dropna()
        .astype(str)
        .unique()
    )
    resolved = requested or (str(revisions[0]) if len(revisions) == 1 else None)
    if resolved is None or re.fullmatch(r"[0-9a-f]{64}", resolved) is None:
        raise ValueError("Classified telemetry requires one exact SHA-256 model_revision.")
    if len(revisions) > 1 or (len(revisions) == 1 and str(revisions[0]) != resolved):
        raise ValueError("Classified telemetry mixes or contradicts model_revision values.")
    return resolved


def _persist_classified_rows(
    connection: Connection,
    frame: pd.DataFrame,
    run_id: str,
    model_version: str,
    model_revision: str,
) -> tuple[int, int]:
    rows = list(frame.iterrows())
    for batch_rows in _batches(rows):
        feature_payloads = [_feature_payload(row, run_id) for _, row in batch_rows]
        existing_features = _select_batch(
            connection,
            SELECT_FEATURE_SQL,
            feature_payloads,
            key_fields=("pipeline_run_id", "clip_id", "record_time", "feature_schema_version"),
        )
        if existing_features:
            _assert_batch_idempotent(
                existing_features,
                [
                    payload
                    for payload in feature_payloads
                    if _matching_rows(
                        existing_features,
                        payload,
                        ("pipeline_run_id", "clip_id", "record_time", "feature_schema_version"),
                    )
                ],
                kind="feature",
                key_fields=("pipeline_run_id", "clip_id", "record_time", "feature_schema_version"),
            )
        connection.execute(text(_without_returning(INSERT_FEATURE_SQL)), feature_payloads)
        stored_features = _select_batch(
            connection,
            SELECT_FEATURE_SQL,
            feature_payloads,
            key_fields=("pipeline_run_id", "clip_id", "record_time", "feature_schema_version"),
        )
        _assert_batch_idempotent(
            stored_features,
            feature_payloads,
            kind="feature",
            key_fields=("pipeline_run_id", "clip_id", "record_time", "feature_schema_version"),
        )
        prediction_payloads: list[dict[str, object]] = []
        for (_, row), feature_payload in zip(batch_rows, feature_payloads, strict=True):
            feature = _find_by_key(
                stored_features,
                feature_payload,
                ("pipeline_run_id", "clip_id", "record_time", "feature_schema_version"),
            )
            prediction_payloads.append(
                _prediction_payload(
                    row,
                    feature_id=int(feature["id"]),
                    pipeline_run_id=run_id,
                    model_version=model_version,
                    model_revision=model_revision,
                )
            )
        existing_predictions = _select_batch(
            connection,
            SELECT_PREDICTION_SQL,
            prediction_payloads,
            key_fields=("telemetry_feature_id", "model_revision"),
        )
        if existing_predictions:
            _assert_batch_idempotent(
                existing_predictions,
                [
                    payload
                    for payload in prediction_payloads
                    if _matching_rows(
                        existing_predictions,
                        payload,
                        ("telemetry_feature_id", "model_revision"),
                    )
                ],
                kind="prediction",
                key_fields=("telemetry_feature_id", "model_revision"),
            )
        connection.execute(text(_without_returning(INSERT_PREDICTION_SQL)), prediction_payloads)
        stored_predictions = _select_batch(
            connection,
            SELECT_PREDICTION_SQL,
            prediction_payloads,
            key_fields=("telemetry_feature_id", "model_revision"),
        )
        _assert_batch_idempotent(
            stored_predictions,
            prediction_payloads,
            kind="prediction",
            key_fields=("telemetry_feature_id", "model_revision"),
        )
    return len(frame), len(frame)


def _batches(items: list[T], size: int = DEFAULT_BATCH_SIZE) -> list[list[T]]:
    """Divide una operación pública en lotes acotados dentro de su transacción."""

    return [items[offset : offset + size] for offset in range(0, len(items), size)]


def _select_batch(
    connection: Connection,
    base_query: str,
    payloads: list[dict[str, object]],
    *,
    key_fields: tuple[str, ...],
) -> list[Mapping[str, object]]:
    prefix = base_query.rsplit("WHERE", maxsplit=1)[0]
    clauses: list[str] = []
    params: dict[str, object] = {}
    for index, payload in enumerate(payloads):
        parts = []
        for field in key_fields:
            parameter = f"{field}_{index}"
            cast = (
                f"CAST(:{parameter} AS UUID)"
                if field == "pipeline_run_id"
                else f":{parameter}"
            )
            parts.append(f"{field} = {cast}")
            params[parameter] = payload[field]
        clauses.append("(" + " AND ".join(parts) + ")")
    statement = text(prefix + "WHERE " + " OR ".join(clauses))
    return list(connection.execute(statement, params).mappings().all())


def _find_by_key(
    rows: list[Mapping[str, object]],
    payload: Mapping[str, object],
    key_fields: tuple[str, ...],
) -> Mapping[str, object]:
    matches = _matching_rows(rows, payload, key_fields)
    if len(matches) != 1:
        raise PersistenceConflictError(
            "PostgreSQL did not resolve exactly one row for an immutable natural key."
        )
    return matches[0]


def _matching_rows(
    rows: list[Mapping[str, object]],
    payload: Mapping[str, object],
    key_fields: tuple[str, ...],
) -> list[Mapping[str, object]]:
    return [
        row
        for row in rows
        if all(_database_values_equal(row.get(field), payload.get(field)) for field in key_fields)
    ]


def _without_returning(statement: str) -> str:
    return statement.rsplit("RETURNING", maxsplit=1)[0]


def _assert_batch_idempotent(
    rows: list[Mapping[str, object]],
    payloads: list[dict[str, object]],
    *,
    kind: str,
    key_fields: tuple[str, ...],
    ignored_fields: set[str] | None = None,
) -> None:
    for payload in payloads:
        existing = _find_by_key(rows, payload, key_fields)
        _assert_idempotent(existing, payload, kind, ignored_fields=ignored_fields)


def _assert_idempotent(
    existing: Mapping[str, object],
    payload: Mapping[str, object],
    kind: str,
    *,
    ignored_fields: set[str] | None = None,
) -> None:
    """Acepta un reintento idéntico y rechaza una colisión con otro contenido."""

    ignored = {"id", "classified_at", *(ignored_fields or set())}
    differences = [
        key
        for key, value in payload.items()
        if key not in ignored and key in existing and not _database_values_equal(existing[key], value)
    ]
    if differences:
        raise PersistenceConflictError(
            f"Immutable {kind} idempotency conflict in fields: {sorted(differences)}"
        )


def _database_values_equal(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, UUID) or isinstance(right, UUID):
        return str(left) == str(right)
    if (
        not _is_boolean(left)
        and not _is_boolean(right)
        and isinstance(left, (Integral, Real, Decimal))
        and isinstance(right, (Integral, Real, Decimal))
    ):
        left_float = float(left)
        right_float = float(right)
        return isfinite(left_float) and isfinite(right_float) and left_float == right_float
    return left == right


def ensure_raw_telemetry_table(engine: Engine) -> None:
    """Rechaza DDL desde notebooks; los cambios de schema son administrativos."""
    del engine
    raise RuntimeError("Apply `alembic upgrade head`; notebooks may not create database tables.")


def ensure_persistence_tables(engine: Engine) -> None:
    """Rechaza DDL desde notebooks; los cambios de schema son administrativos."""
    del engine
    raise RuntimeError("Apply `alembic upgrade head`; notebooks may not create database tables.")


__all__ = [
    "PersistResult",
    "ensure_persistence_tables",
    "ensure_raw_telemetry_table",
    "persist_classified_telemetry",
    "persist_raw_telemetry",
]
