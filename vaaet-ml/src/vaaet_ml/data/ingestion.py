# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Entradas explícitas y componibles para entrenamiento desde fuentes gobernadas."""

from __future__ import annotations

import math
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pandas as pd
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.continuity import CONTINUITY_COLUMN, normalize_continuity_frame
from vaaet.settings import FEATURE_COLS
from vaaet.timestamps import (
    count_naive_timestamps,
    normalize_timestamp_series,
)

from vaaet_ml.data.database import (
    DatabaseSettings,
    get_pg_restore_version,
    inspect_backup_catalog,
    load_human_feedback_components,
    load_telemetry,
    parse_sql_dump_tables,
    restore_backup_to_sql,
)
from vaaet_ml.data.dataset_artifacts import HitlCatalogSource
from vaaet_ml.data.hitl_catalog import (
    load_hitl_catalog_components,
    resolve_effective_human_feedback,
)
from vaaet_ml.data.operational_frames import portable_feedback_components
from vaaet_ml.data.package_codec import (
    DATASET_PACKAGE_CONTRACT,
    SEED_DATASET_PACKAGE_CONTRACT,
    create_dataset_package,
    load_dataset_package,
)
from vaaet_ml.training.lifecycle import TrainingMode

_BACKUP_BOOLEAN_COLUMNS = {
    "is_human_validated",
    "incident_context_reviewed",
    "decision_abstained",
    "measurement_reliable",
    "accident_rule_triggered",
    "accident_alert_started",
}

RAW_REQUIRED_COLUMNS = {
    "clip_id",
    "record_time",
    "avg_speed",
    "count_car",
    "count_truck",
    "count_bus",
    "count_motorcycle",
    "count_bicycle",
    "total_vehicles",
}


class FeedbackPolicy(str, Enum):
    VALIDATED_ONLY = "validated_only"


@dataclass(frozen=True)
class PostgresSource:
    settings: DatabaseSettings
    feature_schema_version: str | None = FEATURE_SCHEMA_VERSION


@dataclass(frozen=True)
class PostgresBackupSource:
    path: Path
    pg_restore_path: Path | None = None


@dataclass(frozen=True)
class RawCsvSource:
    path: Path


@dataclass(frozen=True)
class DatasetPackageSource:
    path: Path


@dataclass(frozen=True)
class SeedDatasetPackageSource:
    """Representa un paquete semilla weak-label declarado de forma explícita."""

    path: Path


TrainingSource = (
    PostgresSource
    | PostgresBackupSource
    | RawCsvSource
    | DatasetPackageSource
    | SeedDatasetPackageSource
    | HitlCatalogSource
)


@dataclass(frozen=True)
class TrainingIngestionPlan:
    """Define fuentes y política de supervisión para una carga de entrenamiento."""

    mode: TrainingMode
    raw_sources: tuple[TrainingSource, ...] = ()
    seed_sources: tuple[SeedDatasetPackageSource, ...] = ()
    feedback_sources: tuple[TrainingSource, ...] = ()
    feedback_policy: FeedbackPolicy = FeedbackPolicy.VALIDATED_ONLY

    def __post_init__(self) -> None:
        if self.feedback_policy is not FeedbackPolicy.VALIDATED_ONLY:
            raise ValueError("Only human-validated feedback can be used for supervised training.")
        if not self.raw_sources and not self.seed_sources and not self.feedback_sources:
            raise ValueError("At least one explicit training source is required.")
        if self.mode is TrainingMode.HITL_RETRAINING and not self.feedback_sources:
            raise ValueError("HITL retraining requires an explicit validated feedback source.")


@dataclass(frozen=True)
class TrainingDataset:
    """Agrupa tablas deduplicadas y su procedencia para entrenar o auditar."""

    raw: pd.DataFrame
    seed_features: pd.DataFrame
    validated_feedback: pd.DataFrame
    confirmed_incidents: pd.DataFrame
    provenance: pd.DataFrame


