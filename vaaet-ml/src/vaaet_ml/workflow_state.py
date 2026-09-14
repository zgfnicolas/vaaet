# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Estado local trazable para etapas operacionales de los notebooks."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import UUID, uuid4

import pandas as pd
from vaaet.inference.traffic_state import assert_progressive_batch_parity
from vaaet.logging import get_logger

_STAGE_NAME = re.compile(r"[a-z][a-z0-9-]{0,63}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
logger = get_logger(__name__)


class WorkflowStageStatus(str, Enum):
    """Estados explícitos de una etapa operacional local."""

    NOT_REQUESTED = "not-requested"
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class InferenceExecutionStatus(str, Enum):
    """Estados publicables de un intento de clasificación."""

    CLASSIFYING = "classifying"
    READY = "ready"
    INSUFFICIENT_CONTEXT = "insufficient-context"
    FAILED = "failed"


class StaleInferenceExecutionError(RuntimeError):
    """Indica que una acción pertenece a un intento de inferencia anterior."""


@dataclass
class InferenceExecutionState:
    """Concentra resultado y autorizaciones de un único intento de inferencia."""

    pipeline_run_id: UUID
    model_revision: str
    classified: pd.DataFrame = field(default_factory=pd.DataFrame)
    attempt_id: UUID = field(default_factory=uuid4)
    status: InferenceExecutionStatus = InferenceExecutionStatus.CLASSIFYING
    persistence_status: WorkflowStageStatus = WorkflowStageStatus.NOT_REQUESTED
    persistence_audit_complete: bool = False

    def __post_init__(self) -> None:
        self.pipeline_run_id = UUID(str(self.pipeline_run_id))
        if _SHA256.fullmatch(self.model_revision) is None:
            raise ValueError("model_revision must be a lowercase SHA-256 value.")
        self.classified = self.classified.iloc[0:0].copy()

    def publish(self, candidate: pd.DataFrame, progressive: Sequence[object]) -> pd.DataFrame:
        if self.status is not InferenceExecutionStatus.CLASSIFYING:
            raise RuntimeError("Inference classification has already reached a terminal state.")
        try:
            published = publish_verified_classification(candidate, progressive)
        except Exception:
            self.fail()
            raise
        self.classified = published
        self.status = (
            InferenceExecutionStatus.INSUFFICIENT_CONTEXT
            if published.empty
            else InferenceExecutionStatus.READY
        )
        return self.classified

    def publish_insufficient_context(self) -> pd.DataFrame:
        if self.status is not InferenceExecutionStatus.CLASSIFYING:
            raise RuntimeError("Inference classification has already reached a terminal state.")
        self.status = InferenceExecutionStatus.INSUFFICIENT_CONTEXT
        return self.classified

    def fail(self) -> None:
        self.classified = self.classified.iloc[0:0].copy()
        self.status = InferenceExecutionStatus.FAILED
        self.persistence_status = WorkflowStageStatus.NOT_REQUESTED
        self.persistence_audit_complete = False

    @property
    def can_persist(self) -> bool:
        return self.status is InferenceExecutionStatus.READY and not self.classified.empty

    def begin_persistence(self) -> None:
        if not self.can_persist:
            raise RuntimeError("Only a verified current classification may be persisted.")
        self.persistence_status = WorkflowStageStatus.RUNNING
        self.persistence_audit_complete = False

    def complete_persistence(self, *, audit_complete: bool) -> None:
        if self.persistence_status is not WorkflowStageStatus.RUNNING:
            raise RuntimeError("Persistence is not running for this inference attempt.")
        self.persistence_status = WorkflowStageStatus.SUCCEEDED
        self.persistence_audit_complete = bool(audit_complete)

    def fail_persistence(self) -> None:
        self.persistence_status = WorkflowStageStatus.FAILED
        self.persistence_audit_complete = False

    def can_review(self, *, require_persistence: bool) -> bool:
        if not self.can_persist:
            return False
        return not require_persistence or (
            self.persistence_status is WorkflowStageStatus.SUCCEEDED
            and self.persistence_audit_complete
        )

    def require_attempt(self, attempt_id: UUID | str) -> None:
        if self.attempt_id != UUID(str(attempt_id)):
            raise StaleInferenceExecutionError(
                "This action belongs to an earlier inference attempt."
            )


@dataclass
class LocalStageAttempt:
    """Representa un intento inmutable y correlacionado con el procesamiento."""

    attempt_id: UUID
    pipeline_run_id: UUID
    stage: str
    started_at: str
    output_rows: int | None = None
    audit_complete: bool = False

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
        try:
            _write_stage_manifest(
                root,
                handle,
                WorkflowStageStatus.FAILED,
                error_category=type(error).__name__,
            )
            handle.audit_complete = True
        except Exception as audit_error:
            logger.warning(
                "Workflow stage failure audit could not be finalized: %s",
                type(audit_error).__name__,
            )
        raise
    else:
        try:
            _write_stage_manifest(root, handle, WorkflowStageStatus.SUCCEEDED)
            handle.audit_complete = True
        except Exception as audit_error:
            handle.audit_complete = False
            logger.warning(
                "Successful workflow stage audit is incomplete: %s",
                type(audit_error).__name__,
            )


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
    destination = directory / (f"{handle.pipeline_run_id}.{handle.stage}.{handle.attempt_id}.json")
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
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            logger.warning("Temporary workflow stage manifest cleanup failed: OSError")
    return destination


__all__ = [
    "InferenceExecutionState",
    "InferenceExecutionStatus",
    "LocalStageAttempt",
    "StaleInferenceExecutionError",
    "WorkflowStageStatus",
    "local_stage_attempt",
    "publish_verified_classification",
    "record_stage_not_requested",
]
