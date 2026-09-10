# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Consultas PostgreSQL read-only y normalización de su resultado tabular."""

from __future__ import annotations

from collections.abc import Sequence
from typing import NoReturn

import pandas as pd
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError
from vaaet.artifacts import FEATURE_SCHEMA_VERSION

from vaaet_persistence.connection import dispose_engine, get_engine
from vaaet_persistence.exceptions import DatabaseOperationError
from vaaet_persistence.settings import DatabaseSettings

RAW_TABLE = "vaaet_raw.traffic_data"
EFFECTIVE_LABELS_VIEW = "vaaet_feedback.effective_human_labels"

TELEMETRY_QUERY = f"""
SELECT id, pipeline_run_id, clip_id, continuity_id, record_time, avg_speed,
       count_car, count_truck, count_bus, count_motorcycle, count_bicycle,
       total_vehicles, near_zero_motion_count, stationary_confirmed_count,
       rejected_speed_count, recovered_track_count, speed_sample_count,
       speed_measurement_quality, optical_flow_tracking_ratio,
       telemetry_schema_version, numeric_representation
FROM {RAW_TABLE}
ORDER BY clip_id, record_time
"""

LEGACY_TELEMETRY_QUERY = """
SELECT id, clip_id, record_time, avg_speed, count_car, count_truck, count_bus,
       count_motorcycle, count_bicycle, total_vehicles
FROM public.traffic_data
ORDER BY clip_id, record_time
"""

HUMAN_GROUND_TRUTH_QUERY = f"""
SELECT id, source_record_id, pipeline_run_id, clip_id, continuity_id, record_time,
       feature_schema_version, avg_speed, total_vehicles, count_car,
       count_truck, count_bus, count_motorcycle, count_bicycle,
       heavy_vehicle_ratio, delta_speed, delta_count, transition_flag,
       speed_variance, cumulative_delta_speed, low_speed_persistence,
       speed_measurement_quality, optical_flow_tracking_ratio,
       near_zero_motion_ratio, stationary_confirmed_ratio,
       near_zero_motion_count, stationary_confirmed_count,
       rejected_speed_count, recovered_track_count, speed_sample_count,
       telemetry_schema_version, data_origin, synthetic_scenario,
       hour_of_day, weather_condition, created_at, prediction_id,
       model_version, model_revision, traffic_state, is_human_validated, reviewer_id,
       reviewed_at, notes, feature_numeric_representation,
       prediction_numeric_representation
FROM {EFFECTIVE_LABELS_VIEW}
WHERE (:feature_schema_version IS NULL OR feature_schema_version = :feature_schema_version)
ORDER BY clip_id, record_time
"""

HUMAN_FEATURES_QUERY = """
SELECT f.id, f.source_record_id, f.pipeline_run_id, f.clip_id, f.continuity_id,
       f.record_time, f.feature_schema_version, f.avg_speed, f.total_vehicles,
       f.count_car, f.count_truck, f.count_bus, f.count_motorcycle,
       f.count_bicycle, f.heavy_vehicle_ratio, f.delta_speed, f.delta_count,
       f.transition_flag, f.speed_variance, f.cumulative_delta_speed,
       f.low_speed_persistence, f.speed_measurement_quality,
       f.optical_flow_tracking_ratio, f.near_zero_motion_ratio,
       f.stationary_confirmed_ratio, f.near_zero_motion_count,
       f.stationary_confirmed_count, f.rejected_speed_count,
       f.recovered_track_count, f.speed_sample_count,
       f.telemetry_schema_version, f.data_origin, f.synthetic_scenario,
       f.hour_of_day, f.weather_condition, f.created_at,
       f.numeric_representation
FROM vaaet_ml.telemetry_features f
WHERE (:feature_schema_version IS NULL OR f.feature_schema_version = :feature_schema_version)
  AND EXISTS (
    SELECT 1
    FROM vaaet_ml.traffic_predictions linked_prediction
    JOIN vaaet_feedback.human_validations linked_validation
      ON linked_validation.prediction_id = linked_prediction.id
    WHERE linked_prediction.telemetry_feature_id = f.id
  )
ORDER BY f.clip_id, f.record_time, f.id
"""