def _load_seed_features(source: SeedDatasetPackageSource) -> pd.DataFrame:
    """Valida contrato, procedencia y orden de features antes de aceptar la semilla."""

    frames = load_dataset_package(
        source.path,
        accepted_contracts=(SEED_DATASET_PACKAGE_CONTRACT, DATASET_PACKAGE_CONTRACT),
    )
    frame = frames.get("features", pd.DataFrame())
    if frame.empty:
        raise ValueError("Explicit seed package contains zero processed feature rows.")
    required = {
        "clip_id",
        CONTINUITY_COLUMN,
        "record_time",
        "feature_schema_version",
        "traffic_state",
        *FEATURE_COLS,
    }
    if missing := required - set(frame.columns):
        raise ValueError(f"Seed feature package is missing fields: {sorted(missing)}")
    feature_order = [column for column in frame.columns if column in FEATURE_COLS]
    if feature_order != list(FEATURE_COLS):
        raise ValueError("Seed package does not preserve the exact 19-feature order.")
    if not pd.to_numeric(frame["traffic_state"], errors="raise").isin((0, 1, 2)).all():
        raise ValueError("Seed package may contain only stable proxy labels 0, 1, and 2.")
    if "is_human_validated" in frame and frame["is_human_validated"].fillna(False).any():
        raise ValueError("Seed package cannot contain human-validated rows.")
    versions = set(frame["feature_schema_version"].dropna().astype(str))
    if versions != {FEATURE_SCHEMA_VERSION}:
        raise ValueError(f"Incompatible seed feature schema versions: {sorted(versions)}")
    package_provenance = frame.attrs.get("vaaet_package_provenance", {})
    package_contract = frame.attrs.get("vaaet_package_contract")
    if package_provenance.get("training_mode") != TrainingMode.SEED_BOOTSTRAP.value or (
        package_provenance.get("supervision") != "weak-proxy"
    ):
        raise ValueError(
            "Seed package provenance must declare seed-bootstrap weak-proxy supervision."
        )
    if package_contract == DATASET_PACKAGE_CONTRACT:
        warnings.warn(
            "Legacy seed package uses vaaet-training-dataset-v1; register it in the "
            "versioned seed store to migrate to vaaet-seed-bootstrap-v1.",
            DeprecationWarning,
            stacklevel=2,
        )
    frame = frame.copy()
    frame["record_time"] = normalize_timestamp_series(frame["record_time"])
    frame["traffic_state"] = pd.to_numeric(frame["traffic_state"], errors="raise").astype(int)
    frame["is_human_validated"] = False
    frame.attrs["vaaet_provenance"] = {
        "package_kind": "processed-seed",
        **package_provenance,
    }
    return frame


