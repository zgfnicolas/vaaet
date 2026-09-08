# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Construcción y publicación atómica de bundles validados."""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

import joblib
from vaaet.artifacts import (
    CONTRACT_VERSION,
    LABEL_MAPPING_FILE,
    MANIFEST_FILE,
    MODEL_FILE,
    MODEL_REVISION_ALGORITHM,
    REQUIRED_FILES,
    SCALER_FILE,
    create_manifest,
    validate_manifest,
)


class SavableModel(Protocol):
    """Define el borde mínimo de guardado compatible con Keras."""

    def save(self, filepath: str | Path) -> None: ...


def build_and_publish_bundle(
    destination: str | Path,
    *,
    model: SavableModel,
    scaler: object,
    label_mapping: Mapping[int, str],
    metrics: Mapping[str, object],
    data_provenance: Mapping[str, object],
    training_lifecycle: Mapping[str, object],
    decision_policy: Mapping[str, object],
    human_holdout: Mapping[str, object] | None,
    training_input_lock: Mapping[str, object] | None,
) -> dict[str, object]:
    """Construye en staging y reemplaza la copia DVC sólo si valida completa."""

    target = Path(destination).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    try:
        if (target / ".gitkeep").is_file():
            shutil.copy2(target / ".gitkeep", staging / ".gitkeep")
        model.save(staging / MODEL_FILE)
        joblib.dump(scaler, staging / SCALER_FILE)
        joblib.dump(dict(label_mapping), staging / LABEL_MAPPING_FILE)
        create_manifest(
            staging,
            metrics=metrics,
            data_provenance=data_provenance,
            training_lifecycle=training_lifecycle,
            decision_policy=decision_policy,
            human_holdout=human_holdout,
            training_input_lock=training_input_lock,
        )
        manifest = dict(validate_manifest(staging))
        _replace_validated_directory(staging, target)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def publish_bundle_copy(source: str | Path, destination: str | Path) -> dict[str, object]:
    """Copia a Drive mediante staging y valida antes y después del reemplazo."""

    source_path = Path(source).resolve()
    validate_manifest(source_path)
    target = Path(destination).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    try:
        for name in (*REQUIRED_FILES, MANIFEST_FILE):
            shutil.copy2(source_path / name, staging / name)
        manifest = dict(validate_manifest(staging))
        _replace_validated_directory(staging, target)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def reexport_historical_bundle(
    source: str | Path,
    destination: str | Path,
    *,
    reason: str,
) -> dict[str, object]:
    """Reemite una identidad v3 antigua sin heredar elegibilidad operacional."""

    if not reason.strip():
        raise ValueError("Historical bundle re-export requires a non-empty reason.")
    source_path = Path(source).resolve()
    target = Path(destination).resolve()
    if target.exists():
        raise FileExistsError(f"Historical re-export destination already exists: {target}")
    original = dict(validate_manifest(source_path, allow_historical_revision=True))
    if original.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("Only historical bundle contract v3 can be re-exported.")
    if original.get("model_revision_algorithm") == MODEL_REVISION_ALGORITHM:
        raise ValueError("Bundle already uses the current model revision algorithm.")
    lifecycle = dict(_mapping(original, "training_lifecycle"))
    lifecycle["production_eligible"] = False
    if lifecycle.get("deployment_stage") == "production":
        lifecycle["deployment_stage"] = "candidate"
    metrics = dict(_mapping(original, "metrics"))
    metrics["production_eligible"] = False
    provenance = dict(_mapping(original, "data_provenance"))
    blockers = list(provenance.get("promotion_blockers", ()))
    blockers.append("re-exported identity requires evaluation under the corrected contract")
    provenance.update(
        {
            "production_eligible": False,
            "promotion_blockers": list(dict.fromkeys(blockers)),
            "reexported_from_model_revision": original.get("model_revision"),
            "reexport_reason": reason.strip(),
        }
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    try:
        for name in REQUIRED_FILES:
            shutil.copy2(source_path / name, staging / name)
        create_manifest(
            staging,
            metrics=metrics,
            data_provenance=provenance,
            training_lifecycle=lifecycle,
            decision_policy=_mapping(original, "decision_policy"),
            human_holdout=(
                _mapping(original, "human_holdout")
                if isinstance(original.get("human_holdout"), Mapping)
                else None
            ),
            training_input_lock=(
                _mapping(original, "training_input_lock")
                if isinstance(original.get("training_input_lock"), Mapping)
                else None
            ),
        )
        manifest = dict(validate_manifest(staging))
        _replace_validated_directory(staging, target)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _mapping(document: Mapping[str, object], field: str) -> Mapping[str, object]:
    value = document.get(field)
    if not isinstance(value, Mapping):
        raise ValueError(f"Historical bundle section is invalid: {field}")
    return value


def _replace_validated_directory(  # noqa: C901 - recuperación explícita por etapa.
    staging: Path, target: Path
) -> None:
    backup = target.with_name(f".{target.name}.backup-{uuid.uuid4().hex}")
    lock = target.with_name(f".{target.name}.publish.lock")
    moved_existing = False
    installed_candidate = False
    lock_descriptor: int | None = None
    try:
        try:
            lock_descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(
                f"Another bundle publication owns the destination lock: {lock}"
            ) from exc
        if target.exists():
            os.replace(target, backup)
            moved_existing = True
        os.replace(staging, target)
        installed_candidate = True
        validate_manifest(target)
    except Exception as publication_error:
        if installed_candidate and target.exists():
            try:
                shutil.rmtree(target)
            except Exception as removal_error:
                raise RuntimeError(
                    "Bundle publication failed and the invalid candidate could not be removed. "
                    f"Candidate destination={target}; preserved backup={backup}"
                ) from removal_error
        if moved_existing and backup.exists():
            try:
                os.replace(backup, target)
            except Exception as restore_error:
                raise RuntimeError(
                    "Bundle publication failed and automatic restoration also failed. "
                    f"Candidate destination={target}; preserved backup={backup}"
                ) from restore_error
        raise publication_error
    else:
        if backup.exists():
            try:
                shutil.rmtree(backup)
            except OSError as cleanup_error:
                warnings.warn(
                    f"Bundle was published, but its recovery backup remains at {backup}: "
                    f"{type(cleanup_error).__name__}",
                    RuntimeWarning,
                    stacklevel=2,
                )
    finally:
        if lock_descriptor is not None:
            try:
                os.close(lock_descriptor)
            except OSError as close_error:
                warnings.warn(
                    f"Bundle publication lock descriptor could not be closed: "
                    f"{type(close_error).__name__}",
                    RuntimeWarning,
                    stacklevel=2,
                )
            try:
                lock.unlink()
            except OSError as unlink_error:
                if not isinstance(unlink_error, FileNotFoundError):
                    warnings.warn(
                        f"Bundle publication lock remains at {lock}: {type(unlink_error).__name__}",
                        RuntimeWarning,
                        stacklevel=2,
                    )


__all__ = [
    "build_and_publish_bundle",
    "publish_bundle_copy",
    "reexport_historical_bundle",
]
