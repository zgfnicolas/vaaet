# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Configuración portable, segura y tipada de PostgreSQL para consumidores VAAET.

El proveedor no forma parte del contrato: una instalación es compatible sólo si
expone PostgreSQL estándar con TLS y privilegios suficientes para el esquema
VAAET. Las migraciones usan una identidad administrativa fuera de Colab; los
workflows usan uno de los perfiles de mínimo privilegio.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TypedDict

from vaaet.logging import get_logger

from vaaet_persistence.constants import DEFAULT_DB_PORT
from vaaet_persistence.exceptions import DatabaseNotConfiguredError

logger = get_logger(__name__)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_SSL_MODES = {"disable", "require", "verify-ca", "verify-full"}
_DEFAULT_POOL_SIZE = 2
_DEFAULT_MAX_OVERFLOW = 0
_DEFAULT_POOL_RECYCLE_SECONDS = 300
_DEFAULT_POOL_TIMEOUT_SECONDS = 30
_DEFAULT_STATEMENT_TIMEOUT_SECONDS = 120
_DEFAULT_LOCK_TIMEOUT_SECONDS = 5
_DEFAULT_RETRY_ATTEMPTS = 3
_DEFAULT_RETRY_BASE_DELAY_SECONDS = 0.5
_APPLICATION_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _validate_application_component(value: str | None, *, label: str) -> None:
    if value is not None and _APPLICATION_COMPONENT.fullmatch(value) is None:
        raise ValueError(
            f"{label} must be a 1-64 character application identifier without secrets."
        )


class DatabaseProfile(str, Enum):
    """Identidad de mínimo privilegio usada por cada workflow."""

    COLLECTION = "collection"
    INFERENCE = "inference"
    TRAINING = "training"
    REVIEW = "review"


_PROFILE_ENV_PREFIX = {
    DatabaseProfile.COLLECTION: "VAAET_COLLECTION_DB",
    DatabaseProfile.INFERENCE: "VAAET_INFERENCE_DB",
    DatabaseProfile.TRAINING: "VAAET_TRAINING_DB",
    DatabaseProfile.REVIEW: "VAAET_REVIEW_DB",
}


class _EndpointValues(TypedDict):
    host: str | None
    port: str | None
    database: str | None
    sslmode: str | None
    sslrootcert: str | None
    sslrootcert_pem: str | None
    connect_timeout: str | None
    statement_timeout: str | None
    lock_timeout: str | None


@dataclass(frozen=True)
class DatabaseEndpointSettings:
    """Endpoint PostgreSQL compartido, sin identidad ni secreto de acceso."""

    host: str
    port: int
    database: str
    sslmode: str = "verify-full"
    sslrootcert: str | None = None
    sslrootcert_pem: str | None = field(default=None, repr=False, compare=False)
    connect_timeout_seconds: int = 10
    statement_timeout_seconds: int = _DEFAULT_STATEMENT_TIMEOUT_SECONDS
    lock_timeout_seconds: int = _DEFAULT_LOCK_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.host or not self.database:
            raise DatabaseNotConfiguredError("PostgreSQL endpoint requires host and database.")
        if not 1 <= int(self.port) <= 65535:
            raise ValueError("PostgreSQL port must be between 1 and 65535.")
        if not 1 <= int(self.connect_timeout_seconds) <= 60:
            raise ValueError("PostgreSQL connect timeout must be between 1 and 60 seconds.")
        if self.sslmode not in _SSL_MODES:
            raise ValueError(f"Unsupported PostgreSQL sslmode: {self.sslmode}")
        if self.sslmode == "disable" and self.host.lower() not in _LOCAL_HOSTS:
            raise ValueError("sslmode=disable is allowed only for an explicit localhost endpoint.")
        if self.sslrootcert and not Path(self.sslrootcert).is_file():
            raise DatabaseNotConfiguredError(
                "VAAET_DB_SSLROOTCERT must reference an existing CA certificate file."
            )
        if self.sslmode == "verify-full" and not (self.sslrootcert or self.sslrootcert_pem):
            raise DatabaseNotConfiguredError(
                "sslmode=verify-full requires VAAET_DB_SSLROOTCERT or "
                "VAAET_DB_SSLROOTCERT_PEM. Use sslmode=require only as an explicit, "
                "documented fallback when the provider cannot expose a CA certificate."
            )
        if not 1 <= int(self.statement_timeout_seconds) <= 3600:
            raise ValueError("PostgreSQL statement timeout must be between 1 and 3600 seconds.")
        if not 1 <= int(self.lock_timeout_seconds) <= 60:
            raise ValueError("PostgreSQL lock timeout must be between 1 and 60 seconds.")


