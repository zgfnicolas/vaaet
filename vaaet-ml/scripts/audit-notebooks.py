#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Audita notebooks VAAET sin modificarlos."""

from __future__ import annotations

import argparse
import ast
import glob
import json
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

SETUP_MARKER = "# Preparación del entorno"
CONFIG_MARKERS = ("# Configuración del workflow",)
SOFT_CELL_LINE_LIMIT = 50
HARD_CELL_LINE_LIMIT = 500

BANNED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sys.path mutation", re.compile(r"\bsys\.path\b")),
    ("requirements file installation", re.compile(r"requirements[^\s\"']*\.txt")),
    ("notebook pip magic", re.compile(r"(?m)^\s*[!%]\s*pip\b")),
)
PIP_INSTALL_PATTERN = re.compile(
    r"[\"']-m[\"']\s*,\s*[\"']pip[\"']\s*,\s*[\"']install[\"']"
)


@dataclass(frozen=True)
class Finding:
    """Representa un hallazgo determinista de la auditoría."""

    severity: str
    path: Path
    message: str
    cell_number: int | None = None

    def render(self) -> str:
        location = str(self.path)
        if self.cell_number is not None:
            location = f"{location}:cell-{self.cell_number}"
        return f"[{self.severity}] {location}: {self.message}"


def _cell_source(cell: object) -> str:
    if not isinstance(cell, dict):
        raise TypeError("cell entry must be an object")
    source = cell.get("source", "")
    if isinstance(source, str):
        return source
    if isinstance(source, list) and all(isinstance(part, str) for part in source):
        return "".join(source)
    raise ValueError("cell source must be a string or list of strings")


def _assigned_names(tree: ast.Module) -> set[str]:
    """Devuelve asignaciones del módulo, incluso dentro de control de flujo."""

    names: set[str] = set()

    class ModuleScopeAssignments(ast.NodeVisitor):
        """Evita confundir las variables locales con configuración del notebook."""

        @staticmethod
        def _record_targets(targets: Sequence[ast.expr]) -> None:
            for target in targets:
                names.update(node.id for node in ast.walk(target) if isinstance(node, ast.Name))

        def visit_Assign(self, node: ast.Assign) -> None:
            self._record_targets(node.targets)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            self._record_targets((node.target,))

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            self._record_targets((node.target,))

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            return

        def visit_Lambda(self, node: ast.Lambda) -> None:
            return

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            return

    ModuleScopeAssignments().visit(tree)
    return names


def _has_src_import(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name == "src" or alias.name.startswith("src.") for alias in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom) and (
            node.module == "src" or (node.module and node.module.startswith("src."))
        ):
            return True
    return False


def _load_code_cells(  # noqa: C901 - valida el notebook en un único recorrido.
    path: Path,
) -> tuple[list[tuple[int, str, ast.Module]], list[Finding]]:
    findings: list[Finding] = []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [], [Finding("ERROR", path, f"invalid notebook JSON: {type(exc).__name__}")]

    cells = document.get("cells") if isinstance(document, dict) else None
    if not isinstance(cells, list):
        return [], [Finding("ERROR", path, "notebook must contain a cells list")]

    code_cells: list[tuple[int, str, ast.Module]] = []
    for cell_number, cell in enumerate(cells, start=1):
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        try:
            source = _cell_source(cell)
        except TypeError as exc:
            findings.append(Finding("ERROR", path, str(exc), cell_number))
            continue

        line_count = len(source.splitlines())
        if line_count > HARD_CELL_LINE_LIMIT:
            findings.append(
                Finding(
                    "ERROR",
                    path,
                    f"code cell has {line_count} lines; hard limit is {HARD_CELL_LINE_LIMIT}",
                    cell_number,
                )
            )
        elif line_count > SOFT_CELL_LINE_LIMIT:
            findings.append(
                Finding(
                    "WARN",
                    path,
                    f"code cell has {line_count} lines; review extraction above {SOFT_CELL_LINE_LIMIT}",
                    cell_number,
                )
            )

        for label, pattern in BANNED_PATTERNS:
            if pattern.search(source):
                findings.append(Finding("ERROR", path, f"forbidden {label}", cell_number))

        try:
            tree = ast.parse(source, filename=f"{path}:cell-{cell_number}")
        except SyntaxError as exc:
            detail = f"invalid Python syntax at line {exc.lineno}: {exc.msg}"
            findings.append(Finding("ERROR", path, detail, cell_number))
            continue
        if _has_src_import(tree):
            findings.append(Finding("ERROR", path, "import through vaaet.* or vaaet_ml.*, never src.*", cell_number))
        code_cells.append((cell_number, source, tree))
    return code_cells, findings


