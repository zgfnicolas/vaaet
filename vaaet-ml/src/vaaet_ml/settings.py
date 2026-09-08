# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Configuración exclusiva del laboratorio y reexportaciones compatibles."""

from __future__ import annotations

import os

from vaaet.settings import (
    ACCIDENT_GATE_MIN_EVIDENCE_SCORE,
    CANONICAL_TIMEZONE,
    DATA_ORIGIN_COL,
    DATA_ORIGINS,
    FEATURE_COLS,
    INCIDENT_PERSISTENCE_MINUTES,
    LABELING_THRESHOLDS,
    MODEL_STATE_LABELS,
    MODEL_VERSION,
    N_MODEL_STATES,
    N_STATES,
    SPEED_MEASUREMENT_QUALITY_MIN,
    SPEED_RANGE,
    STATE_LABELS,
    SYNTHETIC_SCENARIO_COL,
    SYNTHETIC_SCENARIOS,
    TELEMETRY_SCHEMA_VERSION,
    TRAFFIC_LOCAL_TIMEZONE,
    VEHICLE_TYPES,
)
from vaaet_persistence.constants import DATABASE_SCHEMA_VERSION, DATABASE_SCHEMAS
from vaaet_persistence.constants import DEFAULT_DB_PORT as _SHARED_DEFAULT_DB_PORT

RANDOM_SEED: int = 42
MODEL_DIR: str = os.path.join("artifacts", "traffic-state")
DATA_PROCESSED_DIR: str = os.path.join("data", "processed")
DATA_RAW_DIR: str = os.path.join("data", "raw")
MODEL_PATH: str = os.path.join(MODEL_DIR, "traffic_classifier.keras")
SCALER_PATH: str = os.path.join(MODEL_DIR, "feature_scaler.joblib")
LABEL_MAP_PATH: str = os.path.join(MODEL_DIR, "label_mapping.joblib")
DRIVE_ARTIFACT_DIR: str = os.path.join("MyDrive", "vaaet-ml", "artifacts", "traffic-state")
DB_ENV_VARS: tuple[str, ...] = ("VAAET_DB_HOST", "VAAET_DB_PORT", "VAAET_DB_NAME")
DEFAULT_DB_PORT: str = str(_SHARED_DEFAULT_DB_PORT)

# Estos nombres conservan la compatibilidad de notebooks 4.x. El código nuevo
# debe importar los contratos portables directamente desde ``vaaet.settings``.
__all__ = [
    "ACCIDENT_GATE_MIN_EVIDENCE_SCORE",
    "CANONICAL_TIMEZONE",
    "DATABASE_SCHEMAS",
    "DATABASE_SCHEMA_VERSION",
    "DATA_ORIGINS",
    "DATA_ORIGIN_COL",
    "DATA_PROCESSED_DIR",
    "DATA_RAW_DIR",
    "DB_ENV_VARS",
    "DEFAULT_DB_PORT",
    "DRIVE_ARTIFACT_DIR",
    "FEATURE_COLS",
    "INCIDENT_PERSISTENCE_MINUTES",
    "LABELING_THRESHOLDS",
    "MODEL_DIR",
    "MODEL_PATH",
    "MODEL_STATE_LABELS",
    "MODEL_VERSION",
    "N_MODEL_STATES",
    "N_STATES",
    "RANDOM_SEED",
    "SCALER_PATH",
    "SPEED_MEASUREMENT_QUALITY_MIN",
    "SPEED_RANGE",
    "STATE_LABELS",
    "SYNTHETIC_SCENARIOS",
    "SYNTHETIC_SCENARIO_COL",
    "TELEMETRY_SCHEMA_VERSION",
    "TRAFFIC_LOCAL_TIMEZONE",
    "VEHICLE_TYPES",
]
