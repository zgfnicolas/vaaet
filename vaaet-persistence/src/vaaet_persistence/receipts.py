# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Comprobantes inmutables para escrituras PostgreSQL verificables."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from math import isfinite
from numbers import Integral, Real
from typing import Any, cast
from uuid import UUID

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from vaaet_persistence.exceptions import PersistenceConflictError

PERSISTENCE_RECEIPT_ALGORITHM = "sha256-persistence-contract-v1"
_PERSISTENCE_OPERATION_ENTITIES = {
    "raw-telemetry": frozenset({"raw_telemetry"}),
    "classified-telemetry": frozenset(
        {"telemetry_features", "traffic_predictions"}
    ),
    "human-validation": frozenset({"human_validations"}),
}

_RECORD_RECEIPT_SQL = """
SELECT * FROM vaaet_ops.record_persistence_receipt(
    CAST(:pipeline_run_id AS UUID), :operation, :fingerprint_algorithm,
    :content_fingerprint, CAST(:processed_counts AS JSONB),
    CAST(:inserted_counts AS JSONB), :telemetry_schema_version,
    :feature_schema_version, :model_revision
)
"""

_READ_AUDIT_STATE_SQL = """
SELECT * FROM vaaet_ops.read_pipeline_run_audit_state(
    CAST(:pipeline_run_id AS UUID)
)
"""


@dataclass(frozen=True)
class PersistenceReceipt:
    """Prueba el contenido confirmado por una corrida de escritura."""

    pipeline_run_id: UUID
    operation: str
    fingerprint_algorithm: str
    content_fingerprint: str
    processed_counts: Mapping[str, int]
    inserted_counts: Mapping[str, int]
    telemetry_schema_version: str | None = None
    feature_schema_version: str | None = None
    model_revision: str | None = None
    confirmed_at: datetime | None = None
    database_user: str | None = None

    def __post_init__(self) -> None:
        if self.operation not in _PERSISTENCE_OPERATION_ENTITIES:
            raise ValueError("Unsupported persistence receipt operation.")
        if self.fingerprint_algorithm != PERSISTENCE_RECEIPT_ALGORITHM:
            raise ValueError("Unsupported persistence receipt algorithm.")
        if len(self.content_fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in self.content_fingerprint
        ):
            raise ValueError("Persistence receipt fingerprint must be lowercase SHA-256.")
        for label, counts in (
            ("processed_counts", self.processed_counts),
            ("inserted_counts", self.inserted_counts),
        ):
            runtime_counts = cast(Mapping[object, object], counts)
            if not runtime_counts or any(
                not isinstance(key, str)
                or not key
                or isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for key, value in runtime_counts.items()
            ):
                raise ValueError(f"{label} must contain non-negative integer counts.")
        if frozenset(self.processed_counts) != frozenset(self.inserted_counts):
            raise ValueError("Receipt processed and inserted counts must name the same entities.")
        if frozenset(self.processed_counts) != _PERSISTENCE_OPERATION_ENTITIES[self.operation]:
            raise ValueError("Receipt entity counts are incompatible with its operation.")
        if any(
            self.inserted_counts[key] > processed
            for key, processed in self.processed_counts.items()
        ):
            raise ValueError("Receipt inserted counts cannot exceed processed counts.")

    @property
    def processed_rows(self) -> int:
        """Devuelve el soporte total declarado por el comprobante."""

        return sum(self.processed_counts.values())


@dataclass(frozen=True)
class PipelineRunAuditState:
    """Describe el estado autoritativo de una corrida y su comprobante."""

    pipeline_run_id: UUID
    workflow: str
    application_name: str
    application_version: str
    database_user: str
    status: str
    source_kind: str | None
    clip_id: str | None
    input_rows: int | None
    output_rows: int | None
    telemetry_schema_version: str | None
    feature_schema_version: str | None
    model_version: str | None
    model_revision: str | None
    receipt: PersistenceReceipt | None
    reconciles_run_id: UUID | None = None

    @property
    def audit_complete(self) -> bool:
        """Indica que la corrida terminó y conserva evidencia transaccional."""

        return self.status == "succeeded" and self.receipt is not None


