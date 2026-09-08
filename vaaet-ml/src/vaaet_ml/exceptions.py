# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Excepciones del laboratorio, separadas del núcleo portable."""

from __future__ import annotations

from vaaet.exceptions import VAAETError
from vaaet_persistence.exceptions import DatabaseNotConfiguredError, DatabaseOperationError


class LaboratoryError(VAAETError):
    """Raíz de los errores específicos de datos y notebooks del laboratorio."""


class RuntimeConfigurationError(RuntimeError, LaboratoryError):
    """Indica que el runtime local o Colab no cumple un requisito explícito."""


class DatasetArtifactValidationError(ValueError, LaboratoryError):
    """Indica que un snapshot, catálogo o backup de laboratorio es inválido."""


class TrainingStabilityError(ValueError, LaboratoryError):
    """Indica que un ajuste Keras no produjo evidencia numérica utilizable."""


class DvcRegistryError(RuntimeError, LaboratoryError):
    """Raíz de errores seguros del registro DVC del laboratorio."""


class DvcRegistryConfigurationError(DvcRegistryError):
    """Indica una configuración local de remoto DVC ausente o inválida."""


class DvcRegistryOperationError(DvcRegistryError):
    """Indica un fallo de Git o DVC sin exponer diagnósticos sensibles."""


__all__ = [
    "DatabaseNotConfiguredError",
    "DatabaseOperationError",
    "DatasetArtifactValidationError",
    "DvcRegistryConfigurationError",
    "DvcRegistryError",
    "DvcRegistryOperationError",
    "LaboratoryError",
    "RuntimeConfigurationError",
    "TrainingStabilityError",
]
