# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Primitivas deterministas para artefactos inmutables del laboratorio."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from numbers import Integral, Real
from pathlib import Path, PurePosixPath

import pandas as pd
from vaaet.timestamps import normalize_timestamp, normalize_timestamp_series

_UUID_NAMESPACE = uuid.UUID("5ef88f18-4663-4c81-a6f9-5b40b256e083")


def sha256_bytes(payload: bytes) -> str:
    """Calcula el checksum SHA-256 de una carga ya materializada."""

    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    """Calcula un checksum sin cargar el archivo completo en memoria."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_sha256(value: object) -> bool:
    """Indica si el valor tiene la representación hexadecimal SHA-256 esperada."""

    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def utc_now() -> datetime:
    """Devuelve el instante actual explícitamente normalizado a UTC."""

    return datetime.now(timezone.utc)


def stable_uuid(kind: str, *parts: object) -> str:
    """Genera un UUID determinista para una identidad derivada de contenido."""

    material = "|".join([kind, *(str(part) for part in parts)])
    return str(uuid.uuid5(_UUID_NAMESPACE, material))


def canonical_timestamp_identity(value: object) -> str:
    """Representa un instante UTC de forma estable antes de derivar identidades."""

    return normalize_timestamp(value).isoformat()


def canonical_contract_value(column: str, value: object) -> tuple[str, object]:
    """Compara scalars contractuales sin depender de formato ni tipo NumPy."""

    if value is None or value is pd.NA or value is pd.NaT:
        return ("missing", "")
    try:
        missing = pd.isna(value)
        if (type(missing) is bool or type(missing).__name__ == "bool_") and bool(missing):
            return ("missing", "")
    except (TypeError, ValueError):
        pass
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


def valid_uuid(value: object) -> bool:
    """Valida UUIDs de identificadores de dominio sin propagar errores de parseo."""

    try:
        uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def json_safe(value: object) -> object:
    """Convierte valores del dominio a una representación JSON estable y explícita."""

    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value))
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            return json_safe(item_method())
        except (TypeError, ValueError):
            pass
    return value


def atomic_json_write(path: Path, document: Mapping[str, object]) -> None:
    """Persiste un documento JSON sólo después de verificar su serialización."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        json.loads(temporary.read_text(encoding="utf-8"))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def safe_relative_path(value: object, *, label: str = "Catalog package") -> PurePosixPath:
    """Valida una ruta relativa portable antes de resolverla contra un root conocido."""

    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} path must be a non-empty relative path.")
    if "\\" in value or ":" in value:
        raise ValueError(f"Unsafe {label.lower()} path: {value}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Unsafe {label.lower()} path: {value}")
    return path


def canonical_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Normaliza el orden y timestamps usados para fingerprints reproducibles."""

    if frame.empty:
        return frame.copy()
    result = frame.copy()
    if "record_time" in result:
        result["record_time"] = normalize_timestamp_series(result["record_time"]).map(
            lambda value: value.isoformat()
        )
    if "reviewed_at" in result:
        reviewed = pd.to_datetime(result["reviewed_at"], utc=True, errors="coerce")
        result["reviewed_at"] = reviewed.map(
            lambda value: value.isoformat() if pd.notna(value) else ""
        )
    sort_columns = [
        column
        for column in ("clip_id", "record_time", "telemetry_feature_id", "prediction_id", "id")
        if column in result
    ]
    if sort_columns:
        result = result.sort_values(sort_columns, kind="stable")
    return result.reset_index(drop=True)


def frame_bytes(frame: pd.DataFrame, *, ignore_columns: Sequence[str] = ()) -> bytes:
    """Serializa un DataFrame canónico para comparaciones de contenido."""

    portable = canonical_frame(frame).drop(columns=list(ignore_columns), errors="ignore")
    return portable.to_csv(index=False, lineterminator="\n", na_rep="").encode("utf-8")


def frames_fingerprint(frames: Mapping[str, pd.DataFrame]) -> str:
    """Calcula un fingerprint sensible a nombres, filas y contratos de tablas."""

    return _frames_fingerprint(frames, ignore_validation_reviewed_at=False)


def legacy_frames_fingerprint(frames: Mapping[str, pd.DataFrame]) -> str:
    """Reproduce el fingerprint histórico que omitía la fecha de revisión."""

    return _frames_fingerprint(frames, ignore_validation_reviewed_at=True)


def _frames_fingerprint(
    frames: Mapping[str, pd.DataFrame], *, ignore_validation_reviewed_at: bool
) -> str:
    """Calcula la identidad con una política explícita para artefactos históricos."""

    digest = hashlib.sha256()
    for name in sorted(frames):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        ignored_columns = (
            ("reviewed_at",)
            if ignore_validation_reviewed_at and name == "validations"
            else ()
        )
        digest.update(frame_bytes(frames[name], ignore_columns=ignored_columns))
        digest.update(b"\0")
    return digest.hexdigest()


def read_package_manifest(path: Path) -> dict[str, object]:
    """Lee exclusivamente el manifiesto de un ZIP de dataset validando sus rutas."""

    import zipfile

    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if "dataset-manifest.json" not in names or any(
                PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
                for name in names
            ):
                raise ValueError("Dataset package has an unsafe or incomplete member list.")
            document = json.loads(archive.read("dataset-manifest.json").decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile):
        raise ValueError("Invalid dataset package.") from None
    if not isinstance(document, dict):
        raise ValueError("Dataset package manifest must be a JSON object.")
    return document


__all__ = [
    "atomic_json_write",
    "canonical_contract_value",
    "canonical_timestamp_identity",
    "canonical_frame",
    "frame_bytes",
    "frames_fingerprint",
    "legacy_frames_fingerprint",
    "is_sha256",
    "json_safe",
    "read_package_manifest",
    "safe_relative_path",
    "sha256_bytes",
    "sha256_file",
    "stable_uuid",
    "utc_now",
    "valid_uuid",
]
