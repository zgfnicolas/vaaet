# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Estado local trazable para etapas operacionales de los notebooks."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import UUID, uuid4

import pandas as pd
from vaaet.inference.traffic_state import assert_progressive_batch_parity

_STAGE_NAME = re.compile(r"[a-z][a-z0-9-]{0,63}")


class WorkflowStageStatus(str, Enum):
    """Estados explícitos de una etapa operacional local."""

    NOT_REQUESTED = "not-requested"
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class LocalStageAttempt:
    """Representa un intento inmutable y correlacionado con el procesamiento."""

    attempt_id: UUID
    pipeline_run_id: UUID
    stage: str
    started_at: str
    output_rows: int | None = None

    def set_output_rows(self, rows: int) -> None:
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
            raise ValueError("Stage output_rows must be a non-negative integer.")
        self.output_rows = rows


def publish_verified_classification(
    candidate: pd.DataFrame,
    progressive: Sequence[object],
) -> pd.DataFrame:
    """Publica clasificación únicamente después de comprobar la paridad temporal."""

    assert_progressive_batch_parity(progressive, candidate)
    return candidate.copy()


@contextmanager
def local_stage_attempt(
    directory: str | Path,
    *,
    pipeline_run_id: UUID | str,
    stage: str,
) -> Iterator[LocalStageAttempt]:
    """Registra ``running`` antes del trabajo y conserva el intento al finalizar."""

    normalized_stage = _validated_stage(stage)
    handle = LocalStageAttempt(
        attempt_id=uuid4(),
        pipeline_run_id=UUID(str(pipeline_run_id)),
        stage=normalized_stage,
        started_at=_utc_now(),
    )
    root = Path(directory)
    _write_stage_manifest(root, handle, WorkflowStageStatus.PENDING)
    _write_stage_manifest(root, handle, WorkflowStageStatus.RUNNING)
    try:
        yield handle
    except Exception as error:
        _write_stage_manifest(
            root,
            handle,
            WorkflowStageStatus.FAILED,
            error_category=type(error).__name__,
        )
        raise
    else:
        _write_stage_manifest(root, handle, WorkflowStageStatus.SUCCEEDED)


def record_stage_not_requested(
    directory: str | Path,
    *,
    pipeline_run_id: UUID | str,
    stage: str,
) -> Path:
    """Conserva evidencia explícita de una etapa deshabilitada por configuración."""

    handle = LocalStageAttempt(
        attempt_id=uuid4(),
        pipeline_run_id=UUID(str(pipeline_run_id)),
        stage=_validated_stage(stage),
        started_at=_utc_now(),
        output_rows=0,
    )
    return _write_stage_manifest(Path(directory), handle, WorkflowStageStatus.NOT_REQUESTED)


def _validated_stage(stage: str) -> str:
    if not isinstance(stage, str) or _STAGE_NAME.fullmatch(stage) is None:
        raise ValueError("stage must be a safe non-empty identifier.")
    return stage


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_stage_manifest(
    directory: Path,
    handle: LocalStageAttempt,
    status: WorkflowStageStatus,
    *,
    error_category: str | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / (
        f"{handle.pipeline_run_id}.{handle.stage}.{handle.attempt_id}.json"
    )
    payload = {
        "id": str(handle.attempt_id),
        "pipeline_run_id": str(handle.pipeline_run_id),
        "scope": "workflow-stage",
        "stage": handle.stage,
        "status": status.value,
        "started_at": handle.started_at,
        "completed_at": (
            None
            if status in {WorkflowStageStatus.PENDING, WorkflowStageStatus.RUNNING}
            else _utc_now()
        ),
        "output_rows": handle.output_rows,
        "error_category": error_category,
    }
    if destination.exists():
        previous = json.loads(destination.read_text(encoding="utf-8"))
        allowed_previous = {
            WorkflowStageStatus.RUNNING: {WorkflowStageStatus.PENDING.value},
            WorkflowStageStatus.SUCCEEDED: {WorkflowStageStatus.RUNNING.value},
            WorkflowStageStatus.FAILED: {WorkflowStageStatus.RUNNING.value},
        }.get(status, set())
        if previous.get("status") not in allowed_previous:
            raise RuntimeError("A terminal local stage attempt cannot be overwritten.")
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        json.loads(temporary.read_text(encoding="utf-8"))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


__all__ = [
    "LocalStageAttempt",
    "WorkflowStageStatus",
    "local_stage_attempt",
    "publish_verified_classification",
    "record_stage_not_requested",
]
