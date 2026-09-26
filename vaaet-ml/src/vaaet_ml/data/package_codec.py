# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Codec seguro de paquetes ZIP/CSV compartido por ingestión y artefactos."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import tempfile
import zipfile
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from numbers import Integral, Real
from pathlib import Path
from typing import cast

import pandas as pd
from pandas.api.types import is_bool_dtype, is_float_dtype, is_integer_dtype
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.timestamps import normalize_timestamp_series

from vaaet_ml.data.artifact_serialization import read_package_manifest
from vaaet_ml.exceptions import DatasetArtifactValidationError

DATASET_PACKAGE_CONTRACT = "vaaet-training-dataset-v1"
SEED_DATASET_PACKAGE_CONTRACT = "vaaet-seed-bootstrap-v1"
PACKAGE_FILES: dict[str, str] = {
    "raw": "raw-telemetry.csv",
    "features": "telemetry-features.csv",
    "predictions": "traffic-predictions.csv",
    "validations": "human-validations.csv",
}
_BOOLEAN_COLUMNS = {
    "is_human_validated",
    "audit_complete",
    "incident_context_reviewed",
    "decision_abstained",
    "measurement_reliable",
    "accident_rule_triggered",
    "accident_alert_started",
}
CSV_CODEC = "typed-csv-v1"
MINIMUM_TYPED_READER_VERSION = "4.9.2"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    """Extrae sólo miembros que permanecen dentro del directorio temporal."""

    root = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if root not in target.parents and target != root:
            raise DatasetArtifactValidationError("El paquete contiene una ruta insegura.")
    archive.extractall(destination)


def create_dataset_package(
    output_path: str | Path,
    *,
    raw: pd.DataFrame | None = None,
    features: pd.DataFrame | None = None,
    predictions: pd.DataFrame | None = None,
    validations: pd.DataFrame | None = None,
    provenance: Mapping[str, object] | None = None,
    contract_version: str = DATASET_PACKAGE_CONTRACT,
    package_metadata: Mapping[str, object] | None = None,
    overwrite: bool = False,
    include_empty_components: tuple[str, ...] = (),
) -> Path:
    """Crea un ZIP autocontenido con manifiesto, checksums y tablas CSV."""

    output = Path(output_path)
    if output.exists() and not overwrite:
        raise FileExistsError(f"El paquete de datos ya existe: {output.name}")
    if contract_version not in {DATASET_PACKAGE_CONTRACT, SEED_DATASET_PACKAGE_CONTRACT}:
        raise DatasetArtifactValidationError("Contrato de paquete de datos no admitido.")
    output.parent.mkdir(parents=True, exist_ok=True)
    frames = {
        "raw": raw,
        "features": features,
        "predictions": predictions,
        "validations": validations,
    }
    unknown_components = set(include_empty_components) - set(frames)
    if unknown_components:
        raise DatasetArtifactValidationError("El paquete declara componentes vacíos desconocidos.")
    if not any(frame is not None and not frame.empty for frame in frames.values()):
        raise DatasetArtifactValidationError("El paquete requiere al menos una tabla no vacía.")

    with tempfile.TemporaryDirectory(prefix="vaaet-dataset-") as temporary_directory:
        root = Path(temporary_directory)
        files: dict[str, dict[str, object]] = {}
        for component, frame in frames.items():
            if frame is None or (frame.empty and component not in include_empty_components):
                continue
            filename = PACKAGE_FILES[component]
            table_path = root / filename
            frame.to_csv(table_path, index=False)
            file_metadata: dict[str, object] = {
                "filename": filename,
                "rows": int(len(frame)),
                "sha256": _sha256(table_path),
                "columns": list(frame.columns),
                "csv_codec": CSV_CODEC,
                "column_types": {
                    column: _column_type(frame[column]) for column in frame.columns
                },
                "null_cells": {
                    column: [int(index) for index, missing in enumerate(frame[column].isna()) if missing]
                    for column in frame.columns
                    if frame[column].isna().any()
                },
            }
            if "record_time" in frame:
                timestamps = normalize_timestamp_series(
                    frame["record_time"], field_name=f"{component}.record_time"
                )
                file_metadata["record_time_min"] = timestamps.min().isoformat()
                file_metadata["record_time_max"] = timestamps.max().isoformat()
            files[component] = file_metadata
        manifest = {
            "contract_version": contract_version,
            "minimum_reader_version": MINIMUM_TYPED_READER_VERSION,
            "timezone": "UTC",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "files": files,
            "provenance": dict(provenance or {}),
            "package_metadata": dict(package_metadata or {}),
        }
        manifest_path = root / "dataset-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(manifest_path, manifest_path.name)
            for metadata in files.values():
                filename = str(metadata["filename"])
                archive.write(root / filename, filename)
    return output


