# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Contratos tipados que comparten los módulos portables de VAAET.

Estas dataclasses validan los registros internos relevantes y evitan que los
notebooks o consumidores futuros alteren sus contratos silenciosamente.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, cast

import pandas as pd

from vaaet.settings import (
    DATA_ORIGINS,
    MODEL_STATE_LABELS,
    STATE_LABELS,
    SYNTHETIC_SCENARIOS,
    VEHICLE_TYPES,
)
from vaaet.timestamps import normalize_timestamp

DataOrigin = Literal["real", "synthetic"]
SyntheticScenario = Literal["observed", "accident", "congestion"]

__all__ = [
    "ClassificationRecord",
    "DataOrigin",
    "EngineeredTelemetryRecord",
    "SyntheticScenario",
    "TelemetryRecord",
    "TrackSpeedState",
    "TrafficStatePrediction",
]


@dataclass(frozen=True)
class TrafficStatePrediction:
    """Representa la predicción compacta que muestra el video.

    Vive fuera de ``vaaet.vision`` para que la inferencia no cargue OpenCV;
    ``vaaet.vision.pipeline`` y ``vaaet.vision.analysis`` la reexportan.
    """

    state: int
    label: str
    confidence: float
    evidence: float | None = None
    incident_candidate: bool = False

    def __post_init__(self) -> None:
        if self.state not in STATE_LABELS:
            raise ValueError(f"Unsupported traffic state: {self.state}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Prediction confidence must be between 0 and 1")


def _coerce_timestamp(value: object, field_name: str) -> pd.Timestamp:
    timestamp_input = cast(str | int | float | date | datetime, value)
    return normalize_timestamp(timestamp_input, field_name=field_name)


