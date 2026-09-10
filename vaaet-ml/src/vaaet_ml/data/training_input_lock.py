# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Lock inmutable de los inputs exactos seleccionados para entrenar."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from vaaet.artifacts import FEATURE_SCHEMA_VERSION

from vaaet_ml.data.artifact_serialization import (
    atomic_json_write,
    json_safe,
    sha256_bytes,
    stable_uuid,
    utc_now,
)

TRAINING_INPUT_LOCK_CONTRACT = "vaaet-training-input-lock-v1"


@dataclass(frozen=True)
class TrainingInputLock:
    """Documento persistido que identifica los inputs inmutables del entrenamiento."""

    path: Path
    document: Mapping[str, object]

    @property
    def descriptor(self) -> dict[str, str]:
        """Devuelve el descriptor mínimo incluido en el manifiesto de bundle."""

        return {
            "contract": TRAINING_INPUT_LOCK_CONTRACT,
            "lock_id": str(self.document["lock_id"]),
            "fingerprint": str(self.document["fingerprint"]),
            "feature_schema_version": str(self.document["feature_schema_version"]),
        }


def create_training_input_lock(
    output_root: str | Path,
    *,
    training_pipeline_run_id: str,
    training_mode: str,
    seed_snapshot: Mapping[str, object] | None,
    hitl_catalog: Mapping[str, object] | None,
    human_holdout: Mapping[str, object] | None,
    result_rows: Mapping[str, int],
    resolution: Mapping[str, int],
    numeric_representations: Mapping[str, int] | None = None,
) -> TrainingInputLock:
    """Persiste los inputs exactos de un entrenamiento sin aceptar sobrescrituras."""

    run_id = str(uuid.UUID(str(training_pipeline_run_id)))
    fingerprint_payload = json_safe(
        {
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "training_mode": training_mode,
            "seed_snapshot": dict(seed_snapshot) if seed_snapshot is not None else None,
            "hitl_catalog": dict(hitl_catalog) if hitl_catalog is not None else None,
            "human_holdout": dict(human_holdout) if human_holdout is not None else None,
            "result_rows": {key: int(value) for key, value in sorted(result_rows.items())},
            "resolution": {key: int(value) for key, value in sorted(resolution.items())},
            "numeric_representations": {
                key: int(value)
                for key, value in sorted((numeric_representations or {}).items())
            },
        }
    )
    if not isinstance(fingerprint_payload, dict):  # Protege la forma estable de este contrato.
        raise ValueError("Training input lock payload must be a JSON object.")
    canonical = json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"))
    fingerprint = sha256_bytes(canonical.encode("utf-8"))
    document = {
        "contract": TRAINING_INPUT_LOCK_CONTRACT,
        "lock_id": stable_uuid("training-input-lock", fingerprint),
        "fingerprint": fingerprint,
        "created_at": utc_now().isoformat(),
        "training_pipeline_run_id": run_id,
        **fingerprint_payload,
    }
    path = Path(output_root) / run_id / "training-input-lock.json"
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("fingerprint") != fingerprint:
            raise ValueError("Training run already has a different input lock.")
        return TrainingInputLock(path.resolve(), existing)
    atomic_json_write(path, document)
    return TrainingInputLock(path.resolve(), document)


__all__ = [
    "TRAINING_INPUT_LOCK_CONTRACT",
    "TrainingInputLock",
    "create_training_input_lock",
]
