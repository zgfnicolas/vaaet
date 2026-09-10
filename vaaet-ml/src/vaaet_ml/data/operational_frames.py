# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Adapta identidades operacionales PostgreSQL a contratos portables HITL."""

from __future__ import annotations

import pandas as pd

from vaaet_ml.data.artifact_serialization import is_sha256, stable_uuid, valid_uuid


def portable_feedback_components(  # noqa: C901 - adapta tres relaciones contractuales.
    components: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Deriva UUID estables sin cambiar schema, revisión ni procedencia operacional."""

    features = components.get("features", pd.DataFrame()).copy()
    predictions = components.get("predictions", pd.DataFrame()).copy()
    validations = components.get("validations", pd.DataFrame()).copy()
    if features.empty or predictions.empty:
        return {
            **components,
            "features": features,
            "predictions": predictions,
            "validations": validations,
        }

    _require_columns(
        features,
        {"id", "pipeline_run_id", "clip_id", "continuity_id", "record_time", "feature_schema_version"},
        "operational features",
    )
    _require_columns(
        predictions,
        {"id", "pipeline_run_id", "telemetry_feature_id", "model_version", "model_revision"},
        "operational predictions",
    )
    _require_unique_values(features, "id", "operational features")
    _require_unique_values(predictions, "id", "operational predictions")
    if not features["pipeline_run_id"].map(valid_uuid).all():
        raise ValueError("Operational features require UUID pipeline_run_id values.")
    if not predictions["pipeline_run_id"].map(valid_uuid).all():
        raise ValueError("Operational predictions require UUID pipeline_run_id values.")
    if not predictions["model_revision"].map(is_sha256).all():
        raise ValueError("Operational predictions require exact SHA-256 model revisions.")
    if features["feature_schema_version"].isna().any() or features[
        "feature_schema_version"
    ].astype(str).str.strip().eq("").any():
        raise ValueError("Operational features require a declared feature schema.")
    feature_map: dict[str, str] = {}
    portable_feature_ids: list[str] = []
    for row in features.itertuples(index=False):
        source_id = str(row.id)
        portable_id = (
            source_id
            if valid_uuid(source_id)
            else stable_uuid(
                "feature",
                row.pipeline_run_id,
                row.clip_id,
                row.continuity_id,
                row.record_time,
                row.feature_schema_version,
            )
        )
        feature_map[source_id] = portable_id
        portable_feature_ids.append(portable_id)
    features.insert(0, "operational_feature_id", features["id"].astype(str))
    features["id"] = portable_feature_ids

    prediction_map: dict[str, str] = {}
    portable_prediction_ids: list[str] = []
    portable_feature_references: list[str] = []
    for row in predictions.itertuples(index=False):
        source_id = str(row.id)
        feature_id = feature_map.get(str(row.telemetry_feature_id))
        if feature_id is None:
            raise ValueError(
                f"Operational prediction {source_id} references an unknown feature."
            )
        portable_id = (
            source_id
            if valid_uuid(source_id)
            else stable_uuid(
                "prediction",
                row.pipeline_run_id,
                feature_id,
                row.model_revision,
            )
        )
        prediction_map[source_id] = portable_id
        portable_prediction_ids.append(portable_id)
        portable_feature_references.append(feature_id)
    predictions.insert(0, "operational_prediction_id", predictions["id"].astype(str))
    predictions["id"] = portable_prediction_ids
    predictions["telemetry_feature_id"] = portable_feature_references

    if validations.empty:
        return {
            **components,
            "features": features,
            "predictions": predictions,
            "validations": validations,
        }
    _require_columns(
        validations,
        {"id", "prediction_id", "validated_state", "supersedes_validation_id"},
        "operational validations",
    )
    _require_unique_values(validations, "id", "operational validations")
    validations.insert(0, "operational_validation_id", validations["id"].astype(str))
    validations["id"] = validations["id"].map(
        lambda value: str(value)
        if valid_uuid(value)
        else stable_uuid("validation", value)
    )
    validation_map = dict(
        zip(validations["operational_validation_id"], validations["id"], strict=False)
    )
    validations["prediction_id"] = validations["prediction_id"].map(
        lambda value: prediction_map.get(str(value), "")
    )
    if validations["prediction_id"].eq("").any():
        raise ValueError("Operational validations reference predictions outside the snapshot.")
    supplied_parents = validations["supersedes_validation_id"].copy()
    unknown_parents = {
        str(value)
        for value in supplied_parents
        if pd.notna(value) and value and str(value) not in validation_map
    }
    if unknown_parents:
        raise ValueError(
            f"Operational validations reference missing predecessors: {sorted(unknown_parents)}"
        )
    validations["supersedes_validation_id"] = supplied_parents.map(
        lambda value: validation_map[str(value)] if pd.notna(value) and value else pd.NA
    )
    validations["is_human_validated"] = True
    return {**components, "features": features, "predictions": predictions, "validations": validations}


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    if missing := sorted(required - set(frame.columns)):
        raise ValueError(f"{label} are missing fields: {missing}")


def _require_unique_values(frame: pd.DataFrame, column: str, label: str) -> None:
    values = frame[column]
    if values.isna().any() or values.astype(str).str.strip().eq("").any():
        raise ValueError(f"{label} contain missing {column} values.")
    if values.astype(str).duplicated().any():
        raise ValueError(f"{label} contain duplicate {column} values.")


__all__ = ["portable_feedback_components"]
