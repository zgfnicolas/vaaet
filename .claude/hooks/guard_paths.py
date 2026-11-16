# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Bloquea ediciones que VAAET no permite hacer a un agente.

Hook `PreToolUse` de Claude Code para `Edit`, `Write` y `NotebookEdit`. Lee el
evento JSON por stdin y sale con código 2 cuando la ruta es un secreto, un dato
privado, un binario ML, un archivo generado por DVC o una revisión Alembic ya
publicada en `main`. Un error inesperado también bloquea: un guardián que falla
no debe dejar pasar la edición. Cubre sólo herramientas de edición; los
comandos de shell quedan a cargo de los permisos de `settings.json`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath

MIGRATION_VERSIONS = "vaaet-persistence/src/vaaet_persistence/migrations/versions/"
PRIVATE_DATA = "vaaet-ml/data/private/"
PUBLISHED_REFS = ("origin/main", "main")
SECRET_NAMES = {".env", ".env.local"}
SECRET_SUFFIXES = {".pem", ".key"}
BINARY_SUFFIXES = {".keras", ".joblib", ".pt", ".h5"}


def _project_root(event: dict[str, object]) -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or str(event.get("cwd") or ".")
    return Path(root).resolve()


def _target(event: dict[str, object]) -> str | None:
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    value = tool_input.get("file_path") or tool_input.get("notebook_path")
    return str(value) if value else None


def _relative(path: Path, root: Path) -> str | None:
    try:
        return PurePosixPath(path.relative_to(root).as_posix()).as_posix()
    except ValueError:
        return None


def _git(root: Path, *args: str) -> int:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, timeout=5, check=False
        ).returncode
    except (OSError, subprocess.SubprocessError):
        return -1


def is_published_revision(relative: str, absolute: Path, root: Path) -> bool:
    """Indica si la revisión ya existe en la rama principal.

    Una revisión creada o sólo commiteada en la rama de trabajo todavía se puede
    editar. Si no hay una referencia principal disponible, se considera
    publicada toda revisión que exista en disco.
    """

    for ref in PUBLISHED_REFS:
        if _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") == 0:
            return _git(root, "cat-file", "-e", f"{ref}:{relative}") == 0
    return absolute.exists()


def blocked_reason(target: str, root: Path) -> str | None:
    """Devuelve el motivo del bloqueo, o None si la edición está permitida."""

    path = Path(target)
    absolute = (path if path.is_absolute() else root / path).resolve()
    relative = _relative(absolute, root)
    name = absolute.name
    suffix = absolute.suffix.lower()
    if name.lower() in SECRET_NAMES or suffix in SECRET_SUFFIXES:
        return "es un secreto o certificado (RN-24)"
    if name.lower().endswith(".private.json") or name.lower() == "config.local":
        return "es configuración o calibración privada (RN-24)"
    if relative is not None and relative.casefold().startswith(PRIVATE_DATA):
        return "está en vaaet-ml/data/private/, reservado a datos privados (RN-24)"
    if suffix in BINARY_SUFFIXES:
        return "es un binario ML; el bundle se versiona con DVC (RN-24)"
    if suffix == ".dvc" or name == "dvc.lock":
        return "lo genera DVC; usá los comandos de DVC (ADR-0023)"
    if (
        relative is not None
        and relative.startswith(MIGRATION_VERSIONS)
        and suffix == ".py"
        and name != "__init__.py"
        and is_published_revision(relative, absolute, root)
    ):
        return (
            "es una revisión Alembic publicada en main; agregá una revisión nueva en "
            "lugar de modificarla (RN-21, ADR-0037)"
        )
    return None


def main() -> int:
    # Windows usa cp1252 por defecto; Claude Code envía y espera UTF-8.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(event, dict):
        return 0
    target = _target(event)
    if target is None:
        return 0
    try:
        reason = blocked_reason(target, _project_root(event))
    except Exception as exc:  # noqa: BLE001 - un guardián que falla no deja pasar.
        print(
            f"Edición bloqueada: guard_paths.py no pudo evaluar {target} "
            f"({type(exc).__name__}). Revisá la ruta o pedile a una persona el cambio.",
            file=sys.stderr,
        )
        return 2
    if reason is None:
        return 0
    print(
        f"Edición bloqueada por .claude/hooks/guard_paths.py: {target} {reason}. "
        "Si el cambio es necesario, pedile a una persona que lo haga.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
