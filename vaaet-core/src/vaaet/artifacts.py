# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Contrato portable de bundles de modelos compartido con sistemas posteriores."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import re
import subprocess
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from vaaet.exceptions import ArtifactNotFoundError
from vaaet.settings import (
    DEFAULT_CLASS_THRESHOLDS,
    DEFAULT_MIN_PROBABILITY_MARGIN,
    FEATURE_COLS,
    MODEL_STATE_LABELS,
    MODEL_VERSION,
    RECOVERY_PERSISTENCE_MINUTES,
    STATE_LABELS,
    WORSENING_PERSISTENCE_MINUTES,
)

CONTRACT_VERSION = 3
MODEL_REVISION_ALGORITHM = "sha256-inference-contract-v2"
LEGACY_MODEL_REVISION_ALGORITHM = "sha256-inference-contract-v1"
FEATURE_SCHEMA_VERSION = "traffic-features-v3"
LEGACY_CONTRACT_VERSION = 2
LEGACY_FEATURE_SCHEMA_VERSION = "traffic-features-v2"
MODEL_FILE = "traffic_classifier.keras"
SCALER_FILE = "feature_scaler.joblib"
LABEL_MAPPING_FILE = "label_mapping.joblib"
MANIFEST_FILE = "model-manifest.json"
REQUIRED_FILES = (MODEL_FILE, SCALER_FILE, LABEL_MAPPING_FILE)
REQUIRED_FIELDS = {
    "contract_version",
    "feature_schema_version",
    "model_version",
    "model_revision",
    "model_revision_algorithm",
    "generated_at",
    "git_commit",
    "feature_columns",
    "class_mapping",
    "model_output_mapping",
    "decision_policy",
    "files",
    "dependencies",
    "metrics",
    "data_provenance",
    "training_lifecycle",
}
REQUIRED_DEPENDENCIES = ("tensorflow", "scikit-learn", "joblib")
REQUIRED_PROVENANCE_FIELDS = {
    "origin",
    "record_count",
    "synthetic_data_included",
    "human_holdout",
    "production_eligible",
    "promotion_blockers",
}
REQUIRED_POLICY_FIELDS = {
    "architecture",
    "class_thresholds",
    "minimum_probability_margin",
    "worsening_persistence_minutes",
    "recovery_persistence_minutes",
    "automatic_accident_state_allowed",
    "human_confirmation_required_for_accident",
    "temperature",
}
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class TrafficBundleManifest(TypedDict):
    """Estructura validada del manifiesto consumida antes de deserializar."""

    contract_version: int
    feature_schema_version: str
    model_version: str
    model_revision: str
    model_revision_algorithm: str
    generated_at: str
    git_commit: str
    feature_columns: list[str]
    class_mapping: Mapping[str, str]
    model_output_mapping: Mapping[str, str]
    decision_policy: Mapping[str, object]
    files: Mapping[str, Mapping[str, object]]
    dependencies: Mapping[str, str]
    metrics: Mapping[str, object]
    data_provenance: Mapping[str, object]
    training_lifecycle: Mapping[str, object]
    human_holdout: Mapping[str, object] | None
    training_input_lock: Mapping[str, object] | None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _installed_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _git_commit(path: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=path,
            capture_output=True,
            check=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _portable_json_value(value: object) -> object:
    """Convierte evidencia no disponible a JSON estándar antes de publicar."""

    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Mapping):
        return {str(key): _portable_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_portable_json_value(item) for item in value]
    return value


def calculate_model_revision(
    *,
    file_hashes: Mapping[str, str],
    decision_policy: Mapping[str, object],
    feature_schema_version: str,
    training_input_lock: Mapping[str, object] | None,
    input_policy: str,
    algorithm: str = MODEL_REVISION_ALGORITHM,
) -> str:
    """Identifica de forma inmutable pesos, transformación y política exactos."""

    payload = {
        "files": {name: file_hashes[name] for name in sorted(file_hashes)},
        "decision_policy": dict(decision_policy),
        "feature_schema_version": feature_schema_version,
        "training_input_lock": dict(training_input_lock or {}),
        "input_policy": input_policy,
        "algorithm": algorithm,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_manifest(
    bundle_dir: str | Path,
    *,
    metrics: Mapping[str, object],
    data_provenance: Mapping[str, object],
    training_lifecycle: Mapping[str, object],
    decision_policy: Mapping[str, object] | None = None,
    human_holdout: Mapping[str, object] | None = None,
    training_input_lock: Mapping[str, object] | None = None,
) -> Path:
    """Crea el manifiesto de serving después de una exportación válida."""
    directory = Path(bundle_dir).resolve()
    missing = [name for name in REQUIRED_FILES if not (directory / name).is_file()]
    if missing:
        raise ArtifactNotFoundError(f"Missing artifact files: {', '.join(missing)}")

    policy: dict[str, object] = {
        "architecture": "hierarchical-stable-flow-with-incident-candidate",
        "class_thresholds": {str(key): value for key, value in DEFAULT_CLASS_THRESHOLDS.items()},
        "minimum_probability_margin": DEFAULT_MIN_PROBABILITY_MARGIN,
        "worsening_persistence_minutes": WORSENING_PERSISTENCE_MINUTES,
        "recovery_persistence_minutes": RECOVERY_PERSISTENCE_MINUTES,
        "automatic_accident_state_allowed": False,
        "human_confirmation_required_for_accident": True,
        "temperature": 1.0,
    }
    if decision_policy:
        policy.update(dict(decision_policy))
    lifecycle = dict(training_lifecycle)
    file_hashes = {name: _sha256(directory / name) for name in REQUIRED_FILES}
    model_revision = calculate_model_revision(
        file_hashes=file_hashes,
        decision_policy=policy,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        training_input_lock=training_input_lock,
        input_policy=str(lifecycle.get("input_policy", "")),
    )
    manifest: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "model_revision": model_revision,
        "model_revision_algorithm": MODEL_REVISION_ALGORITHM,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(directory),
        "feature_columns": list(FEATURE_COLS),
        "class_mapping": {str(key): value for key, value in STATE_LABELS.items()},
        "model_output_mapping": {str(key): value for key, value in MODEL_STATE_LABELS.items()},
        "decision_policy": policy,
        "files": {name: {"sha256": digest} for name, digest in file_hashes.items()},
        "dependencies": {
            name: _installed_version(name) or "unknown" for name in REQUIRED_DEPENDENCIES
        },
        "metrics": dict(metrics),
        "data_provenance": dict(data_provenance),
        "training_lifecycle": lifecycle,
        "human_holdout": dict(human_holdout) if human_holdout is not None else None,
        "training_input_lock": (
            dict(training_input_lock) if training_input_lock is not None else None
        ),
    }
    portable_manifest = _portable_json_value(manifest)
    if not isinstance(portable_manifest, dict):  # Protege la raíz contractual.
        raise TypeError("Bundle manifest must serialize as a JSON object.")
    output = directory / MANIFEST_FILE
    output.write_text(
        json.dumps(portable_manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    validate_manifest(directory)
    return output


def validate_manifest(
    bundle_dir: str | Path, *, allow_historical_revision: bool = False
) -> TrafficBundleManifest:
    """Valida compatibilidad e integridad antes de cargar un bundle soportado."""
    # La importación diferida mantiene la fachada pública libre de un ciclo de
    # importación: los validadores sólo necesitan el contrato ya definido arriba.
    from vaaet.artifact_validation import validate_manifest as _validate_manifest

    return _validate_manifest(bundle_dir, allow_historical_revision=allow_historical_revision)
