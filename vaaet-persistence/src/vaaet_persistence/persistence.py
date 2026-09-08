# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Escrituras idempotentes sobre los schemas PostgreSQL migrados de VAAET."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID, uuid4

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import ProgrammingError
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.continuity import normalize_continuity_frame
from vaaet.logging import get_logger
from vaaet.settings import FEATURE_COLS, MODEL_VERSION, STATE_LABELS, TELEMETRY_SCHEMA_VERSION
from vaaet.timestamps import normalize_timestamp

from vaaet_persistence.connection import get_engine
from vaaet_persistence.pipeline_runs import PipelineRunMetadata, PipelineWorkflow, pipeline_run
from vaaet_persistence.settings import DatabaseSettings

logger = get_logger(__name__)

RAW_TABLE = "vaaet_raw.traffic_data"
FEATURE_TABLE = "vaaet_ml.telemetry_features"
PREDICTION_TABLE = "vaaet_ml.traffic_predictions"


@dataclass(frozen=True)
class PersistResult:
    """Resume las filas persistidas y la corrida que conserva su lineage."""

    telemetry_rows: int
    classification_rows: int
    pipeline_run_id: str


def _operation_engine(
    settings: DatabaseSettings | None, engine: Engine | None
) -> tuple[Engine, bool]:
    """Resuelve el engine y conserva explícitamente quién debe liberarlo."""

    if engine is not None:
        return engine, False
    if settings is None:
        raise ValueError("PostgreSQL writes require explicit settings or an engine.")
    return get_engine(settings), True


def _utc_timestamp(value: object) -> object:
    if value is None or pd.isna(value):
        return None
    return normalize_timestamp(value).to_pydatetime()


def _nullable_int(value: object) -> int | None:
    return None if value is None or pd.isna(value) else int(value)


def _nullable_float(value: object) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def _nullable_str(value: object) -> str | None:
    return None if value is None or pd.isna(value) else str(value)


def _require_migrated_schema(exc: Exception) -> RuntimeError:
    return RuntimeError(
        "The VAAET PostgreSQL schema is unavailable. Apply `alembic upgrade head` "
        "with the administrator profile before running a notebook."
    )


INSERT_RAW_SQL = f"""
INSERT INTO {RAW_TABLE} (
    pipeline_run_id, clip_id, continuity_id, record_time, avg_speed, count_car, count_truck,
    count_bus, count_motorcycle, count_bicycle, total_vehicles,
    near_zero_motion_count, stationary_confirmed_count, rejected_speed_count,
    recovered_track_count, speed_sample_count, speed_measurement_quality,
    optical_flow_tracking_ratio, telemetry_schema_version
) VALUES (
    :pipeline_run_id, :clip_id, :continuity_id, :record_time, :avg_speed, :count_car, :count_truck,
    :count_bus, :count_motorcycle, :count_bicycle, :total_vehicles,
    :near_zero_motion_count, :stationary_confirmed_count, :rejected_speed_count,
    :recovered_track_count, :speed_sample_count, :speed_measurement_quality,
    :optical_flow_tracking_ratio, :telemetry_schema_version
)
ON CONFLICT (clip_id, record_time) DO NOTHING
RETURNING id
"""

SELECT_RAW_SQL = f"""
SELECT id, pipeline_run_id, clip_id, continuity_id, record_time, avg_speed,
       count_car, count_truck, count_bus, count_motorcycle, count_bicycle,
       total_vehicles, near_zero_motion_count, stationary_confirmed_count,
       rejected_speed_count, recovered_track_count, speed_sample_count,
       speed_measurement_quality, optical_flow_tracking_ratio,
       telemetry_schema_version
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
    weather_condition
) VALUES (
    :source_record_id, :pipeline_run_id, :clip_id, :continuity_id, :record_time, :feature_schema_version,
    :avg_speed, :total_vehicles, :count_car, :count_truck, :count_bus,
    :count_motorcycle, :count_bicycle, :heavy_vehicle_ratio, :delta_speed, :delta_count,
    :transition_flag, :speed_variance, :cumulative_delta_speed, :low_speed_persistence,
    :speed_measurement_quality, :optical_flow_tracking_ratio, :near_zero_motion_ratio,
    :stationary_confirmed_ratio, :near_zero_motion_count, :stationary_confirmed_count,
    :rejected_speed_count, :recovered_track_count, :speed_sample_count,
    :telemetry_schema_version, :data_origin, :synthetic_scenario, :hour_of_day,
    :weather_condition
)
ON CONFLICT (pipeline_run_id, clip_id, record_time, feature_schema_version) DO NOTHING
RETURNING id
"""


