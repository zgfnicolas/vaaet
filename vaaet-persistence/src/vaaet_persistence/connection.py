# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Conexión, reintentos y diagnóstico seguro de PostgreSQL."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.pool import NullPool, QueuePool
from vaaet.logging import get_logger

from vaaet_persistence.constants import (
    DATABASE_SCHEMAS,
    DEFAULT_DB_PORT,
    REQUIRED_DATABASE_REVISION,
)
from vaaet_persistence.exceptions import DatabaseOperationError, DatabaseSchemaVersionError
from vaaet_persistence.settings import (
    DatabaseAdminSettings,
    DatabaseProfile,
    DatabaseSettings,
    materialize_root_certificate,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class DatabaseHealth:
    """Diagnóstico no secreto que puede mostrarse en una salida de notebook."""

    profile: str
    host: str
    port: int
    database: str
    server_version: str
    current_role: str
    ssl_enabled: bool
    available_schemas: tuple[str, ...]


DatabaseConnectionSettings = DatabaseSettings | DatabaseAdminSettings
_MANAGED_CERTIFICATES: dict[int, str] = {}


def _settings_url(settings: DatabaseConnectionSettings) -> URL:
    """Construye una URL SQLAlchemy sin convertir credenciales en texto plano."""

    return URL.create(
        "postgresql+psycopg2",
        username=settings.username,
        password=settings.password,
        host=settings.host,
        port=settings.port,
        database=settings.database,
    )


def _connect_args(
    settings: DatabaseConnectionSettings, *, root_certificate: str | None = None
) -> dict[str, object]:
    """Construye parámetros de conexión comunes sin serializar credenciales."""

    connect_args: dict[str, object] = {
        "connect_timeout": settings.connect_timeout_seconds,
        "application_name": settings.application,
        "sslmode": settings.sslmode,
        "options": (
            f"-c statement_timeout={settings.statement_timeout_seconds * 1000} "
            f"-c lock_timeout={settings.lock_timeout_seconds * 1000}"
        ),
    }
    if root_certificate or settings.sslrootcert:
        connect_args["sslrootcert"] = root_certificate or settings.sslrootcert
    return connect_args


def _create_managed_engine(
    settings: DatabaseConnectionSettings,
    *,
    admin: bool,
) -> Engine:
    temporary_certificate: str | None = None
    try:
        certificate = settings.sslrootcert
        if settings.endpoint.sslrootcert_pem and not certificate:
            temporary_certificate = materialize_root_certificate(
                settings.endpoint.sslrootcert_pem.replace("\\n", "\n")
            )
            certificate = temporary_certificate
        kwargs: dict[str, object] = {
            "connect_args": _connect_args(settings, root_certificate=certificate),
            "hide_parameters": True,
        }
        if admin:
            kwargs["poolclass"] = NullPool
        else:
            assert isinstance(settings, DatabaseSettings)
            kwargs.update(
                {
                    "poolclass": QueuePool,
                    "pool_size": settings.pool.pool_size,
                    "max_overflow": settings.pool.max_overflow,
                    "pool_timeout": settings.pool.timeout_seconds,
                    "pool_pre_ping": True,
                    "pool_recycle": settings.pool.recycle_seconds,
                }
            )
        engine = create_engine(_settings_url(settings), **kwargs)
        if temporary_certificate:
            _MANAGED_CERTIFICATES[id(engine)] = temporary_certificate
        return engine
    except Exception:
        if temporary_certificate:
            Path(temporary_certificate).unlink(missing_ok=True)
        raise


def dispose_engine(engine: Engine) -> None:
    """Libera un engine propio y su CA efímera sin depender de settings mutables."""

    temporary_certificate = _MANAGED_CERTIFICATES.pop(id(engine), None)
    try:
        engine.dispose()
    finally:
        if temporary_certificate:
            try:
                Path(str(temporary_certificate)).unlink(missing_ok=True)
            except OSError:
                logger.warning("Temporary PostgreSQL CA cleanup failed: OSError")


def get_engine(settings: DatabaseSettings) -> Engine:
    """Crea un engine para el perfil explícito con un pool pequeño y saludable."""

    return _create_managed_engine(settings, admin=False)


def create_admin_engine(settings: DatabaseAdminSettings) -> Engine:
    """Crea una conexión administrativa efímera para Alembic fuera de notebooks."""

    return _create_managed_engine(settings, admin=True)


@contextmanager
def database_engine(settings: DatabaseSettings) -> Iterator[Engine]:
    """Expone un engine comprobado y elimina certificados PEM temporales al cerrar."""

    engine = get_engine(settings)
    try:
        execute_with_retry(
            lambda: _probe_connection(engine),
            attempts=settings.retry.attempts,
            initial_delay_seconds=settings.retry.base_delay_seconds,
        )
        yield engine
    finally:
        dispose_engine(engine)


def _probe_connection(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def inspect_database(engine: Engine, profile: DatabaseProfile | str) -> DatabaseHealth:
    """Consulta información operativa sin leer tablas ni mostrar credenciales."""

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT current_setting('server_version'), current_user, "
                "COALESCE((SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()), FALSE)"
            )
        ).one()
        available = tuple(
            schema
            for schema in DATABASE_SCHEMAS
            if connection.execute(text("SELECT to_regnamespace(:schema)"), {"schema": schema}).scalar()
        )
    url = engine.url
    return DatabaseHealth(
        profile=DatabaseProfile(profile).value,
        host=str(url.host or ""),
        port=int(url.port or DEFAULT_DB_PORT),
        database=str(url.database or ""),
        server_version=str(row[0]),
        current_role=str(row[1]),
        ssl_enabled=bool(row[2]),
        available_schemas=available,
    )


