# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Excepciones seguras de la capa PostgreSQL compartida."""

import re
from typing import Any

from vaaet.exceptions import VAAETError

_SQLSTATE = re.compile(r"[0-9A-Z]{5}")


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
        category: str = "infrastructure",
        operation: str | None = None,
        sqlstate: str | None = None,
        run_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.operation = operation
        self.sqlstate = sqlstate
        self.run_id = run_id


class PersistenceConflictError(ValueError, PersistenceError):
    """Indica una colisión idempotente cuyo contenido no coincide."""


class PersistenceValidationError(ValueError, PersistenceError):
    """Indica que una entrada externa incumple el contrato persistible."""


class DatabaseSchemaVersionError(RuntimeError, PersistenceError):
    """Indica que una escritura apunta a una revisión Alembic incompatible."""


class PipelineAuditIncompleteError(RuntimeError, PersistenceError):
    """Comunica un resultado confirmado cuyo cierre auditable quedó pendiente."""

    def __init__(
        self,
        message: str,
        *,
        confirmed_result: Any,
        run_id: str,
        audit_error_category: str | None,
    ) -> None:
        super().__init__(message)
        self.confirmed_result = confirmed_result
        self.run_id = run_id
        self.audit_error_category = audit_error_category


def safe_sqlstate(error: BaseException) -> str | None:
    """Extrae únicamente un SQLSTATE contractual sin exponer mensajes externos."""

    value = getattr(getattr(error, "orig", None), "pgcode", None)
    normalized = value.upper() if isinstance(value, str) else None
    return normalized if normalized is not None and _SQLSTATE.fullmatch(normalized) else None


__all__ = [
    "DatabaseNotConfiguredError",
    "DatabaseOperationError",
    "DatabaseSchemaVersionError",
    "PipelineAuditIncompleteError",
    "PersistenceConflictError",
    "PersistenceError",
    "PersistenceValidationError",
    "safe_sqlstate",
]
