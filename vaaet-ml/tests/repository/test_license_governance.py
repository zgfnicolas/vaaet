# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Regression checks for the monorepo AGPL demo route."""

from __future__ import annotations

import json
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = ML_ROOT.parent


def test_root_license_is_agpl_v3() -> None:
    license_text = (WORKSPACE_ROOT / "LICENSE").read_text(encoding="utf-8")

    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3, 19 November 2007" in license_text


def test_packages_declare_agpl_v3_only() -> None:
    for project_root in (
        WORKSPACE_ROOT / "vaaet-core",
        WORKSPACE_ROOT / "vaaet-persistence",
        ML_ROOT,
    ):
        metadata = (project_root / "pyproject.toml").read_text(encoding="utf-8")
        assert 'license = "AGPL-3.0-only"' in metadata


def test_serving_policy_allows_agpl_or_enterprise() -> None:
    policy = (WORKSPACE_ROOT / "docs/governance/third-party-licenses.md").read_text(
        encoding="utf-8"
    )
    agent_rules = (WORKSPACE_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    for source in (policy, agent_rules):
        normalized = source.casefold()
        assert "demo pública agpl-3.0" in normalized
        assert "enterprise" in normalized
        assert "MIT" not in source


def test_executable_sources_and_notebooks_carry_agpl_notices() -> None:
    source_roots = (
        WORKSPACE_ROOT / "vaaet-core/src",
        WORKSPACE_ROOT / "vaaet-core/tests",
        WORKSPACE_ROOT / "vaaet-persistence/src",
        WORKSPACE_ROOT / "vaaet-persistence/tests",
        ML_ROOT / "src",
        ML_ROOT / "tests",
        ML_ROOT / "scripts",
        ML_ROOT / "migrations",
        WORKSPACE_ROOT / ".github/workflows",
    )
    executable_files = [
        path
        for root in source_roots
        for pattern in ("*.py", "*.sh", "*.yml", "*.yaml")
        for path in root.rglob(pattern)
    ]

    assert executable_files
    for source_file in executable_files:
        header = "\n".join(source_file.read_text(encoding="utf-8").splitlines()[:3])
        assert "SPDX-FileCopyrightText: 2026 VAAET Contributors" in header
        assert "SPDX-License-Identifier: AGPL-3.0-only" in header

    for notebook in (ML_ROOT / "notebooks").rglob("*.ipynb"):
        metadata = json.loads(notebook.read_text(encoding="utf-8"))["metadata"]
        assert metadata["license"] == "AGPL-3.0-only"
        assert metadata["copyright"] == "Copyright (C) 2026 VAAET Contributors"


def test_agpl_demo_checklist_and_aws_runbook_are_linked() -> None:
    checklist = (WORKSPACE_ROOT / "docs/governance/agpl-demo-release-checklist.md").read_text(
        encoding="utf-8"
    )
    runbook = (WORKSPACE_ROOT / "docs/operations/aws-temporary-demo-runbook.md").read_text(
        encoding="utf-8"
    )
    normalized_runbook = " ".join(runbook.split())

    assert "Commit inmutable y tag público" in checklist
    assert "Inventario de activos" in checklist
    assert "validate_manifest()" in checklist
    assert "AWS puede generar cargos" in normalized_runbook
    assert "No usar la cuenta root" in runbook
    assert "enlace al tag de código fuente" in runbook
