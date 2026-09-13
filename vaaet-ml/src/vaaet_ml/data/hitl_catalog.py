# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Catálogo inmutable y resolución global de paquetes de revisión HITL."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from numbers import Integral, Real
from pathlib import Path, PurePosixPath

import pandas as pd
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.continuity import normalize_continuity_frame
from vaaet.settings import FEATURE_COLS
from vaaet.timestamps import normalize_timestamp_series

from vaaet_ml.data.artifact_serialization import (
    atomic_json_write,
    canonical_timestamp_identity,
    is_sha256,
    read_package_manifest,
    safe_relative_path,
    sha256_file,
    stable_uuid,
    utc_now,
    valid_uuid,
)
from vaaet_ml.data.package_codec import load_dataset_package

HITL_CATALOG_CONTRACT = "vaaet-dataset-catalog-v1"
HITL_CATALOG_FILE = "catalog.json"
HITL_PACKAGE_FILE = "vaaet-training-dataset-v1.zip"
_HITL_FINGERPRINT_ALGORITHMS = {
    "sha256-contractual-frames-v1",
    "sha256-contractual-frames-v2",
}


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
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise ValueError("Invalid HITL catalog.") from None
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
    algorithm = entry.get("fingerprint_algorithm", "sha256-contractual-frames-v1")
    if algorithm not in _HITL_FINGERPRINT_ALGORITHMS:
        raise ValueError("HITL catalog fingerprint algorithm is unsupported.")


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
        "package_fingerprint_algorithms": [
            entry.get("fingerprint_algorithm", "sha256-contractual-frames-v1")
            for entry in entries
        ],
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
    features, predictions, validations = _canonicalize_feedback_identities(
        features, predictions, validations
    )
    features = _deduplicate_uuid_rows(features, name="features")
    predictions = _deduplicate_uuid_rows(predictions, name="predictions")
    validations = _deduplicate_uuid_rows(validations, name="validations")
    validations = _deduplicate_equivalent_validations(validations)
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
    if "_source_prediction_ids" in predictions:
        projection_columns.append("_source_prediction_ids")
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
    prediction_lineage = (
        "_source_prediction_ids" if "_source_prediction_ids" in feedback else "prediction_id"
    )
    feedback["source_prediction_ids"] = feedback.groupby(
        ["clip_id", "record_time"], dropna=False
    )[prediction_lineage].transform(_join_lineage_values)
    validation_lineage = (
        "_source_validation_ids" if "_source_validation_ids" in feedback else "validation_id"
    )
    feedback["source_validation_ids"] = feedback.groupby(
        ["clip_id", "record_time"], dropna=False
    )[validation_lineage].transform(_join_lineage_values)
    feedback = feedback.drop_duplicates(["clip_id", "record_time"], keep="last")
    return normalize_continuity_frame(feedback)