def _coerce_int(value: object, field_name: str) -> int:
    """Convierte un escalar externo y conserva un error de frontera claro."""

    try:
        return int(cast(str | int | float, value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _coerce_float(value: object, field_name: str) -> float:
    """Convierte un escalar externo sin filtrar detalles del adaptador."""

    try:
        return float(cast(str | int | float, value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc


def _coerce_data_origin(value: object) -> DataOrigin:
    origin = str(value)
    if origin not in DATA_ORIGINS:
        raise ValueError(f"data_origin must be one of {DATA_ORIGINS}")
    return cast(DataOrigin, origin)


def _coerce_synthetic_scenario(value: object) -> SyntheticScenario:
    scenario = str(value)
    if scenario not in SYNTHETIC_SCENARIOS:
        raise ValueError(f"synthetic_scenario must be one of {SYNTHETIC_SCENARIOS}")
    return cast(SyntheticScenario, scenario)


def _validate_non_negative_int(value: int, field_name: str) -> None:
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0")


def _validate_ratio(value: float, field_name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be within [0, 1]")


def _validate_origin(origin: str, scenario: str) -> None:
    if origin not in DATA_ORIGINS:
        raise ValueError(f"data_origin must be one of {DATA_ORIGINS}")
    if scenario not in SYNTHETIC_SCENARIOS:
        raise ValueError(f"synthetic_scenario must be one of {SYNTHETIC_SCENARIOS}")
    if origin == "real" and scenario != "observed":
        raise ValueError("real records must use synthetic_scenario='observed'")
    if origin == "synthetic" and scenario == "observed":
        raise ValueError("synthetic records must declare a non-observed scenario")


@dataclass(frozen=True)
class TelemetryRecord:
    """Representa una fila validada de telemetría cruda."""

    id: int
    record_time: pd.Timestamp
    avg_speed: float
    count_car: int
    count_truck: int
    count_bus: int
    count_motorcycle: int
    count_bicycle: int
    total_vehicles: int
    clip_id: str | None = None
    data_origin: DataOrigin = "real"
    synthetic_scenario: SyntheticScenario = "observed"
    near_zero_motion_count: int = 0
    stationary_confirmed_count: int = 0
    rejected_speed_count: int = 0
    recovered_track_count: int = 0
    speed_sample_count: int = 0
    speed_measurement_quality: float = 1.0

    def __post_init__(self) -> None:
        if self.id <= 0:
            raise ValueError("id must be > 0")
        object.__setattr__(
            self,
            "record_time",
            _coerce_timestamp(self.record_time, "record_time"),
        )
        if self.avg_speed < 0:
            raise ValueError("avg_speed must be >= 0")
        for field_name in (
            "count_car",
            "count_truck",
            "count_bus",
            "count_motorcycle",
            "count_bicycle",
            "total_vehicles",
            "near_zero_motion_count",
            "stationary_confirmed_count",
            "rejected_speed_count",
            "recovered_track_count",
            "speed_sample_count",
        ):
            _validate_non_negative_int(int(getattr(self, field_name)), field_name)

        total_counted = (
            self.count_car
            + self.count_truck
            + self.count_bus
            + self.count_motorcycle
            + self.count_bicycle
        )
        if self.total_vehicles < total_counted:
            raise ValueError("total_vehicles cannot be lower than the counted vehicles")
        _validate_ratio(self.speed_measurement_quality, "speed_measurement_quality")
        _validate_origin(self.data_origin, self.synthetic_scenario)

    @classmethod
    def from_mapping(cls, row: Mapping[str, object]) -> TelemetryRecord:
        """Convierte un registro externo y valida cada valor en la frontera."""

        return cls(
            id=_coerce_int(row["id"], "id"),
            record_time=row["record_time"],
            avg_speed=_coerce_float(row["avg_speed"], "avg_speed"),
            count_car=_coerce_int(row["count_car"], "count_car"),
            count_truck=_coerce_int(row["count_truck"], "count_truck"),
            count_bus=_coerce_int(row["count_bus"], "count_bus"),
            count_motorcycle=_coerce_int(row["count_motorcycle"], "count_motorcycle"),
            count_bicycle=_coerce_int(row["count_bicycle"], "count_bicycle"),
            total_vehicles=_coerce_int(row["total_vehicles"], "total_vehicles"),
            clip_id=str(row["clip_id"]) if row.get("clip_id") is not None else None,
            data_origin=_coerce_data_origin(row.get("data_origin", "real")),
            synthetic_scenario=_coerce_synthetic_scenario(row.get("synthetic_scenario", "observed")),
            near_zero_motion_count=_coerce_int(
                row.get("near_zero_motion_count", 0), "near_zero_motion_count"
            ),
            stationary_confirmed_count=_coerce_int(
                row.get("stationary_confirmed_count", 0), "stationary_confirmed_count"
            ),
            rejected_speed_count=_coerce_int(
                row.get("rejected_speed_count", 0), "rejected_speed_count"
            ),
            recovered_track_count=_coerce_int(
                row.get("recovered_track_count", 0), "recovered_track_count"
            ),
            speed_sample_count=_coerce_int(row.get("speed_sample_count", 0), "speed_sample_count"),
            speed_measurement_quality=_coerce_float(
                row.get("speed_measurement_quality", 1.0), "speed_measurement_quality"
            ),
        )


@dataclass(frozen=True)
class EngineeredTelemetryRecord:
    """Representa una fila validada de features para el clasificador."""

    source_record_id: int
    record_time: pd.Timestamp
    avg_speed: float
    total_vehicles: int
    heavy_vehicle_ratio: float
    delta_speed: float
    delta_count: int
    transition_flag: int
    speed_variance: float
    cumulative_delta_speed: float
    low_speed_persistence: float
    speed_measurement_quality: float
    near_zero_motion_ratio: float
    stationary_confirmed_ratio: float
    hour_of_day: int
    weather_condition: int
    data_origin: DataOrigin = "real"
    synthetic_scenario: SyntheticScenario = "observed"

    def __post_init__(self) -> None:
        if self.source_record_id <= 0:
            raise ValueError("source_record_id must be > 0")
        object.__setattr__(
            self,
            "record_time",
            _coerce_timestamp(self.record_time, "record_time"),
        )
        if self.avg_speed < 0:
            raise ValueError("avg_speed must be >= 0")
        _validate_non_negative_int(self.total_vehicles, "total_vehicles")
        _validate_ratio(self.heavy_vehicle_ratio, "heavy_vehicle_ratio")
        _validate_ratio(
            self.speed_measurement_quality,
            "speed_measurement_quality",
        )
        _validate_ratio(self.near_zero_motion_ratio, "near_zero_motion_ratio")
        _validate_ratio(
            self.stationary_confirmed_ratio,
            "stationary_confirmed_ratio",
        )
        if self.transition_flag not in (0, 1):
            raise ValueError("transition_flag must be binary")
        if not 0 <= self.hour_of_day <= 23:
            raise ValueError("hour_of_day must be within [0, 23]")
        if self.weather_condition not in (0, 1):
            raise ValueError("weather_condition must be binary")
        if self.speed_variance < 0:
            raise ValueError("speed_variance must be >= 0")
        _validate_origin(self.data_origin, self.synthetic_scenario)


@dataclass(frozen=True)
class ClassificationRecord:
    """Representa una predicción automática separada de la verdad humana."""

    telemetry_feature_id: int
    traffic_state: int
    state_label: str
    confidence: float
    model_version: str
    data_origin: DataOrigin = "real"
    synthetic_scenario: SyntheticScenario = "observed"
    model_traffic_state: int | None = None
    model_confidence: float | None = None
    accident_rule_triggered: bool = False
    accident_evidence_score: float = 0.0

    def __post_init__(self) -> None:
        if self.telemetry_feature_id <= 0:
            raise ValueError("telemetry_feature_id must be > 0")
        if self.traffic_state not in MODEL_STATE_LABELS:
            raise ValueError("Automatic traffic_state must be Normal, Reduced, or Congested.")
        expected_label = MODEL_STATE_LABELS[self.traffic_state]
        if self.state_label != expected_label:
            raise ValueError(
                f"state_label must match STATE_LABELS[{self.traffic_state}]={expected_label!r}"
            )
        _validate_ratio(self.confidence, "confidence")
        if not self.model_version:
            raise ValueError("model_version must be non-empty")
        if (
            self.model_traffic_state is not None
            and self.model_traffic_state not in MODEL_STATE_LABELS
        ):
            raise ValueError("model_traffic_state must be a stable traffic state")
        if self.model_confidence is not None:
            _validate_ratio(self.model_confidence, "model_confidence")
        _validate_ratio(self.accident_evidence_score, "accident_evidence_score")
        _validate_origin(self.data_origin, self.synthetic_scenario)


@dataclass(frozen=True)
class TrackSpeedState:
    """Representa el estado validado de velocidad de un track."""

    track_id: int
    vehicle_type: str
    history_length: int
    flow_tracking_ratio: float
    recovered_after_gap: int
    is_stationary: bool
    is_near_zero_motion: bool = False
    candidate_speed: float | None = None
    smoothed_speed: float | None = None
    measurement_quality: float = 1.0

    def __post_init__(self) -> None:
        if self.track_id <= 0:
            raise ValueError("track_id must be > 0")
        if self.vehicle_type not in VEHICLE_TYPES:
            raise ValueError(f"vehicle_type must be one of {VEHICLE_TYPES}")
        if self.history_length < 0:
            raise ValueError("history_length must be >= 0")
        _validate_ratio(self.flow_tracking_ratio, "flow_tracking_ratio")
        if self.recovered_after_gap < 0:
            raise ValueError("recovered_after_gap must be >= 0")
        if self.candidate_speed is not None and self.candidate_speed < 0:
            raise ValueError("candidate_speed must be >= 0")
        if self.smoothed_speed is not None and self.smoothed_speed < 0:
            raise ValueError("smoothed_speed must be >= 0")
        _validate_ratio(self.measurement_quality, "measurement_quality")