@dataclass(frozen=True)
class DatabasePoolSettings:
    """Límites conservadores de conexiones para consumidores VAAET."""

    pool_size: int = _DEFAULT_POOL_SIZE
    max_overflow: int = _DEFAULT_MAX_OVERFLOW
    recycle_seconds: int = _DEFAULT_POOL_RECYCLE_SECONDS
    timeout_seconds: int = _DEFAULT_POOL_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not 1 <= int(self.pool_size) <= 5:
            raise ValueError("PostgreSQL pool size must be between 1 and 5.")
        if not 0 <= int(self.max_overflow) <= 5:
            raise ValueError("PostgreSQL pool overflow must be between 0 and 5.")
        if not 0 <= int(self.recycle_seconds) <= 3600:
            raise ValueError("PostgreSQL pool recycle must be between 0 and 3600 seconds.")
        if self.pool_size + self.max_overflow > 5:
            raise ValueError("PostgreSQL pool size plus overflow must not exceed 5 connections.")
        if not 1 <= int(self.timeout_seconds) <= 120:
            raise ValueError("PostgreSQL pool timeout must be between 1 and 120 seconds.")


@dataclass(frozen=True)
class DatabaseRetrySettings:
    """Reintentos acotados para comprobar conectividad sin ocultar fallos persistentes."""

    attempts: int = _DEFAULT_RETRY_ATTEMPTS
    base_delay_seconds: float = _DEFAULT_RETRY_BASE_DELAY_SECONDS

    def __post_init__(self) -> None:
        if not 1 <= int(self.attempts) <= 5:
            raise ValueError("PostgreSQL retry attempts must be between 1 and 5.")
        if not 0 <= float(self.base_delay_seconds) <= 5:
            raise ValueError("PostgreSQL retry base delay must be between 0 and 5 seconds.")


@dataclass(frozen=True, repr=False)
class DatabaseSettings:
    """Configuración de un perfil operativo con representación libre de secretos.

    Conserva la firma plana 4.x para no romper notebooks y consumidores. Las
    propiedades ``endpoint`` y ``pool`` exponen los contratos reutilizables.
    """

    profile: DatabaseProfile
    host: str
    port: int
    database: str
    username: str
    password: str = field(repr=False)
    sslmode: str = "verify-full"
    sslrootcert: str | None = None
    sslrootcert_pem: str | None = field(default=None, repr=False, compare=False)
    connect_timeout_seconds: int = 10
    statement_timeout_seconds: int = _DEFAULT_STATEMENT_TIMEOUT_SECONDS
    lock_timeout_seconds: int = _DEFAULT_LOCK_TIMEOUT_SECONDS
    application_name: str | None = None
    application_version: str | None = None
    pool: DatabasePoolSettings = field(default_factory=DatabasePoolSettings)
    retry: DatabaseRetrySettings = field(default_factory=DatabaseRetrySettings)

    def __post_init__(self) -> None:
        if not self.username or not self.password:
            raise DatabaseNotConfiguredError(
                f"Incomplete PostgreSQL configuration for profile={self.profile.value}."
            )
        _ = self.endpoint
        _validate_application_component(self.application_name, label="application_name")
        _validate_application_component(self.application_version, label="application_version")

    def __repr__(self) -> str:
        return (
            "DatabaseSettings("
            f"profile={self.profile.value!r}, host={self.host!r}, port={self.port!r}, "
            f"database={self.database!r}, username='<redacted>', password='<redacted>', "
            f"sslmode={self.sslmode!r})"
        )

    @property
    def endpoint(self) -> DatabaseEndpointSettings:
        """Devuelve el endpoint validado sin credenciales del perfil."""

        return DatabaseEndpointSettings(
            host=self.host,
            port=self.port,
            database=self.database,
            sslmode=self.sslmode,
            sslrootcert=self.sslrootcert,
            sslrootcert_pem=self.sslrootcert_pem,
            connect_timeout_seconds=self.connect_timeout_seconds,
            statement_timeout_seconds=self.statement_timeout_seconds,
            lock_timeout_seconds=self.lock_timeout_seconds,
        )

    @property
    def application(self) -> str:
        """Devuelve una identidad segura para observabilidad del cliente SQL."""

        name = self.application_name or f"vaaet-{self.profile.value}"
        return f"{name}/{self.application_version}" if self.application_version else name