def _latest_validated_feedback(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return resolve_effective_human_feedback(
        frames.get("features", pd.DataFrame()),
        frames.get("predictions", pd.DataFrame()),
        frames.get("validations", pd.DataFrame()),
    )


def _load_feedback_components(
    source: TrainingSource,
) -> tuple[dict[str, pd.DataFrame], dict[str, object]]:
    if isinstance(source, PostgresSource):
        return (
            portable_feedback_components(load_human_feedback_components(
                settings=source.settings,
                feature_schema_version=source.feature_schema_version,
            )),
            {"source_kind": "postgres-history"},
        )
    if isinstance(source, DatasetPackageSource):
        return load_dataset_package(source.path), {"source_kind": "dataset-package"}
    if isinstance(source, PostgresBackupSource):
        frames = _frames_from_backup(source, components={"features", "predictions", "validations"})
        details = next(
            (
                item.attrs.get("vaaet_provenance", {})
                for item in frames.values()
                if item.attrs.get("vaaet_provenance")
            ),
            {},
        )
        return portable_feedback_components(frames), dict(details)
    if isinstance(source, HitlCatalogSource):
        return load_hitl_catalog_components(source)
    raise ValueError(f"Source {type(source).__name__} cannot provide validated feedback.")


def _frames_from_backup(  # noqa: C901 - valida variantes históricas en un único borde.
    source: PostgresBackupSource, *, components: set[str]
) -> dict[str, pd.DataFrame]:
    """Extrae tablas reconocidas sin ejecutar el SQL contenido en el backup."""

    catalog = inspect_backup_catalog(source.path, pg_restore_path=source.pg_restore_path)
    if not catalog:
        raise ValueError("PostgreSQL backup contains no recognized VAAET tables.")
    aliases = {
        "raw": ("vaaet_raw.traffic_data", "public.traffic_data"),
        "features": ("vaaet_ml.telemetry_features", "public.telemetry_raw"),
        "predictions": ("vaaet_ml.traffic_predictions", "public.traffic_classifications"),
        "validations": ("vaaet_feedback.human_validations",),
    }
    unknown = components - set(aliases)
    if unknown:
        raise ValueError(f"Unknown backup components requested: {sorted(unknown)}")
    selected_tables = tuple(
        table_name
        for component in components
        for table_name in aliases[component]
        if table_name in catalog
    )
    if not selected_tables:
        raise ValueError(
            f"PostgreSQL backup does not contain requested components: {sorted(components)}"
        )
    reader_version = get_pg_restore_version(source.pg_restore_path)
    sql_path = restore_backup_to_sql(
        source.path,
        pg_restore_path=source.pg_restore_path,
        tables=selected_tables,
    )
    try:
        tables = parse_sql_dump_tables(sql_path)
    finally:
        sql_path.unlink(missing_ok=True)
    result: dict[str, pd.DataFrame] = {}
    for key, names in aliases.items():
        for name in names:
            if name in tables:
                frame = tables[name]
                frame.attrs["vaaet_provenance"] = {
                    "archive_table": name,
                    "backup_layout": "legacy" if name.startswith("public.") else "modern",
                    "reader_version": reader_version,
                }
                result[key] = frame
                break
    for frame in result.values():
        for column in _BACKUP_BOOLEAN_COLUMNS.intersection(frame.columns):
            frame[column] = frame[column].map(_parse_backup_boolean)
    if "validations" not in result and "predictions" in result:
        legacy = result["predictions"]
        if "is_human_validated" in legacy:
            flags = legacy["is_human_validated"].map(_parse_contract_boolean)
            validated = legacy.loc[flags].copy()
            if not validated.empty:
                validated["prediction_id"] = validated["id"]
                validated["validated_state"] = validated["human_override_state"].fillna(
                    validated["traffic_state"]
                )
                validated["reviewed_at"] = validated.get("validated_at", validated["classified_at"])
                validated["reviewer_id"] = "legacy-import"
                validated.attrs["vaaet_provenance"] = legacy.attrs.get("vaaet_provenance", {})
                result["validations"] = validated
    return result


def _load_raw(source: TrainingSource) -> pd.DataFrame:
    if isinstance(source, PostgresSource):
        frame = load_telemetry(settings=source.settings)
    elif isinstance(source, RawCsvSource):
        frame = pd.read_csv(source.path, float_precision="round_trip")
    elif isinstance(source, DatasetPackageSource):
        frame = load_dataset_package(source.path).get("raw", pd.DataFrame())
    elif isinstance(source, PostgresBackupSource):
        frame = _frames_from_backup(source, components={"raw"}).get("raw", pd.DataFrame())
    elif isinstance(source, SeedDatasetPackageSource):
        raise ValueError("SeedDatasetPackageSource must be declared in seed_sources.")
    elif isinstance(source, HitlCatalogSource):
        raise ValueError("HitlCatalogSource cannot be used as a raw source.")
    else:
        raise TypeError(f"Unsupported raw source: {type(source)!r}")
    if frame.empty:
        details = frame.attrs.get("vaaet_provenance", {})
        archive_table = details.get("archive_table")
        suffix = f" ({archive_table})" if archive_table else ""
        raise ValueError(
            f"Explicit raw source {type(source).__name__}{suffix} contains zero telemetry rows."
        )
    temporal_provenance = dict(frame.attrs.get("vaaet_provenance", {}))
    naive_count = count_naive_timestamps(frame["record_time"])
    frame = frame.copy()
    frame["record_time"] = normalize_timestamp_series(frame["record_time"])
    temporal_provenance.update(
        {
            "timestamp_timezone": "UTC",
            "naive_timezone_assumption": "America/Argentina/Buenos_Aires",
            "naive_timestamps_localized": naive_count,
        }
    )
    frame.attrs["vaaet_provenance"] = temporal_provenance
    return frame


def _deduplicate_raw(frames: Sequence[pd.DataFrame]) -> pd.DataFrame:
    non_empty = [frame.copy() for frame in frames if not frame.empty]
    if not non_empty:
        return pd.DataFrame()
    combined = pd.concat(non_empty, ignore_index=True)
    required = RAW_REQUIRED_COLUMNS
    if missing := required - set(combined.columns):
        raise ValueError(f"Raw sources are missing fields: {sorted(missing)}")
    combined["record_time"] = normalize_timestamp_series(combined["record_time"])
    comparison = [column for column in combined.columns if column not in {"id", "pipeline_run_id"}]
    for _, group in combined.groupby(["clip_id", "record_time"], dropna=False):
        if len(group[comparison].drop_duplicates()) > 1:
            raise ValueError(
                f"Conflicting raw records for clip={group.iloc[0]['clip_id']} "
                f"time={group.iloc[0]['record_time']}"
            )
    return combined.drop_duplicates(["clip_id", "record_time"], keep="last").reset_index(drop=True)


def _deduplicate_feedback(
    frames: Sequence[pd.DataFrame], *, require_human_validation: bool = True
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Consolida decisiones humanas y separa incidentes del MLP estable."""

    non_empty = [frame.copy() for frame in frames if not frame.empty]
    if not non_empty:
        return pd.DataFrame(), pd.DataFrame()
    versions_by_source = [
        _validate_processed_frame_contract(frame, require_human_validation) for frame in non_empty
    ]
    combined = pd.concat(non_empty, ignore_index=True)
    required = {"clip_id", "record_time", "traffic_state", *FEATURE_COLS}
    if missing := required - set(combined.columns):
        raise ValueError(f"Validated feedback is missing fields: {sorted(missing)}")
    versions = set().union(*versions_by_source)
    if len(versions) != 1:
        raise ValueError(
            f"Processed feedback cannot mix feature schema versions: {sorted(versions)}"
        )
    combined["record_time"] = normalize_timestamp_series(combined["record_time"])
    combined.attrs["legacy_feature_schema"] = versions == {"traffic-features-v2"}
    states = pd.to_numeric(combined["traffic_state"], errors="raise")
    if (
        not states.map(lambda value: float(value).is_integer()).all()
        or not states.isin((0, 1, 2, 3)).all()
    ):
        raise ValueError("Feedback traffic_state values must be integers from 0 through 3.")
    combined["traffic_state"] = states.astype(int)
    comparison = [*FEATURE_COLS, "traffic_state", "feature_schema_version"]
    comparison.extend(
        column
        for column in (
            CONTINUITY_COLUMN,
            "numeric_representation",
            "feature_numeric_representation",
            "prediction_numeric_representation",
        )
        if column in combined
    )
    for _, group in combined.groupby(["clip_id", "record_time"], dropna=False):
        if (
            group["traffic_state"].nunique() > 1
            or len(group[comparison].drop_duplicates()) > 1
        ):
            raise ValueError(
                f"Conflicting human labels or features for clip={group.iloc[0]['clip_id']} "
                f"time={group.iloc[0]['record_time']}"
            )
    combined = (
        _attach_lineage_sets(combined)
        .drop_duplicates(["clip_id", "record_time"], keep="last")
        .sort_values(["clip_id", "record_time"])
        .reset_index(drop=True)
    )
    combined = normalize_continuity_frame(combined)
    incidents = combined.loc[combined["traffic_state"].eq(3)].reset_index(drop=True)
    stable = combined.loc[combined["traffic_state"].isin((0, 1, 2))].reset_index(drop=True)
    return stable, incidents


def _validate_processed_frame_contract(  # noqa: C901 - valida un borde tabular externo.
    frame: pd.DataFrame, require_human_validation: bool
) -> set[str]:
    """Valida schema, orden y lineage antes de consolidar fuentes procesadas."""

    feature_order = [column for column in frame.columns if column in FEATURE_COLS]
    if feature_order != list(FEATURE_COLS):
        raise ValueError("Validated feedback does not preserve the exact 19-feature order.")
    if require_human_validation:
        if "is_human_validated" not in frame:
            raise ValueError("Feedback sources must explicitly prove human validation.")
        confirmation = frame["is_human_validated"].map(_parse_contract_boolean)
        if not confirmation.all():
            raise ValueError("Feedback sources contain unvalidated predictions.")
        frame["is_human_validated"] = confirmation.astype(bool)
    if "feature_schema_version" not in frame:
        raise ValueError("Processed feedback requires feature_schema_version.")
    if frame["feature_schema_version"].isna().any():
        raise ValueError("Processed feedback requires feature_schema_version on every row.")
    versions = set(frame["feature_schema_version"].astype(str))
    accepted = {FEATURE_SCHEMA_VERSION, "traffic-features-v2"}
    if len(versions) != 1 or not versions.issubset(accepted):
        raise ValueError(f"Incompatible feature schema versions: {sorted(versions)}")
    if versions == {FEATURE_SCHEMA_VERSION} and CONTINUITY_COLUMN not in frame:
        raise ValueError("Current processed feedback requires continuity_id.")
    if (
        require_human_validation
        and versions == {FEATURE_SCHEMA_VERSION}
        and "model_revision" not in frame
    ):
        raise ValueError("Current processed feedback requires model_revision lineage.")
    if require_human_validation and versions == {FEATURE_SCHEMA_VERSION}:
        revisions = frame["model_revision"].astype("string")
        if revisions.isna().any() or not revisions.str.fullmatch(r"[0-9a-f]{64}").all():
            raise ValueError("Current processed feedback requires SHA-256 model_revision values.")
        if "numeric_representation" not in frame:
            raise ValueError(
                "Current processed feedback requires numeric_representation lineage."
            )
        representations = frame["numeric_representation"].astype("string")
        if representations.isna().any() or not representations.isin(
            ("float64", "legacy-rounded")
        ).all():
            raise ValueError("Processed feedback has invalid numeric representation lineage.")
    numeric = frame.loc[:, FEATURE_COLS].apply(pd.to_numeric, errors="raise")
    if not numeric.map(math.isfinite).all().all():
        raise ValueError("Processed feedback contains non-finite feature values.")
    frame.loc[:, FEATURE_COLS] = numeric.astype(float)
    return versions


def _parse_contract_boolean(value: object) -> bool:
    if type(value) is bool or type(value).__name__ == "bool_":
        return bool(value)
    raise ValueError("is_human_validated must contain contractual boolean values.")


def _parse_backup_boolean(value: object) -> bool:
    """Decodifica el vocabulario booleano emitido por COPY de PostgreSQL."""

    if type(value) is bool or type(value).__name__ == "bool_":
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"t", "f", "true", "false"}:
        return value.strip().lower() in {"t", "true"}
    raise ValueError("PostgreSQL backup contains a non-contractual boolean value.")


def _attach_lineage_sets(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    candidates = {
        "source_prediction_ids": ("prediction_id", "id_prediction"),
        "source_validation_ids": ("validation_id", "id_y"),
    }
    for output, names in candidates.items():
        available = next((name for name in names if name in result), None)
        if available is None:
            continue
        values = result.groupby(["clip_id", "record_time"], dropna=False)[available].transform(
            lambda group: ",".join(sorted({str(item) for item in group.dropna()}))
        )
        result[output] = values
    return result


def compose_supervised_dataset(
    proxy_features: pd.DataFrame, validated_feedback: pd.DataFrame
) -> pd.DataFrame:
    """Combina etiquetas proxy estables con prioridad para las etiquetas humanas."""
    if proxy_features.empty and validated_feedback.empty:
        raise ValueError("No stable training records are available for composition.")
    frames: list[pd.DataFrame] = []
    if not proxy_features.empty:
        proxy = proxy_features.copy()
        proxy["is_human_validated"] = False
        frames.append(proxy)
    if not validated_feedback.empty:
        human = validated_feedback.copy()
        if not human["traffic_state"].isin((0, 1, 2)).all():
            raise ValueError("Accident must not enter the stable MLP supervised dataset.")
        human["data_origin"] = "real"
        human["synthetic_scenario"] = "observed"
        human["is_human_validated"] = True
        frames.append(human)
    columns = list(dict.fromkeys(column for frame in frames for column in frame.columns))
    aligned = [frame.reindex(columns=columns) for frame in frames]
    combined = pd.concat(aligned, ignore_index=True)
    combined["record_time"] = normalize_timestamp_series(combined["record_time"])
    return (
        combined.sort_values("is_human_validated")
        .drop_duplicates(["clip_id", "record_time"], keep="last")
        .sort_values(["clip_id", "record_time"])
        .reset_index(drop=True)
    )


def load_training_inputs(plan: TrainingIngestionPlan) -> TrainingDataset:
    """Carga y consolida únicamente las fuentes declaradas en el plan validado."""

    raw_frames: list[pd.DataFrame] = []
    seed_frames: list[pd.DataFrame] = []
    feedback_components: dict[str, list[pd.DataFrame]] = {
        "features": [],
        "predictions": [],
        "validations": [],
    }
    provenance: list[dict[str, object]] = []
    for index, source in enumerate(plan.raw_sources):
        frame = _load_raw(source)
        raw_frames.append(frame)
        provenance.append(
            {
                "kind": "raw",
                "source_index": index,
                "source_type": type(source).__name__,
                "rows": len(frame),
                **frame.attrs.get("vaaet_provenance", {}),
            }
        )
    for index, source in enumerate(plan.seed_sources):
        frame = _load_seed_features(source)
        seed_frames.append(frame)
        provenance.append(
            {
                "kind": "processed_seed",
                "source_index": index,
                "source_type": type(source).__name__,
                "rows": len(frame),
                **frame.attrs.get("vaaet_provenance", {}),
            }
        )
    for index, source in enumerate(plan.feedback_sources):
        components, source_details = _load_feedback_components(source)
        for kind in feedback_components:
            frame = components.get(kind, pd.DataFrame())
            if not frame.empty:
                feedback_components[kind].append(frame)
        validation_rows = len(components.get("validations", pd.DataFrame()))
        provenance.append(
            {
                "kind": "validated_feedback",
                "source_index": index,
                "source_type": type(source).__name__,
                "rows": validation_rows,
                **source_details,
            }
        )
    raw = _deduplicate_raw(raw_frames)
    seed, seed_incidents = _deduplicate_feedback(seed_frames, require_human_validation=False)
    if not seed_incidents.empty:
        raise ValueError("Processed seed datasets cannot contain Accident targets.")
    combined_components = {
        kind: pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        for kind, frames in feedback_components.items()
    }
    effective_feedback = (
        _latest_validated_feedback(combined_components)
        if any(not frame.empty for frame in combined_components.values())
        else pd.DataFrame()
    )
    feedback, incidents = _deduplicate_feedback([effective_feedback])
    if raw.empty and seed.empty and feedback.empty and incidents.empty:
        raise ValueError("No usable raw telemetry or validated feedback was loaded.")
    return TrainingDataset(raw, seed, feedback, incidents, pd.DataFrame(provenance))


__all__ = [
    "DATASET_PACKAGE_CONTRACT",
    "SEED_DATASET_PACKAGE_CONTRACT",
    "DatasetPackageSource",
    "FeedbackPolicy",
    "HitlCatalogSource",
    "PostgresBackupSource",
    "PostgresSource",
    "RawCsvSource",
    "SeedDatasetPackageSource",
    "TrainingDataset",
    "TrainingIngestionPlan",
    "compose_supervised_dataset",
    "create_dataset_package",
    "load_dataset_package",
    "load_training_inputs",
]
