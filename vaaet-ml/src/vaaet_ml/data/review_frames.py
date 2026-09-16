# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Conversión validada de una sesión de revisión a tablas inmutables."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime

import pandas as pd
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.continuity import normalize_continuity_frame
from vaaet.settings import FEATURE_COLS

from vaaet_ml.data.artifact_serialization import (
    canonical_contract_value,
    canonical_timestamp_identity,
    is_sha256,
    stable_uuid,
    valid_uuid,
)

_REVIEW_SOURCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def normalize_review_frames(
    classified: pd.DataFrame,
    validations: pd.DataFrame | Sequence[object],
    *,
    pipeline_run_id: str,
    model_version: str,
    finalized_at: datetime,
) -> dict[str, pd.DataFrame]:
    """Convierte clasificación y decisiones a tablas relacionales verificables."""

    run_id = _validated_run_id(pipeline_run_id)
    classified = _deduplicate_source_predictions(classified)
    normalized = normalize_continuity_frame(classified).reset_index(drop=True)
    features = _normalize_features(normalized, run_id)
    predictions, source_prediction_ids = _normalize_predictions(
        normalized, features, run_id, model_version
    )
    validation_frame = _normalize_validations(
        validations,
        source_prediction_ids=source_prediction_ids,
        prediction_ids=predictions["id"].tolist(),
        run_id=run_id,
        finalized_at=finalized_at,
    )
    reviewed = set(validation_frame["prediction_id"].astype(str))
    predictions["review_status"] = predictions["id"].map(
        lambda value: "validated" if str(value) in reviewed else "unreviewed"
    )
    return {
        "features": features,
        "predictions": predictions,
        "validations": validation_frame,
    }


def _deduplicate_source_predictions(classified: pd.DataFrame) -> pd.DataFrame:
    """Rechaza un ID ambiguo y admite sólo repeticiones contractualmente idénticas."""

    if "prediction_id" not in classified or classified["prediction_id"].isna().any():
        return classified.copy()
    result: list[pd.Series] = []
    for identifier, group in classified.groupby(
        classified["prediction_id"].astype(str), sort=False, dropna=False
    ):
        first = group.iloc[0]
        reference = tuple(
            canonical_contract_value(column, first[column])
            for column in classified.columns
            if column != "prediction_id"
        )
        if any(
            tuple(
                canonical_contract_value(column, row[column])
                for column in classified.columns
                if column != "prediction_id"
            )
            != reference
            for _, row in group.iloc[1:].iterrows()
        ):
            raise ValueError(
                "Classified review rows contain ambiguous prediction identities: "
                f"{identifier}"
            )
        result.append(first)
    return pd.DataFrame(result, columns=classified.columns).reset_index(drop=True)


def _validated_run_id(pipeline_run_id: str) -> str:
    try:
        return str(uuid.UUID(str(pipeline_run_id)))
    except ValueError as exc:
        raise ValueError("pipeline_run_id must be a UUID.") from exc


def _normalize_features(classified: pd.DataFrame, run_id: str) -> pd.DataFrame:
    if classified.empty:
        raise ValueError("A HITL review session requires classified feature rows.")
    required = {"clip_id", "record_time", *FEATURE_COLS}
    if missing := sorted(required - set(classified.columns)):
        raise ValueError(f"Classified review rows are missing fields: {missing}")
    features = classified.copy().reset_index(drop=True)
    if "feature_schema_version" not in features:
        raise ValueError("Classified review rows require feature_schema_version.")
    schemas = set(features["feature_schema_version"].dropna().astype(str))
    if schemas != {FEATURE_SCHEMA_VERSION} or features["feature_schema_version"].isna().any():
        raise ValueError(
            "Operational HITL export requires the current feature schema on every row."
        )
    if "pipeline_run_id" in features:
        declared_runs = set(features["pipeline_run_id"].dropna().astype(str))
        if declared_runs and declared_runs != {run_id}:
            raise ValueError("Classified review rows contradict pipeline_run_id.")
    features["pipeline_run_id"] = run_id
    if "numeric_representation" in features:
        representations = set(features["numeric_representation"].dropna().astype(str))
        if representations and representations != {"float64"}:
            raise ValueError("New HITL exports require float64 numeric representation.")
    features["numeric_representation"] = "float64"
    operational_ids = features.get(
        "operational_feature_id", features.get("id", pd.Series(pd.NA, index=features.index))
    )
    features["id"] = [
        stable_uuid(
            "feature",
            run_id,
            row.clip_id,
            row.continuity_id,
            canonical_timestamp_identity(row.record_time),
            row.feature_schema_version,
        )
        for row in features.itertuples()
    ]
    features["operational_feature_id"] = operational_ids
    prediction_columns = {
        "prediction_id",
        "traffic_state",
        "state_label",
        "confidence",
        "model_confidence",
        "model_traffic_state",
        "probability_margin",
        "decision_abstained",
        "measurement_reliable",
        "accident_rule_triggered",
        "accident_alert_started",
        "accident_evidence_score",
    }
    metadata = [
        column
        for column in features.columns
        if column not in FEATURE_COLS and column not in prediction_columns
    ]
    return features[[*metadata, *FEATURE_COLS]]