@dataclass(frozen=True, repr=False)
class DatabaseAdminSettings:
    """Identidad administrativa para Alembic y provisionamiento fuera de Colab."""

    endpoint: DatabaseEndpointSettings
    username: str
    password: str = field(repr=False)
    application_name: str | None = None
    application_version: str | None = None

    def __post_init__(self) -> None:
        if not self.username or not self.password:
            raise DatabaseNotConfiguredError(
                "PostgreSQL administrator requires username and password."
            )
        _validate_application_component(self.application_name, label="application_name")
        _validate_application_component(self.application_version, label="application_version")

    def __repr__(self) -> str:
        return (
            "DatabaseAdminSettings("
            f"host={self.host!r}, port={self.port!r}, database={self.database!r}, "
            "username='<redacted>', password='<redacted>', "
            f"sslmode={self.sslmode!r})"
        )

    @property
    def host(self) -> str:
        """Expone el host del endpoint para la fábrica SQLAlchemy."""

        return self.endpoint.host

    @property
    def port(self) -> int:
        """Expone el puerto del endpoint para la fábrica SQLAlchemy."""

        return self.endpoint.port

    @property
    def database(self) -> str:
        """Expone la base del endpoint para la fábrica SQLAlchemy."""

        return self.endpoint.database

    @property
    def sslmode(self) -> str:
        """Expone el modo TLS validado del endpoint."""

        return self.endpoint.sslmode

    @property
    def sslrootcert(self) -> str | None:
        """Expone la CA validada del endpoint, si corresponde."""

        return self.endpoint.sslrootcert

    @property
    def connect_timeout_seconds(self) -> int:
        """Expone el timeout validado del endpoint."""

        return self.endpoint.connect_timeout_seconds

    @property
    def statement_timeout_seconds(self) -> int:
        return self.endpoint.statement_timeout_seconds

    @property
    def lock_timeout_seconds(self) -> int:
        return self.endpoint.lock_timeout_seconds

    @property
    def application(self) -> str:
        """Identifica las sesiones administrativas sin revelar el proveedor."""

        name = self.application_name or "vaaet-migration"
        return f"{name}/{self.application_version}" if self.application_version else name


def _environment_setting(name: str) -> str | None:
    """Lee sólo el entorno local o CI; nunca consulta APIs de notebook."""

    value = os.environ.get(name)
    if value is None or value == "":
        return None
    if name.endswith("_PASSWORD"):
        return value
    return value.strip() or None


def materialize_root_certificate(pem: str) -> str:
    """Materializa un PEM temporal con permisos exclusivos del proceso actual."""

    descriptor, path = tempfile.mkstemp(prefix="vaaet-postgres-ca-", suffix=".pem")
    try:
        os.write(descriptor, pem.encode("utf-8"))
    finally:
        os.close(descriptor)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return path


def _load_env_file(env_file: str | Path | None) -> None:
    """Carga un archivo explícito para administración local, nunca implícitamente."""

    if env_file is None:
        return
    try:
        from dotenv import load_dotenv
    except ImportError as exc:  # pragma: no cover - dependencia opcional
        raise DatabaseNotConfiguredError(
            "python-dotenv is required when env_file is supplied."
        ) from exc
    load_dotenv(dotenv_path=Path(env_file), override=False)


def _endpoint_values(read_value: Callable[[str], str | None]) -> _EndpointValues:
    """Recolecta valores sin validar para permitir compatibilidad 4.x controlada."""

    return {
        "host": read_value("VAAET_DB_HOST"),
        "port": read_value("VAAET_DB_PORT"),
        "database": read_value("VAAET_DB_NAME"),
        "sslmode": read_value("VAAET_DB_SSLMODE"),
        "sslrootcert": read_value("VAAET_DB_SSLROOTCERT"),
        "sslrootcert_pem": read_value("VAAET_DB_SSLROOTCERT_PEM"),
        "connect_timeout": read_value("VAAET_DB_CONNECT_TIMEOUT"),
        "statement_timeout": read_value("VAAET_DB_STATEMENT_TIMEOUT"),
        "lock_timeout": read_value("VAAET_DB_LOCK_TIMEOUT"),
    }


def _parse_int(value: str | None, *, default: int, name: str) -> int:
    """Convierte un ajuste numérico sin incluir su valor potencialmente sensible."""

    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc


def _parse_float(value: str | None, *, default: float, name: str) -> float:
    """Convierte un límite decimal de runtime sin exponer su valor en errores."""

    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number.") from exc


