# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Conexión, reintentos y diagnóstico seguro de PostgreSQL."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool, QueuePool
from vaaet.logging import get_logger

from vaaet_persistence.constants import DATABASE_SCHEMAS, DEFAULT_DB_PORT
from vaaet_persistence.exceptions import DatabaseOperationError
from vaaet_persistence.settings import (
    DatabaseAdminSettings,
    DatabaseProfile,
    DatabaseSettings,
    cleanup_temporary_root_certificate,
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


def _connect_args(settings: DatabaseConnectionSettings) -> dict[str, object]:
    """Construye parámetros de conexión comunes sin serializar credenciales."""

    connect_args: dict[str, object] = {
        "connect_timeout": settings.connect_timeout_seconds,
        "application_name": settings.application,
        "sslmode": settings.sslmode,
    }
    if settings.sslrootcert:
        connect_args["sslrootcert"] = settings.sslrootcert
    return connect_args


def get_engine(settings: DatabaseSettings) -> Engine:
    """Crea un engine para el perfil explícito con un pool pequeño y saludable."""

    return create_engine(
        _settings_url(settings),
        connect_args=_connect_args(settings),
        poolclass=QueuePool,
        pool_size=settings.pool.pool_size,
        max_overflow=settings.pool.max_overflow,
        pool_pre_ping=True,
        pool_recycle=settings.pool.recycle_seconds,
        hide_parameters=True,
    )


def create_admin_engine(settings: DatabaseAdminSettings) -> Engine:
    """Crea una conexión administrativa efímera para Alembic fuera de notebooks."""

    return create_engine(
        _settings_url(settings),
        connect_args=_connect_args(settings),
        poolclass=NullPool,
        hide_parameters=True,
    )


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
        engine.dispose()
        cleanup_temporary_root_certificate(settings)


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
            if attempt == attempts:
                raise DatabaseOperationError(
                    "PostgreSQL operation failed after bounded retries."
                ) from exc
            time.sleep(initial_delay_seconds * (2 ** (attempt - 1)))
    raise AssertionError("unreachable")


__all__ = [
    "DatabaseHealth",
    "create_admin_engine",
    "database_engine",
    "execute_with_retry",
    "get_engine",
    "inspect_database",
    "test_connection",
]
