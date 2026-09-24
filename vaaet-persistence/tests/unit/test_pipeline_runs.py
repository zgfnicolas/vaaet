# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for redacted pipeline lifecycle records."""

from __future__ import annotations

import json
from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from vaaet_persistence.pipeline_runs import (
    PipelineRunMetadata,
    PipelineWorkflow,
    complete_reconciled_pipeline_run,
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
    assert run.outcome is not None
    assert run.outcome.work_succeeded
    assert run.outcome.audit_complete


def test_successful_work_survives_audit_close_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    completed: list[str] = []

    def fail_finish(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("audit storage unavailable")

    monkeypatch.setattr("vaaet_persistence.pipeline_runs.finish_pipeline_run", fail_finish)
    with pipeline_run(
        PipelineRunMetadata(
            workflow=PipelineWorkflow.INFERENCE,
            application_name="test-consumer",
            application_version="1.0.0",
        ),
        local_manifest_directory=tmp_path,
    ) as run:
        completed.append("written")
        run.set_output_rows(1)

    assert completed == ["written"]
    assert run.outcome is not None
    assert run.outcome.work_succeeded
    assert not run.outcome.audit_complete
    assert run.outcome.audit_error_category == "RuntimeError"


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


@pytest.mark.parametrize("rows", [True, 1.5, -1])
def test_pipeline_run_rejects_non_integer_output_counts(tmp_path, rows: object) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        with pipeline_run(
            PipelineRunMetadata(
                workflow=PipelineWorkflow.TRAINING,
                application_name="test-consumer",
                application_version="1.0.0",
            ),
            local_manifest_directory=tmp_path,
        ) as run:
            run.set_output_rows(rows)  # type: ignore[arg-type]


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


@pytest.mark.parametrize("rows", [True, 1.5, -1])
def test_pipeline_metadata_rejects_non_integer_input_counts(rows: object) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        PipelineRunMetadata(
            workflow=PipelineWorkflow.TRAINING,
            application_name="test-consumer",
            application_version="1.0.0",
            input_rows=rows,  # type: ignore[arg-type]
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


def test_reconciliation_closes_original_and_records_a_separate_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_id = uuid4()
    executed: list[dict[str, object]] = []

    class Result:
        def scalar_one(self):
            return executed[-1]["reconciliation_run_id"]

    class Connection:
        def execute(self, _statement, payload):
            executed.append(payload)
            return Result()

    class Engine:
        @contextmanager
        def begin(self):
            yield Connection()

    monkeypatch.setattr(
        "vaaet_persistence.pipeline_runs.require_database_revision", lambda _connection: None
    )

    outcome = complete_reconciled_pipeline_run(
        run_id=original_id,
        output_rows=3,
        engine=Engine(),  # type: ignore[arg-type]
        workflow=PipelineWorkflow.COLLECTION,
        application_version="0.3.0",
        operation="raw-telemetry",
        content_fingerprint="a" * 64,
    )

    assert outcome.audit_complete
    assert outcome.run_id == original_id
    assert outcome.reconciliation_run_id is not None
    assert outcome.reconciliation_run_id != original_id
    assert len(executed) == 1
    assert executed[0]["original_run_id"] == str(original_id)


def test_failed_reconciliation_propagates_a_safe_domain_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_id = uuid4()

    class Connection:
        def execute(self, _statement, _payload):
            raise SQLAlchemyError("private driver detail")

    class Engine:
        @contextmanager
        def begin(self):
            yield Connection()

    monkeypatch.setattr(
        "vaaet_persistence.pipeline_runs.require_database_revision", lambda _connection: None
    )
    with pytest.raises(Exception, match="pipeline lineage") as captured:
        complete_reconciled_pipeline_run(
            run_id=original_id,
            output_rows=3,
            engine=Engine(),  # type: ignore[arg-type]
            workflow=PipelineWorkflow.INFERENCE,
            application_version="0.3.0",
            operation="classified-telemetry",
            content_fingerprint="b" * 64,
            model_revision="c" * 64,
        )
    assert "private driver detail" not in str(captured.value)
