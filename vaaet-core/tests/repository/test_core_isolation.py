# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Architectural boundary checks for the portable VAAET core."""

from __future__ import annotations

import ast
import logging
import subprocess
import sys
from pathlib import Path

from pytest import MonkeyPatch

from vaaet.logging import get_logger

CORE_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_IMPORTS = (
    "vaaet_ml",
    "sqlalchemy",
    "psycopg",
    "google.colab",
    "dvc",
    "pydrive",
)


def test_core_has_no_lab_storage_or_notebook_dependencies() -> None:
    source_files = CORE_ROOT.joinpath("src", "vaaet").rglob("*.py")
    violations: list[str] = []
    for path in source_files:
        content = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_IMPORTS:
            if forbidden in content:
                violations.append(f"{path.relative_to(CORE_ROOT)} -> {forbidden}")
    assert violations == []


def test_core_distribution_declares_only_portable_base_dependencies() -> None:
    pyproject = (CORE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "vaaet-core"' in pyproject
    assert "sqlalchemy" not in pyproject
    assert "psycopg" not in pyproject
    assert "dvc" not in pyproject


def test_core_uses_explicit_imports_and_portable_exceptions() -> None:
    """Evita que un atajo de importación reintroduzca límites de laboratorio."""

    wildcard_imports: list[str] = []
    for path in CORE_ROOT.joinpath("src", "vaaet").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
                wildcard_imports.append(str(path.relative_to(CORE_ROOT)))

    exceptions_source = CORE_ROOT.joinpath("src", "vaaet", "exceptions.py").read_text(
        encoding="utf-8"
    ).lower()
    assert wildcard_imports == []
    assert "database" not in exceptions_source
    assert "colab" not in exceptions_source


def test_inference_imports_without_the_vision_extra() -> None:
    """Permite usar `vaaet-core[inference]` sin OpenCV ni Ultralytics."""

    probe = (
        "import sys; import vaaet.inference; import vaaet.inference.traffic_state; "
        "loaded = sorted(m for m in ('cv2', 'ultralytics') if m in sys.modules); "
        "assert not loaded, loaded"
    )
    subprocess.run([sys.executable, "-c", probe], check=True)


def test_get_logger_has_no_root_configuration_side_effect(
    monkeypatch: MonkeyPatch,
) -> None:
    """Una librería no debe alterar handlers globales al pedir un logger."""

    configured: list[bool] = []
    monkeypatch.setattr(logging, "basicConfig", lambda **_kwargs: configured.append(True))
    get_logger("vaaet.tests.no_side_effect")
    assert configured == []