def _deduplicate_uuid_rows(  # noqa: C901 - consolida contenido y procedencia por UUID.
    frame: pd.DataFrame, *, name: str
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    if "id" not in frame:
        raise ValueError(f"Catalog {name} rows require globally unique UUID id values.")
    if not frame["id"].map(valid_uuid).all():
        raise ValueError(f"Catalog {name} contains non-UUID identifiers.")
    complementary_provenance = {
        "features": {"created_at"},
        "predictions": {"classified_at", "review_status"},
        "validations": set(),
    }.get(name, set())
    comparison = [
        column
        for column in frame.columns
        if not column.startswith(("_catalog_", "_source_"))
        and not column.startswith("operational_")
        and column not in complementary_provenance
    ]
    result_rows: list[pd.Series] = []
    for identifier, group in frame.groupby("id", dropna=False):
        merged = group.iloc[0].copy()
        for column in comparison:
            present = [value for value in group[column] if not _missing_value(value)]
            canonical = {_canonical_comparison_value(column, value) for value in present}
            if len(canonical) > 1:
                if name == "validations":
                    raise ValueError(
                        f"Conflicting human labels or validation payloads exist for UUID {identifier}."
                    )
                raise ValueError(f"Conflicting catalog {name} rows for UUID {identifier}.")
            if _missing_value(merged.get(column)) and present:
                merged[column] = present[0]
        for column in group.columns:
            if column.startswith("_source_"):
                merged[column] = _join_lineage_values(group[column])
            elif _missing_value(merged.get(column)):
                present = [value for value in group[column] if not _missing_value(value)]
                if present:
                    merged[column] = present[0]
        result_rows.append(merged)
    return pd.DataFrame(result_rows, columns=frame.columns).reset_index(drop=True)


def _canonicalize_feedback_identities(
    features: pd.DataFrame,
    predictions: pd.DataFrame,
    validations: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Reconcilia aliases históricos únicamente desde claves naturales completas."""

    canonical_features = features.copy()
    canonical_predictions = predictions.copy()
    canonical_validations = validations.copy()
    feature_aliases: dict[str, str] = {}
    if "record_time" in canonical_features:
        canonical_features["record_time"] = normalize_timestamp_series(
            canonical_features["record_time"]
        )
    feature_ids: list[str] = []
    feature_sources: list[str] = []
    for row in canonical_features.itertuples(index=False):
        source_id = str(row.id)
        required = (
            getattr(row, "pipeline_run_id", None),
            getattr(row, "clip_id", None),
            getattr(row, "continuity_id", None),
            getattr(row, "record_time", None),
            getattr(row, "feature_schema_version", None),
        )
        canonical_id = source_id
        if all(not _missing_value(value) for value in required):
            canonical_id = stable_uuid(
                "feature",
                required[0],
                required[1],
                required[2],
                canonical_timestamp_identity(required[3]),
                required[4],
            )
        feature_aliases[source_id] = canonical_id
        feature_ids.append(canonical_id)
        feature_sources.append(source_id)
    canonical_features["id"] = feature_ids
    canonical_features["_source_feature_ids"] = feature_sources

    prediction_aliases: dict[str, str] = {}
    prediction_ids: list[str] = []
    prediction_sources: list[str] = []
    feature_references: list[str] = []
    for row in canonical_predictions.itertuples(index=False):
        source_id = str(row.id)
        source_feature = str(row.telemetry_feature_id)
        feature_id = feature_aliases.get(source_feature, source_feature)
        run_id = getattr(row, "pipeline_run_id", None)
        revision = getattr(row, "model_revision", None)
        canonical_id = source_id
        if not _missing_value(run_id) and is_sha256(revision):
            canonical_id = stable_uuid("prediction", run_id, feature_id, revision)
        prediction_aliases[source_id] = canonical_id
        prediction_ids.append(canonical_id)
        prediction_sources.append(source_id)
        feature_references.append(feature_id)
    canonical_predictions["id"] = prediction_ids
    canonical_predictions["telemetry_feature_id"] = feature_references
    canonical_predictions["_source_prediction_ids"] = prediction_sources

    if not canonical_validations.empty:
        canonical_validations["prediction_id"] = canonical_validations["prediction_id"].map(
            lambda value: prediction_aliases.get(str(value), str(value))
        )
    return canonical_features, canonical_predictions, canonical_validations


def _deduplicate_equivalent_validations(validations: pd.DataFrame) -> pd.DataFrame:
    """Consolida decisiones idénticas sin perder sus UUID originales."""

    if validations.empty:
        return validations
    frame = validations.copy()
    frame["_source_validation_ids"] = frame["id"].astype(str)
    comparison = [
        column
        for column in frame.columns
        if column not in {"id", "pipeline_run_id"}
        and not column.startswith(("_catalog_", "_source_", "operational_"))
    ]
    aliases: dict[str, str] = {}
    groups: dict[tuple[tuple[str, object], ...], list[int]] = {}
    for index, row in frame.iterrows():
        key = tuple(
            _canonical_comparison_value(column, row[column])
            if not _missing_value(row[column])
            else ("missing", "")
            for column in comparison
        )
        groups.setdefault(key, []).append(index)
    rows: list[pd.Series] = []
    for indexes in groups.values():
        group = frame.loc[indexes]
        canonical_id = sorted(group["id"].astype(str))[0]
        merged = group.iloc[0].copy()
        merged["id"] = canonical_id
        merged["_source_validation_ids"] = _join_lineage_values(group["id"])
        for source_id in group["id"].astype(str):
            aliases[source_id] = canonical_id
        rows.append(merged)
    result = pd.DataFrame(rows, columns=frame.columns).reset_index(drop=True)
    result["supersedes_validation_id"] = result["supersedes_validation_id"].map(
        lambda value: aliases.get(str(value), value) if not _missing_value(value) else pd.NA
    )
    return result


def _missing_value(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _canonical_comparison_value(column: str, value: object) -> tuple[str, object]:
    if column in {"record_time", "reviewed_at", "created_at", "classified_at"}:
        return ("timestamp", canonical_timestamp_identity(value))
    if type(value) is bool or type(value).__name__ == "bool_":
        return ("boolean", bool(value))
    if isinstance(value, Decimal):
        return ("number", float(value))
    if isinstance(value, Integral) and not isinstance(value, bool):
        return ("number", int(value))
    if isinstance(value, Real) and not isinstance(value, bool):
        return ("number", float(value))
    if isinstance(value, str):
        return ("text", value)
    return (type(value).__name__, str(value))


def _join_lineage_values(values: pd.Series) -> str:
    identifiers: set[str] = set()
    for value in values.dropna():
        identifiers.update(item for item in str(value).split(",") if item)
    return ",".join(sorted(identifiers))


def _resolve_validation_graph(validations: pd.DataFrame) -> pd.DataFrame:
    if validations.empty:
        return validations.copy()
    _validate_validation_graph_columns(validations)
    children, parents, prediction_by_id = _validation_relationships(validations)
    _require_linear_validation_chains(children)
    roots_by_prediction = _validation_roots(parents, prediction_by_id)
    _require_unambiguous_roots(roots_by_prediction)
    leaves = []
    visited: set[str] = set()
    for prediction, root in roots_by_prediction.items():
        leaf, chain = _validation_leaf_with_chain(root[0], children, prediction)
        leaves.append(leaf)
        visited.update(chain)
    unreachable = sorted(set(prediction_by_id) - visited)
    if unreachable:
        raise ValueError(
            f"Human validation graph contains unreachable nodes or a disconnected cycle: {unreachable}"
        )
    return validations.loc[validations["id"].astype(str).isin(leaves)].copy()


def _validate_validation_graph_columns(  # noqa: C901 - valida el dominio humano tabular.
    validations: pd.DataFrame,
) -> None:
    required = {
        "id",
        "prediction_id",
        "validated_state",
        "is_human_validated",
        "reviewer_id",
        "reviewed_at",
        "review_source",
        "incident_context_reviewed",
        "supersedes_validation_id",
    }
    if missing := sorted(required - set(validations.columns)):
        raise ValueError(f"Catalog validations are missing fields: {missing}")
    if not validations["prediction_id"].map(valid_uuid).all():
        raise ValueError("Catalog validation prediction_id values must be UUIDs.")
    if validations["id"].map(valid_uuid).eq(False).any():
        raise ValueError("Catalog validation id values must be UUIDs.")
    if validations["validated_state"].map(
        lambda value: type(value) is bool or type(value).__name__ == "bool_"
    ).any():
        raise ValueError("Human validations require integer states, not booleans.")
    states = pd.to_numeric(validations["validated_state"], errors="raise")
    if (
        not states.map(lambda value: float(value).is_integer()).all()
        or not states.isin((0, 1, 2, 3)).all()
    ):
        raise ValueError("Human validations require integer states from 0 through 3.")
    if "pipeline_run_id" in validations:
        declared_runs = validations["pipeline_run_id"].dropna()
        if not declared_runs.map(valid_uuid).all():
            raise ValueError("Catalog validation pipeline_run_id values must be UUIDs when declared.")
    if validations["reviewer_id"].isna().any() or validations[
        "reviewer_id"
    ].astype(str).str.strip().eq("").any():
        raise ValueError("Human validations require a stable reviewer_id.")
    reviewed = pd.to_datetime(validations["reviewed_at"], utc=True, errors="coerce")
    if reviewed.isna().any():
        raise ValueError("Human validations require a valid reviewed_at timestamp.")
    if validations["review_source"].isna().any() or validations[
        "review_source"
    ].astype(str).str.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}").eq(False).any():
        raise ValueError("Human validations require a safe review_source identifier.")
    if not validations["incident_context_reviewed"].map(
        lambda value: type(value) is bool or type(value).__name__ == "bool_"
    ).all():
        raise ValueError("incident_context_reviewed must contain contractual booleans.")
    accidents = states.eq(3)
    notes = validations.get("notes", pd.Series(pd.NA, index=validations.index))
    if accidents.any() and (
        not validations.loc[accidents, "incident_context_reviewed"].all()
        or notes.loc[accidents].isna().any()
        or notes.loc[accidents].astype(str).str.strip().eq("").any()
    ):
        raise ValueError("Accident requires confirmed temporal context and a non-empty note.")


def _validation_leaf_with_chain(
    root: str, children: Mapping[str, list[str]], prediction: str
) -> tuple[str, set[str]]:
    visited: set[str] = set()
    current = root
    while True:
        if current in visited:
            raise ValueError(f"Human validation graph contains a cycle for {prediction}.")
        visited.add(current)
        successors = children[current]
        if not successors:
            return current, visited
        current = successors[0]


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
