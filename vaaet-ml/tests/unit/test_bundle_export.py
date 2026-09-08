# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Garantías atómicas de publicación del bundle candidato."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from vaaet.artifacts import (
    LEGACY_MODEL_REVISION_ALGORITHM,
    MANIFEST_FILE,
    REQUIRED_FILES,
    calculate_model_revision,
    validate_manifest,
)

from vaaet_ml.training.bundle_export import (
    _replace_validated_directory,
    build_and_publish_bundle,
    reexport_historical_bundle,
)


class _Model:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def save(self, filepath: str | Path) -> None:
        Path(filepath).write_bytes(self.payload)


def _publish(destination: Path, payload: bytes) -> dict[str, object]:
    return build_and_publish_bundle(
        destination,
        model=_Model(payload),
        scaler={"scale": 1},
        label_mapping={0: "Normal", 1: "Reduced", 2: "Congested", 3: "Accident"},
        metrics={"direct_f1_macro": 0.5, "final_f1_macro": 0.5, "production_eligible": False},
        data_provenance={
            "origin": "test",
            "record_count": 3,
            "synthetic_data_included": False,
            "telemetry_v3_coverage": 0.0,
            "human_holdout": False,
            "production_eligible": False,
            "promotion_blockers": ["test bundle"],
        },
        training_lifecycle={
            "training_mode": "seed-bootstrap",
            "supervision": "weak-proxy",
            "deployment_stage": "pilot",
            "input_policy": "legacy-v1-bootstrap",
            "production_eligible": False,
        },
        decision_policy={"temperature": 1.0},
        human_holdout=None,
        training_input_lock=None,
    )


def test_bundle_is_published_only_after_full_validation(tmp_path: Path) -> None:
    destination = tmp_path / "bundle"

    manifest = _publish(destination, b"first-model")

    assert validate_manifest(destination)["model_revision"] == manifest["model_revision"]
    assert all((destination / name).is_file() for name in (*REQUIRED_FILES, MANIFEST_FILE))


def test_failed_final_validation_restores_previous_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "bundle"
    _publish(destination, b"first-model")
    original = {
        name: (destination / name).read_bytes() for name in (*REQUIRED_FILES, MANIFEST_FILE)
    }
    real_validate = validate_manifest
    calls = 0

    def fail_after_swap(path: str | Path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("simulated final validation failure")
        return real_validate(path)

    monkeypatch.setattr("vaaet_ml.training.bundle_export.validate_manifest", fail_after_swap)

    with pytest.raises(ValueError, match="simulated"):
        _publish(destination, b"second-model")

    assert {
        name: (destination / name).read_bytes() for name in (*REQUIRED_FILES, MANIFEST_FILE)
    } == original
    validate_manifest(destination)


def test_failed_first_move_preserves_original_bundle(tmp_path: Path) -> None:
    target = tmp_path / "bundle"
    staging = tmp_path / "staging"
    target.mkdir()
    staging.mkdir()
    sentinel = target / "original.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with (
        patch(
            "vaaet_ml.training.bundle_export.os.replace",
            side_effect=PermissionError("simulated first move failure"),
        ),
        pytest.raises(PermissionError, match="first move"),
    ):
        _replace_validated_directory(staging, target)

    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_existing_publication_lock_rejects_second_writer(tmp_path: Path) -> None:
    target = tmp_path / "bundle"
    staging = tmp_path / "staging"
    staging.mkdir()
    target.with_name(".bundle.publish.lock").touch()

    with pytest.raises(RuntimeError, match="owns the destination lock"):
        _replace_validated_directory(staging, target)