def load_dataset_package(
    path: str | Path,
    *,
    accepted_contracts: tuple[str, ...] = (DATASET_PACKAGE_CONTRACT,),
) -> dict[str, pd.DataFrame]:
    """Valida y carga un paquete de datos sin exponer detalles del filesystem."""

    package = Path(path)
    if not package.is_file():
        raise FileNotFoundError(f"No se encontró el paquete de datos: {package.name}")
    try:
        with tempfile.TemporaryDirectory(prefix="vaaet-dataset-read-") as temporary_directory:
            root = Path(temporary_directory)
            with zipfile.ZipFile(package) as archive:
                _safe_extract(archive, root)
            manifest = _read_dataset_manifest(root, accepted_contracts)
            return _load_dataset_components(root, manifest)
    except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError):
        raise DatasetArtifactValidationError("El paquete de datos no puede leerse.") from None


def _read_dataset_manifest(root: Path, accepted_contracts: tuple[str, ...]) -> dict[str, object]:
    manifest_path = root / "dataset-manifest.json"
    if not manifest_path.is_file():
        raise DatasetArtifactValidationError("Falta el manifiesto del paquete de datos.")
    decoded = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise DatasetArtifactValidationError("El manifiesto del paquete debe ser un objeto.")
    manifest = cast(dict[str, object], decoded)
    if manifest.get("contract_version") not in accepted_contracts:
        raise DatasetArtifactValidationError("Versión de contrato de paquete no admitida.")
    if not isinstance(manifest.get("files"), dict):
        raise DatasetArtifactValidationError("El manifiesto no declara archivos válidos.")
    minimum_reader = manifest.get("minimum_reader_version")
    if minimum_reader is not None:
        parts = str(minimum_reader).split(".")
        if len(parts) != 3 or not all(part.isdecimal() for part in parts):
            raise DatasetArtifactValidationError("La versión mínima del lector es inválida.")
        if tuple(map(int, parts)) > (4, 9, 2):
            raise DatasetArtifactValidationError("El paquete requiere un lector más reciente.")
    return manifest


def _load_dataset_components(root: Path, manifest: Mapping[str, object]) -> dict[str, pd.DataFrame]:
    files = manifest["files"]
    if not isinstance(files, Mapping):
        raise DatasetArtifactValidationError("El manifiesto no declara archivos válidos.")
    typed_files = cast(Mapping[str, object], files)
    return {
        component: _load_dataset_component(root, component, metadata, manifest)
        for component, metadata in typed_files.items()
    }