def _build_endpoint(values: _EndpointValues) -> DatabaseEndpointSettings:
    """Valida el endpoint sin materializar secretos en el sistema de archivos."""

    return DatabaseEndpointSettings(
        host=values["host"] or "",
        port=_parse_int(values["port"], default=int(DEFAULT_DB_PORT), name="VAAET_DB_PORT"),
        database=values["database"] or "",
        sslmode=(values["sslmode"] or "verify-full").lower(),
        sslrootcert=values["sslrootcert"],
        sslrootcert_pem=values["sslrootcert_pem"],
        connect_timeout_seconds=_parse_int(
            values["connect_timeout"], default=10, name="VAAET_DB_CONNECT_TIMEOUT"
        ),
        statement_timeout_seconds=_parse_int(
            values["statement_timeout"],
            default=_DEFAULT_STATEMENT_TIMEOUT_SECONDS,
            name="VAAET_DB_STATEMENT_TIMEOUT",
        ),
        lock_timeout_seconds=_parse_int(
            values["lock_timeout"],
            default=_DEFAULT_LOCK_TIMEOUT_SECONDS,
            name="VAAET_DB_LOCK_TIMEOUT",
        ),
    )


def _load_pool_settings(read_value: Callable[[str], str | None]) -> DatabasePoolSettings:
    """Carga límites pequeños por entorno sin incorporar semántica de proveedor."""

    return DatabasePoolSettings(
        pool_size=_parse_int(
            read_value("VAAET_DB_POOL_SIZE"), default=_DEFAULT_POOL_SIZE, name="VAAET_DB_POOL_SIZE"
        ),
        max_overflow=_parse_int(
            read_value("VAAET_DB_MAX_OVERFLOW"),
            default=_DEFAULT_MAX_OVERFLOW,
            name="VAAET_DB_MAX_OVERFLOW",
        ),
        recycle_seconds=_parse_int(
            read_value("VAAET_DB_POOL_RECYCLE_SECONDS"),
            default=_DEFAULT_POOL_RECYCLE_SECONDS,
            name="VAAET_DB_POOL_RECYCLE_SECONDS",
        ),
        timeout_seconds=_parse_int(
            read_value("VAAET_DB_POOL_TIMEOUT"),
            default=_DEFAULT_POOL_TIMEOUT_SECONDS,
            name="VAAET_DB_POOL_TIMEOUT",
        ),
    )


def _load_retry_settings(read_value: Callable[[str], str | None]) -> DatabaseRetrySettings:
    """Carga reintentos explícitos sin transformar fallos persistentes en éxito."""

    return DatabaseRetrySettings(
        attempts=_parse_int(
            read_value("VAAET_DB_RETRY_ATTEMPTS"),
            default=_DEFAULT_RETRY_ATTEMPTS,
            name="VAAET_DB_RETRY_ATTEMPTS",
        ),
        base_delay_seconds=_parse_float(
            read_value("VAAET_DB_RETRY_BASE_DELAY_SECONDS"),
            default=_DEFAULT_RETRY_BASE_DELAY_SECONDS,
            name="VAAET_DB_RETRY_BASE_DELAY_SECONDS",
        ),
    )


def _missing_workflow_values(
    values: _EndpointValues, username: str | None, password: str | None, prefix: str
) -> list[str]:
    """Devuelve nombres de variables ausentes sin revelar sus valores."""

    return [
        name
        for name, value in {
            "VAAET_DB_HOST": values["host"],
            "VAAET_DB_NAME": values["database"],
            f"{prefix}_USER": username,
            f"{prefix}_PASSWORD": password,
        }.items()
        if not value
    ]


