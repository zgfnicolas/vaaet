# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Finalización idempotente de sesiones de revisión humana HITL."""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

import pandas as pd
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.settings import MODEL_STATE_LABELS

from vaaet_ml.data.artifact_serialization import (
    frames_fingerprint,
    is_sha256,
    legacy_frames_fingerprint,
    read_package_manifest,
    sha256_file,
    stable_uuid,
    utc_now,
)
from vaaet_ml.data.hitl_catalog import (
    HITL_CATALOG_FILE,
    HITL_PACKAGE_FILE,
    HitlReviewCatalog,
)
from vaaet_ml.data.package_codec import create_dataset_package, load_dataset_package
from vaaet_ml.data.review_frames import normalize_review_frames

HITL_FINGERPRINT_ALGORITHM = "sha256-contractual-frames-v2"
LEGACY_HITL_FINGERPRINT_ALGORITHM = "sha256-contractual-frames-v1"


@dataclass(frozen=True)
class FinalizedReviewSession:
    """Resultado seguro de persistir localmente una sesión de revisión HITL."""

    package_id: str
    fingerprint: str
    package_sha256: str
    local_path: Path
    canonical_path: Path | None
    sync_status: str
    reviewed_rows: int
    pending_rows: int
    catalog_revision: int | None = None
    sync_error: str | None = None


def finalize_review_session(
    *,
    classified: pd.DataFrame,
    validations: pd.DataFrame | Sequence[object],
    pipeline_run_id: str,
    model_version: str,
    git_commit: str,
    vaaet_version: str,
    local_root: str | Path,
    canonical_root: str | Path | None = None,
) -> FinalizedReviewSession:
    """Finaliza una sesión inmutable y la registra opcionalmente en Drive."""

    finalized_at = utc_now()
    frames = normalize_review_frames(
        classified,
        validations,
        pipeline_run_id=pipeline_run_id,
        model_version=model_version,
        finalized_at=finalized_at,
    )
    fingerprint = _review_fingerprint(frames, HITL_FINGERPRINT_ALGORITHM)
    package_id = stable_uuid("hitl-package", pipeline_run_id, fingerprint)
    metadata = _session_metadata(
        frames,
        package_id=package_id,
        pipeline_run_id=pipeline_run_id,
        fingerprint=fingerprint,
        model_version=model_version,
        git_commit=git_commit,
        vaaet_version=vaaet_version,
        finalized_at=finalized_at,
    )
    local_path, metadata = _ensure_local_package(
        frames,
        metadata=metadata,
        local_root=Path(local_root),
        pipeline_run_id=pipeline_run_id,
        fingerprint=fingerprint,
    )
    package_sha256 = sha256_file(local_path)
    reviewed_rows = int(metadata["reviewed_rows"])
    pending_rows = int(metadata["pending_rows"])
    if canonical_root is None:
        return FinalizedReviewSession(
            package_id,
            fingerprint,
            package_sha256,
            local_path,
            None,
            "pending-sync",
            reviewed_rows,
            pending_rows,
        )
    return _sync_to_catalog(
        frames,
        metadata=metadata,
        package_id=package_id,
        fingerprint=fingerprint,
        package_sha256=package_sha256,
        local_path=local_path,
        canonical_root=Path(canonical_root),
        pipeline_run_id=pipeline_run_id,
        vaaet_version=vaaet_version,
        reviewed_rows=reviewed_rows,
        pending_rows=pending_rows,
    )