def _normalize_predictions(
    classified: pd.DataFrame,
    features: pd.DataFrame,
    run_id: str,
    model_version: str,
) -> tuple[pd.DataFrame, pd.Series]:
    revisions = set(classified.get("model_revision", pd.Series(dtype=str)).dropna().astype(str))
    if len(revisions) != 1 or not is_sha256(next(iter(revisions), "")):
        raise ValueError("Classified review rows require one exact SHA-256 model_revision.")
    model_revision = next(iter(revisions))
    declared_versions = set(
        classified.get("model_version", pd.Series(dtype=str)).dropna().astype(str)
    )
    if declared_versions and declared_versions != {model_version}:
        raise ValueError("Classified review rows contradict model_version.")
    source_ids = classified.get(
        "prediction_id", pd.Series(range(1, len(classified) + 1), index=classified.index)
    )
    if source_ids.isna().any():
        raise ValueError("Classified review rows contain incomplete prediction identities.")
    source_identity = source_ids.astype(str)
    if source_identity.duplicated(keep=False).any():
        duplicates = sorted(source_identity[source_identity.duplicated(keep=False)].unique())
        raise ValueError(
            "Classified review rows contain ambiguous prediction identities: "
            f"{duplicates}"
        )
    prediction_ids = [
        stable_uuid("prediction", run_id, feature_id, model_revision)
        for feature_id in features["id"]
    ]
    prediction_columns = [
        column
        for column in (
            "traffic_state",
            "state_label",
            "confidence",
            "model_traffic_state",
            "model_confidence",
            "probability_margin",
            "decision_abstained",
            "measurement_reliable",
            "accident_rule_triggered",
            "accident_alert_started",
            "accident_evidence_score",
        )
        if column in classified
    ]
    predictions = classified[prediction_columns].copy()
    predictions.insert(0, "model_revision", model_revision)
    predictions.insert(0, "model_version", model_version)
    predictions.insert(0, "telemetry_feature_id", features["id"].tolist())
    predictions.insert(0, "id", prediction_ids)
    predictions["pipeline_run_id"] = run_id
    predictions["numeric_representation"] = "float64"
    predictions["operational_prediction_id"] = source_ids.tolist()
    return predictions, source_ids


