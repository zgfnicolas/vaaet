# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""CLI local para configurar y consultar el registro DVC de VAAET."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from vaaet_ml.exceptions import DvcRegistryError

from .models import (
    RegistryEntry,
    RegistryMaterializationPurpose,
    RegistryProvider,
    RemoteConfiguration,
)
from .service import DvcRegistryService


def _workspace_root() -> Path:
    """Resuelve la raíz desde la ubicación instalada del paquete de laboratorio."""

    return Path(__file__).resolve().parents[4]


def build_parser() -> argparse.ArgumentParser:
    """Construye la interfaz explícita, sin comandos implícitos ni destructivos."""

    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    configure = subcommands.add_parser(
        "configure", help="configura el remoto local ignorado por Git"
    )
    configure.add_argument(
        "provider", choices=tuple(provider.value for provider in RegistryProvider)
    )
    configure.add_argument("--url", required=True, help="URL sin credenciales del almacenamiento")
    configure.add_argument("--endpoint-url", help="endpoint HTTPS requerido para Cloudflare R2")
    configure.add_argument("--profile", help="perfil local AWS o DVC, sin secretos")
    configure.add_argument("--region", help="región AWS; R2 usa siempre auto")
    configure.add_argument(
        "--service-account-file", type=Path, help="clave privada de Drive fuera del repo"
    )
    configure.add_argument(
        "--replace", action="store_true", help="reemplaza el remoto local existente"
    )

    subcommands.add_parser("doctor", help="verifica DVC y la configuración local sin usar red")
    subcommands.add_parser("stage", help="valida el bundle y crea su metadata DVC")
    subcommands.add_parser("push", help="publica un puntero DVC ya consolidado en Git")

    list_command = subcommands.add_parser("list", help="resume versiones DVC por revisión Git")
    list_command.add_argument(
        "--limit", type=int, default=20, help="máximo de revisiones a inspeccionar"
    )
    list_command.add_argument(
        "--model-version", help="filtra por la versión informativa del manifiesto"
    )
    list_command.add_argument("--format", choices=("text", "json"), default="text")

    get_command = subcommands.add_parser(
        "get", help="materializa una revisión en un directorio nuevo"
    )
    get_command.add_argument(
        "--revision", required=True, help="commit, tag o referencia Git inmutable"
    )
    get_command.add_argument(
        "--out", type=Path, required=True, help="directorio nuevo fuera del bundle activo"
    )
    get_command.add_argument(
        "--historical-evaluation",
        action="store_true",
        help="permite materializar identidades antiguas sólo para evaluación offline",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Ejecuta un comando y devuelve un código portable para shells y CI."""

    arguments = build_parser().parse_args(argv)
    service = DvcRegistryService(_workspace_root())
    try:
        command = cast(str, arguments.command)
        if command == "configure":
            configuration = RemoteConfiguration(
                provider=RegistryProvider(cast(str, arguments.provider)),
                url=cast(str, arguments.url),
                endpoint_url=cast(str | None, arguments.endpoint_url),
                profile=cast(str | None, arguments.profile),
                region=cast(str | None, arguments.region),
                service_account_file=cast(Path | None, arguments.service_account_file),
                replace=cast(bool, arguments.replace),
            )
            service.configure_remote(configuration)
            print("Remoto local configurado. Ejecutá vaaet-registry doctor antes de sincronizar.")
        elif command == "doctor":
            health = service.doctor()
            print(
                f"Registro DVC listo: remoto={health.remote_name}, proveedor={health.provider.value}."
            )
        elif command == "stage":
            version = service.stage_bundle()
            print(f"Bundle validado y registrado en DVC: {version}.")
        elif command == "push":
            service.push_bundle()
            print("Bundle DVC publicado para la revisión Git actual.")
        elif command == "list":
            entries = service.list_entries(
                limit=cast(int, arguments.limit),
                model_version=cast(str | None, arguments.model_version),
            )
            _print_entries(entries, cast(str, arguments.format))
        elif command == "get":
            version = service.get_bundle(
                cast(str, arguments.revision),
                cast(Path, arguments.out),
                purpose=(
                    RegistryMaterializationPurpose.HISTORICAL_EVALUATION
                    if cast(bool, arguments.historical_evaluation)
                    else RegistryMaterializationPurpose.INFERENCE
                ),
            )
            print(f"Bundle materializado y validado: {version}.")
        else:  # pragma: no cover - argparse limita los subcomandos disponibles.
            raise DvcRegistryError("Comando de registro no reconocido.")
    except DvcRegistryError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


def _print_entries(entries: Sequence[RegistryEntry], output_format: str) -> None:
    """Presenta el catálogo sin emitir rutas, URLs ni mensajes de proveedores."""

    if output_format == "json":
        print(json.dumps([entry.as_dict() for entry in entries], indent=2, sort_keys=True))
        return
    if not entries:
        print("No hay versiones DVC registradas en el historial Git.")
        return
    for entry in entries:
        state = "disponible" if entry.available else "no disponible"
        usage = "sólo-histórico" if entry.historical_only else "operacional"
        blockers = ",".join(entry.promotion_blockers) or "-"
        print(
            f"{entry.revision[:12]}  {entry.model_version or '-'}  "
            f"{entry.deployment_stage or '-'}  {entry.provenance_origin or '-'}  "
            f"{entry.input_lock_id or '-'}  {blockers}  {usage}  {state}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