HUMAN_PREDICTIONS_QUERY = """
SELECT p.id, p.pipeline_run_id, p.telemetry_feature_id, p.model_version,
       p.model_revision, p.numeric_representation
FROM vaaet_ml.traffic_predictions p
JOIN vaaet_ml.telemetry_features f ON f.id = p.telemetry_feature_id
WHERE (:feature_schema_version IS NULL OR f.feature_schema_version = :feature_schema_version)
  AND EXISTS (
    SELECT 1 FROM vaaet_feedback.human_validations linked_validation
    WHERE linked_validation.prediction_id = p.id
  )
ORDER BY p.id
"""

HUMAN_VALIDATIONS_QUERY = """
SELECT hv.id, hv.prediction_id, hv.validated_state, TRUE AS is_human_validated,
       hv.reviewer_id, hv.reviewed_at, hv.notes, hv.supersedes_validation_id,
       hv.pipeline_run_id, hv.review_source, hv.incident_context_reviewed
FROM vaaet_feedback.human_validations hv
JOIN vaaet_ml.traffic_predictions p ON p.id = hv.prediction_id
JOIN vaaet_ml.telemetry_features f ON f.id = p.telemetry_feature_id
WHERE (:feature_schema_version IS NULL OR f.feature_schema_version = :feature_schema_version)
ORDER BY hv.reviewed_at, hv.id
"""

_LEGACY_MISSING_COLUMNS = (
    "pipeline_run_id",
    "continuity_id",
    "near_zero_motion_count",
    "stationary_confirmed_count",
    "rejected_speed_count",
    "recovered_track_count",
    "speed_sample_count",
    "speed_measurement_quality",
    "optical_flow_tracking_ratio",
    "telemetry_schema_version",
    "numeric_representation",
)


def _active_engine(
    settings: DatabaseSettings | None, engine: Engine | None
) -> tuple[Engine, bool]:
    """Resuelve ownership sin elegir un perfil implícito."""

    if engine is not None:
        return engine, False
    if settings is None:
        raise ValueError("PostgreSQL operations require explicit settings or an engine.")
    return get_engine(settings), True


def load_telemetry(
    settings: DatabaseSettings | None = None,
    engine: Engine | None = None,
) -> pd.DataFrame:
    """Carga telemetría canónica y agrega columnas nulas al fallback legado explícito."""

    active_engine, owns_engine = _active_engine(settings, engine)
    try:
        try:
            return pd.read_sql(text(TELEMETRY_QUERY), active_engine)
        except ProgrammingError:
            try:
                legacy = pd.read_sql(text(LEGACY_TELEMETRY_QUERY), active_engine)
            except SQLAlchemyError as exc:
                _raise_read_error(exc, operation="load-legacy-telemetry")
            for column in _LEGACY_MISSING_COLUMNS:
                legacy[column] = pd.NA
            return legacy
        except SQLAlchemyError as exc:
            _raise_read_error(exc, operation="load-telemetry")
    finally:
        if owns_engine:
            dispose_engine(active_engine)