def audit_notebook(path: Path) -> list[Finding]:  # noqa: C901 - agrupa todas las reglas de auditoría.
    """Devuelve todos los hallazgos de un notebook."""
    code_cells, findings = _load_code_cells(path)
    if not code_cells:
        if not any(item.severity == "ERROR" for item in findings):
            findings.append(Finding("ERROR", path, "notebook contains no valid code cells"))
        return findings

    setup_cells = [number for number, source, _ in code_cells if SETUP_MARKER in source]
    config_cells = [
        number
        for number, source, _ in code_cells
        if any(marker in source for marker in CONFIG_MARKERS)
    ]
    if len(setup_cells) != 1:
        findings.append(
            Finding("ERROR", path, f"expected exactly one setup cell, found {len(setup_cells)}")
        )
    if len(config_cells) != 1:
        findings.append(
            Finding(
                "ERROR",
                path,
                f"expected exactly one executable configuration cell, found {len(config_cells)}",
            )
        )

    pip_install_cells = [
        number for number, source, _ in code_cells if PIP_INSTALL_PATTERN.search(source)
    ]
    if len(pip_install_cells) > 1:
        findings.append(
            Finding(
                "ERROR",
                path,
                f"expected at most one project installation, found {len(pip_install_cells)}",
            )
        )
    elif len(pip_install_cells) == 1 and len(setup_cells) == 1:
        install_cell = pip_install_cells[0]
        if install_cell != setup_cells[0]:
            findings.append(
                Finding(
                    "ERROR",
                    path,
                    "project installation must remain in the single setup cell",
                    install_cell,
                )
            )

    if len(config_cells) == 1:
        config_number = config_cells[0]
        config_tree = next(tree for number, _, tree in code_cells if number == config_number)
        configured_names = _assigned_names(config_tree)
        for number, _, tree in code_cells:
            if number == config_number:
                continue
            duplicated = sorted(configured_names & _assigned_names(tree))
            for name in duplicated:
                findings.append(
                    Finding(
                        "ERROR",
                        path,
                        f"configuration name {name!r} is reassigned outside its owning cell",
                        number,
                    )
                )
    return findings


def _expand_inputs(raw_inputs: Sequence[str]) -> tuple[list[Path], list[str]]:
    paths: set[Path] = set()
    errors: list[str] = []
    for raw in raw_inputs:
        matches = [Path(item) for item in glob.glob(raw, recursive=True)]
        if not matches:
            candidate = Path(raw)
            matches = [candidate] if candidate.exists() else []
        if not matches:
            errors.append(f"input does not exist or match any path: {raw}")
            continue
        for match in matches:
            if match.is_dir():
                paths.update(match.rglob("*.ipynb"))
            elif match.suffix == ".ipynb":
                paths.add(match)
            else:
                errors.append(f"input is not a notebook or directory: {match}")
    return sorted(paths, key=lambda item: str(item).lower()), errors


def _print_findings(findings: Iterable[Finding]) -> tuple[int, int]:
    errors = 0
    warnings = 0
    for finding in findings:
        print(finding.render())
        errors += finding.severity == "ERROR"
        warnings += finding.severity == "WARN"
    return errors, warnings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Notebook files, directories, or glob patterns")
    args = parser.parse_args(argv)

    notebook_paths, input_errors = _expand_inputs(args.paths)
    if input_errors:
        for message in input_errors:
            print(f"[ERROR] {message}")
        return 2
    if not notebook_paths:
        print("[ERROR] no notebooks found")
        return 2

    all_findings: list[Finding] = []
    for path in notebook_paths:
        findings = audit_notebook(path)
        all_findings.extend(findings)
        if not findings:
            print(f"[PASS] {path}")

    errors, warnings = _print_findings(all_findings)
    print(
        f"Audited {len(notebook_paths)} notebook(s): "
        f"{errors} error(s), {warnings} warning(s)"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
