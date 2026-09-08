# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Excepciones seguras de la capa PostgreSQL compartida."""

from vaaet.exceptions import VAAETError


class PersistenceError(VAAETError):
    """Raíz de errores propios de persistencia VAAET."""


class DatabaseNotConfiguredError(RuntimeError, PersistenceError):
    """Indica que falta configuración segura requerida por un consumidor."""


class DatabaseOperationError(RuntimeError, PersistenceError):
    """Indica un fallo no recuperable de una operación PostgreSQL."""


__all__ = ["DatabaseNotConfiguredError", "DatabaseOperationError", "PersistenceError"]
