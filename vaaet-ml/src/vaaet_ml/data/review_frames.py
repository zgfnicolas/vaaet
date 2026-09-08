# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Conversión validada de una sesión de revisión a tablas inmutables."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime

import pandas as pd
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.continuity import normalize_continuity_frame
from vaaet.settings import FEATURE_COLS

from vaaet_ml.data.artifact_serialization import is_sha256, stable_uuid, valid_uuid


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
    features = _normalize_features(classified, run_id)
    predictions, source_prediction_ids = _normalize_predictions(
        classified, features, run_id, model_version
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
    features = normalize_continuity_frame(classified).reset_index(drop=True)
    existing_ids = features.get("id", pd.Series(pd.NA, index=features.index)).astype("string")
    features["id"] = [
        str(value)
        if valid_uuid(value)
        else stable_uuid("feature", run_id, row.clip_id, row.record_time)
        for value, row in zip(existing_ids, features.itertuples(), strict=False)
    ]
    features["feature_schema_version"] = FEATURE_SCHEMA_VERSION
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
    source_ids = classified.get(
        "prediction_id", pd.Series(range(1, len(classified) + 1), index=classified.index)
    )
    prediction_ids = [
        value
        if valid_uuid(value)
        else stable_uuid("prediction", run_id, feature_id, model_revision)
        for value, feature_id in zip(source_ids.astype(str), features["id"], strict=False)
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
    return predictions, source_ids


def _normalize_validations(
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
    if "prediction_id" not in frame or "validated_state" not in frame:
        raise ValueError("Review validations require prediction_id and validated_state.")
    id_map = {
        str(source_id): prediction_id
        for source_id, prediction_id in zip(source_prediction_ids, prediction_ids, strict=False)
    }
    frame["prediction_id"] = frame["prediction_id"].map(
        lambda value: id_map.get(str(value), str(value))
    )
    unknown = set(frame["prediction_id"]) - set(prediction_ids)
    if unknown:
        raise ValueError(
            f"Validations reference predictions outside the session: {sorted(unknown)}"
        )
    states = pd.to_numeric(frame["validated_state"], errors="raise")
    if (
        not states.map(lambda value: float(value).is_integer()).all()
        or not states.isin((0, 1, 2, 3)).all()
    ):
        raise ValueError("Human validations must use public states 0 through 3.")
    frame["validated_state"] = states.astype(int)
    frame["is_human_validated"] = True
    supplied_ids = frame.get("id", pd.Series(pd.NA, index=frame.index))
    frame["id"] = [
        str(value)
        if pd.notna(value) and valid_uuid(value)
        else stable_uuid(
            "validation",
            prediction_id,
            state,
            frame.iloc[index].get("reviewer_id", "unknown"),
            frame.iloc[index].get("notes", ""),
        )
        for index, (value, prediction_id, state) in enumerate(
            zip(supplied_ids, frame["prediction_id"], frame["validated_state"], strict=False)
        )
    ]
    frame["supersedes_validation_id"] = _supersedes_ids(frame)
    if "reviewed_at" not in frame:
        frame["reviewed_at"] = finalized_at.isoformat()
    frame["pipeline_run_id"] = run_id
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