def load_telemetry_window(  # noqa: C901 - coordina una fotografía transaccional multitabla.
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    pipeline_run_ids: Sequence[str] = (),
    clip_ids: Sequence[str] = (),
    settings: DatabaseSettings | None = None,
    engine: Engine | None = None,
) -> pd.DataFrame:
    """Carga una cohorte raw acotada usando un intervalo UTC semiabierto y parámetros SQL."""

    start_time = pd.Timestamp(start)
    end_time = pd.Timestamp(end)
    if start_time.tzinfo is None or end_time.tzinfo is None:
        raise ValueError("Telemetry window bounds must be timezone-aware.")
    if end_time <= start_time:
        raise ValueError("Telemetry window end must be after start.")
    if any(not isinstance(value, str) or not value.strip() for value in pipeline_run_ids):
        raise ValueError("Pipeline run filters must be non-empty strings.")
    if any(not isinstance(value, str) or not value.strip() for value in clip_ids):
        raise ValueError("Clip filters must be non-empty strings.")

    clauses = ["record_time >= :start", "record_time < :end"]
    params: dict[str, object] = {"start": start_time, "end": end_time}
    if pipeline_run_ids:
        clauses.append("pipeline_run_id IN :pipeline_run_ids")
        params["pipeline_run_ids"] = list(pipeline_run_ids)
    if clip_ids:
        clauses.append("clip_id IN :clip_ids")
        params["clip_ids"] = list(clip_ids)
    statement = text(
        f"""
SELECT id, pipeline_run_id, clip_id, continuity_id, record_time, avg_speed,
       count_car, count_truck, count_bus, count_motorcycle, count_bicycle,
       total_vehicles, near_zero_motion_count, stationary_confirmed_count,
       rejected_speed_count, recovered_track_count, speed_sample_count,
       speed_measurement_quality, optical_flow_tracking_ratio,
       telemetry_schema_version, numeric_representation
FROM {RAW_TABLE}
WHERE {" AND ".join(clauses)}
ORDER BY clip_id, record_time
"""
    )
    if pipeline_run_ids:
        statement = statement.bindparams(bindparam("pipeline_run_ids", expanding=True))
    if clip_ids:
        statement = statement.bindparams(bindparam("clip_ids", expanding=True))

    active_engine, owns_engine = _active_engine(settings, engine)
    try:
        try:
            return pd.read_sql(statement, active_engine, params=params)
        except SQLAlchemyError as exc:
            _raise_read_error(exc, operation="load-telemetry-window")
    finally:
        if owns_engine:
            dispose_engine(active_engine)


def load_human_ground_truth(
    settings: DatabaseSettings | None = None,
    engine: Engine | None = None,
    *,
    feature_schema_version: str | None = FEATURE_SCHEMA_VERSION,
) -> pd.DataFrame:
    """Carga etiquetas efectivas de un schema explícito, en modo read-only."""

    active_engine, owns_engine = _active_engine(settings, engine)
    try:
        try:
            return pd.read_sql(
                text(HUMAN_GROUND_TRUTH_QUERY),
                active_engine,
                params={"feature_schema_version": feature_schema_version},
            )
        except SQLAlchemyError as exc:
            _raise_read_error(exc, operation="load-human-ground-truth")
    finally:
        if owns_engine:
            dispose_engine(active_engine)


def load_human_feedback_components(
    settings: DatabaseSettings | None = None,
    engine: Engine | None = None,
    *,
    feature_schema_version: str | None = FEATURE_SCHEMA_VERSION,
) -> dict[str, pd.DataFrame]:
    """Carga la historia HITL completa para resolver correcciones globalmente."""

    active_engine, owns_engine = _active_engine(settings, engine)
    params = {"feature_schema_version": feature_schema_version}
    try:
        try:
            with active_engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as connection:
                with connection.begin():
                    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                    return {
                        "features": pd.read_sql(
                            text(HUMAN_FEATURES_QUERY), connection, params=params
                        ),
                        "predictions": pd.read_sql(
                            text(HUMAN_PREDICTIONS_QUERY), connection, params=params
                        ),
                        "validations": pd.read_sql(
                            text(HUMAN_VALIDATIONS_QUERY), connection, params=params
                        ),
                    }
        except SQLAlchemyError as exc:
            _raise_read_error(exc, operation="load-human-feedback-components")
    finally:
        if owns_engine:
            dispose_engine(active_engine)


def _raise_read_error(exc: SQLAlchemyError, *, operation: str) -> NoReturn:
    sqlstate = getattr(getattr(exc, "orig", None), "pgcode", None)
    raise DatabaseOperationError(
        "PostgreSQL read operation failed.",
        operation=operation,
        sqlstate=sqlstate,
    ) from None


__all__ = [
    "EFFECTIVE_LABELS_VIEW",
    "HUMAN_GROUND_TRUTH_QUERY",
    "HUMAN_FEATURES_QUERY",
    "HUMAN_PREDICTIONS_QUERY",
    "HUMAN_VALIDATIONS_QUERY",
    "LEGACY_TELEMETRY_QUERY",
    "RAW_TABLE",
    "TELEMETRY_QUERY",
    "load_human_ground_truth",
    "load_human_feedback_components",
    "load_telemetry",
    "load_telemetry_window",
]
