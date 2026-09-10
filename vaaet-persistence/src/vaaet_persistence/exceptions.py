# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Excepciones seguras de la capa PostgreSQL compartida."""

from vaaet.exceptions import VAAETError


class PersistenceError(VAAETError):
    """Raíz de errores propios de persistencia VAAET."""


class DatabaseNotConfiguredError(RuntimeError, PersistenceError):
    """Indica que falta configuración segura requerida por un consumidor."""


class DatabaseOperationError(RuntimeError, PersistenceError):
    """Indica un fallo PostgreSQL mediante contexto seguro y estructurado."""

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        sqlstate: str | None = None,
        run_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.sqlstate = sqlstate
        self.run_id = run_id


class PersistenceConflictError(ValueError, PersistenceError):
    """Indica una colisión idempotente cuyo contenido no coincide."""


class PersistenceValidationError(ValueError, PersistenceError):
    """Indica que una entrada externa incumple el contrato persistible."""


class DatabaseSchemaVersionError(RuntimeError, PersistenceError):
    """Indica que una escritura apunta a una revisión Alembic incompatible."""


__all__ = [
    "DatabaseNotConfiguredError",
    "DatabaseOperationError",
    "DatabaseSchemaVersionError",
    "PersistenceConflictError",
    "PersistenceError",
    "PersistenceValidationError",
]
