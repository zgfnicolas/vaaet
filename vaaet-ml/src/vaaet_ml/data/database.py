# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Fachada compatible 4.x para la operación PostgreSQL del laboratorio.

La configuración, la conexión, las consultas read-only y los backups viven en
módulos cohesionados para que un consumidor no cargue responsabilidades ajenas.
"""

import os  # noqa: F401 - superficie de parcheo compatible para pruebas 4.x.
import shutil  # noqa: F401 - superficie de parcheo compatible para pruebas 4.x.
import subprocess  # noqa: F401 - superficie de parcheo compatible para pruebas 4.x.
from pathlib import Path

import pandas as pd  # noqa: F401 - superficie de parcheo compatible para pruebas 4.x.

from vaaet_ml.data.database_backup import (
    FEATURE_TABLE,
    PREDICTION_TABLE,
    VALIDATION_TABLE,
    get_pg_restore_version,
    inspect_backup_catalog,
    parse_sql_dump,
    parse_sql_dump_tables,
    restore_backup_to_sql,
)
from vaaet_ml.data.database_connection import (
    DatabaseHealth,
    _settings_url,
    create_admin_engine,
    database_engine,
    dispose_engine,
    execute_with_retry,
    get_engine,
    inspect_database,
    test_connection,
)
from vaaet_ml.data.database_queries import (
    EFFECTIVE_LABELS_VIEW,
    HUMAN_GROUND_TRUTH_QUERY,
    LEGACY_TELEMETRY_QUERY,
    RAW_TABLE,
    TELEMETRY_QUERY,
    load_human_feedback_components,
    load_human_ground_truth,
    load_telemetry,
    load_telemetry_window,
)
from vaaet_ml.data.database_settings import (
    DatabaseAdminSettings,
    DatabaseEndpointSettings,
    DatabasePoolSettings,
    DatabaseProfile,
    DatabaseRetrySettings,
    DatabaseSettings,
    cleanup_temporary_root_certificate,
    get_optional_database_settings,
    load_database_admin_settings,
    load_database_settings,
    load_reviewer_id,
)


def load_from_backup(
    backup_path: str | Path,
    cache_csv: str | Path | None = None,
    pg_restore_path: str | Path | None = None,
) -> pd.DataFrame:
    """Conserva puntos de parcheo 4.x mientras delega el lector al módulo dueño."""

    sql_path = restore_backup_to_sql(backup_path, pg_restore_path=pg_restore_path)
    try:
        frame = parse_sql_dump(sql_path)
    finally:
        sql_path.unlink(missing_ok=True)
    if cache_csv is not None:
        destination = Path(cache_csv)
        destination.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(destination, index=False)
    return frame


__all__ = [
    "EFFECTIVE_LABELS_VIEW",
    "FEATURE_TABLE",
    "HUMAN_GROUND_TRUTH_QUERY",
    "LEGACY_TELEMETRY_QUERY",
    "PREDICTION_TABLE",
    "RAW_TABLE",
    "TELEMETRY_QUERY",
    "VALIDATION_TABLE",
    "DatabaseHealth",
    "DatabaseAdminSettings",
    "DatabaseEndpointSettings",
    "DatabasePoolSettings",
    "DatabaseProfile",
    "DatabaseRetrySettings",
    "DatabaseSettings",
    "cleanup_temporary_root_certificate",
    "create_admin_engine",
    "database_engine",
    "dispose_engine",
    "execute_with_retry",
    "get_engine",
    "get_optional_database_settings",
    "get_pg_restore_version",
    "inspect_backup_catalog",
    "inspect_database",
    "load_database_settings",
    "load_database_admin_settings",
    "load_from_backup",
    "load_human_feedback_components",
    "load_human_ground_truth",
    "load_reviewer_id",
    "load_telemetry",
    "load_telemetry_window",
    "parse_sql_dump",
    "parse_sql_dump_tables",
    "restore_backup_to_sql",
    "test_connection",
    "_settings_url",
]