def _load_dataset_component(
    root: Path, component: object, metadata: object, manifest: Mapping[str, object]
) -> pd.DataFrame:
    if not isinstance(component, str) or component not in PACKAGE_FILES or not isinstance(metadata, Mapping):
        raise DatasetArtifactValidationError("El paquete declara un componente desconocido.")
    metadata = cast(Mapping[str, object], metadata)
    filename = metadata.get("filename")
    if filename != PACKAGE_FILES[component]:
        raise DatasetArtifactValidationError("El paquete declara un nombre de archivo inesperado.")
    table_path = root / str(filename)
    if not table_path.is_file() or _sha256(table_path) != metadata.get("sha256"):
        raise DatasetArtifactValidationError("El checksum de una tabla del paquete no coincide.")
    if metadata.get("csv_codec") == CSV_CODEC:
        frame = _read_typed_csv(table_path, metadata)
    elif "csv_codec" not in metadata:
        frame = pd.read_csv(table_path, float_precision="round_trip")
        frame.attrs["vaaet_legacy_csv"] = True
    else:
        raise DatasetArtifactValidationError("El paquete declara un codec CSV desconocido.")
    declared_rows = metadata.get("rows")
    if type(declared_rows) is not int or len(frame) != declared_rows:
        raise DatasetArtifactValidationError("La cantidad de filas del paquete no coincide.")
    if list(frame.columns) != metadata.get("columns"):
        raise DatasetArtifactValidationError("Las columnas del paquete no coinciden.")
    if metadata.get("csv_codec") != CSV_CODEC:
        for column in _BOOLEAN_COLUMNS.intersection(frame.columns):
            frame[column] = frame[column].map(_decode_csv_boolean)
    frame.attrs["vaaet_package_provenance"] = manifest.get("provenance", {})
    frame.attrs["vaaet_package_metadata"] = manifest.get("package_metadata", {})
    frame.attrs["vaaet_package_contract"] = manifest["contract_version"]
    return frame


def _column_type(series: pd.Series) -> str:  # noqa: C901 - distingue tipos mixtos sin inferencia textual.
    """Declara el tipo lógico sin inferirlo del texto serializado."""

    if is_bool_dtype(series):
        return "boolean"
    if is_integer_dtype(series):
        return "integer"
    if is_float_dtype(series):
        return "float64"
    present = [value for value in cast(list[object], series.tolist()) if not _is_missing(value)]
    if not present:
        return "text"
    if all(isinstance(value, str) for value in present):
        return "text"
    if all(isinstance(value, (datetime, pd.Timestamp)) for value in present):
        return "timestamp"
    if all(type(value) is bool for value in present):
        return "boolean"
    if any(type(value) is bool for value in present):
        raise DatasetArtifactValidationError("Una columna mezcla booleanos con otros tipos.")
    if all(isinstance(value, Integral) for value in present):
        return "integer"
    if all(isinstance(value, (Real, Decimal)) for value in present):
        return "float64"
    raise DatasetArtifactValidationError("Una columna contiene tipos incompatibles con CSV tipado.")


def _is_missing(value: object) -> bool:
    return value is None or value is pd.NA or value is pd.NaT or (
        isinstance(value, Real) and math.isnan(float(value))
    )