def load_database_settings(
    profile: DatabaseProfile | str,
    *,
    application_name: str,
    application_version: str,
    env_file: str | Path | None = None,
    value_provider: Callable[[str], str | None] | None = None,
) -> DatabaseSettings:
    """Carga un perfil explícito desde entorno o un proveedor de valores inyectado."""

    active_profile = DatabaseProfile(profile)
    if not application_name.strip() or not application_version.strip():
        raise ValueError("Database consumers require application_name and application_version.")
    _load_env_file(env_file)
    read_value = value_provider or _environment_setting
    prefix = _PROFILE_ENV_PREFIX[active_profile]
    values = _endpoint_values(read_value)
    username = read_value(f"{prefix}_USER")
    password = read_value(f"{prefix}_PASSWORD")

    missing = _missing_workflow_values(values, username, password, prefix)
    if missing:
        raise DatabaseNotConfiguredError(
            f"PostgreSQL profile={active_profile.value} is not configured; missing: "
            + ", ".join(missing)
        )

    pool = _load_pool_settings(read_value)
    retry = _load_retry_settings(read_value)
    endpoint = _build_endpoint(values)
    if endpoint.sslmode == "require":
        logger.warning(
            "PostgreSQL TLS encrypts transport but does not verify server identity (sslmode=require)."
        )
    elif endpoint.sslmode == "verify-ca":
        logger.warning(
            "PostgreSQL TLS validates the CA but not the endpoint hostname (sslmode=verify-ca)."
        )
    return DatabaseSettings(
        profile=active_profile,
        host=endpoint.host,
        port=endpoint.port,
        database=endpoint.database,
        username=str(username),
        password=str(password),
        sslmode=endpoint.sslmode,
        sslrootcert=endpoint.sslrootcert,
        sslrootcert_pem=endpoint.sslrootcert_pem,
        connect_timeout_seconds=endpoint.connect_timeout_seconds,
        statement_timeout_seconds=endpoint.statement_timeout_seconds,
        lock_timeout_seconds=endpoint.lock_timeout_seconds,
        application_name=application_name,
        application_version=application_version,
        pool=pool,
        retry=retry,
    )


def load_database_admin_settings(
    *,
    application_name: str,
    application_version: str,
    env_file: str | Path | None = None,
    value_provider: Callable[[str], str | None] | None = None,
) -> DatabaseAdminSettings:
    """Carga administración desde un proveedor explícito, fuera de notebooks."""

    if not application_name.strip() or not application_version.strip():
        raise ValueError("Database consumers require application_name and application_version.")
    _load_env_file(env_file)
    read_value = value_provider or _environment_setting
    values = _endpoint_values(read_value)
    username = read_value("VAAET_ADMIN_DB_USER")
    password = read_value("VAAET_ADMIN_DB_PASSWORD")

    typed_configuration_started = bool(username or password or values["host"] or values["database"])

    if typed_configuration_started:
        missing = _missing_workflow_values(values, username, password, "VAAET_ADMIN_DB")
        if missing:
            raise DatabaseNotConfiguredError(
                "PostgreSQL administrator is not configured; missing: " + ", ".join(missing)
            )
        endpoint = _build_endpoint(values)
        if endpoint.sslmode == "require":
            logger.warning(
                "PostgreSQL administrator uses sslmode=require without server identity verification."
            )
        return DatabaseAdminSettings(
            endpoint=endpoint,
            username=str(username),
            password=str(password),
            application_name=application_name,
            application_version=application_version,
        )

    raise DatabaseNotConfiguredError(
        "PostgreSQL administrator is not configured; set VAAET_DB_* plus "
        "VAAET_ADMIN_DB_USER/PASSWORD outside Colab."
    )


def cleanup_temporary_root_certificate(
    settings: DatabaseSettings | DatabaseAdminSettings,
) -> None:
    """Elimina la CA efímera creada desde un secreto PEM al cerrar la conexión."""

    # La CA PEM se materializa y elimina junto con el engine, no con settings.
    del settings


def get_optional_database_settings(
    profile: DatabaseProfile | str,
    *,
    application_name: str,
    application_version: str,
    env_file: str | Path | None = None,
    value_provider: Callable[[str], str | None] | None = None,
) -> DatabaseSettings | None:
    """Devuelve un perfil opcional sin ocultar errores de configuración válidos."""

    active_profile = DatabaseProfile(profile)
    _load_env_file(env_file)
    read_value = value_provider or _environment_setting
    prefix = _PROFILE_ENV_PREFIX[active_profile]
    username = read_value(f"{prefix}_USER")
    password = read_value(f"{prefix}_PASSWORD")
    if username is None and password is None:
        logger.info(
            "Optional PostgreSQL profile=%s is not configured", active_profile.value
        )
        return None
    return load_database_settings(
        active_profile,
        application_name=application_name,
        application_version=application_version,
        value_provider=read_value,
    )


def load_reviewer_id(
    *, value_provider: Callable[[str], str | None] | None = None
) -> str:
    """Carga el seudónimo estable del revisor sin registrarlo en logs."""

    reviewer_id = (value_provider or _environment_setting)("VAAET_REVIEWER_ID")
    if not reviewer_id:
        raise DatabaseNotConfiguredError(
            "VAAET_REVIEWER_ID is required by the configured value provider or environment."
        )
    return reviewer_id


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
