# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Catálogo inmutable y resolución global de paquetes de revisión HITL."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path, PurePosixPath

import pandas as pd
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.continuity import normalize_continuity_frame
from vaaet.settings import FEATURE_COLS
from vaaet.timestamps import normalize_timestamp_series

from vaaet_ml.data.artifact_serialization import (
    atomic_json_write,
    is_sha256,
    read_package_manifest,
    safe_relative_path,
    sha256_file,
    utc_now,
    valid_uuid,
)
from vaaet_ml.data.package_codec import load_dataset_package

HITL_CATALOG_CONTRACT = "vaaet-dataset-catalog-v1"
HITL_CATALOG_FILE = "catalog.json"
HITL_PACKAGE_FILE = "vaaet-training-dataset-v1.zip"


class CatalogSelection(str, Enum):
    """Selecciones deterministas admitidas del catálogo HITL."""

    ALL_ACTIVE = "all-active"


@dataclass(frozen=True)
class HitlCatalogSource:
    """Origen inmutable y selección explícita para cargar feedback HITL."""

    catalog_path: Path
    selection: CatalogSelection = CatalogSelection.ALL_ACTIVE

    def __post_init__(self) -> None:
        object.__setattr__(self, "catalog_path", Path(self.catalog_path))
        object.__setattr__(self, "selection", CatalogSelection(self.selection))


