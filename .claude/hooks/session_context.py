# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Informa al iniciar la sesión la rama y los planes gobernados abiertos.

Hook `SessionStart` de Claude Code. Lo que escribe en stdout se agrega al
contexto de la sesión. No usa red ni modifica el repositorio, y nunca falla:
ante cualquier error termina con código 0 sin imprimir nada.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

OPEN_STATUS = re.compile(r"^- Estado(?: global)?:\s*En progreso", re.MULTILINE)


def _branch(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def open_plans(root: Path) -> list[str]:
    """Lista los planes gobernados con estado «En progreso», sin el archivo."""

    plans_dir = root / "docs" / "governance" / "plans"
    plans: list[str] = []
    for path in sorted(plans_dir.glob("*.md")):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if OPEN_STATUS.search(content):
            plans.append(path.relative_to(root).as_posix())
    return plans


def main() -> int:
    # Windows usa cp1252 por defecto; Claude Code espera UTF-8.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".").resolve()
    lines: list[str] = []
    branch = _branch(root)
    if branch:
        lines.append(f"Rama actual: {branch}.")
    plans = open_plans(root)
    if plans:
        lines.append(
            "Planes gobernados en progreso (ejecutá sólo la fase actual): " + ", ".join(plans)
        )
    if lines:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - un hook de contexto nunca debe cortar la sesión.
        sys.exit(0)