def calculate_persistence_fingerprint(
    operation: str,
    observations: Sequence[Mapping[str, object]],
) -> str:
    """Calcula una identidad estable preservando tipos y timestamps UTC."""

    if not operation or not observations:
        raise ValueError("A persistence fingerprint requires an operation and observations.")
    canonical_rows = [_canonical_mapping(observation) for observation in observations]
    canonical_rows.sort(
        key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"))
    )
    payload = {
        "algorithm": PERSISTENCE_RECEIPT_ALGORITHM,
        "operation": operation,
        "observations": canonical_rows,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_persistence_receipt(
    *,
    pipeline_run_id: UUID | str,
    operation: str,
    observations: Sequence[Mapping[str, object]],
    processed_counts: Mapping[str, int],
    inserted_counts: Mapping[str, int],
    telemetry_schema_version: str | None = None,
    feature_schema_version: str | None = None,
    model_revision: str | None = None,
) -> PersistenceReceipt:
    """Construye un comprobante validado antes de iniciar su escritura."""

    return PersistenceReceipt(
        pipeline_run_id=UUID(str(pipeline_run_id)),
        operation=operation,
        fingerprint_algorithm=PERSISTENCE_RECEIPT_ALGORITHM,
        content_fingerprint=calculate_persistence_fingerprint(operation, observations),
        processed_counts=dict(processed_counts),
        inserted_counts=dict(inserted_counts),
        telemetry_schema_version=telemetry_schema_version,
        feature_schema_version=feature_schema_version,
        model_revision=model_revision,
    )


def record_persistence_receipt(
    connection: Connection,
    receipt: PersistenceReceipt,
) -> PersistenceReceipt:
    """Registra o recupera el comprobante dentro de la transacción de datos."""

    row = (
        connection.execute(
            text(_RECORD_RECEIPT_SQL),
            {
                "pipeline_run_id": str(receipt.pipeline_run_id),
                "operation": receipt.operation,
                "fingerprint_algorithm": receipt.fingerprint_algorithm,
                "content_fingerprint": receipt.content_fingerprint,
                "processed_counts": json.dumps(dict(receipt.processed_counts), sort_keys=True),
                "inserted_counts": json.dumps(dict(receipt.inserted_counts), sort_keys=True),
                "telemetry_schema_version": receipt.telemetry_schema_version,
                "feature_schema_version": receipt.feature_schema_version,
                "model_revision": receipt.model_revision,
            },
        )
        .mappings()
        .one()
    )
    stored = _receipt_from_row(row)
    if not receipts_match(stored, receipt, include_inserted_counts=False):
        raise PersistenceConflictError("Immutable persistence receipt conflict.")
    return stored


def read_pipeline_run_audit_state(
    connection: Connection,
    pipeline_run_id: UUID | str,
) -> PipelineRunAuditState:
    """Lee la corrida y su comprobante mediante una operación controlada."""

    row = (
        connection.execute(
            text(_READ_AUDIT_STATE_SQL),
            {"pipeline_run_id": str(UUID(str(pipeline_run_id)))},
        )
        .mappings()
        .one()
    )
    receipt = None
    if row.get("content_fingerprint") is not None:
        receipt = _receipt_from_row(row)
    reconciles = row.get("reconciles_run_id")
    return PipelineRunAuditState(
        pipeline_run_id=UUID(str(row["pipeline_run_id"])),
        workflow=str(row["workflow"]),
        application_name=str(row["application_name"]),
        application_version=str(row["application_version"]),
        database_user=str(row["database_user"]),
        status=str(row["status"]),
        source_kind=_optional_text(row.get("source_kind")),
        clip_id=_optional_text(row.get("clip_id")),
        input_rows=_optional_int(row.get("input_rows")),
        output_rows=_optional_int(row.get("output_rows")),
        telemetry_schema_version=_optional_text(row.get("telemetry_schema_version")),
        feature_schema_version=_optional_text(row.get("feature_schema_version")),
        model_version=_optional_text(row.get("model_version")),
        model_revision=_optional_text(row.get("model_revision")),
        receipt=receipt,
        reconciles_run_id=UUID(str(reconciles)) if reconciles else None,
    )


def receipts_match(
    stored: PersistenceReceipt,
    expected: PersistenceReceipt,
    *,
    include_inserted_counts: bool,
) -> bool:
    """Compara evidencia contractual sin depender de metadata PostgreSQL."""

    return (
        stored.pipeline_run_id == expected.pipeline_run_id
        and stored.operation == expected.operation
        and stored.fingerprint_algorithm == expected.fingerprint_algorithm
        and stored.content_fingerprint == expected.content_fingerprint
        and dict(stored.processed_counts) == dict(expected.processed_counts)
        and (
            not include_inserted_counts
            or dict(stored.inserted_counts) == dict(expected.inserted_counts)
        )
        and stored.telemetry_schema_version == expected.telemetry_schema_version
        and stored.feature_schema_version == expected.feature_schema_version
        and stored.model_revision == expected.model_revision
    )


def _receipt_from_row(row: Mapping[Any, Any]) -> PersistenceReceipt:
    confirmed = row.get("confirmed_at")
    return PersistenceReceipt(
        pipeline_run_id=UUID(str(row["pipeline_run_id"])),
        operation=str(row["operation"]),
        fingerprint_algorithm=str(row["fingerprint_algorithm"]),
        content_fingerprint=str(row["content_fingerprint"]),
        processed_counts=_integer_mapping(row["processed_counts"]),
        inserted_counts=_integer_mapping(row["inserted_counts"]),
        telemetry_schema_version=_optional_text(row.get("receipt_telemetry_schema_version")),
        feature_schema_version=_optional_text(row.get("receipt_feature_schema_version")),
        model_revision=_optional_text(row.get("receipt_model_revision")),
        confirmed_at=_optional_datetime(confirmed),
        database_user=_optional_text(row.get("receipt_database_user")),
    )


def _integer_mapping(value: object) -> dict[str, int]:
    if isinstance(value, str):
        value = cast(object, json.loads(value))
    if not isinstance(value, Mapping):
        raise ValueError("Persistence receipt counts must be a JSON object.")
    mapping = cast(Mapping[object, object], value)
    return {str(key): _strict_count(count) for key, count in mapping.items()}


def _strict_count(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Persistence receipt counts must be integers, not booleans.")
    if isinstance(value, Integral):
        parsed = int(value)
    elif isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise ValueError("Persistence receipt counts must be finite integers.")
        parsed = int(value)
    elif isinstance(value, Real):
        numeric = float(value)
        if not isfinite(numeric) or not numeric.is_integer():
            raise ValueError("Persistence receipt counts must be finite integers.")
        parsed = int(numeric)
    else:
        raise ValueError("Persistence receipt counts must be numeric integers.")
    if parsed < 0:
        raise ValueError("Persistence receipt counts cannot be negative.")
    return parsed


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else _strict_count(value)


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        return pd.Timestamp(value).to_pydatetime()
    raise ValueError("Persistence receipt confirmation time is invalid.")


def _canonical_mapping(value: Mapping[Any, Any]) -> dict[str, object]:
    return {
        str(key): _canonical_value(item)
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
    }


def _canonical_value(value: object) -> Any:  # noqa: C901 - preserva tipos contractuales.
    if value is None or value is pd.NA or value is pd.NaT:
        return {"type": "null", "value": None}
    if isinstance(value, bool) or type(value).__name__ == "bool_":
        return {"type": "bool", "value": bool(value)}
    if isinstance(value, UUID):
        return {"type": "uuid", "value": str(value)}
    if isinstance(value, (datetime, date, pd.Timestamp)):
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")
        return {"type": "datetime", "value": timestamp.isoformat()}
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if isinstance(value, Integral):
        return {"type": "int", "value": int(value)}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Persistence fingerprints reject non-finite decimal values.")
        return {"type": "float64", "value": float(value).hex()}
    if isinstance(value, Real):
        rendered = float(value)
        if not isfinite(rendered):
            raise ValueError("Persistence fingerprints reject non-finite floating values.")
        return {"type": "float64", "value": rendered.hex()}
    if isinstance(value, str):
        return {"type": "str", "value": value}
    if isinstance(value, Mapping):
        return {
            "type": "mapping",
            "value": _canonical_mapping(cast(Mapping[Any, Any], value)),
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        sequence = cast(Sequence[object], value)
        return {
            "type": "sequence",
            "value": [_canonical_value(item) for item in sequence],
        }
    raise TypeError(f"Unsupported persistence fingerprint value: {type(value).__name__}")


__all__ = [
    "PERSISTENCE_RECEIPT_ALGORITHM",
    "PersistenceReceipt",
    "PipelineRunAuditState",
    "build_persistence_receipt",
    "calculate_persistence_fingerprint",
    "read_pipeline_run_audit_state",
    "record_persistence_receipt",
    "receipts_match",
]