class HitlReviewCatalog:
    """Catálogo atómico de paquetes HITL con checksum e historial inmutable."""

    def __init__(self, catalog_path: str | Path) -> None:
        self.path = Path(catalog_path)
        self.root = self.path.parent

    def load(self) -> dict[str, object]:
        """Carga y valida el catálogo, o devuelve un documento vacío válido."""

        if not self.path.is_file():
            return {
                "contract": HITL_CATALOG_CONTRACT,
                "revision": 0,
                "updated_at": None,
                "entries": [],
            }
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid HITL catalog: {exc}") from exc
        self._validate(document)
        return document

    def find(self, *, pipeline_run_id: str, fingerprint: str) -> dict[str, object] | None:
        """Encuentra el único registro idempotente de una sesión finalizada."""

        return next(
            (
                entry
                for entry in self.load()["entries"]
                if entry["pipeline_run_id"] == pipeline_run_id
                and entry["fingerprint"] == fingerprint
            ),
            None,
        )

    def register(self, entry: Mapping[str, object]) -> dict[str, object]:
        """Registra una entrada nueva sin reemplazar paquetes ya publicados."""

        document = self.load()
        entries = document["entries"]
        existing = next(
            (
                item
                for item in entries
                if item["package_id"] == entry.get("package_id")
                or (
                    item["pipeline_run_id"] == entry.get("pipeline_run_id")
                    and item["fingerprint"] == entry.get("fingerprint")
                )
            ),
            None,
        )
        if existing is not None:
            if dict(existing) != dict(entry):
                raise ValueError("Catalog registration conflicts with an existing package.")
            return document
        updated = {
            **document,
            "revision": int(document["revision"]) + 1,
            "updated_at": utc_now().isoformat(),
            "entries": [*entries, dict(entry)],
        }
        self._validate(updated)
        atomic_json_write(self.path, updated)
        return updated

    def selected_entries(
        self, selection: CatalogSelection = CatalogSelection.ALL_ACTIVE
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        """Devuelve entradas activas ordenadas de forma estable."""

        if CatalogSelection(selection) is not CatalogSelection.ALL_ACTIVE:
            raise ValueError(f"Unsupported catalog selection: {selection}")
        document = self.load()
        entries = [entry for entry in document["entries"] if entry["status"] == "active"]
        entries.sort(key=lambda entry: (entry["created_at"], entry["package_id"]))
        return document, entries

    def set_status(self, package_id: str, status: str) -> dict[str, object]:
        """Activa o pone en cuarentena una entrada sin borrarla del historial."""

        if status not in {"active", "quarantined"}:
            raise ValueError("Catalog status must be active or quarantined.")
        normalized_id = str(uuid.UUID(str(package_id)))
        document = self.load()
        matches = [entry for entry in document["entries"] if entry["package_id"] == normalized_id]
        if not matches:
            raise KeyError(f"HITL catalog package not found: {normalized_id}")
        if matches[0]["status"] == status:
            return document
        updated = {
            **document,
            "revision": int(document["revision"]) + 1,
            "updated_at": utc_now().isoformat(),
            "entries": [
                {**entry, "status": status} if entry["package_id"] == normalized_id else entry
                for entry in document["entries"]
            ],
        }
        self._validate(updated)
        atomic_json_write(self.path, updated)
        return updated

    def package_path(self, entry: Mapping[str, object]) -> Path:
        """Resuelve la ruta de una entrada sin permitir escapes del catálogo."""

        relative = safe_relative_path(entry.get("path"))
        candidate = self.root.joinpath(*relative.parts).resolve()
        root = self.root.resolve()
        if root != candidate and root not in candidate.parents:
            raise ValueError("Catalog package path escapes its root.")
        return candidate

    def _validate(self, document: object) -> None:
        if not isinstance(document, dict) or document.get("contract") != HITL_CATALOG_CONTRACT:
            raise ValueError("Unsupported HITL catalog contract.")
        if type(document.get("revision")) is not int or document["revision"] < 0:
            raise ValueError("HITL catalog revision must be a non-negative integer.")
        entries = document.get("entries")
        if not isinstance(entries, list):
            raise ValueError("HITL catalog entries must be a list.")
        package_ids: set[str] = set()
        paths: set[str] = set()
        for entry in entries:
            self._validate_entry(entry, package_ids, paths)

    @staticmethod
    def _validate_entry(entry: object, package_ids: set[str], paths: set[str]) -> None:
        if not isinstance(entry, dict):
            raise ValueError("HITL catalog entries must be JSON objects.")
        relative = _validate_catalog_entry_identity(entry, package_ids, paths)
        _validate_catalog_entry_integrity(entry)
        _validate_catalog_entry_lifecycle(entry)
        _validate_catalog_entry_counts(entry)
        _validate_catalog_entry_version(entry)
        package_ids.add(str(entry["package_id"]))
        paths.add(relative)


def _validate_catalog_entry_identity(
    entry: dict[str, object], package_ids: set[str], paths: set[str]
) -> str:
    required = {
        "package_id",
        "path",
        "created_at",
        "pipeline_run_id",
        "sha256",
        "fingerprint",
        "clips",
        "rows",
        "human_support",
        "status",
        "feature_schema_version",
        "model_revision",
        "vaaet_version",
    }
    if missing := sorted(required - entry.keys()):
        raise ValueError(f"HITL catalog entry is incomplete: {missing}")
    try:
        uuid.UUID(str(entry["package_id"]))
        uuid.UUID(str(entry["pipeline_run_id"]))
    except ValueError as exc:
        raise ValueError("Catalog package and pipeline run IDs must be UUIDs.") from exc
    relative = safe_relative_path(entry["path"]).as_posix()
    if PurePosixPath(relative).name != HITL_PACKAGE_FILE:
        raise ValueError("Catalog entries must reference the contractual HITL filename.")
    if entry["package_id"] in package_ids or relative in paths:
        raise ValueError("HITL catalog contains duplicate IDs or paths.")
    return relative


def _validate_catalog_entry_integrity(entry: Mapping[str, object]) -> None:
    if not is_sha256(entry["sha256"]) or not is_sha256(entry["fingerprint"]):
        raise ValueError("HITL catalog checksums must be SHA-256.")
    if not is_sha256(entry["model_revision"]):
        raise ValueError("HITL catalog model_revision must be SHA-256.")


def _validate_catalog_entry_lifecycle(entry: Mapping[str, object]) -> None:
    if entry["status"] not in {"active", "quarantined"}:
        raise ValueError("HITL catalog status must be active or quarantined.")
    try:
        created_at = datetime.fromisoformat(str(entry["created_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("HITL catalog created_at must be ISO-8601.") from exc
    if created_at.tzinfo is None:
        raise ValueError("HITL catalog created_at must include a timezone.")


def _validate_catalog_entry_counts(entry: Mapping[str, object]) -> None:
    if type(entry["clips"]) is not int or entry["clips"] < 0:
        raise ValueError("HITL catalog clip count must be non-negative.")
    for field in ("rows", "human_support"):
        values = entry[field]
        if not isinstance(values, dict) or any(
            type(value) is not int or value < 0 for value in values.values()
        ):
            raise ValueError(f"HITL catalog {field} must contain non-negative counts.")


def _validate_catalog_entry_version(entry: Mapping[str, object]) -> None:
    if entry["feature_schema_version"] != FEATURE_SCHEMA_VERSION:
        raise ValueError("HITL catalog feature schema is incompatible.")
    if not isinstance(entry["vaaet_version"], str) or not entry["vaaet_version"]:
        raise ValueError("HITL catalog VAAET version must be non-empty.")


def load_hitl_catalog_feedback(
    source: HitlCatalogSource,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Carga y resuelve el feedback humano efectivo de paquetes activos."""

    combined, source_descriptor = load_hitl_catalog_components(source)
    input_counts = {kind: int(len(frame)) for kind, frame in combined.items()}
    features = _deduplicate_uuid_rows(combined["features"], name="features")
    predictions = _deduplicate_uuid_rows(combined["predictions"], name="predictions")
    validations = _deduplicate_uuid_rows(combined["validations"], name="validations")
    feedback = resolve_effective_human_feedback(features, predictions, validations)
    descriptor = {
        **source_descriptor,
        "resolved_validations": int(len(feedback)),
        "duplicate_rows_resolved": {
            kind: input_counts[kind] - len(frame)
            for kind, frame in {
                "features": features,
                "predictions": predictions,
                "validations": validations,
            }.items()
        },
        "corrections_resolved": int(
            validations.get("supersedes_validation_id", pd.Series(dtype=object))
            .fillna("")
            .astype(str)
            .str.strip()
            .ne("")
            .sum()
        ),
    }
    feedback.attrs["vaaet_provenance"] = descriptor
    return feedback, descriptor


def load_hitl_catalog_components(
    source: HitlCatalogSource,
) -> tuple[dict[str, pd.DataFrame], dict[str, object]]:
    """Carga componentes sin resolverlos para consolidar varias fuentes globalmente."""

    catalog = HitlReviewCatalog(source.catalog_path)
    document, entries = catalog.selected_entries(source.selection)
    if not entries:
        raise ValueError("The HITL catalog contains no active packages.")
    frames_by_kind = _load_catalog_frames(catalog, entries)
    combined = {
        kind: pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        for kind, frames in frames_by_kind.items()
    }
    return combined, {
        "contract": HITL_CATALOG_CONTRACT,
        "revision": int(document["revision"]),
        "catalog_sha256": sha256_file(source.catalog_path),
        "package_ids": [entry["package_id"] for entry in entries],
        "package_fingerprints": [entry["fingerprint"] for entry in entries],
        "package_sha256": [entry["sha256"] for entry in entries],
    }


def _load_catalog_frames(
    catalog: HitlReviewCatalog, entries: list[dict[str, object]]
) -> dict[str, list[pd.DataFrame]]:
    frames_by_kind: dict[str, list[pd.DataFrame]] = {
        "features": [],
        "predictions": [],
        "validations": [],
    }
    for entry in entries:
        package_path = catalog.package_path(entry)
        if not package_path.is_file():
            raise FileNotFoundError(f"Cataloged HITL package not found: {package_path}")
        if sha256_file(package_path) != entry["sha256"]:
            raise ValueError(f"Cataloged HITL package checksum mismatch: {entry['package_id']}")
        package_frames = load_dataset_package(package_path)
        metadata = read_package_manifest(package_path).get("package_metadata", {})
        if not isinstance(metadata, Mapping) or metadata.get("fingerprint") != entry["fingerprint"]:
            raise ValueError(f"Cataloged HITL package fingerprint mismatch: {entry['package_id']}")
        for kind in frames_by_kind:
            frame = package_frames.get(kind, pd.DataFrame()).copy()
            if not frame.empty:
                frame["_catalog_package_id"] = entry["package_id"]
                frames_by_kind[kind].append(frame)
    return frames_by_kind


def resolve_effective_human_feedback(  # noqa: C901 - consolida el borde HITL completo.
    features: pd.DataFrame, predictions: pd.DataFrame, validations: pd.DataFrame
) -> pd.DataFrame:
    if features.empty or predictions.empty:
        raise ValueError("Active HITL packages contain no compatible features and predictions.")
    if validations.empty:
        return pd.DataFrame()
    features = _deduplicate_uuid_rows(features, name="features")
    predictions = _deduplicate_uuid_rows(predictions, name="predictions")
    validations = _deduplicate_uuid_rows(validations, name="validations")
    if not set(predictions["telemetry_feature_id"].astype(str)).issubset(
        set(features["id"].astype(str))
    ):
        raise ValueError("Catalog predictions reference missing feature UUIDs.")
    if not set(validations["prediction_id"].astype(str)).issubset(
        set(predictions["id"].astype(str))
    ):
        raise ValueError("Catalog validations reference missing prediction UUIDs.")
    validated_flags = validations.get("is_human_validated")
    if validated_flags is None or not validated_flags.map(_strict_boolean).all():
        raise ValueError("HITL validation history contains records without human confirmation.")
    latest = _resolve_validation_graph(validations).rename(columns={"id": "validation_id"})
    required_prediction_columns = {"id", "telemetry_feature_id", "model_version", "model_revision"}
    if missing := sorted(required_prediction_columns - set(predictions.columns)):
        raise ValueError(f"Catalog predictions are missing fields: {missing}")
    projection_columns = ["id", "telemetry_feature_id", "model_version", "model_revision"]
    if "numeric_representation" in predictions:
        projection_columns.append("numeric_representation")
    projection = predictions[projection_columns].rename(
        columns={"numeric_representation": "prediction_numeric_representation"}
    )
    feedback = features.merge(
        projection,
        left_on="id",
        right_on="telemetry_feature_id",
        suffixes=("", "_prediction"),
    ).merge(latest, left_on="id_prediction", right_on="prediction_id")
    states = pd.to_numeric(feedback["validated_state"], errors="raise")
    if (
        not states.map(lambda value: float(value).is_integer()).all()
        or not states.isin((0, 1, 2, 3)).all()
    ):
        raise ValueError("Human validations require integer states from 0 through 3.")
    feedback["traffic_state"] = states.astype(int)
    feedback["is_human_validated"] = True
    feedback["record_time"] = normalize_timestamp_series(feedback["record_time"])
    comparison = [*FEATURE_COLS, "traffic_state"]
    if "continuity_id" in feedback:
        comparison.append("continuity_id")
    for _, group in feedback.groupby(["clip_id", "record_time"], dropna=False):
        if len(group[comparison].drop_duplicates()) > 1:
            raise ValueError("Conflicting effective human feedback exists for the same minute.")
    feedback["source_prediction_ids"] = feedback.groupby(["clip_id", "record_time"], dropna=False)[
        "prediction_id"
    ].transform(lambda values: ",".join(sorted({str(value) for value in values.dropna()})))
    feedback["source_validation_ids"] = feedback.groupby(["clip_id", "record_time"], dropna=False)[
        "validation_id"
    ].transform(lambda values: ",".join(sorted({str(value) for value in values.dropna()})))
    feedback = feedback.drop_duplicates(["clip_id", "record_time"], keep="last")
    return normalize_continuity_frame(feedback)


def _deduplicate_uuid_rows(frame: pd.DataFrame, *, name: str) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    if "id" not in frame:
        raise ValueError(f"Catalog {name} rows require globally unique UUID id values.")
    if not frame["id"].map(valid_uuid).all():
        raise ValueError(f"Catalog {name} contains non-UUID identifiers.")
    comparison = [column for column in frame.columns if not column.startswith("_catalog_")]
    for identifier, group in frame.groupby("id", dropna=False):
        normalized = group[comparison].fillna("<NULL>").astype(str)
        if len(normalized.drop_duplicates()) > 1:
            if name == "validations":
                raise ValueError(
                    f"Conflicting human labels or validation payloads exist for UUID {identifier}."
                )
            raise ValueError(f"Conflicting catalog {name} rows for UUID {identifier}.")
    return frame.drop_duplicates("id", keep="last").reset_index(drop=True)


def _resolve_validation_graph(validations: pd.DataFrame) -> pd.DataFrame:
    if validations.empty:
        return validations.copy()
    _validate_validation_graph_columns(validations)
    children, parents, prediction_by_id = _validation_relationships(validations)
    _require_linear_validation_chains(children)
    roots_by_prediction = _validation_roots(parents, prediction_by_id)
    _require_unambiguous_roots(roots_by_prediction)
    leaves = [
        _validation_leaf(root[0], children, prediction)
        for prediction, root in roots_by_prediction.items()
    ]
    return validations.loc[validations["id"].astype(str).isin(leaves)].copy()


def _validate_validation_graph_columns(validations: pd.DataFrame) -> None:
    required = {
        "id",
        "prediction_id",
        "validated_state",
        "is_human_validated",
        "supersedes_validation_id",
    }
    if missing := sorted(required - set(validations.columns)):
        raise ValueError(f"Catalog validations are missing fields: {missing}")
    if not validations["prediction_id"].map(valid_uuid).all():
        raise ValueError("Catalog validation prediction_id values must be UUIDs.")
    states = pd.to_numeric(validations["validated_state"], errors="raise")
    if (
        not states.map(lambda value: float(value).is_integer()).all()
        or not states.isin((0, 1, 2, 3)).all()
    ):
        raise ValueError("Human validations require integer states from 0 through 3.")


def _strict_boolean(value: object) -> bool:
    if type(value) is bool or type(value).__name__ == "bool_":
        return bool(value)
    raise ValueError("Human validation flags must be contractual booleans.")


def _validation_relationships(
    validations: pd.DataFrame,
) -> tuple[dict[str, list[str]], dict[str, str | None], dict[str, str]]:
    identifiers = set(validations["id"].astype(str))
    children: dict[str, list[str]] = {identifier: [] for identifier in identifiers}
    prediction_by_id = dict(
        zip(validations["id"].astype(str), validations["prediction_id"].astype(str), strict=False)
    )
    parents: dict[str, str | None] = {}
    for row in validations.itertuples():
        identifier = str(row.id)
        parent = _validation_parent(row.supersedes_validation_id)
        if parent is not None:
            _validate_validation_parent(identifier, parent, identifiers, prediction_by_id)
            children[parent].append(identifier)
        parents[identifier] = parent
    return children, parents, prediction_by_id


def _validation_parent(value: object) -> str | None:
    return None if pd.isna(value) or not str(value).strip() else str(value)


def _validate_validation_parent(
    identifier: str, parent: str, identifiers: set[str], prediction_by_id: Mapping[str, str]
) -> None:
    if parent not in identifiers:
        raise ValueError(f"Validation {identifier} supersedes an unknown validation {parent}.")
    if prediction_by_id[parent] != prediction_by_id[identifier]:
        raise ValueError("A validation cannot supersede a validation for another prediction.")


def _require_linear_validation_chains(children: Mapping[str, list[str]]) -> None:
    branches = {identifier: values for identifier, values in children.items() if len(values) > 1}
    if branches:
        raise ValueError(f"Human validation graph contains branches: {branches}")


def _validation_roots(
    parents: Mapping[str, str | None], prediction_by_id: Mapping[str, str]
) -> dict[str, list[str]]:
    roots: dict[str, list[str]] = {prediction: [] for prediction in set(prediction_by_id.values())}
    for identifier, parent in parents.items():
        if parent is None:
            roots.setdefault(prediction_by_id[identifier], []).append(identifier)
    return roots


def _require_unambiguous_roots(roots_by_prediction: Mapping[str, list[str]]) -> None:
    rootless = [prediction for prediction, roots in roots_by_prediction.items() if not roots]
    if rootless:
        raise ValueError(f"Human validation graph contains a cycle or lacks a root: {rootless}")
    ambiguous = {
        prediction: roots for prediction, roots in roots_by_prediction.items() if len(roots) > 1
    }
    if ambiguous:
        raise ValueError(f"Human validation graph has conflicting roots: {ambiguous}")


def _validation_leaf(root: str, children: Mapping[str, list[str]], prediction: str) -> str:
    current = root
    visited: set[str] = set()
    while True:
        if current in visited:
            raise ValueError(f"Human validation graph contains a cycle for {prediction}.")
        visited.add(current)
        if not children[current]:
            return current
        current = children[current][0]


__all__ = [
    "CatalogSelection",
    "HITL_CATALOG_CONTRACT",
    "HITL_CATALOG_FILE",
    "HITL_PACKAGE_FILE",
    "HitlCatalogSource",
    "HitlReviewCatalog",
    "load_hitl_catalog_feedback",
    "load_hitl_catalog_components",
    "resolve_effective_human_feedback",
]
