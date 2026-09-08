# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Fachada 4.x de conexión; la implementación canónica es compartida."""

from __future__ import annotations

import warnings
from collections.abc import Mapping

from sqlalchemy.engine import Engine
from vaaet_persistence.connection import (
    DatabaseHealth,
    _settings_url,
    create_admin_engine,
    database_engine,
    execute_with_retry,
    inspect_database,
    test_connection,
)
from vaaet_persistence.connection import get_engine as _get_engine
from vaaet_persistence.settings import DatabaseProfile, DatabaseSettings

from vaaet_ml.data.database_settings import load_database_settings
from vaaet_ml.settings import DEFAULT_DB_PORT

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def get_engine(settings: DatabaseSettings | Mapping[str, str] | None = None) -> Engine:
    """Conserva mappings y perfil training implícito sólo durante VAAET 4.x."""

    if settings is None:
        settings = load_database_settings(DatabaseProfile.TRAINING)
    if not isinstance(settings, DatabaseSettings):
        warnings.warn(
            "Dictionary DB configs are deprecated; use DatabaseSettings.",
            DeprecationWarning,
            stacklevel=2,
        )
        host = settings.get("host", "")
        settings = DatabaseSettings(
            profile=DatabaseProfile.TRAINING,
            host=host,
            port=int(settings.get("port", DEFAULT_DB_PORT)),
            database=settings.get("dbname", settings.get("database", "")),
            username=settings.get("user", settings.get("username", "")),
            password=settings.get("password", ""),
            sslmode=settings.get(
                "sslmode", "disable" if host in _LOCAL_HOSTS else "require"
            ),
            sslrootcert=settings.get("sslrootcert"),
            application_name="vaaet-ml-training",
            application_version="4.x-compatibility",
        )
    return _get_engine(settings)


__all__ = [
    "DatabaseHealth",
    "_settings_url",
    "create_admin_engine",
    "database_engine",
    "execute_with_retry",
    "get_engine",
    "inspect_database",
    "test_connection",
]
