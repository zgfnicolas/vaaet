# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Límites de dependencias y recursos instalables de persistencia."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import vaaet_persistence

COMPONENT_ROOT = Path(__file__).parents[2]
SOURCE_ROOT = COMPONENT_ROOT / "src" / "vaaet_persistence"


def test_component_imports_without_the_ml_laboratory() -> None:
    assert vaaet_persistence.__version__ == "0.2.0"
    forbidden = {"vaaet_ml", "tensorflow", "ultralytics", "dvc", "google", "ipywidgets"}
    imported: set[str] = set()
    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
    assert imported.isdisjoint(forbidden)


def test_historical_migration_bytes_are_unchanged() -> None:
    expected = {
        "20260804_0001_postgres_schemas_hitl.py": (
            "916b3af17484696c0825bbe4a3e808ec8975c5942e75fc92fe75b4c239902414"
        ),
        "20260806_0002_postgres_hardening_pipeline_runs.py": (
            "fc16ec8b96fd15e006338416f3d2774ed851a933f29486f64abd6d34f2d7cea1"
        ),
        "20260905_0003_temporal_continuity_model_revision.py": (
            "bb94c88ab54ccac0107bbd2411fd3c9215d4bb8e1e8cb87821d60cb440aad4ea"
        ),
    }
    versions = SOURCE_ROOT / "migrations" / "versions"
    observed = {
        name: hashlib.sha256(versions.joinpath(name).read_bytes()).hexdigest()
        for name in expected
    }
    assert observed == expected


def test_alembic_has_one_canonical_revision_directory() -> None:
    legacy_versions = COMPONENT_ROOT.parent / "vaaet-ml" / "migrations" / "versions"
    assert not list(legacy_versions.glob("202*.py"))
    config = (COMPONENT_ROOT / "alembic.ini").read_text(encoding="utf-8")
    assert "script_location = vaaet_persistence:migrations" in config
    current = SOURCE_ROOT / "migrations" / "versions" / (
        "20260909_0004_numeric_fidelity_hitl_integrity.py"
    )
    assert current.is_file()
    assert 'down_revision = "20260905_0003"' in current.read_text(encoding="utf-8")


def test_current_migration_encodes_numeric_hitl_and_privilege_contracts() -> None:
    migration = SOURCE_ROOT / "migrations" / "versions" / (
        "20260909_0004_numeric_fidelity_hitl_integrity.py"
    )
    source = migration.read_text(encoding="utf-8")
    assert "TYPE DOUBLE PRECISION" in source
    assert "numeric_representation" in source
    assert "application_name" in source
    assert "telemetry_schema_version DROP DEFAULT" in source
    assert "feature_schema_version DROP DEFAULT" in source
    assert "human_validation_conflicts" in source
    assert "unreachable_nodes" in source
    assert "pg_advisory_xact_lock" in source
    assert "GRANT SELECT ON public.alembic_version" in source
    assert "cannot be downgraded safely" in source


def test_role_provisioning_can_verify_the_required_alembic_revision() -> None:
    source = (SOURCE_ROOT / "migrations" / "provision-roles.sql").read_text(
        encoding="utf-8"
    )
    assert "GRANT SELECT ON public.alembic_version" in source
    for role in (
        "vaaet_collection_role",
        "vaaet_inference_role",
        "vaaet_training_role",
        "vaaet_reviewer_role",
    ):
        assert role in source