def sync_finalized_review_session(
    local_path: str | Path,
    *,
    canonical_root: str | Path,
) -> FinalizedReviewSession:
    """Sincroniza un ZIP local ya sellado sin reconstruir identidad ni fechas."""

    package = Path(local_path)
    frames = load_dataset_package(package)
    metadata = read_package_manifest(package).get("package_metadata", {})
    required = {
        "package_id",
        "pipeline_run_id",
        "fingerprint",
        "vaaet_version",
        "reviewed_rows",
        "pending_rows",
        "human_support",
        "model_revision",
        "finalized_at",
    }
    if not isinstance(metadata, Mapping):
        raise ValueError("Pending HITL package metadata must be an object.")
    missing = sorted(required - metadata.keys())
    if missing:
        raise ValueError(f"Pending HITL package metadata is incomplete: {missing}")
    fingerprint_algorithm = str(
        metadata.get("fingerprint_algorithm", LEGACY_HITL_FINGERPRINT_ALGORITHM)
    )
    fingerprint = _review_fingerprint(frames, fingerprint_algorithm)
    if fingerprint != metadata["fingerprint"]:
        raise ValueError("Pending HITL package content contradicts its fingerprint.")
    return _sync_to_catalog(
        frames,
        metadata=metadata,
        package_id=str(metadata["package_id"]),
        fingerprint=fingerprint,
        package_sha256=sha256_file(package),
        local_path=package,
        canonical_root=Path(canonical_root),
        pipeline_run_id=str(metadata["pipeline_run_id"]),
        vaaet_version=str(metadata["vaaet_version"]),
        reviewed_rows=int(metadata["reviewed_rows"]),
        pending_rows=int(metadata["pending_rows"]),
    )


def import_legacy_hitl_package(
    package_path: str | Path,
    *,
    pipeline_run_id: str,
    git_commit: str,
    vaaet_version: str,
    local_root: str | Path,
    canonical_root: str | Path,
) -> FinalizedReviewSession:
    """Migra explícitamente un ZIP HITL legado al catálogo inmutable."""

    frames = load_dataset_package(package_path)
    features = frames.get("features", pd.DataFrame())
    predictions = frames.get("predictions", pd.DataFrame())
    validations = frames.get("validations", pd.DataFrame())
    if features.empty or predictions.empty:
        raise ValueError("Legacy HITL import requires feature and prediction tables.")
    required_predictions = {"id", "telemetry_feature_id", "model_version", "model_revision"}
    if missing := sorted(required_predictions - set(predictions.columns)):
        raise ValueError(f"Legacy HITL predictions are missing fields: {missing}")
    projection = predictions[
        ["id", "telemetry_feature_id", "model_version", "model_revision"]
    ].rename(
        columns={
            "id": "prediction_id",
            "model_version": "imported_model_version",
            "model_revision": "imported_model_revision",
        }
    )
    classified = features.merge(
        projection,
        left_on="id",
        right_on="telemetry_feature_id",
        how="inner",
        validate="one_to_one",
    )
    if len(classified) != len(features):
        raise ValueError("Legacy HITL package does not relate every feature to one prediction.")
    model_versions = set(classified["imported_model_version"].dropna().astype(str))
    if len(model_versions) != 1:
        raise ValueError("Legacy HITL package must contain exactly one model version.")
    model_version = next(iter(model_versions))
    classified["model_version"] = model_version
    revisions = set(classified["imported_model_revision"].dropna().astype(str))
    if len(revisions) != 1 or not all(is_sha256(value) for value in revisions):
        raise ValueError(
            "Legacy HITL import requires a verifiable exact model_revision; "
            "incomplete packages are inspection-only."
        )
    classified["model_revision"] = next(iter(revisions))
    classified = classified.drop(
        columns=["telemetry_feature_id", "imported_model_version", "imported_model_revision"]
    )
    return finalize_review_session(
        classified=classified,
        validations=validations,
        pipeline_run_id=pipeline_run_id,
        model_version=model_version,
        git_commit=git_commit,
        vaaet_version=vaaet_version,
        local_root=local_root,
        canonical_root=canonical_root,
    )