def test_connection(engine: Engine) -> bool:
    """Devuelve un diagnóstico booleano sin filtrar la excepción de infraestructura."""

    try:
        execute_with_retry(lambda: _probe_connection(engine))
        return True
    except OperationalError:  # pragma: no cover - servicio externo
        logger.warning("PostgreSQL connection test failed: OperationalError")
        return False
    except DatabaseOperationError:  # pragma: no cover - servicio externo
        logger.warning("PostgreSQL connection test failed after bounded retries")
        return False


def require_database_revision(connection: Connection) -> None:
    """Bloquea escrituras si Alembic no acredita la revisión requerida."""

    try:
        revision = connection.execute(
            text("SELECT version_num FROM public.alembic_version")
        ).scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise DatabaseOperationError(
            "PostgreSQL schema revision could not be verified.",
            operation="verify-schema-revision",
            sqlstate=getattr(getattr(exc, "orig", None), "pgcode", None),
        ) from None
    if revision != REQUIRED_DATABASE_REVISION:
        raise DatabaseSchemaVersionError(
            "PostgreSQL schema revision is incompatible; apply the governed Alembic upgrade."
        )


def execute_with_retry(
    operation: Callable[[], object],
    *,
    attempts: int = 3,
    initial_delay_seconds: float = 0.5,
) -> object:
    """Reintenta sólo fallos operativos transitorios y redacta su causa externa."""

    if attempts < 1:
        raise ValueError("Database retry attempts must be positive.")
    if initial_delay_seconds < 0:
        raise ValueError("Database retry delay must be non-negative.")
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except OperationalError as exc:
            sqlstate = getattr(getattr(exc, "orig", None), "pgcode", None)
            if not _is_transient_connectivity(sqlstate) or attempt == attempts:
                raise DatabaseOperationError(
                    "PostgreSQL operation failed after bounded retries.",
                    operation="health-check",
                    sqlstate=sqlstate,
                ) from None
            time.sleep(initial_delay_seconds * (2 ** (attempt - 1)))
    raise AssertionError("unreachable")


def _is_transient_connectivity(sqlstate: object) -> bool:
    """Limita reintentos a fallos de conexión, nunca autenticación o contrato."""

    return sqlstate is None or str(sqlstate).startswith("08")


__all__ = [
    "DatabaseHealth",
    "create_admin_engine",
    "database_engine",
    "dispose_engine",
    "execute_with_retry",
    "get_engine",
    "inspect_database",
    "require_database_revision",
    "test_connection",
]
