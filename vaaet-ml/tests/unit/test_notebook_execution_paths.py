# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Ejecuta las celdas de persistencia sin Colab ni PostgreSQL externo."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.settings import TELEMETRY_SCHEMA_VERSION
from vaaet_persistence import PipelineWorkflow, prepare_persistence_run_metadata

from vaaet_ml.workflow_state import InferenceExecutionState, InferenceExecutionStatus

NOTEBOOK_ROOT = Path(__file__).resolve().parents[2] / "notebooks"


def _cell(path: Path, prefix: str) -> str:
    document = json.loads(path.read_text(encoding="utf-8"))
    matches = [
        "".join(cell["source"])
        for cell in document["cells"]
        if cell["cell_type"] == "code" and "".join(cell["source"]).startswith(prefix)
    ]
    assert len(matches) == 1
    return matches[0]


def _context(captured: list[object], run_id: object) -> dict[str, object]:
    @contextmanager
    def local_stage_attempt(*_args: object, **_kwargs: object):
        yield SimpleNamespace(audit_complete=True, set_output_rows=lambda _rows: None)

    @contextmanager
    def database_engine(_settings: object):
        yield object()

    @contextmanager
    def pipeline_run(metadata: object, **_kwargs: object):
        captured.append(metadata)
        yield SimpleNamespace(
            id=run_id,
            outcome=SimpleNamespace(work_succeeded=True, audit_complete=True),
            set_output_rows=lambda _rows: None,
        )

    return {
        "REPO_ROOT": Path("/tmp/vaaet-test"),
        "GIT_COMMIT": "abc1234",
        "PipelineWorkflow": PipelineWorkflow,
        "prepare_persistence_run_metadata": prepare_persistence_run_metadata,
        "local_stage_attempt": local_stage_attempt,
        "database_engine": database_engine,
        "pipeline_run": pipeline_run,
        "DatabaseProfile": SimpleNamespace(COLLECTION="collection", INFERENCE="inference"),
        "get_optional_database_settings": lambda _profile: object(),
        "inspect_database": lambda *_args: SimpleNamespace(
            server_version="17", ssl_enabled=True, available_schemas=[]
        ),
        "package_version": lambda _name: "4.9.1",
        "print": lambda *_args: None,
    }


def test_collection_cell_registers_exact_raw_input_before_insert() -> None:
    run_id = uuid4()
    captured: list[object] = []
    frame = pd.DataFrame(
        {
            "clip_id": ["clip-a", "clip-a"],
            "telemetry_schema_version": [TELEMETRY_SCHEMA_VERSION] * 2,
        }
    )
    video = Path("/tmp/clip-a.mp4")
    namespace = {
        **_context(captured, run_id),
        "result": SimpleNamespace(telemetry=frame),
        "COLLECTION_PIPELINE_RUN_ID": run_id,
        "PROCESSED_VIDEO_PATH": video.resolve(),
        "VIDEO_PATH": video,
        "WORKFLOW_CONFIG": SimpleNamespace(persist_to_database=True),
        "persist_raw_telemetry": lambda *_args, **_kwargs: 2,
    }
    code = _cell(
        NOTEBOOK_ROOT / "data-collection" / "collect_traffic_telemetry.ipynb",
        "COLLECTION_POSTGRES_DATA_SAVED = False",
    )
    exec(compile(code, "collection-persistence-cell", "exec"), namespace)

    assert len(captured) == 1
    metadata = captured[0]
    assert metadata.workflow is PipelineWorkflow.COLLECTION
    assert metadata.input_rows == 2
    assert metadata.feature_schema_version is None
    assert metadata.model_revision is None
    assert namespace["COLLECTION_POSTGRES_PERSISTENCE_SUCCEEDED"] is True


def test_inference_cell_registers_exact_classified_input_and_revision() -> None:
    run_id = uuid4()
    captured: list[object] = []
    frame = pd.DataFrame(
        {
            "clip_id": ["clip-a"],
            "telemetry_schema_version": [TELEMETRY_SCHEMA_VERSION],
            "feature_schema_version": [FEATURE_SCHEMA_VERSION],
        }
    )
    state = InferenceExecutionState(run_id, "a" * 64)
    state.classified = frame
    state.status = InferenceExecutionStatus.READY
    namespace = {
        **_context(captured, run_id),
        "WORKFLOW_CONFIG": SimpleNamespace(persist_to_database=True),
        "INFERENCE_STATE": state,
        "LOCAL_INFERENCE_RUN_ID": run_id,
        "manifest": {"model_version": "mlp-v3.0"},
        "bundle": SimpleNamespace(model_revision="a" * 64),
        "persist_classified_telemetry": lambda *_args, **_kwargs: SimpleNamespace(
            telemetry_rows=1,
            inserted_telemetry_rows=1,
            inserted_classification_rows=1,
        ),
    }
    code = _cell(
        NOTEBOOK_ROOT / "inference" / "analyze_traffic_video.ipynb",
        "INFERENCE_PIPELINE_RUN_ID = None",
    )
    exec(compile(code, "inference-persistence-cell", "exec"), namespace)

    assert len(captured) == 1
    metadata = captured[0]
    assert metadata.workflow is PipelineWorkflow.INFERENCE
    assert metadata.input_rows == 1
    assert metadata.feature_schema_version == FEATURE_SCHEMA_VERSION
    assert metadata.model_revision == "a" * 64
    assert state.persistence_audit_complete
