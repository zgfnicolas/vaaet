# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Constantes contractuales del almacenamiento PostgreSQL compartido."""

DEFAULT_DB_PORT = 5432
DATABASE_SCHEMA_VERSION = "vaaet-db-v3"
DATABASE_SCHEMAS = (
    "vaaet_raw",
    "vaaet_ml",
    "vaaet_feedback",
    "vaaet_ops",
)

__all__ = [
    "DATABASE_SCHEMAS",
    "DATABASE_SCHEMA_VERSION",
    "DEFAULT_DB_PORT",
]
