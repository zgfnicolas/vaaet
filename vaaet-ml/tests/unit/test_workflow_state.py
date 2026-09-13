# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pandas as pd
import pytest

from vaaet_ml.workflow_state import (
    WorkflowStageStatus,
    local_stage_attempt,
    publish_verified_classification,
    record_stage_not_requested,
)


def test_stage_attempt_transitions_pending_running_succeeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vaaet_ml import workflow_state

    statuses: list[WorkflowStageStatus] = []
    original = workflow_state._write_stage_manifest

    def capture(*args, **kwargs):
        statuses.append(args[2])
        return original(*args, **kwargs)

    monkeypatch.setattr(workflow_state, "_write_stage_manifest", capture)
    with local_stage_attempt(tmp_path, pipeline_run_id=uuid.uuid4(), stage="persistence"):
        pass

    assert statuses == [
        WorkflowStageStatus.PENDING,
        WorkflowStageStatus.RUNNING,
        WorkflowStageStatus.SUCCEEDED,
    ]


def test_stage_attempt_preserves_running_then_success(tmp_path: Path) -> None:
    run_id = uuid.uuid4()
    with local_stage_attempt(tmp_path, pipeline_run_id=run_id, stage="persistence") as attempt:
        path = next(tmp_path.glob("*.json"))
        assert json.loads(path.read_text(encoding="utf-8"))["status"] == "running"
        attempt.set_output_rows(3)

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["status"] == "succeeded"
    assert document["output_rows"] == 3
    assert document["pipeline_run_id"] == str(run_id)


def test_stage_attempt_records_failure_without_hiding_it(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="primary"):
        with local_stage_attempt(
            tmp_path, pipeline_run_id=uuid.uuid4(), stage="persistence"
        ):
            raise RuntimeError("primary")

    document = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert document["status"] == "failed"
    assert document["error_category"] == "RuntimeError"


def test_interruption_before_work_leaves_pending_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vaaet_ml import workflow_state

    original = workflow_state._write_stage_manifest

    def interrupt(directory, handle, status, **kwargs):
        if status is WorkflowStageStatus.RUNNING:
            raise KeyboardInterrupt
        return original(directory, handle, status, **kwargs)

    monkeypatch.setattr(workflow_state, "_write_stage_manifest", interrupt)
    with pytest.raises(KeyboardInterrupt):
        with local_stage_attempt(
            tmp_path, pipeline_run_id=uuid.uuid4(), stage="persistence"
        ):
            pass

    document = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert document["status"] == "pending"
    assert document["completed_at"] is None


def test_not_requested_creates_separate_attempts(tmp_path: Path) -> None:
    run_id = uuid.uuid4()
    first = record_stage_not_requested(tmp_path, pipeline_run_id=run_id, stage="persistence")
    second = record_stage_not_requested(tmp_path, pipeline_run_id=run_id, stage="persistence")

    assert first != second
    assert json.loads(first.read_text(encoding="utf-8"))["status"] == "not-requested"


def test_classification_is_not_published_when_parity_fails(monkeypatch) -> None:
    candidate = pd.DataFrame({"traffic_state": [0]})

    def fail(*_args: object) -> None:
        raise ValueError("parity")

    monkeypatch.setattr("vaaet_ml.workflow_state.assert_progressive_batch_parity", fail)
    with pytest.raises(ValueError, match="parity"):
        publish_verified_classification(candidate, [])
