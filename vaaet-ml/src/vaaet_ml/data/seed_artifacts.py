# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Snapshots semilla inmutables para el entrenamiento bootstrap."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

import pandas as pd
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.settings import FEATURE_COLS, MODEL_STATE_LABELS
from vaaet.timestamps import normalize_timestamp_series

from vaaet_ml.data.artifact_serialization import (
    atomic_json_write,
    frames_fingerprint,
    read_package_manifest,
    safe_relative_path,
    sha256_file,
    utc_now,
)
from vaaet_ml.data.package_codec import (
    DATASET_PACKAGE_CONTRACT,
    SEED_DATASET_PACKAGE_CONTRACT,
    create_dataset_package,
    load_dataset_package,
)

SEED_ARTIFACT_CONTRACT = "vaaet-seed-bootstrap-v1"
SEED_POINTER_CONTRACT = "vaaet-seed-bootstrap-pointer-v1"
SEED_POINTER_FILE = "current.json"


class DatasetArtifactAction(str, Enum):
    """Acción explícita sobre un artefacto inmutable y versionado."""

    REUSE_OR_CREATE = "reuse-or-create"
    CREATE_NEW_VERSION = "create-new-version"


@dataclass(frozen=True)
class SeedArtifactConfig:
    """Configuración de resolución para un snapshot semilla inmutable."""

    store_root: Path
    action: DatasetArtifactAction = DatasetArtifactAction.REUSE_OR_CREATE
    update_reason: str | None = None
    git_commit: str = "unknown"
    vaaet_version: str = "unknown"

    def __post_init__(self) -> None:
        object.__setattr__(self, "store_root", Path(self.store_root))
        object.__setattr__(self, "action", DatasetArtifactAction(self.action))
        if self.action is DatasetArtifactAction.CREATE_NEW_VERSION and not (
            self.update_reason and self.update_reason.strip()
        ):
            raise ValueError("Creating a new seed generation requires update_reason.")


@dataclass(frozen=True)
class SeedArtifactSnapshot:
    """Contenido y metadatos validados de un snapshot semilla."""

    path: Path
    manifest: Mapping[str, object]
    features: pd.DataFrame

    @property
    def descriptor(self) -> dict[str, object]:
        """Devuelve la identidad inmutable apta para el input lock de entrenamiento."""

        return {
            "contract": SEED_ARTIFACT_CONTRACT,
            "snapshot_id": str(self.manifest["snapshot_id"]),
            "generation": int(self.manifest["generation"]),
            "fingerprint": str(self.manifest["fingerprint"]),
            "sha256": str(self.manifest["package_sha256"]),
            "rows": int(len(self.features)),
            "filename": self.path.name,
        }


