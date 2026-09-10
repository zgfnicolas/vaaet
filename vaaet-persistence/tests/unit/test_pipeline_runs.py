# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for redacted pipeline lifecycle records."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from vaaet_persistence.pipeline_runs import (
    PipelineRunMetadata,
    PipelineWorkflow,
    pipeline_run,
)


def test_local_pipeline_run_records_success_without_arbitrary_metadata(tmp_path) -> None:
    metadata = PipelineRunMetadata(
        workflow=PipelineWorkflow.COLLECTION,
        application_name="test-consumer",
        application_version="1.0.0",
        git_commit="abc1234",
        source_kind="video",
        clip_id="bridge-test",
        input_rows=1,
        model_version=None,
        feature_schema_version=None,
    )

    with pipeline_run(metadata, local_manifest_directory=tmp_path) as run:
        running = json.loads((tmp_path / f"{run.id}.json").read_text(encoding="utf-8"))
        assert running["status"] == "running"
        assert running["completed_at"] is None
        run.set_output_rows(12)

    payload = json.loads((tmp_path / f"{run.id}.json").read_text(encoding="utf-8"))
    assert payload["status"] == "succeeded"
    assert payload["workflow"] == "collection"
    assert payload["output_rows"] == 12
    assert "password" not in json.dumps(payload).lower()


def test_pipeline_run_preserves_a_preallocated_training_identifier(tmp_path) -> None:
    run_id = uuid4()

    with pipeline_run(
        PipelineRunMetadata(
            workflow=PipelineWorkflow.TRAINING,
            application_name="test-consumer",
            application_version="1.0.0",
        ),
        local_manifest_directory=tmp_path,
        run_id=run_id,
    ) as run:
        pass

    assert run.id == run_id
    assert (tmp_path / f"{run_id}.json").is_file()


def test_training_run_records_revision_resolved_after_bundle_validation(tmp_path) -> None:
    revision = "a" * 64

    with pipeline_run(
        PipelineRunMetadata(
            workflow=PipelineWorkflow.TRAINING,
            application_name="test-consumer",
            application_version="1.0.0",
        ),
        local_manifest_directory=tmp_path,
    ) as run:
        run.set_model_revision(revision)

    payload = json.loads((tmp_path / f"{run.id}.json").read_text(encoding="utf-8"))
    assert payload["model_revision"] == revision


def test_local_pipeline_run_records_only_exception_category(tmp_path) -> None:
    metadata = PipelineRunMetadata(
        workflow=PipelineWorkflow.INFERENCE,
        application_name="test-consumer",
        application_version="1.0.0",
    )

    with pytest.raises(RuntimeError, match="sensitive detail"):
        with pipeline_run(metadata, local_manifest_directory=tmp_path) as run:
            raise RuntimeError("sensitive detail")

    payload = json.loads((tmp_path / f"{run.id}.json").read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["error_category"] == "RuntimeError"
    assert "sensitive detail" not in json.dumps(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_kind", "postgresql://user:secret@host/db"),
        ("clip_id", "password=secret"),
        ("clip_id", "C:\\private\\clip"),
    ],
)
def test_pipeline_metadata_rejects_connection_material(field, value) -> None:
    arguments = {
        "workflow": PipelineWorkflow.TRAINING,
        "application_name": "test-consumer",
        "application_version": "1.0.0",
        field: value,
    }
    with pytest.raises(ValueError, match="credentials|filesystem path"):
        PipelineRunMetadata(**arguments)


def test_pipeline_metadata_rejects_unsafe_application_identity() -> None:
    with pytest.raises(ValueError, match="safe application_name"):
        PipelineRunMetadata(
            PipelineWorkflow.INFERENCE,
            "postgresql://private",
            "1.0.0",
        )


def test_local_fallback_requires_explicit_destination() -> None:
    with pytest.raises(ValueError, match="local manifest directory"):
        with pipeline_run(
            PipelineRunMetadata(
                PipelineWorkflow.TRAINING,
                "test-consumer",
                "1.0.0",
            )
        ):
            pass
