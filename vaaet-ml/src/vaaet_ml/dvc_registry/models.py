# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Contratos tipados del adaptador DVC de laboratorio."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol


class RegistryProvider(str, Enum):
    """Backends soportados sin acoplar el bundle a un proveedor concreto."""

    GOOGLE_DRIVE = "gdrive"
    AMAZON_S3 = "s3"
    CLOUDFLARE_R2 = "r2"


class RegistryMaterializationPurpose(str, Enum):
    """Separa recuperación operacional de inspección histórica explícita."""

    INFERENCE = "inference"
    HISTORICAL_EVALUATION = "historical-evaluation"


@dataclass(frozen=True)
class RemoteConfiguration:
    """Valores no secretos necesarios para preparar un remoto local de DVC."""

    provider: RegistryProvider
    url: str
    endpoint_url: str | None = None
    profile: str | None = None
    region: str | None = None
    service_account_file: Path | None = None
    replace: bool = False


@dataclass(frozen=True)
class CommandResult:
    """Resultado mínimo y testeable de un comando externo."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    """Ejecuta comandos estructurados sin construir un shell."""

    def run(self, arguments: Sequence[str], *, cwd: Path) -> CommandResult:
        """Ejecuta una orden y devuelve sólo sus streams de texto."""


class ModuleFinder(Protocol):
    """Resuelve plugins opcionales sin importarlos durante el diagnóstico."""

    def __call__(self, module_name: str) -> bool:
        """Informa si un módulo está disponible en el intérprete actual."""


@dataclass(frozen=True)
class RegistryHealth:
    """Diagnóstico seguro del adaptador, sin URLs ni credenciales."""

    provider: RegistryProvider
    remote_name: str


@dataclass(frozen=True)
class RegistryEntry:
    """Resumen read-only de una revisión DVC materializada y validada."""

    revision: str
    model_version: str | None
    deployment_stage: str | None
    production_eligible: bool | None
    training_mode: str | None
    input_policy: str | None
    supervision: str | None
    provenance_origin: str | None
    input_lock_id: str | None
    promotion_blockers: tuple[str, ...]
    historical_only: bool
    available: bool

    def as_dict(self) -> dict[str, object]:
        """Convierte el resumen a datos JSON seguros para la salida de la CLI."""

        return {
            "revision": self.revision,
            "model_version": self.model_version,
            "deployment_stage": self.deployment_stage,
            "production_eligible": self.production_eligible,
            "training_mode": self.training_mode,
            "input_policy": self.input_policy,
            "supervision": self.supervision,
            "provenance_origin": self.provenance_origin,
            "input_lock_id": self.input_lock_id,
            "promotion_blockers": list(self.promotion_blockers),
            "historical_only": self.historical_only,
            "available": self.available,
        }
