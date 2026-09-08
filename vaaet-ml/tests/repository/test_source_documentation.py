# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import ast
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = ML_ROOT.parent
CORE_SOURCE_ROOT = WORKSPACE_ROOT / "vaaet-core" / "src" / "vaaet"
PERSISTENCE_SOURCE_ROOT = WORKSPACE_ROOT / "vaaet-persistence" / "src" / "vaaet_persistence"
ML_SOURCE_ROOT = ML_ROOT / "src" / "vaaet_ml"

CRITICAL_DOCSTRINGS = {
    CORE_SOURCE_ROOT / "contracts.py": ("TelemetryRecord.from_mapping",),
    CORE_SOURCE_ROOT / "vision" / "tracking.py": ("SORTTracker._match_existing_tracks",),
    CORE_SOURCE_ROOT / "vision" / "pipeline.py": ("VisionPipelineSession._measure_motion",),
    ML_SOURCE_ROOT / "data" / "ingestion.py": (
        "TrainingIngestionPlan",
        "TrainingDataset",
        "_load_seed_features",
        "_frames_from_backup",
        "_deduplicate_feedback",
        "load_training_inputs",
    ),
    PERSISTENCE_SOURCE_ROOT / "persistence.py": (
        "PersistResult",
        "persist_raw_telemetry",
        "persist_classified_telemetry",
    ),
    PERSISTENCE_SOURCE_ROOT / "pipeline_runs.py": (
        "PipelineWorkflow",
        "PipelineRunHandle",
    ),
    ML_SOURCE_ROOT / "data" / "pipeline_runs.py": ("PipelineRunMetadata",),
    ML_SOURCE_ROOT / "evaluation" / "dataset_validation.py": (
        "DatasetAudit",
        "_build_audit_evidence",
    ),
    ML_SOURCE_ROOT / "training" / "partitions.py": ("TrainingPartitions",),
    ML_SOURCE_ROOT / "data" / "review_frames.py": ("_normalize_validations",),
    ML_SOURCE_ROOT / "data" / "review_finalization.py": ("_sync_to_catalog",),
    ML_SOURCE_ROOT / "training" / "holdout_resolution.py": ("_select_groups",),
    ML_SOURCE_ROOT / "training" / "observability.py": (
        "_runtime_evidence",
        "_validate_report_document",
        "_reject_sensitive_values",
    ),
}


def _active_python_files() -> list[Path]:
    return [
        *CORE_SOURCE_ROOT.rglob("*.py"),
        *PERSISTENCE_SOURCE_ROOT.rglob("*.py"),
        *ML_SOURCE_ROOT.rglob("*.py"),
        *ML_ROOT.joinpath("scripts").glob("*.py"),
    ]


def _definitions(tree: ast.Module) -> dict[str, ast.AST]:
    definitions: dict[str, ast.AST] = {}
    for node in tree.body:
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        definitions[node.name] = node
        if isinstance(node, ast.ClassDef):
            definitions.update(
                {
                    f"{node.name}.{member.name}": member
                    for member in node.body
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
            )
    return definitions


def test_active_sources_and_scripts_have_module_docstrings() -> None:
    missing = [
        str(path.relative_to(WORKSPACE_ROOT))
        for path in _active_python_files()
        if ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) is None
    ]
    assert not missing, f"Módulos activos sin docstring: {missing}"


def test_critical_boundaries_have_docstrings() -> None:
    missing: list[str] = []
    for path, symbols in CRITICAL_DOCSTRINGS.items():
        definitions = _definitions(ast.parse(path.read_text(encoding="utf-8")))
        for symbol in symbols:
            node = definitions.get(symbol)
            if node is None or ast.get_docstring(node) is None:
                missing.append(f"{path.relative_to(WORKSPACE_ROOT)}:{symbol}")
    assert not missing, f"Fronteras críticas sin docstring: {missing}"