def _read_typed_csv(  # noqa: C901 - valida el manifiesto y cada columna contractual.
    path: Path, metadata: Mapping[str, object]
) -> pd.DataFrame:
    raw_columns = metadata.get("columns")
    raw_types = metadata.get("column_types")
    raw_null_cells = metadata.get("null_cells")
    if (
        not isinstance(raw_columns, list)
        or not isinstance(raw_types, dict)
        or not isinstance(raw_null_cells, dict)
    ):
        raise DatasetArtifactValidationError("Los tipos o nulos del CSV son inválidos.")
    columns = cast(list[object], raw_columns)
    types = cast(dict[object, object], raw_types)
    null_cells = cast(dict[object, object], raw_null_cells)
    if (
        not all(isinstance(column, str) for column in columns)
        or not all(isinstance(key, str) and isinstance(value, str) for key, value in types.items())
        or set(types) != set(columns)
        or not all(isinstance(key, str) for key in null_cells)
        or not set(null_cells).issubset(columns)
    ):
        raise DatasetArtifactValidationError("Los tipos o nulos del CSV son inválidos.")
    typed_columns = cast(list[str], columns)
    typed_types = cast(dict[str, str], types)
    typed_null_cells = cast(dict[str, object], null_cells)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    if list(frame.columns) != typed_columns:
        raise DatasetArtifactValidationError("Las columnas tipadas del CSV no coinciden.")
    for column in typed_columns:
        raw_positions = typed_null_cells.get(column, [])
        if not isinstance(raw_positions, list):
            raise DatasetArtifactValidationError("Las posiciones de nulos del CSV son inválidas.")
        positions = cast(list[object], raw_positions)
        for value in positions:
            if type(value) is not int:
                raise DatasetArtifactValidationError("Las posiciones de nulos del CSV son inválidas.")
            index = value
            if index < 0 or index >= len(frame):
                raise DatasetArtifactValidationError("Las posiciones de nulos del CSV son inválidas.")
        typed_positions = cast(list[int], positions)
        if len(set(typed_positions)) != len(typed_positions):
            raise DatasetArtifactValidationError("Las posiciones de nulos del CSV son inválidas.")
        values = frame[column].astype(object)
        missing = set(typed_positions)
        if any(values.iloc[index] != "" for index in missing):
            raise DatasetArtifactValidationError("Un nulo declarado contradice el CSV.")
        for index in missing:
            values.iloc[index] = None
        kind = typed_types[column]
        try:
            if kind == "text":
                frame[column] = values
            elif kind == "integer":
                frame[column] = values.map(
                    lambda value: None if value is None else int(cast(str, value))
                )
            elif kind == "float64":
                numeric = values.map(
                    lambda value: None if value is None else float(cast(str, value))
                )
                if any(
                    index not in missing and not math.isfinite(value)
                    for index, value in enumerate(numeric)
                ):
                    raise ValueError("non-finite CSV value")
                frame[column] = numeric
            elif kind == "timestamp":
                frame[column] = values.map(
                    lambda value: None if value is None else pd.Timestamp(cast(str, value))
                )
            elif kind == "boolean":
                frame[column] = values.map(
                    lambda value: None if value is None else _decode_csv_boolean(value)
                )
            else:
                raise DatasetArtifactValidationError("El CSV declara un tipo de columna desconocido.")
        except (ValueError, OverflowError, TypeError):
            raise DatasetArtifactValidationError(
                "El CSV contiene un valor incompatible con su tipo declarado."
            ) from None
    return frame


def _decode_csv_boolean(value: object) -> bool:
    """Decodifica únicamente el vocabulario booleano del transporte CSV."""

    if type(value) is bool or type(value).__name__ == "bool_":
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise DatasetArtifactValidationError(
        "Una columna booleana del paquete contiene un valor no contractual."
    )


def require_unambiguous_supervised_csv(path: str | Path) -> None:
    """Bloquea supervisión con textos legacy que el parser puede reinterpretar."""

    manifest = read_package_manifest(Path(path))
    files = manifest["files"]
    if not isinstance(files, Mapping):
        raise DatasetArtifactValidationError("El manifiesto del paquete es inválido.")
    typed_files = cast(Mapping[str, object], files)
    text_columns = {
        "features": {"clip_id", "continuity_id"},
        "validations": {"reviewer_id", "notes", "review_source"},
    }
    with zipfile.ZipFile(path) as archive:
        for component, columns in text_columns.items():
            metadata = typed_files.get(component)
            if not isinstance(metadata, Mapping) or metadata.get("csv_codec") == CSV_CODEC:
                continue
            metadata = cast(Mapping[str, object], metadata)
            filename = metadata.get("filename")
            if filename != PACKAGE_FILES[component]:
                raise DatasetArtifactValidationError("El paquete declara un CSV inesperado.")
            rows = csv.DictReader(io.StringIO(archive.read(str(filename)).decode("utf-8")))
            for row in rows:
                for column in columns.intersection(row):
                    value = row[column]
                    if value is None or value == "" or value in {"NA", "NULL", "N/A", "NaN", "null"}:
                        raise DatasetArtifactValidationError(
                            "El CSV histórico contiene texto ambiguo; sólo se admite inspección."
                        )
                    if column == "reviewer_id" and value.isdecimal():
                        raise DatasetArtifactValidationError(
                            "El CSV histórico contiene un revisor numérico ambiguo."
                        )
