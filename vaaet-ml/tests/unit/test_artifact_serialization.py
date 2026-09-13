# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Pruebas de primitivas deterministas de artefactos del laboratorio."""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from vaaet_ml.data.artifact_serialization import (
    atomic_json_write,
    canonical_frame,
    frame_bytes,
    frames_fingerprint,
    is_sha256,
    json_safe,
    legacy_frames_fingerprint,
    read_package_manifest,
    safe_relative_path,
    sha256_bytes,
    sha256_file,
    stable_uuid,
    utc_now,
    valid_uuid,
)


@dataclass(frozen=True)
class _SerializableValue:
    path: Path
    created_at: datetime


class _ScalarValue:
    def item(self) -> int:
        return 7


class _UnsupportedScalar:
    def item(self) -> object:
        raise TypeError("not scalar")


def test_checksums_and_identifiers_are_stable(tmp_path: Path) -> None:
    payload = b"vaaet"
    package = tmp_path / "payload.bin"
    package.write_bytes(payload)

    checksum = sha256_bytes(payload)

    assert checksum == sha256_file(package)
    assert is_sha256(checksum)
    assert not is_sha256("ABC")
    assert stable_uuid("clip", "demo", 1) == stable_uuid("clip", "demo", 1)
    assert valid_uuid(stable_uuid("clip", "demo", 1))
    assert not valid_uuid(None)
    assert utc_now().tzinfo is timezone.utc


def test_json_safe_converts_supported_domain_values() -> None:
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    value = _SerializableValue(Path("snapshots/current.json"), created_at)

    assert json_safe({"values": {1, 2}, "payload": value, "scalar": _ScalarValue()}) == {
        "values": [1, 2],
        "payload": {
            "path": "snapshots/current.json",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        "scalar": 7,
    }
    unsupported = _UnsupportedScalar()
    assert json_safe(unsupported) is unsupported


def test_atomic_json_write_replaces_only_valid_documents(tmp_path: Path) -> None:
    document = tmp_path / "catalog" / "current.json"
    atomic_json_write(document, {"generation": 1})

    assert json.loads(document.read_text(encoding="utf-8")) == {"generation": 1}

    with pytest.raises(TypeError):
        atomic_json_write(document, {"not_json": object()})

    assert json.loads(document.read_text(encoding="utf-8")) == {"generation": 1}
    assert not list(document.parent.glob(".*.tmp"))


@pytest.mark.parametrize("value", [None, "", "../escape.zip", "/absolute.zip", "a\\b.zip", "C:drive.zip"])
def test_safe_relative_path_rejects_unsafe_values(value: object) -> None:
    with pytest.raises(ValueError):
        safe_relative_path(value)


def test_safe_relative_path_accepts_portable_member_name() -> None:
    assert safe_relative_path("snapshots/demo.zip").as_posix() == "snapshots/demo.zip"


def test_canonical_frames_and_fingerprints_seal_review_timestamp() -> None:
    frame = pd.DataFrame(
        {
            "clip_id": ["b", "a"],
            "record_time": ["2026-01-01T00:01:00Z", "2026-01-01T00:00:00Z"],
            "reviewed_at": ["2026-01-02T00:00:00Z", None],
            "value": [2, 1],
        }
    )

    canonical = canonical_frame(frame)
    altered = frame.copy()
    altered.loc[0, "reviewed_at"] = "2026-02-02T00:00:00Z"

    assert canonical["clip_id"].tolist() == ["a", "b"]
    assert frame_bytes(frame) == frame_bytes(canonical)
    assert frames_fingerprint({"validations": frame}) != frames_fingerprint(
        {"validations": altered}
    )
    assert legacy_frames_fingerprint({"validations": frame}) == legacy_frames_fingerprint(
        {"validations": altered}
    )


def test_read_package_manifest_validates_zip_members_and_json(tmp_path: Path) -> None:
    valid = tmp_path / "valid.zip"
    with zipfile.ZipFile(valid, "w") as archive:
        archive.writestr("dataset-manifest.json", json.dumps({"contract": "v1"}))
    assert read_package_manifest(valid) == {"contract": "v1"}

    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("dataset-manifest.json", "{}")
        archive.writestr("../escape.csv", "bad")
    with pytest.raises(ValueError, match="unsafe or incomplete"):
        read_package_manifest(unsafe)

    malformed = tmp_path / "malformed.zip"
    with zipfile.ZipFile(malformed, "w") as archive:
        archive.writestr("dataset-manifest.json", "[")
    with pytest.raises(ValueError, match="Invalid dataset package"):
        read_package_manifest(malformed)

    scalar = tmp_path / "scalar.zip"
    with zipfile.ZipFile(scalar, "w") as archive:
        archive.writestr("dataset-manifest.json", "[]")
    with pytest.raises(ValueError, match="JSON object"):
        read_package_manifest(scalar)
