# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Evidencia explícita que habilita feedback humano supervisado."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from numbers import Real
from typing import cast
from uuid import UUID

import pandas as pd
from vaaet_persistence.receipts import (
    PERSISTENCE_RECEIPT_ALGORITHM,
    calculate_persistence_fingerprint,
)

from vaaet_ml.data.artifact_serialization import is_sha256


class ReviewAuditOrigin(str, Enum):
    """Identifica el sistema que confirmó una decisión humana."""

    PORTABLE = "portable"
    POSTGRESQL = "postgresql"


@dataclass(frozen=True)
class ReviewAuditEvidence:
    """Relaciona una decisión con su estado auditable y comprobante."""

    validation_id: str
    origin: ReviewAuditOrigin
    audit_complete: bool
    pipeline_run_id: str | None = None
    receipt_fingerprint: str | None = None

    def __post_init__(self) -> None:
        try:
            UUID(self.validation_id)
        except (TypeError, ValueError, AttributeError):
            raise ValueError("Review audit evidence requires a validation UUID.") from None
        if type(self.audit_complete) is not bool or not self.audit_complete:
            raise ValueError("Human review audit is incomplete or unverified.")
        if self.origin is ReviewAuditOrigin.POSTGRESQL:
            try:
                UUID(str(self.pipeline_run_id))
            except (TypeError, ValueError, AttributeError):
                raise ValueError("PostgreSQL review requires a verified pipeline run.") from None
            if not is_sha256(self.receipt_fingerprint):
                raise ValueError("PostgreSQL review requires an immutable receipt fingerprint.")
        elif self.receipt_fingerprint is not None:
            raise ValueError("Portable review must not claim a PostgreSQL receipt.")


def _records(frame: pd.DataFrame) -> list[dict[str, object]]:
    """Acota el borde no tipado de pandas a registros contractuales."""

    return cast(list[dict[str, object]], frame.to_dict("records"))


def _missing(value: object) -> bool:
    """Reconoce sólo marcadores escalares ausentes, sin aceptar colecciones."""

    return value is None or value is pd.NA or value is pd.NaT or (
        isinstance(value, Real) and math.isnan(float(value))
    )


def _optional_text(value: object) -> str | None:
    return None if _missing(value) else str(value)