def _normalize_validations(  # noqa: C901 - normaliza el contrato externo completo.
    validations: pd.DataFrame | Sequence[object],
    *,
    source_prediction_ids: pd.Series,
    prediction_ids: list[str],
    run_id: str,
    finalized_at: datetime,
) -> pd.DataFrame:
    """Normaliza decisiones append-only y preserva su vínculo con la predicción."""

    frame = _validation_frame(validations)
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "id",
                "prediction_id",
                "validated_state",
                "is_human_validated",
                "reviewer_id",
                "reviewed_at",
                "notes",
                "review_source",
                "incident_context_reviewed",
                "supersedes_validation_id",
                "pipeline_run_id",
            ]
        )
    if "validation_id" in frame and "id" not in frame:
        frame = frame.rename(columns={"validation_id": "id"})
    required = {
        "prediction_id",
        "validated_state",
        "reviewer_id",
        "reviewed_at",
        "review_source",
        "incident_context_reviewed",
    }
    if missing := sorted(required - set(frame.columns)):
        raise ValueError(f"Review validations are missing fields: {missing}")
    id_map = {
        str(source_id): prediction_id
        for source_id, prediction_id in zip(source_prediction_ids, prediction_ids, strict=True)
    }
    frame["prediction_id"] = frame["prediction_id"].map(
        lambda value: id_map.get(str(value), str(value))
    )
    unknown = set(frame["prediction_id"]) - set(prediction_ids)
    if unknown:
        raise ValueError(
            f"Validations reference predictions outside the session: {sorted(unknown)}"
        )
    if frame["validated_state"].map(
        lambda value: type(value) is bool or type(value).__name__ == "bool_"
    ).any():
        raise ValueError("Human validations must use integer states, not booleans.")
    states = pd.to_numeric(frame["validated_state"], errors="raise")
    if (
        not states.map(lambda value: float(value).is_integer()).all()
        or not states.isin((0, 1, 2, 3)).all()
    ):
        raise ValueError("Human validations must use public states 0 through 3.")
    frame["validated_state"] = states.astype(int)
    if "is_human_validated" in frame and not frame["is_human_validated"].map(
        lambda value: (type(value) is bool or type(value).__name__ == "bool_")
        and bool(value)
    ).all():
        raise ValueError("Review exports accept only explicitly human-validated decisions.")
    frame["is_human_validated"] = True
    if "id" not in frame or not frame["id"].map(valid_uuid).all():
        raise ValueError("Human validations require an explicit UUID identity.")
    frame["id"] = frame["id"].astype(str)
    frame["supersedes_validation_id"] = _supersedes_ids(frame)
    declared_parents = frame["supersedes_validation_id"].dropna()
    if not declared_parents.map(valid_uuid).all():
        raise ValueError("supersedes_validation_id must contain UUID values when declared.")
    reviewed_at = pd.to_datetime(frame["reviewed_at"], utc=True, errors="raise")
    if reviewed_at.isna().any():
        raise ValueError("Human validation reviewed_at is required on every row.")
    frame["reviewed_at"] = reviewed_at
    if frame["reviewer_id"].isna().any() or frame["reviewer_id"].astype(str).str.strip().eq("").any():
        raise ValueError("Human validation reviewer_id is required on every row.")
    if frame["review_source"].isna().any() or frame["review_source"].astype(str).map(
        lambda value: _REVIEW_SOURCE.fullmatch(value) is not None
    ).eq(False).any():
        raise ValueError("Human validation review_source must be a safe identifier.")
    if not frame["incident_context_reviewed"].map(
        lambda value: type(value) is bool or type(value).__name__ == "bool_"
    ).all():
        raise ValueError("incident_context_reviewed must contain contractual booleans.")
    accidents = frame["validated_state"].eq(3)
    notes = frame.get("notes", pd.Series(pd.NA, index=frame.index))
    if accidents.any() and (
        not frame.loc[accidents, "incident_context_reviewed"].all()
        or notes.loc[accidents].isna().any()
        or notes.loc[accidents].astype(str).str.strip().eq("").any()
    ):
        raise ValueError("Accident requires confirmed temporal context and a non-empty note.")
    if "pipeline_run_id" not in frame:
        frame["pipeline_run_id"] = run_id
    else:
        if frame["pipeline_run_id"].isna().any():
            raise ValueError("Human validation pipeline_run_id cannot be missing when declared.")
        if not frame["pipeline_run_id"].astype(str).map(valid_uuid).all():
            raise ValueError("Human validation pipeline_run_id must be a UUID.")
    return frame


def _validation_frame(validations: pd.DataFrame | Sequence[object]) -> pd.DataFrame:
    if isinstance(validations, pd.DataFrame):
        return validations.copy()
    records = [asdict(item) if is_dataclass(item) else dict(item) for item in validations]
    return pd.DataFrame(records)


def _supersedes_ids(frame: pd.DataFrame) -> pd.Series:
    if "supersedes_validation_id" not in frame:
        return pd.Series(pd.NA, index=frame.index)
    return frame["supersedes_validation_id"].map(
        lambda value: str(value) if pd.notna(value) and value else pd.NA
    )


__all__ = ["normalize_review_frames"]
