# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Fachada 4.x de configuración PostgreSQL y adaptador de Secrets Colab."""

from __future__ import annotations

import os
import warnings
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.engine import make_url
from vaaet_persistence.exceptions import DatabaseNotConfiguredError
from vaaet_persistence.settings import (
    DatabaseAdminSettings,
    DatabaseEndpointSettings,
    DatabasePoolSettings,
    DatabaseProfile,
    DatabaseRetrySettings,
    DatabaseSettings,
    cleanup_temporary_root_certificate,
)
from vaaet_persistence.settings import (
    get_optional_database_settings as _get_optional_database_settings,
)
from vaaet_persistence.settings import (
    load_database_admin_settings as _load_database_admin_settings,
)
from vaaet_persistence.settings import load_database_settings as _load_database_settings
from vaaet_persistence.settings import load_reviewer_id as _load_reviewer_id

from vaaet_ml import __version__
from vaaet_ml.settings import DEFAULT_DB_PORT

_ADMIN_URL_OPTIONS = {"application_name", "connect_timeout", "sslmode", "sslrootcert"}


def _environment_value(name: str) -> str | None:
    return (os.environ.get(name) or "").strip() or None


def _colab_secret(name: str) -> str | None:
    """Lee Secrets sólo en la frontera del notebook y tolera su ausencia."""

    try:
        from google.colab import userdata
    except ImportError:
        return None
    try:
        value = userdata.get(name)
    except Exception:  # pragma: no cover - frontera externa no determinista
        return None
    return str(value).strip() if value else None


def _notebook_value(name: str) -> str | None:
    return _colab_secret(name) or _environment_value(name)


def _legacy_aware_provider(
    profile: DatabaseProfile,
    read_value: Callable[[str], str | None],
    *,
    allow_legacy: bool,
) -> Callable[[str], str | None]:
    """Traduce variables 4.x sin trasladar compatibilidad al componente compartido."""

    prefix = f"VAAET_{profile.value.upper()}_DB"
    modern = {
        "VAAET_DB_HOST": read_value("VAAET_DB_HOST"),
        "VAAET_DB_NAME": read_value("VAAET_DB_NAME"),
        f"{prefix}_USER": read_value(f"{prefix}_USER"),
        f"{prefix}_PASSWORD": read_value(f"{prefix}_PASSWORD"),
    }
    if not allow_legacy or all(modern.values()):
        return read_value
    legacy = {
        "VAAET_DB_HOST": read_value("DB_HOST"),
        "VAAET_DB_PORT": read_value("DB_PORT"),
        "VAAET_DB_NAME": read_value("DB_NAME"),
        f"{prefix}_USER": read_value("DB_USER"),
        f"{prefix}_PASSWORD": read_value("DB_PASSWORD"),
    }
    if not all(
        legacy[name]
        for name in ("VAAET_DB_HOST", "VAAET_DB_NAME", f"{prefix}_USER", f"{prefix}_PASSWORD")
    ):
        return read_value
    warnings.warn(
        "DB_* variables are deprecated and will be removed in VAAET 5.0; "
        "use VAAET_DB_* plus profile-specific credentials.",
        FutureWarning,
        stacklevel=3,
    )

    def translated(name: str) -> str | None:
        return read_value(name) or legacy.get(name)

    return translated


def load_database_settings(
    profile: DatabaseProfile | str,
    *,
    env_file: str | Path | None = None,
    allow_legacy: bool = True,
) -> DatabaseSettings:
    """Conserva Secrets → entorno y delega validación a la biblioteca compartida."""

    active_profile = DatabaseProfile(profile)
    provider = _legacy_aware_provider(
        active_profile, _notebook_value, allow_legacy=allow_legacy
    )
    return _load_database_settings(
        active_profile,
        application_name=f"vaaet-ml-{active_profile.value}",
        application_version=__version__,
        env_file=env_file,
        value_provider=provider,
    )


def _legacy_admin_settings(raw_url: str) -> DatabaseAdminSettings:
    try:
        url = make_url(raw_url)
    except Exception as exc:
        raise DatabaseNotConfiguredError("VAAET_DATABASE_ADMIN_URL is invalid.") from exc
    if not url.drivername.startswith("postgresql"):
        raise DatabaseNotConfiguredError("VAAET_DATABASE_ADMIN_URL must target PostgreSQL.")
    if not url.host or not url.database or not url.username or url.password is None:
        raise DatabaseNotConfiguredError(
            "VAAET_DATABASE_ADMIN_URL requires host, database and administrator credentials."
        )
    options = dict(url.query)
    unsupported = sorted(set(options) - _ADMIN_URL_OPTIONS)
    if unsupported:
        raise DatabaseNotConfiguredError(
            "VAAET_DATABASE_ADMIN_URL contains unsupported connection options: "
            + ", ".join(unsupported)
        )
    endpoint = DatabaseEndpointSettings(
        host=url.host,
        port=url.port or int(DEFAULT_DB_PORT),
        database=url.database,
        sslmode=str(options.get("sslmode") or "verify-full").lower(),
        sslrootcert=str(options["sslrootcert"]) if "sslrootcert" in options else None,
        connect_timeout_seconds=int(options.get("connect_timeout", 10)),
    )
    return DatabaseAdminSettings(
        endpoint=endpoint,
        username=url.username,
        password=url.password,
        application_name=str(options.get("application_name") or "vaaet-ml-migration"),
        application_version=__version__,
    )


def load_database_admin_settings(
    *, env_file: str | Path | None = None, allow_legacy: bool = True
) -> DatabaseAdminSettings:
    """Mantiene la URL administrativa 4.x fuera de la API nueva."""

    raw_url = _environment_value("VAAET_DATABASE_ADMIN_URL")
    has_typed_credentials = bool(
        _environment_value("VAAET_ADMIN_DB_USER")
        or _environment_value("VAAET_ADMIN_DB_PASSWORD")
    )
    if allow_legacy and raw_url and not has_typed_credentials:
        warnings.warn(
            "VAAET_DATABASE_ADMIN_URL is deprecated and will be removed in VAAET 5.0; "
            "use VAAET_DB_* plus VAAET_ADMIN_DB_USER/PASSWORD.",
            FutureWarning,
            stacklevel=2,
        )
        return _legacy_admin_settings(raw_url)
    return _load_database_admin_settings(
        application_name="vaaet-ml-migration",
        application_version=__version__,
        env_file=env_file,
        value_provider=_environment_value,
    )


def get_optional_database_settings(
    profile: DatabaseProfile | str,
    *,
    env_file: str | Path | None = None,
) -> DatabaseSettings | None:
    active_profile = DatabaseProfile(profile)
    provider = _legacy_aware_provider(active_profile, _notebook_value, allow_legacy=True)
    return _get_optional_database_settings(
        active_profile,
        application_name=f"vaaet-ml-{active_profile.value}",
        application_version=__version__,
        env_file=env_file,
        value_provider=provider,
    )


def load_reviewer_id() -> str:
    return _load_reviewer_id(value_provider=_notebook_value)


__all__ = [
    "DatabaseAdminSettings",
    "DatabaseEndpointSettings",
    "DatabasePoolSettings",
    "DatabaseProfile",
    "DatabaseRetrySettings",
    "DatabaseSettings",
    "cleanup_temporary_root_certificate",
    "get_optional_database_settings",
    "load_database_admin_settings",
    "load_database_settings",
    "load_reviewer_id",
]