INSERT_PREDICTION_SQL = f"""
INSERT INTO {PREDICTION_TABLE} (
    telemetry_feature_id, pipeline_run_id, classified_at, traffic_state, state_label,
    confidence, model_version, model_revision, model_traffic_state, model_state_label,
    model_confidence, probability_margin, decision_abstained, measurement_reliable,
    accident_rule_triggered, accident_alert_started, accident_evidence_score
) VALUES (
    :telemetry_feature_id, :pipeline_run_id, CURRENT_TIMESTAMP, :traffic_state, :state_label,
    :confidence, :model_version, :model_revision, :model_traffic_state, :model_state_label,
    :model_confidence, :probability_margin, :decision_abstained, :measurement_reliable,
    :accident_rule_triggered, :accident_alert_started, :accident_evidence_score
)
ON CONFLICT (telemetry_feature_id, model_revision) DO NOTHING
RETURNING id
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
       synthetic_scenario, hour_of_day, weather_condition
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
       accident_alert_started, accident_evidence_score
FROM {PREDICTION_TABLE}
WHERE telemetry_feature_id = :telemetry_feature_id
  AND model_revision = :model_revision
"""


def _raw_payload(row: pd.Series, pipeline_run_id: str) -> dict[str, object]:
    return {
        "pipeline_run_id": pipeline_run_id,
        "clip_id": str(row["clip_id"]),
        "continuity_id": str(row.get("continuity_id", f"{row['clip_id']}:continuity-0001")),
        "record_time": _utc_timestamp(row["record_time"]),
        "avg_speed": float(row["avg_speed"]),
        "count_car": int(row["count_car"]),
        "count_truck": int(row["count_truck"]),
        "count_bus": int(row["count_bus"]),
        "count_motorcycle": int(row["count_motorcycle"]),
        "count_bicycle": int(row["count_bicycle"]),
        "total_vehicles": int(row["total_vehicles"]),
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
    }


