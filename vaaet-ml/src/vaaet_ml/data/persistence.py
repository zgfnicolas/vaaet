# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Fachada 4.x para escrituras PostgreSQL compartidas."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

import pandas as pd
from sqlalchemy.engine import Engine
from vaaet.settings import MODEL_VERSION
from vaaet_persistence.persistence import (
    PersistResult,
    ensure_persistence_tables,
    ensure_raw_telemetry_table,
)
from vaaet_persistence.persistence import (
    persist_classified_telemetry as _persist_classified_telemetry,
)
from vaaet_persistence.persistence import persist_raw_telemetry as _persist_raw_telemetry
from vaaet_persistence.settings import DatabaseSettings

from vaaet_ml import __version__
from vaaet_ml.data.database_connection import get_engine


def persist_raw_telemetry(
    df: pd.DataFrame,
    *,
    settings: DatabaseSettings | Mapping[str, str] | None = None,
    config: Mapping[str, str] | None = None,
    engine: Engine | None = None,
    pipeline_run_id: UUID | str | None = None,
) -> int:
    """Delega la escritura raw y conserva inputs 4.x deprecados."""

    if engine is not None or df.empty:
        return _persist_raw_telemetry(
            df,
            engine=engine,
            settings=settings if isinstance(settings, DatabaseSettings) else None,
            pipeline_run_id=pipeline_run_id,
            application_name="vaaet-ml-collection",
            application_version=__version__,
        )
    active_engine = get_engine(settings or config)
    try:
        return _persist_raw_telemetry(
            df,
            engine=active_engine,
            pipeline_run_id=pipeline_run_id,
            application_name="vaaet-ml-collection",
            application_version=__version__,
        )
    finally:
        active_engine.dispose()


def persist_classified_telemetry(
    df: pd.DataFrame,
    *,
    settings: DatabaseSettings | Mapping[str, str] | None = None,
    config: Mapping[str, str] | None = None,
    engine: Engine | None = None,
    model_version: str = MODEL_VERSION,
    model_revision: str | None = None,
    pipeline_run_id: UUID | str | None = None,
) -> PersistResult:
    """Delega features y predicciones como una única transacción."""

    if engine is not None or df.empty:
        return _persist_classified_telemetry(
            df,
            engine=engine,
            settings=settings if isinstance(settings, DatabaseSettings) else None,
            model_version=model_version,
            model_revision=model_revision,
            pipeline_run_id=pipeline_run_id,
            application_name="vaaet-ml-inference",
            application_version=__version__,
        )
    active_engine = get_engine(settings or config)
    try:
        return _persist_classified_telemetry(
            df,
            engine=active_engine,
            model_version=model_version,
            model_revision=model_revision,
            pipeline_run_id=pipeline_run_id,
            application_name="vaaet-ml-inference",
            application_version=__version__,
        )
    finally:
        active_engine.dispose()


__all__ = [
    "PersistResult",
    "ensure_persistence_tables",
    "ensure_raw_telemetry_table",
    "persist_classified_telemetry",
    "persist_raw_telemetry",
]