def _session_metadata(
    frames: Mapping[str, pd.DataFrame],
    *,
    package_id: str,
    pipeline_run_id: str,
    fingerprint: str,
    model_version: str,
    git_commit: str,
    vaaet_version: str,
    finalized_at: datetime,
) -> dict[str, object]:
    validations = frames["validations"]
    predictions = frames["predictions"]
    return {
        "package_id": package_id,
        "pipeline_run_id": str(uuid.UUID(str(pipeline_run_id))),
        "finalized_at": finalized_at.isoformat(),
        "fingerprint": fingerprint,
        "fingerprint_algorithm": HITL_FINGERPRINT_ALGORITHM,
        "model_version": model_version,
        "model_revision": str(predictions["model_revision"].iloc[0]),
        "git_commit": git_commit,
        "vaaet_version": vaaet_version,
        "clips": sorted(frames["features"]["clip_id"].astype(str).unique().tolist()),
        "prediction_support": {
            str(state): int(count)
            for state, count in predictions.get("traffic_state", pd.Series(dtype=int))
            .value_counts()
            .sort_index()
            .items()
        },
        "reviewed_rows": int(len(validations)),
        "pending_rows": int(predictions["review_status"].eq("unreviewed").sum()),
        "human_support": _human_support(validations),
    }


def _ensure_local_package(
    frames: Mapping[str, pd.DataFrame],
    *,
    metadata: dict[str, object],
    local_root: Path,
    pipeline_run_id: str,
    fingerprint: str,
) -> tuple[Path, Mapping[str, object]]:
    local_path = local_root / "pending-sync" / f"{pipeline_run_id}_{fingerprint}" / HITL_PACKAGE_FILE
    if local_path.is_file():
        existing = read_package_manifest(local_path).get("package_metadata", {})
        if not isinstance(existing, Mapping) or existing.get("fingerprint") != fingerprint:
            raise ValueError("Pending HITL package path contains different session content.")
        load_dataset_package(local_path)
        return local_path, existing
    local_path.parent.mkdir(parents=True, exist_ok=True)
    create_dataset_package(
        local_path,
        features=frames["features"],
        predictions=frames["predictions"],
        validations=frames["validations"],
        provenance={"origin": "inference-human-review-session"},
        package_metadata=metadata,
        overwrite=False,
        include_empty_components=("validations",),
    )
    load_dataset_package(local_path)
    return local_path, metadata


def _sync_to_catalog(
    frames: Mapping[str, pd.DataFrame],
    *,
    metadata: Mapping[str, object],
    package_id: str,
    fingerprint: str,
    package_sha256: str,
    local_path: Path,
    canonical_root: Path,
    pipeline_run_id: str,
    vaaet_version: str,
    reviewed_rows: int,
    pending_rows: int,
) -> FinalizedReviewSession:
    """Sincroniza el paquete en forma idempotente y verifica su identidad canónica."""

    catalog = HitlReviewCatalog(canonical_root / HITL_CATALOG_FILE)
    existing = catalog.find(pipeline_run_id=str(pipeline_run_id), fingerprint=fingerprint)
    if existing is not None:
        canonical_path = catalog.package_path(existing)
        if not canonical_path.is_file() or sha256_file(canonical_path) != existing["sha256"]:
            raise ValueError("Cataloged HITL package is missing or corrupted.")
        return FinalizedReviewSession(
            package_id,
            fingerprint,
            package_sha256,
            local_path,
            canonical_path,
            "synced",
            reviewed_rows,
            pending_rows,
            int(catalog.load()["revision"]),
        )
    try:
        canonical_path, document = _publish_to_catalog(
            catalog,
            frames=frames,
            metadata=metadata,
            package_id=package_id,
            fingerprint=fingerprint,
            package_sha256=package_sha256,
            local_path=local_path,
            pipeline_run_id=pipeline_run_id,
            vaaet_version=vaaet_version,
            reviewed_rows=reviewed_rows,
            pending_rows=pending_rows,
        )
    except (OSError, ValueError) as exc:
        return FinalizedReviewSession(
            package_id,
            fingerprint,
            package_sha256,
            local_path,
            None,
            "pending-sync",
            reviewed_rows,
            pending_rows,
            sync_error=f"Drive synchronization failed ({type(exc).__name__}).",
        )
    return FinalizedReviewSession(
        package_id,
        fingerprint,
        package_sha256,
        local_path,
        canonical_path,
        "synced",
        reviewed_rows,
        pending_rows,
        int(document["revision"]),
    )


