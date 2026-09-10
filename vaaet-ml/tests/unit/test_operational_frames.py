# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Adaptación verificable de IDs PostgreSQL a relaciones portables."""

from __future__ import annotations

from uuid import uuid4

import pandas as pd
import pytest
from vaaet.artifacts import FEATURE_SCHEMA_VERSION

from vaaet_ml.data.artifact_serialization import valid_uuid
from vaaet_ml.data.operational_frames import portable_feedback_components


def _components() -> dict[str, pd.DataFrame]:
    first_run = str(uuid4())
    second_run = str(uuid4())
    validation_id = str(uuid4())
    features = pd.DataFrame(
        [
            {
                "id": 20,
                "pipeline_run_id": second_run,
                "clip_id": "clip-b",
                "continuity_id": "clip-b:continuity-1",
                "record_time": "2026-09-09T12:01:00Z",
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "numeric_representation": "float64",
            },
            {
                "id": 10,
                "pipeline_run_id": first_run,
                "clip_id": "clip-a",
                "continuity_id": "clip-a:continuity-1",
                "record_time": "2026-09-09T12:00:00Z",
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "numeric_representation": "float64",
            },
        ]
    )
    predictions = pd.DataFrame(
        [
            {
                "id": 100,
                "pipeline_run_id": first_run,
                "telemetry_feature_id": 10,
                "model_version": "mlp-v3.0",
                "model_revision": "a" * 64,
                "numeric_representation": "float64",
            },
            {
                "id": 200,
                "pipeline_run_id": second_run,
                "telemetry_feature_id": 20,
                "model_version": "mlp-v3.0",
                "model_revision": "b" * 64,
                "numeric_representation": "float64",
            },
        ]
    )
    validations = pd.DataFrame(
        [
            {
                "id": validation_id,
                "prediction_id": 200,
                "validated_state": 2,
                "supersedes_validation_id": pd.NA,
                "is_human_validated": True,
            }
        ]
    )
    return {"features": features, "predictions": predictions, "validations": validations}


def test_operational_relations_are_resolved_by_keys_not_row_position() -> None:
    portable = portable_feedback_components(_components())
    features = portable["features"].set_index("operational_feature_id")
    predictions = portable["predictions"].set_index("operational_prediction_id")
    validation = portable["validations"].iloc[0]

    assert valid_uuid(features.loc["10", "id"])
    assert valid_uuid(features.loc["20", "id"])
    assert predictions.loc["100", "telemetry_feature_id"] == features.loc["10", "id"]
    assert predictions.loc["200", "telemetry_feature_id"] == features.loc["20", "id"]
    assert validation["prediction_id"] == predictions.loc["200", "id"]
    assert validation["operational_validation_id"] == validation["id"]


def test_operational_adapter_rejects_invalid_revision_and_duplicate_ids() -> None:
    components = _components()
    components["predictions"].loc[0, "model_revision"] = "not-a-revision"
    with pytest.raises(ValueError, match="SHA-256"):
        portable_feedback_components(components)

    components = _components()
    components["features"].loc[1, "id"] = components["features"].loc[0, "id"]
    with pytest.raises(ValueError, match="duplicate id"):
        portable_feedback_components(components)