def _feature_payload(row: pd.Series, pipeline_run_id: str) -> dict[str, object]:
    source_id = row.get("source_record_id", row.get("id"))
    return {
        "source_record_id": _nullable_int(source_id),
        "pipeline_run_id": pipeline_run_id,
        "clip_id": str(row["clip_id"]),
        "continuity_id": str(row.get("continuity_id", f"{row['clip_id']}:continuity-0001")),
        "record_time": _utc_timestamp(row["record_time"]),
        "feature_schema_version": str(
            row.get("feature_schema_version", FEATURE_SCHEMA_VERSION)
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
        "telemetry_schema_version": _nullable_str(row.get("telemetry_schema_version")),
        "data_origin": str(row.get("data_origin", "real")),
        "synthetic_scenario": str(row.get("synthetic_scenario", "observed")),
        "hour_of_day": _nullable_int(row.get("hour_of_day")),
        "weather_condition": _nullable_int(row.get("weather_condition")),
    }


def _prediction_payload(
    row: pd.Series,
    *,
    feature_id: int,
    pipeline_run_id: str,
    model_version: str,
    model_revision: str,
) -> dict[str, object]:
    state = int(row.get("traffic_state", 0))
    model_state = int(row.get("model_traffic_state", state))
    if state not in (0, 1, 2) or model_state not in (0, 1, 2):
        raise ValueError(
            "Automatic predictions may contain only Normal, Reduced, or Congested; "
            "Accident belongs exclusively to vaaet_feedback.human_validations."
        )
    if bool(row.get("accident_gate_applied", False)):
        raise ValueError("The bundle forbids an automatic Accident gate override.")
    row_revision = row.get("model_revision")
    exact_revision = model_revision if row_revision is None or pd.isna(row_revision) else str(row_revision)
    row_version = row.get("model_version")
    semantic_version = model_version if row_version is None or pd.isna(row_version) else str(row_version)
    return {
        "telemetry_feature_id": feature_id,
        "pipeline_run_id": pipeline_run_id,
        "traffic_state": state,
        "state_label": str(row.get("state_label", STATE_LABELS[state])),
        "confidence": float(row.get("confidence", 0.0)),
        "model_version": semantic_version,
        "model_revision": exact_revision,
        "model_traffic_state": model_state,
        "model_state_label": str(row.get("model_state_label", STATE_LABELS[model_state])),
        "model_confidence": float(row.get("model_confidence", row.get("confidence", 0.0))),
        "probability_margin": _nullable_float(row.get("probability_margin")),
        "decision_abstained": bool(row.get("decision_abstained", False)),
        "measurement_reliable": (
            bool(row.get("measurement_reliable"))
            if pd.notna(row.get("measurement_reliable"))
            else None
        ),
        "accident_rule_triggered": bool(row.get("accident_rule_triggered", False)),
        "accident_alert_started": bool(row.get("accident_alert_started", False)),
        "accident_evidence_score": float(row.get("accident_evidence_score", 0.0)),
    }


def persist_raw_telemetry(
    df: pd.DataFrame,
    *,
    settings: DatabaseSettings | None = None,
    engine: Engine | None = None,
    pipeline_run_id: UUID | str | None = None,
    application_name: str | None = None,
    application_version: str | None = None,
) -> int:
    """Persiste telemetría cruda de forma idempotente dentro de una corrida."""

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
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Raw telemetry is missing required columns: {sorted(missing)}")
    if pipeline_run_id is None and (not application_name or not application_version):
        raise ValueError(
            "Automatic pipeline lineage requires application_name and application_version."
        )
    run_id = str(pipeline_run_id or uuid4())
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
            raise _require_migrated_schema(exc) from exc
        finally:
            if owns_engine:
                active_engine.dispose()
    normalized = normalize_continuity_frame(df)
    try:
        with active_engine.begin() as connection:
            inserted = _persist_raw_rows(connection, normalized, run_id)
    except ProgrammingError as exc:
        raise _require_migrated_schema(exc) from exc
    finally:
        if owns_engine:
            active_engine.dispose()
    return inserted


def _persist_raw_rows(
    connection: Connection,
    frame: pd.DataFrame,
    run_id: str,
) -> int:
    """Inserta filas nuevas y comprueba el contenido de colisiones naturales."""

    inserted = 0
    for _, row in frame.iterrows():
        payload = _raw_payload(row, run_id)
        raw_id = connection.execute(text(INSERT_RAW_SQL), payload).scalar_one_or_none()
        if raw_id is None:
            existing = connection.execute(
                text(SELECT_RAW_SQL), payload
            ).mappings().one()
            _assert_idempotent(
                existing,
                payload,
                "raw telemetry",
                ignored_fields={"pipeline_run_id"},
            )
        else:
            inserted += 1
    return inserted


def persist_classified_telemetry(
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

    run_id = str(pipeline_run_id or uuid4())
    if df.empty:
        return PersistResult(0, 0, run_id)
    required = {
        "clip_id",
        "continuity_id",
        "record_time",
        "feature_schema_version",
        "traffic_state",
        *FEATURE_COLS,
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Classified telemetry is missing required columns: {sorted(missing)}")
    schema_versions = df["feature_schema_version"].dropna().astype(str).unique()
    if len(schema_versions) != 1 or schema_versions[0] != FEATURE_SCHEMA_VERSION:
        raise ValueError(
            "Operational prediction persistence requires the current feature schema."
        )
    resolved_revision = _resolve_model_revision(df, model_revision)
    if pipeline_run_id is None and (not application_name or not application_version):
        raise ValueError(
            "Automatic pipeline lineage requires application_name and application_version."
        )
    active_engine, owns_engine = _operation_engine(settings, engine)
    if pipeline_run_id is None:
        try:
            clip_ids = df["clip_id"].dropna().astype(str).unique()
            metadata = PipelineRunMetadata(
                workflow=PipelineWorkflow.INFERENCE,
                application_name=application_name,
                application_version=application_version,
                source_kind="dataframe",
                clip_id=str(clip_ids[0]) if len(clip_ids) == 1 else None,
                input_rows=len(df),
                telemetry_schema_version=None,
                model_revision=resolved_revision,
            )
            with pipeline_run(metadata, engine=active_engine) as run:
                persisted = persist_classified_telemetry(
                    df,
                    engine=active_engine,
                    model_version=model_version,
                    model_revision=resolved_revision,
                    pipeline_run_id=run.id,
                )
                run.set_output_rows(persisted.classification_rows)
            return persisted
        except ProgrammingError as exc:
            raise _require_migrated_schema(exc) from exc
        finally:
            if owns_engine:
                active_engine.dispose()
    try:
        with active_engine.begin() as connection:
            telemetry_rows, prediction_rows = _persist_classified_rows(
                connection, df, run_id, model_version, resolved_revision
            )
    except ProgrammingError as exc:
        raise _require_migrated_schema(exc) from exc
    finally:
        if owns_engine:
            active_engine.dispose()
    logger.info(
        "Persistence completed: telemetry_rows=%s prediction_rows=%s model_version=%s run=%s",
        telemetry_rows,
        prediction_rows,
        model_version,
        run_id,
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
    telemetry_rows = 0
    prediction_rows = 0
    for _, row in frame.iterrows():
        feature_payload = _feature_payload(row, run_id)
        feature_id = connection.execute(
            text(INSERT_FEATURE_SQL), feature_payload
        ).scalar_one_or_none()
        if feature_id is None:
            existing = connection.execute(
                text(SELECT_FEATURE_SQL), feature_payload
            ).mappings().one()
            _assert_idempotent(existing, feature_payload, "feature")
            feature_id = existing["id"]
        prediction_payload = _prediction_payload(
            row,
            feature_id=int(feature_id),
            pipeline_run_id=run_id,
            model_version=model_version,
            model_revision=model_revision,
        )
        prediction_id = connection.execute(
            text(INSERT_PREDICTION_SQL), prediction_payload
        ).scalar_one_or_none()
        if prediction_id is None:
            existing = connection.execute(
                text(SELECT_PREDICTION_SQL), prediction_payload
            ).mappings().one()
            _assert_idempotent(existing, prediction_payload, "prediction")
        telemetry_rows += 1
        prediction_rows += 1
    return telemetry_rows, prediction_rows


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
        raise ValueError(
            f"Immutable {kind} idempotency conflict in fields: {sorted(differences)}"
        )


def _database_values_equal(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, UUID) or isinstance(right, UUID):
        return str(left) == str(right)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= 1e-9
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
