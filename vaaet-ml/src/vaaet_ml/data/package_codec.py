# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Codec seguro de paquetes ZIP/CSV compartido por ingestión y artefactos."""

from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from collections.abc import Mapping
from pathlib import Path

import pandas as pd
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.timestamps import normalize_timestamp_series

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
    "incident_context_reviewed",
    "decision_abstained",
    "measurement_reliable",
    "accident_rule_triggered",
    "accident_alert_started",
}


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
    except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError) as error:
        raise DatasetArtifactValidationError("El paquete de datos no puede leerse.") from error


def _read_dataset_manifest(root: Path, accepted_contracts: tuple[str, ...]) -> dict[str, object]:
    manifest_path = root / "dataset-manifest.json"
    if not manifest_path.is_file():
        raise DatasetArtifactValidationError("Falta el manifiesto del paquete de datos.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise DatasetArtifactValidationError("El manifiesto del paquete debe ser un objeto.")
    if manifest.get("contract_version") not in accepted_contracts:
        raise DatasetArtifactValidationError("Versión de contrato de paquete no admitida.")
    if not isinstance(manifest.get("files"), dict):
        raise DatasetArtifactValidationError("El manifiesto no declara archivos válidos.")
    return manifest


def _load_dataset_components(root: Path, manifest: Mapping[str, object]) -> dict[str, pd.DataFrame]:
    files = manifest["files"]
    if not isinstance(files, Mapping):
        raise DatasetArtifactValidationError("El manifiesto no declara archivos válidos.")
    return {
        component: _load_dataset_component(root, component, metadata, manifest)
        for component, metadata in files.items()
    }


def _load_dataset_component(
    root: Path, component: object, metadata: object, manifest: Mapping[str, object]
) -> pd.DataFrame:
    if not isinstance(component, str) or component not in PACKAGE_FILES or not isinstance(metadata, Mapping):
        raise DatasetArtifactValidationError("El paquete declara un componente desconocido.")
    filename = metadata.get("filename")
    if filename != PACKAGE_FILES[component]:
        raise DatasetArtifactValidationError("El paquete declara un nombre de archivo inesperado.")
    table_path = root / str(filename)
    if not table_path.is_file() or _sha256(table_path) != metadata.get("sha256"):
        raise DatasetArtifactValidationError("El checksum de una tabla del paquete no coincide.")
    frame = pd.read_csv(table_path, float_precision="round_trip")
    if len(frame) != int(metadata.get("rows", -1)):
        raise DatasetArtifactValidationError("La cantidad de filas del paquete no coincide.")
    if list(frame.columns) != metadata.get("columns"):
        raise DatasetArtifactValidationError("Las columnas del paquete no coinciden.")
    for column in _BOOLEAN_COLUMNS.intersection(frame.columns):
        frame[column] = frame[column].map(_decode_csv_boolean)
    frame.attrs["vaaet_package_provenance"] = manifest.get("provenance", {})
    frame.attrs["vaaet_package_metadata"] = manifest.get("package_metadata", {})
    frame.attrs["vaaet_package_contract"] = manifest["contract_version"]
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