def validate_review_audit(  # noqa: C901 - valida todos los orígenes en un borde común.
    validations: pd.DataFrame,
    *,
    declared_origin: ReviewAuditOrigin | None = None,
    predictions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Rechaza decisiones pendientes o de procedencia ambigua antes de supervisar."""

    result = validations.copy()
    if result.empty:
        return result
    if "review_audit_origin" not in result:
        if declared_origin is None:
            raise ValueError("Human review audit provenance is unknown; inspection only.")
        result["review_audit_origin"] = declared_origin.value
    if declared_origin is not None and any(
        origin != declared_origin.value
        for origin in result["review_audit_origin"].tolist()
    ):
        raise ValueError("Human review audit provenance contradicts the declared origin.")
    if "audit_complete" not in result:
        raise ValueError("Human review audit status is unknown; inspection only.")
    if "id" not in result:
        raise ValueError("Human review audit evidence requires validation IDs.")
    for row in _records(result):
        try:
            origin = ReviewAuditOrigin(row["review_audit_origin"])
        except (ValueError, TypeError):
            raise ValueError("Human review audit provenance is unknown; inspection only.") from None
        fingerprint = row.get("persistence_receipt_fingerprint")
        ReviewAuditEvidence(
            validation_id=str(row["id"]),
            origin=origin,
            audit_complete=cast(bool, row["audit_complete"]),
            pipeline_run_id=_optional_text(row.get("pipeline_run_id")),
            receipt_fingerprint=_optional_text(fingerprint),
        )
    if predictions is not None:
        _verify_postgres_decision_fingerprints(result, predictions)
    return result


def _verify_postgres_decision_fingerprints(
    validations: pd.DataFrame, predictions: pd.DataFrame
) -> None:
    """Comprueba que cada recibo PostgreSQL corresponde a la decisión exportada."""

    postgres = validations.loc[
        [origin == "postgresql" for origin in validations["review_audit_origin"].tolist()]
    ]
    if postgres.empty:
        return
    if predictions.empty or "id" not in predictions:
        raise ValueError("PostgreSQL review requires its contractual predictions.")
    operational_column = (
        "operational_prediction_id"
        if "operational_prediction_id" in predictions
        else "id"
    )
    if predictions["id"].astype(str).duplicated().any():
        raise ValueError("PostgreSQL review prediction identities are ambiguous.")
    operational_by_id = dict(
        zip(
            predictions["id"].astype(str),
            predictions[operational_column],
            strict=True,
        )
    )
    for row in _records(postgres):
        operational_id = operational_by_id.get(str(row["prediction_id"]))
        if operational_id is None or isinstance(operational_id, bool):
            raise ValueError("PostgreSQL review has no verified operational prediction ID.")
        try:
            prediction_id = int(operational_id)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("PostgreSQL review prediction ID is not integral.") from None
        if str(operational_id) not in {str(prediction_id), f"{prediction_id}.0"}:
            raise ValueError("PostgreSQL review prediction ID is not integral.")
        payload = _decision_receipt_payload(row, prediction_id)
        expected = calculate_persistence_fingerprint("human-validation", [payload])
        if expected != row["persistence_receipt_fingerprint"]:
            raise ValueError("PostgreSQL review receipt contradicts the decision content.")


def _decision_receipt_payload(row: Mapping[str, object], prediction_id: int) -> dict[str, object]:
    notes = row.get("notes")
    parent = row.get("supersedes_validation_id")
    return {
        "id": str(row["id"]),
        "prediction_id": prediction_id,
        "validated_state": int(cast(int, row["validated_state"])),
        "reviewer_id": row["reviewer_id"],
        "reviewed_at": pd.Timestamp(str(row["reviewed_at"])),
        "notes": None if _missing(notes) else notes,
        "review_source": row["review_source"],
        "incident_context_reviewed": row["incident_context_reviewed"],
        "supersedes_validation_id": _optional_text(parent),
        "pipeline_run_id": str(row["pipeline_run_id"]),
    }


def validate_review_audit_manifest(
    validations: pd.DataFrame, metadata: Mapping[str, object]
) -> None:
    """Exige que el manifiesto describa exactamente las decisiones del ZIP."""

    declared = metadata.get("review_audit_evidence")
    if not isinstance(declared, list):
        raise ValueError("Review package has no complete audit evidence manifest.")
    items = cast(list[object], declared)
    if len(items) != len(validations):
        raise ValueError("Review package has no complete audit evidence manifest.")
    expected = {
        str(row["id"]): (
            str(row["review_audit_origin"]),
            row["audit_complete"],
            _optional_text(row.get("pipeline_run_id")),
            _optional_text(row.get("persistence_receipt_fingerprint")),
        )
        for row in _records(validations)
    }
    if len(expected) != len(validations):
        raise ValueError("Review package contains duplicate validation identities.")
    actual: dict[str, tuple[object, ...]] = {}
    for item in items:
        if not isinstance(item, dict) or "validation_id" not in item:
            raise ValueError("Review package audit evidence is malformed.")
        entry = cast(dict[str, object], item)
        identity = str(entry["validation_id"])
        if identity in actual:
            raise ValueError("Review package audit evidence contains duplicate identities.")
        actual[identity] = (
            entry.get("origin"),
            entry.get("audit_complete"),
            entry.get("pipeline_run_id"),
            entry.get("receipt_fingerprint"),
        )
    if actual != expected:
        raise ValueError("Review package manifest contradicts its audit evidence rows.")


def build_review_audit_manifest(validations: pd.DataFrame) -> list[dict[str, object]]:
    """Construye la declaración extensible desde decisiones ya validadas."""

    return [
        {
            "validation_id": str(row["id"]),
            "origin": str(row["review_audit_origin"]),
            "audit_complete": row["audit_complete"],
            "pipeline_run_id": _optional_text(row.get("pipeline_run_id")),
            "receipt_fingerprint": _optional_text(
                row.get("persistence_receipt_fingerprint")
            ),
        }
        for row in _records(validations)
    ]


def verify_backup_review_audit(  # noqa: C901 - verifica la cadena completa de cada decisión.
    components: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Verifica cada decisión del backup contra su corrida y comprobante inmutable."""

    validations = components.get("validations", pd.DataFrame()).copy()
    if validations.empty:
        return components
    runs = components.get("runs", pd.DataFrame())
    receipts = components.get("receipts", pd.DataFrame())
    if runs.empty or receipts.empty:
        raise ValueError("Backup review audit evidence is incomplete; inspection only.")
    required = {
        "validations": {
            "id", "prediction_id", "validated_state", "reviewer_id", "reviewed_at",
            "review_source", "incident_context_reviewed", "pipeline_run_id",
        },
        "runs": {"id", "workflow", "status", "input_rows", "output_rows", "database_user"},
        "receipts": {
            "pipeline_run_id", "operation", "fingerprint_algorithm", "content_fingerprint",
            "processed_counts", "inserted_counts", "database_user",
        },
    }
    for name, frame in (("validations", validations), ("runs", runs), ("receipts", receipts)):
        if required[name] - set(frame.columns):
            raise ValueError("Backup review audit evidence is incomplete; inspection only.")
    if runs["id"].astype(str).duplicated().any() or receipts[
        "pipeline_run_id"
    ].astype(str).duplicated().any():
        raise ValueError("Backup review audit identities are ambiguous.")
    run_by_id = runs.set_index(runs["id"].astype(str))
    receipt_by_run = receipts.set_index(receipts["pipeline_run_id"].astype(str))
    fingerprints: list[str] = []
    for row in _records(validations):
        run_id = str(row.get("pipeline_run_id"))
        if run_id not in run_by_id.index or run_id not in receipt_by_run.index:
            raise ValueError("Backup review audit has a missing run or receipt; inspection only.")
        run = cast(pd.Series, run_by_id.loc[run_id])
        receipt = cast(pd.Series, receipt_by_run.loc[run_id])
        if (
            run["workflow"] != "review"
            or run["status"] != "succeeded"
            or int(cast(int, run["input_rows"])) != 1
            or int(cast(int, run["output_rows"])) != 1
            or receipt["operation"] != "human-validation"
            or receipt["fingerprint_algorithm"] != PERSISTENCE_RECEIPT_ALGORITHM
            or str(run["database_user"]) != str(receipt["database_user"])
        ):
            raise ValueError("Backup review audit contradicts its operational run.")
        counts: object = receipt["processed_counts"]
        inserted: object = receipt["inserted_counts"]
        if isinstance(counts, str):
            counts = json.loads(counts)
        if isinstance(inserted, str):
            inserted = json.loads(inserted)
        if counts != {"human_validations": 1} or inserted != {"human_validations": 1}:
            raise ValueError("Backup review receipt has incomplete support.")
        payload = _decision_receipt_payload(row, int(cast(int, row["prediction_id"])))
        fingerprint = calculate_persistence_fingerprint("human-validation", [payload])
        if fingerprint != str(receipt["content_fingerprint"]).strip():
            raise ValueError("Backup review receipt does not match the stored decision.")
        fingerprints.append(fingerprint)
    validations["review_audit_origin"] = ReviewAuditOrigin.POSTGRESQL.value
    validations["audit_complete"] = True
    validations["persistence_receipt_fingerprint"] = fingerprints
    components["validations"] = validate_review_audit(validations)
    return components


__all__ = [
    "ReviewAuditEvidence",
    "ReviewAuditOrigin",
    "build_review_audit_manifest",
    "validate_review_audit",
    "validate_review_audit_manifest",
    "verify_backup_review_audit",
]
