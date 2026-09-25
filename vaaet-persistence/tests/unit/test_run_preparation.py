# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Metadata de escritura derivada de observaciones contractuales reales."""

import pandas as pd
import pytest

from vaaet_persistence.pipeline_runs import PipelineWorkflow
from vaaet_persistence.run_preparation import prepare_persistence_run_metadata


@pytest.mark.parametrize("workflow", [PipelineWorkflow.COLLECTION, PipelineWorkflow.INFERENCE])
def test_prepared_video_run_has_reconcilable_identity(workflow: PipelineWorkflow) -> None:
    frame = pd.DataFrame(
        [
            {
                "clip_id": "clip-a",
                "telemetry_schema_version": "traffic-telemetry-v3",
                "feature_schema_version": "traffic-features-v3",
            }
        ]
        * 2
    )
    classified = workflow is PipelineWorkflow.INFERENCE
    metadata = prepare_persistence_run_metadata(
        frame,
        workflow=workflow,
        application_name="test-video",
        application_version="4.9.1",
        model_version="mlp-v3.0" if classified else None,
        model_revision="a" * 64 if classified else None,
    )
    assert metadata.input_rows == 2
    assert metadata.clip_id == "clip-a"
    assert metadata.telemetry_schema_version == "traffic-telemetry-v3"
    assert metadata.feature_schema_version == ("traffic-features-v3" if classified else None)
    assert metadata.model_revision == ("a" * 64 if classified else None)


def test_preparation_rejects_mixed_clips_before_starting_a_run() -> None:
    frame = pd.DataFrame(
        [
            {"clip_id": "a", "telemetry_schema_version": "traffic-telemetry-v3"},
            {"clip_id": "b", "telemetry_schema_version": "traffic-telemetry-v3"},
        ]
    )
    with pytest.raises(ValueError, match="one clip"):
        prepare_persistence_run_metadata(
            frame,
            workflow=PipelineWorkflow.COLLECTION,
            application_name="test-video",
            application_version="4.9.1",
        )