def test_failed_restoration_preserves_backup_for_manual_recovery(tmp_path: Path) -> None:
    target = tmp_path / "bundle"
    staging = tmp_path / "staging"
    target.mkdir()
    staging.mkdir()
    (target / "original.txt").write_text("keep", encoding="utf-8")
    real_replace = __import__("os").replace
    calls = 0

    def fail_install_and_restore(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls in {2, 3}:
            raise PermissionError("simulated recovery failure")
        real_replace(source, destination)

    with (
        patch("vaaet_ml.training.bundle_export.os.replace", side_effect=fail_install_and_restore),
        pytest.raises(RuntimeError, match="preserved backup"),
    ):
        _replace_validated_directory(staging, target)

    backups = list(tmp_path.glob(".bundle.backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "original.txt").read_text(encoding="utf-8") == "keep"


def test_failed_candidate_installation_restores_previous_bundle(tmp_path: Path) -> None:
    target = tmp_path / "bundle"
    staging = tmp_path / "staging"
    target.mkdir()
    staging.mkdir()
    (target / "original.txt").write_text("keep", encoding="utf-8")
    real_replace = __import__("os").replace
    calls = 0

    def fail_installation(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("simulated candidate installation failure")
        real_replace(source, destination)

    with (
        patch("vaaet_ml.training.bundle_export.os.replace", side_effect=fail_installation),
        pytest.raises(PermissionError, match="installation failure"),
    ):
        _replace_validated_directory(staging, target)

    assert (target / "original.txt").read_text(encoding="utf-8") == "keep"
    assert not list(tmp_path.glob(".bundle.backup-*"))


def test_failed_candidate_removal_preserves_backup_and_candidate(tmp_path: Path) -> None:
    target = tmp_path / "bundle"
    staging = tmp_path / "staging"
    target.mkdir()
    staging.mkdir()
    (target / "original.txt").write_text("keep", encoding="utf-8")
    (staging / "candidate.txt").write_text("invalid", encoding="utf-8")

    with (
        patch(
            "vaaet_ml.training.bundle_export.validate_manifest",
            side_effect=ValueError("simulated validation failure"),
        ),
        patch(
            "vaaet_ml.training.bundle_export.shutil.rmtree",
            side_effect=PermissionError("simulated candidate removal failure"),
        ),
        pytest.raises(RuntimeError, match="invalid candidate could not be removed"),
    ):
        _replace_validated_directory(staging, target)

    assert (target / "candidate.txt").read_text(encoding="utf-8") == "invalid"
    backups = list(tmp_path.glob(".bundle.backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "original.txt").read_text(encoding="utf-8") == "keep"


def test_historical_reexport_uses_new_destination_and_loses_eligibility(
    tmp_path: Path,
) -> None:
    source = tmp_path / "historical"
    _publish(source, b"historical-model")
    manifest_path = source / MANIFEST_FILE
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["model_revision"] = calculate_model_revision(
        file_hashes={name: document["files"][name]["sha256"] for name in REQUIRED_FILES},
        decision_policy=document["decision_policy"],
        feature_schema_version=document["feature_schema_version"],
        training_input_lock=document["training_input_lock"],
        input_policy=document["training_lifecycle"]["input_policy"],
        algorithm=LEGACY_MODEL_REVISION_ALGORITHM,
    )
    del document["model_revision_algorithm"]
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    destination = tmp_path / "reexported"

    reexported = reexport_historical_bundle(source, destination, reason="adopt corrected identity")

    assert reexported["model_revision"] != document["model_revision"]
    assert reexported["training_lifecycle"]["production_eligible"] is False
    assert (
        reexported["data_provenance"]["reexported_from_model_revision"]
        == document["model_revision"]
    )
    with pytest.raises(FileExistsError, match="already exists"):
        reexport_historical_bundle(source, destination, reason="repeat")


def test_historical_reexport_rejects_current_identity(tmp_path: Path) -> None:
    source = tmp_path / "current"
    _publish(source, b"current-model")

    with pytest.raises(ValueError, match="already uses the current"):
        reexport_historical_bundle(source, tmp_path / "copy", reason="not required")


def test_backup_cleanup_failure_does_not_undo_publication(tmp_path: Path) -> None:
    target = tmp_path / "bundle"
    staging = tmp_path / "staging"
    target.mkdir()
    staging.mkdir()
    (target / "payload.txt").write_text("old", encoding="utf-8")
    (staging / "payload.txt").write_text("new", encoding="utf-8")
    real_rmtree = shutil.rmtree

    def fail_backup_cleanup(path: str | Path) -> None:
        candidate = Path(path)
        if candidate.name.startswith(".bundle.backup-"):
            raise PermissionError("simulated cleanup failure")
        real_rmtree(candidate)

    with (
        patch("vaaet_ml.training.bundle_export.validate_manifest"),
        patch(
            "vaaet_ml.training.bundle_export.shutil.rmtree",
            side_effect=fail_backup_cleanup,
        ),
        pytest.warns(RuntimeWarning, match="recovery backup remains"),
    ):
        _replace_validated_directory(staging, target)

    assert (target / "payload.txt").read_text(encoding="utf-8") == "new"
    assert len(list(tmp_path.glob(".bundle.backup-*"))) == 1
