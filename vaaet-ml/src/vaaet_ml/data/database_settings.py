# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Configuración portable, segura y tipada de PostgreSQL para el laboratorio.

El proveedor no forma parte del contrato: una instalación es compatible sólo si
expone PostgreSQL estándar con TLS y privilegios suficientes para el esquema
VAAET. Las migraciones usan una identidad administrativa fuera de Colab; los
workflows usan uno de los perfiles de mínimo privilegio.
"""

from __future__ import annotations

import os
import stat
import tempfile
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TypedDict

from sqlalchemy.engine import make_url
from vaaet.logging import get_logger

from vaaet_ml.exceptions import DatabaseNotConfiguredError
from vaaet_ml.settings import DEFAULT_DB_PORT

logger = get_logger(__name__)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_SSL_MODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
_ADMIN_URL_OPTIONS = {"application_name", "connect_timeout", "sslmode", "sslrootcert"}
_DEFAULT_POOL_SIZE = 2
_DEFAULT_MAX_OVERFLOW = 0
_DEFAULT_POOL_RECYCLE_SECONDS = 300
_DEFAULT_RETRY_ATTEMPTS = 3
_DEFAULT_RETRY_BASE_DELAY_SECONDS = 0.5


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


@dataclass(frozen=True)
class DatabaseEndpointSettings:
    """Endpoint PostgreSQL compartido, sin identidad ni secreto de acceso."""

    host: str
    port: int
    database: str
    sslmode: str = "verify-full"
    sslrootcert: str | None = None
    connect_timeout_seconds: int = 10
    _temporary_root_cert: bool = field(default=False, repr=False, compare=False)

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
        if self.sslmode == "verify-full" and not self.sslrootcert:
            raise DatabaseNotConfiguredError(
                "sslmode=verify-full requires VAAET_DB_SSLROOTCERT or "
                "VAAET_DB_SSLROOTCERT_PEM. Use sslmode=require only as an explicit, "
                "documented fallback when the provider cannot expose a CA certificate."
            )


@dataclass(frozen=True)
class DatabasePoolSettings:
    """Límites conservadores de conexiones para runtimes de laboratorio."""

    pool_size: int = _DEFAULT_POOL_SIZE
    max_overflow: int = _DEFAULT_MAX_OVERFLOW
    recycle_seconds: int = _DEFAULT_POOL_RECYCLE_SECONDS

    def __post_init__(self) -> None:
        if not 1 <= int(self.pool_size) <= 5:
            raise ValueError("PostgreSQL pool size must be between 1 and 5.")
        if not 0 <= int(self.max_overflow) <= 5:
            raise ValueError("PostgreSQL pool overflow must be between 0 and 5.")
        if not 0 <= int(self.recycle_seconds) <= 3600:
            raise ValueError("PostgreSQL pool recycle must be between 0 and 3600 seconds.")
        if self.pool_size + self.max_overflow > 5:
            raise ValueError("PostgreSQL pool size plus overflow must not exceed 5 connections.")


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
    connect_timeout_seconds: int = 10
    application_name: str | None = None
    _temporary_root_cert: bool = field(default=False, repr=False, compare=False)
    pool: DatabasePoolSettings = field(default_factory=DatabasePoolSettings)
    retry: DatabaseRetrySettings = field(default_factory=DatabaseRetrySettings)

    def __post_init__(self) -> None:
        if not self.username or not self.password:
            raise DatabaseNotConfiguredError(
                f"Incomplete PostgreSQL configuration for profile={self.profile.value}."
            )
        _ = self.endpoint

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
            connect_timeout_seconds=self.connect_timeout_seconds,
            _temporary_root_cert=self._temporary_root_cert,
        )

    @property
    def application(self) -> str:
        """Devuelve una identidad segura para observabilidad del cliente SQL."""

        return self.application_name or f"vaaet-{self.profile.value}-4.6.1"


@dataclass(frozen=True, repr=False)
class DatabaseAdminSettings:
    """Identidad administrativa para Alembic y provisionamiento fuera de Colab."""

    endpoint: DatabaseEndpointSettings
    username: str
    password: str = field(repr=False)
    application_name: str | None = None

    def __post_init__(self) -> None:
        if not self.username or not self.password:
            raise DatabaseNotConfiguredError(
                "PostgreSQL administrator requires username and password."
            )

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
    def application(self) -> str:
        """Identifica las sesiones administrativas sin revelar el proveedor."""

        return self.application_name or "vaaet-migration-4.6.1"


def _colab_secret(name: str) -> str | None:
    """Lee un secreto de Colab sin hacer de su ausencia un error de runtime."""

    try:
        from google.colab import userdata
    except ImportError:
        return None
    try:
        value = userdata.get(name)
    except Exception:  # pragma: no cover - frontera de Colab no determinista
        return None
    return str(value).strip() if value else None


def _setting(name: str) -> str | None:
    """Obtiene secretos de Colab antes de consultar variables de entorno."""

    return _colab_secret(name) or _environment_setting(name)


def _environment_setting(name: str) -> str | None:
    """Lee sólo el entorno local o CI; nunca consulta APIs de notebook."""

    return (os.environ.get(name) or "").strip() or None


def _materialize_root_certificate(pem: str) -> str:
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
    """Valida TLS y libera un PEM temporal si la configuración es inválida."""

    root_cert = values["sslrootcert"]
    temporary_cert = False
    if values["sslrootcert_pem"] and not root_cert:
        root_cert = _materialize_root_certificate(values["sslrootcert_pem"].replace("\\n", "\n"))
        temporary_cert = True
    try:
        return DatabaseEndpointSettings(
            host=values["host"] or "",
            port=_parse_int(values["port"], default=int(DEFAULT_DB_PORT), name="VAAET_DB_PORT"),
            database=values["database"] or "",
            sslmode=(values["sslmode"] or "verify-full").lower(),
            sslrootcert=root_cert,
            connect_timeout_seconds=_parse_int(
                values["connect_timeout"], default=10, name="VAAET_DB_CONNECT_TIMEOUT"
            ),
            _temporary_root_cert=temporary_cert,
        )
    except Exception:
        if temporary_cert and root_cert:
            Path(root_cert).unlink(missing_ok=True)
        raise


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
    env_file: str | Path | None = None,
    allow_legacy: bool = True,
) -> DatabaseSettings:
    """Carga un perfil desde Secrets Colab o entorno sin registrar credenciales."""

    active_profile = DatabaseProfile(profile)
    _load_env_file(env_file)
    prefix = _PROFILE_ENV_PREFIX[active_profile]
    values = _endpoint_values(_setting)
    username = _setting(f"{prefix}_USER")
    password = _setting(f"{prefix}_PASSWORD")

    if allow_legacy and _missing_workflow_values(values, username, password, prefix):
        legacy = {
            "host": _setting("DB_HOST"),
            "port": _setting("DB_PORT"),
            "database": _setting("DB_NAME"),
            "username": _setting("DB_USER"),
            "password": _setting("DB_PASSWORD"),
        }
        if all(legacy[name] for name in ("host", "database", "username", "password")):
            warnings.warn(
                "DB_* variables are deprecated and will be removed in VAAET 5.0; "
                "use VAAET_DB_* plus profile-specific credentials.",
                FutureWarning,
                stacklevel=2,
            )
            values["host"] = values["host"] or legacy["host"]
            values["port"] = values["port"] or legacy["port"]
            values["database"] = values["database"] or legacy["database"]
            username = username or legacy["username"]
            password = password or legacy["password"]

    missing = _missing_workflow_values(values, username, password, prefix)
    if missing:
        raise DatabaseNotConfiguredError(
            f"PostgreSQL profile={active_profile.value} is not configured; missing: "
            + ", ".join(missing)
        )

    pool = _load_pool_settings(_setting)
    retry = _load_retry_settings(_setting)
    endpoint = _build_endpoint(values)
    if endpoint.sslmode == "require":
        logger.warning(
            "PostgreSQL TLS encrypts transport but does not verify server identity (sslmode=require)."
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
        connect_timeout_seconds=endpoint.connect_timeout_seconds,
        _temporary_root_cert=endpoint._temporary_root_cert,
        pool=pool,
        retry=retry,
    )


def _load_legacy_admin_settings(raw_url: str) -> DatabaseAdminSettings:
    """Convierte la URL administrativa 4.x a contratos seguros y estructurados."""

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
        connect_timeout_seconds=_parse_int(
            str(options["connect_timeout"]) if "connect_timeout" in options else None,
            default=10,
            name="VAAET_DATABASE_ADMIN_URL connect_timeout",
        ),
    )
    return DatabaseAdminSettings(
        endpoint=endpoint,
        username=url.username,
        password=url.password,
        application_name=str(options["application_name"])
        if "application_name" in options
        else None,
    )


def load_database_admin_settings(
    *, env_file: str | Path | None = None, allow_legacy: bool = True
) -> DatabaseAdminSettings:
    """Carga administración local o CI sin consultar Secrets ni APIs de Colab."""

    _load_env_file(env_file)
    values = _endpoint_values(_environment_setting)
    username = _environment_setting("VAAET_ADMIN_DB_USER")
    password = _environment_setting("VAAET_ADMIN_DB_PASSWORD")
    raw_url = _environment_setting("VAAET_DATABASE_ADMIN_URL")

    # Una URL 4.x completa no se mezcla con un endpoint de workflow que haya
    # quedado en el entorno. La nueva vía sólo prevalece al aportar alguna de
    # sus credenciales administrativas, evitando combinar dos identidades.
    if allow_legacy and raw_url and not username and not password:
        warnings.warn(
            "VAAET_DATABASE_ADMIN_URL is deprecated and will be removed in VAAET 5.0; "
            "use VAAET_DB_* plus VAAET_ADMIN_DB_USER/PASSWORD.",
            FutureWarning,
            stacklevel=2,
        )
        return _load_legacy_admin_settings(raw_url)

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
            endpoint=endpoint, username=str(username), password=str(password)
        )

    raise DatabaseNotConfiguredError(
        "PostgreSQL administrator is not configured; set VAAET_DB_* plus "
        "VAAET_ADMIN_DB_USER/PASSWORD outside Colab."
    )


def cleanup_temporary_root_certificate(
    settings: DatabaseSettings | DatabaseAdminSettings,
) -> None:
    """Elimina la CA efímera creada desde un secreto PEM al cerrar la conexión."""

    endpoint = settings.endpoint
    if endpoint._temporary_root_cert and endpoint.sslrootcert:
        Path(endpoint.sslrootcert).unlink(missing_ok=True)


def get_optional_database_settings(
    profile: DatabaseProfile | str,
    *,
    env_file: str | Path | None = None,
) -> DatabaseSettings | None:
    """Devuelve un perfil opcional sin ocultar errores de configuración válidos."""

    try:
        return load_database_settings(profile, env_file=env_file)
    except DatabaseNotConfiguredError:
        logger.info(
            "Optional PostgreSQL profile=%s is not configured", DatabaseProfile(profile).value
        )
        return None


def load_reviewer_id() -> str:
    """Carga el seudónimo estable del revisor sin registrarlo en logs."""

    reviewer_id = _setting("VAAET_REVIEWER_ID")
    if not reviewer_id:
        raise DatabaseNotConfiguredError(
            "VAAET_REVIEWER_ID is required in Colab Secrets or the local environment."
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
