# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Fachada 4.x de consultas tabulares PostgreSQL."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd
from sqlalchemy.engine import Engine
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet_persistence.connection import dispose_engine
from vaaet_persistence.queries import (
    EFFECTIVE_LABELS_VIEW,
    HUMAN_FEATURES_QUERY,
    HUMAN_GROUND_TRUTH_QUERY,
    HUMAN_PREDICTIONS_QUERY,
    HUMAN_VALIDATIONS_QUERY,
    LEGACY_TELEMETRY_QUERY,
    RAW_TABLE,
    TELEMETRY_QUERY,
)
from vaaet_persistence.queries import load_human_feedback_components as _load_components
from vaaet_persistence.queries import load_human_ground_truth as _load_ground_truth
from vaaet_persistence.queries import load_telemetry as _load_telemetry
from vaaet_persistence.queries import load_telemetry_window as _load_window
from vaaet_persistence.settings import DatabaseSettings

from vaaet_ml.data.database_connection import get_engine


def _resolve(
    settings: DatabaseSettings | Mapping[str, str] | None, engine: Engine | None
) -> tuple[Engine, bool]:
    if engine is not None:
        return engine, False
    return get_engine(settings), True


def load_telemetry(
    settings: DatabaseSettings | Mapping[str, str] | None = None,
    engine: Engine | None = None,
) -> pd.DataFrame:
    active, owns = _resolve(settings, engine)
    try:
        return _load_telemetry(engine=active)
    finally:
        if owns:
            dispose_engine(active)


def load_telemetry_window(
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    pipeline_run_ids: Sequence[str] = (),
    clip_ids: Sequence[str] = (),
    settings: DatabaseSettings | Mapping[str, str] | None = None,
    engine: Engine | None = None,
) -> pd.DataFrame:
    """Conserva validación temprana aun para el perfil implícito 4.x."""

    start_time = pd.Timestamp(start)
    end_time = pd.Timestamp(end)
    if start_time.tzinfo is None or end_time.tzinfo is None:
        raise ValueError("Telemetry window bounds must be timezone-aware.")
    if end_time <= start_time:
        raise ValueError("Telemetry window end must be after start.")
    active, owns = _resolve(settings, engine)
    try:
        return _load_window(
            start=start,
            end=end,
            pipeline_run_ids=pipeline_run_ids,
            clip_ids=clip_ids,
            engine=active,
        )
    finally:
        if owns:
            dispose_engine(active)


def load_human_ground_truth(
    settings: DatabaseSettings | Mapping[str, str] | None = None,
    engine: Engine | None = None,
    *,
    feature_schema_version: str | None = FEATURE_SCHEMA_VERSION,
) -> pd.DataFrame:
    active, owns = _resolve(settings, engine)
    try:
        return _load_ground_truth(
            engine=active, feature_schema_version=feature_schema_version
        )
    finally:
        if owns:
            dispose_engine(active)


def load_human_feedback_components(
    settings: DatabaseSettings | Mapping[str, str] | None = None,
    engine: Engine | None = None,
    *,
    feature_schema_version: str | None = FEATURE_SCHEMA_VERSION,
) -> dict[str, pd.DataFrame]:
    active, owns = _resolve(settings, engine)
    try:
        return _load_components(
            engine=active, feature_schema_version=feature_schema_version
        )
    finally:
        if owns:
            dispose_engine(active)


__all__ = [
    "EFFECTIVE_LABELS_VIEW",
    "HUMAN_FEATURES_QUERY",
    "HUMAN_GROUND_TRUTH_QUERY",
    "HUMAN_PREDICTIONS_QUERY",
    "HUMAN_VALIDATIONS_QUERY",
    "LEGACY_TELEMETRY_QUERY",
    "RAW_TABLE",
    "TELEMETRY_QUERY",
    "load_human_feedback_components",
    "load_human_ground_truth",
    "load_telemetry",
    "load_telemetry_window",
]