def _publish_to_catalog(
    catalog: HitlReviewCatalog,
    *,
    frames: Mapping[str, pd.DataFrame],
    metadata: Mapping[str, object],
    package_id: str,
    fingerprint: str,
    package_sha256: str,
    local_path: Path,
    pipeline_run_id: str,
    vaaet_version: str,
    reviewed_rows: int,
    pending_rows: int,
) -> tuple[Path, dict[str, object]]:
    finalized_at = datetime.fromisoformat(str(metadata["finalized_at"]).replace("Z", "+00:00"))
    relative_path = PurePosixPath(
        f"{finalized_at:%Y}",
        f"{finalized_at:%m}",
        f"{finalized_at:%d}",
        f"{finalized_at:%Y%m%dT%H%M%SZ}_{pipeline_run_id}_{fingerprint}",
        HITL_PACKAGE_FILE,
    )
    canonical_path = catalog.root.joinpath(*relative_path.parts)
    _copy_immutable(local_path, canonical_path, package_sha256)
    remote_frames = load_dataset_package(canonical_path)
    fingerprint_algorithm = str(
        metadata.get("fingerprint_algorithm", LEGACY_HITL_FINGERPRINT_ALGORITHM)
    )
    if _review_fingerprint(remote_frames, fingerprint_algorithm) != fingerprint:
        raise ValueError("The synchronized HITL package failed remote content validation.")
    entry = {
        "package_id": package_id,
        "path": relative_path.as_posix(),
        "created_at": str(metadata["finalized_at"]),
        "pipeline_run_id": str(uuid.UUID(str(pipeline_run_id))),
        "sha256": package_sha256,
        "fingerprint": fingerprint,
        "fingerprint_algorithm": fingerprint_algorithm,
        "clips": int(frames["features"]["clip_id"].nunique()),
        "rows": {
            "features": int(len(frames["features"])),
            "predictions": int(len(frames["predictions"])),
            "validations": reviewed_rows,
            "unreviewed": pending_rows,
        },
        "human_support": dict(metadata["human_support"]),
        "status": "active",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "model_revision": str(metadata["model_revision"]),
        "vaaet_version": vaaet_version,
    }
    return canonical_path, catalog.register(entry)


def _copy_immutable(source: Path, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256_file(destination) != expected_sha256:
            raise ValueError("Immutable HITL destination already contains different data.")
        return
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        if sha256_file(temporary) != expected_sha256:
            raise ValueError("HITL package checksum changed during Drive synchronization.")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _human_support(validations: pd.DataFrame) -> dict[str, int]:
    labels = {**MODEL_STATE_LABELS, 3: "Accident"}
    if validations.empty:
        return {label: 0 for label in labels.values()}
    return {
        label: int(validations["validated_state"].eq(state).sum())
        for state, label in labels.items()
    }


def _review_fingerprint(
    frames: Mapping[str, pd.DataFrame], algorithm: str
) -> str:
    if algorithm == HITL_FINGERPRINT_ALGORITHM:
        return frames_fingerprint(frames)
    if algorithm == LEGACY_HITL_FINGERPRINT_ALGORITHM:
        return legacy_frames_fingerprint(frames)
    raise ValueError(f"Unsupported HITL fingerprint algorithm: {algorithm}")


__all__ = [
    "FinalizedReviewSession",
    "HITL_FINGERPRINT_ALGORITHM",
    "LEGACY_HITL_FINGERPRINT_ALGORITHM",
    "finalize_review_session",
    "import_legacy_hitl_package",
    "sync_finalized_review_session",
]