class VersionedSeedStore:
    """Snapshots semilla inmutables con un puntero current actualizado atómicamente."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.snapshots = self.root / "snapshots"
        self.pointer_path = self.root / SEED_POINTER_FILE

    def load_current(self) -> SeedArtifactSnapshot | None:
        """Carga el snapshot actual y verifica que el puntero coincida con su ZIP."""

        if not self.pointer_path.is_file():
            return None
        try:
            pointer = json.loads(self.pointer_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise ValueError("Invalid seed pointer.") from None
        if pointer.get("contract") != SEED_POINTER_CONTRACT:
            raise ValueError("Unsupported seed pointer contract.")
        if pointer.get("snapshot_contract") != SEED_ARTIFACT_CONTRACT:
            raise ValueError("Unsupported seed snapshot contract in pointer.")
        relative = safe_relative_path(pointer.get("path"))
        snapshot = self.load_snapshot(self.root.joinpath(*relative.parts))
        for field, value in snapshot.descriptor.items():
            if field != "contract" and field in pointer and pointer[field] != value:
                raise ValueError(f"Seed pointer {field} does not match its snapshot.")
        return snapshot

    def load_snapshot(self, path: str | Path) -> SeedArtifactSnapshot:
        """Valida el paquete y su proveniencia semilla antes de exponer sus features."""

        package = Path(path)
        frames = load_dataset_package(
            package,
            accepted_contracts=(SEED_DATASET_PACKAGE_CONTRACT, DATASET_PACKAGE_CONTRACT),
        )
        features = _prepare_seed_features(frames.get("features", pd.DataFrame()))
        manifest = read_package_manifest(package)
        metadata = manifest.get("package_metadata", {})
        provenance = manifest.get("provenance", {})
        contract = manifest.get("contract_version")
        if contract == DATASET_PACKAGE_CONTRACT and not (
            isinstance(provenance, Mapping)
            and provenance.get("training_mode") == "seed-bootstrap"
            and provenance.get("supervision") == "weak-proxy"
        ):
            raise ValueError("Legacy seed package lacks weak-proxy seed provenance.")
        if contract == SEED_DATASET_PACKAGE_CONTRACT:
            metadata = _validate_seed_metadata(metadata)
        else:
            metadata = {
                "snapshot_id": str(uuid.uuid5(uuid.UUID("5ef88f18-4663-4c81-a6f9-5b40b256e083"), frames_fingerprint({"features": features}))),
                "generation": 0,
                "fingerprint": frames_fingerprint({"features": features}),
                "created_at": "legacy",
                "previous_snapshot_id": None,
                "update_reason": "legacy import",
            }
        fingerprint = frames_fingerprint({"features": features})
        if metadata.get("fingerprint") != fingerprint:
            raise ValueError("Seed snapshot content fingerprint mismatch.")
        return SeedArtifactSnapshot(
            package.resolve(),
            {**metadata, "package_sha256": sha256_file(package)},
            features,
        )

    def resolve(
        self, features: pd.DataFrame, config: SeedArtifactConfig
    ) -> SeedArtifactSnapshot:
        """Reutiliza contenido idéntico o crea una nueva generación explícita."""

        prepared = _prepare_seed_features(features)
        fingerprint = frames_fingerprint({"features": prepared})
        current = self.load_current()
        if current is not None and current.manifest["fingerprint"] == fingerprint:
            return current
        if current is not None and config.action is DatasetArtifactAction.REUSE_OR_CREATE:
            raise ValueError(
                "Processed seed data differs from the current immutable snapshot. "
                "Use CREATE_NEW_VERSION with an update reason."
            )
        if current is None and config.action is DatasetArtifactAction.CREATE_NEW_VERSION:
            raise ValueError("No seed snapshot exists; use REUSE_OR_CREATE for generation 0001.")

        generation = 1 if current is None else int(current.manifest["generation"]) + 1
        metadata = self._metadata(current, generation, fingerprint, config)
        filename = f"vaaet-seed-bootstrap-v1-{generation:04d}-{fingerprint}.zip"
        final_path = self.snapshots / filename
        self.snapshots.mkdir(parents=True, exist_ok=True)
        if final_path.exists():
            return self._recover_existing(final_path, fingerprint, generation)
        temporary = self.snapshots / f".{filename}.{uuid.uuid4().hex}.tmp"
        try:
            create_dataset_package(
                temporary,
                features=prepared,
                provenance={
                    "training_mode": "seed-bootstrap",
                    "supervision": "weak-proxy",
                    "git_commit": config.git_commit,
                },
                contract_version=SEED_ARTIFACT_CONTRACT,
                package_metadata=metadata,
                overwrite=False,
            )
            candidate = self.load_snapshot(temporary)
            if (
                candidate.manifest["fingerprint"] != fingerprint
                or int(candidate.manifest["generation"]) != generation
            ):
                raise ValueError("Temporary seed snapshot validation returned different metadata.")
            os.replace(temporary, final_path)
            snapshot = self.load_snapshot(final_path)
            self._write_current_pointer(snapshot)
            return snapshot
        finally:
            temporary.unlink(missing_ok=True)

    def import_legacy(
        self, package_path: str | Path, config: SeedArtifactConfig
    ) -> SeedArtifactSnapshot:
        """Migra explícitamente un ZIP semilla legado al store inmutable."""

        return self.resolve(self.load_snapshot(package_path).features, config)

    def _write_current_pointer(self, snapshot: SeedArtifactSnapshot) -> None:
        try:
            relative = snapshot.path.relative_to(self.root.resolve())
        except ValueError as exc:
            raise ValueError("Seed snapshot is outside its configured store.") from exc
        pointer = {
            "contract": SEED_POINTER_CONTRACT,
            "snapshot_contract": SEED_ARTIFACT_CONTRACT,
            "path": PurePosixPath(*relative.parts).as_posix(),
            **{key: value for key, value in snapshot.descriptor.items() if key != "contract"},
        }
        atomic_json_write(self.pointer_path, pointer)

    def _recover_existing(
        self, path: Path, fingerprint: str, generation: int
    ) -> SeedArtifactSnapshot:
        try:
            snapshot = self.load_snapshot(path)
        except (OSError, ValueError) as exc:
            raise FileExistsError(
                "Seed snapshot exists without a valid pointer and failed validation; "
                f"the file was preserved for manual recovery: {path}"
            ) from exc
        if (
            snapshot.manifest["fingerprint"] != fingerprint
            or int(snapshot.manifest["generation"]) != generation
        ):
            raise FileExistsError(
                "Seed snapshot path is occupied by an incompatible immutable artifact: "
                f"{path}"
            )
        self._write_current_pointer(snapshot)
        return snapshot

    @staticmethod
    def _metadata(
        current: SeedArtifactSnapshot | None,
        generation: int,
        fingerprint: str,
        config: SeedArtifactConfig,
    ) -> dict[str, object]:
        return {
            "snapshot_id": str(uuid.uuid4()),
            "generation": generation,
            "fingerprint": fingerprint,
            "created_at": utc_now().isoformat(),
            "previous_snapshot_id": (
                str(current.manifest["snapshot_id"]) if current is not None else None
            ),
            "update_reason": (
                "initial processed seed snapshot"
                if current is None
                else str(config.update_reason).strip()
            ),
            "git_commit": config.git_commit,
            "vaaet_version": config.vaaet_version,
        }


def _prepare_seed_features(frame: pd.DataFrame) -> pd.DataFrame:
    _validate_seed_source(frame)
    result = frame.copy()
    result["record_time"] = normalize_timestamp_series(result["record_time"])
    result["traffic_state"] = pd.to_numeric(result["traffic_state"], errors="raise").astype(int)
    _validate_seed_labels(result)
    _validate_seed_schema(result)
    _validate_seed_feature_values(result)
    _validate_seed_natural_keys(result)
    metadata = [column for column in result if column not in FEATURE_COLS]
    return (
        result[[*metadata, *FEATURE_COLS]]
        .drop_duplicates(["clip_id", "record_time"], keep="last")
        .sort_values(["clip_id", "record_time"])
        .reset_index(drop=True)
    )


def _validate_seed_source(frame: pd.DataFrame) -> None:
    required = {"clip_id", "record_time", "traffic_state", *FEATURE_COLS}
    if frame.empty:
        raise ValueError("Seed snapshot cannot contain zero feature rows.")
    if missing := sorted(required - set(frame.columns)):
        raise ValueError(f"Seed snapshot is missing fields: {missing}")
    feature_order = [column for column in frame.columns if column in FEATURE_COLS]
    if feature_order != list(FEATURE_COLS):
        raise ValueError("Seed snapshot does not preserve the exact 19-feature order.")


def _validate_seed_labels(frame: pd.DataFrame) -> None:
    if not frame["traffic_state"].isin(MODEL_STATE_LABELS).all():
        raise ValueError("Seed snapshot may contain only stable proxy labels 0, 1, and 2.")
    if "is_human_validated" in frame and frame["is_human_validated"].fillna(False).any():
        raise ValueError("Seed snapshots cannot contain human-validated rows.")
    frame["is_human_validated"] = False


def _validate_seed_schema(frame: pd.DataFrame) -> None:
    if "feature_schema_version" not in frame:
        frame["feature_schema_version"] = FEATURE_SCHEMA_VERSION
    versions = set(frame["feature_schema_version"].dropna().astype(str))
    if versions != {FEATURE_SCHEMA_VERSION}:
        raise ValueError(f"Seed feature schema is incompatible: {sorted(versions)}")


def _validate_seed_feature_values(frame: pd.DataFrame) -> None:
    for column in FEATURE_COLS:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    if frame[FEATURE_COLS].isna().any().any():
        raise ValueError("Seed snapshot contains missing canonical feature values.")


def _validate_seed_natural_keys(frame: pd.DataFrame) -> None:
    comparison = ["traffic_state", *FEATURE_COLS]
    for _, group in frame.groupby(["clip_id", "record_time"], dropna=False):
        if len(group[comparison].drop_duplicates()) > 1:
            raise ValueError("Seed snapshot contains conflicting natural record keys.")


def _validate_seed_metadata(value: object) -> Mapping[str, object]:
    required = {
        "snapshot_id",
        "generation",
        "fingerprint",
        "created_at",
        "previous_snapshot_id",
        "update_reason",
    }
    if not isinstance(value, Mapping):
        raise ValueError("Seed package metadata must be a JSON object.")
    if missing := sorted(required - value.keys()):
        raise ValueError(f"Seed package metadata is incomplete: {missing}")
    try:
        uuid.UUID(str(value["snapshot_id"]))
    except ValueError as exc:
        raise ValueError("Seed snapshot_id must be a UUID.") from exc
    generation = value["generation"]
    if type(generation) is not int or generation < 1:
        raise ValueError("Seed generation must be a positive integer.")
    return value


__all__ = [
    "DatasetArtifactAction",
    "SEED_ARTIFACT_CONTRACT",
    "SEED_POINTER_FILE",
    "SeedArtifactConfig",
    "SeedArtifactSnapshot",
    "VersionedSeedStore",
]
