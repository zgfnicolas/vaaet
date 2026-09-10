# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Entorno Alembic para migraciones administrativas y provider-neutral.

Las revisiones Alembic escritas explícitamente son la única autoridad de DDL.
Este módulo no conoce AWS, Supabase, Neon ni Colab: recibe un endpoint
PostgreSQL validado y una identidad administrativa desde el entorno local o CI.
"""

from __future__ import annotations

from logging.config import fileConfig
from typing import cast

from alembic import context
from sqlalchemy.engine import Connection

from vaaet_persistence import __version__
from vaaet_persistence.connection import create_admin_engine, dispose_engine
from vaaet_persistence.settings import (
    DatabaseAdminSettings,
    cleanup_temporary_root_certificate,
    load_database_admin_settings,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _admin_settings() -> DatabaseAdminSettings:
    """Carga la identidad administrativa fuera de notebooks y sin registrar el DSN."""

    return load_database_admin_settings(
        application_name="vaaet-persistence-alembic",
        application_version=__version__,
    )


def run_migrations_offline() -> None:
    """Genera SQL con el dialecto PostgreSQL sin incluir credenciales en la salida."""

    settings = _admin_settings()
    try:
        context.configure(
            url="postgresql+psycopg2://",
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
        )
        with context.begin_transaction():
            context.run_migrations()
    finally:
        cleanup_temporary_root_certificate(settings)


def _run_migrations_with_connection(connection: Connection) -> None:
    """Ejecuta DDL versionado sobre una conexión administrada o inyectada en pruebas."""

    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Conecta con TLS y ``NullPool`` para aplicar migraciones una única vez."""

    injected_connection = cast(Connection | None, config.attributes.get("connection"))
    if injected_connection is not None:
        _run_migrations_with_connection(injected_connection)
        return

    settings = _admin_settings()
    engine = create_admin_engine(settings)
    try:
        with engine.connect() as connection:
            _run_migrations_with_connection(connection)
    finally:
        dispose_engine(engine)
        cleanup_temporary_root_certificate(settings)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
