# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Pruebas de regresión para el auditor estructural portable de notebooks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
AUDITOR = WORKSPACE_ROOT / "vaaet-ml" / "scripts" / "audit-notebooks.py"


def _write_notebook(path: Path, code_cells: list[str]) -> None:
    """Escribe un notebook mínimo para validar reglas estructurales aisladas."""

    cells = [
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": source,
        }
        for source in code_cells
    ]
    path.write_text(json.dumps({"cells": cells}), encoding="utf-8")


def _audit(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(AUDITOR), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_auditor_rejects_configuration_reassigned_in_control_flow(tmp_path: Path) -> None:
    notebook_path = tmp_path / "nested-reassignment.ipynb"
    _write_notebook(
        notebook_path,
        [
            "# Preparación del entorno: ejecutá esta celda una vez por runtime.\npass\n",
            "# Configuración del workflow: editá únicamente esta celda.\nPERSIST_TO_DATABASE = False\n",
            "if True:\n    PERSIST_TO_DATABASE = True\n",
        ],
    )

    result = _audit(notebook_path)

    assert result.returncode == 1
    assert "configuration name 'PERSIST_TO_DATABASE' is reassigned" in result.stdout


def test_auditor_ignores_function_local_names(tmp_path: Path) -> None:
    notebook_path = tmp_path / "function-local.ipynb"
    _write_notebook(
        notebook_path,
        [
            "# Preparación del entorno: ejecutá esta celda una vez por runtime.\npass\n",
            "# Configuración del workflow: editá únicamente esta celda.\nPERSIST_TO_DATABASE = False\n",
            "def local_preview() -> bool:\n    PERSIST_TO_DATABASE = True\n    return PERSIST_TO_DATABASE\n",
        ],
    )

    result = _audit(notebook_path)

    assert result.returncode == 0, result.stdout
