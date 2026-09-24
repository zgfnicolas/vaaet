# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Registros redactados y neutrales de proveedor para el ciclo de los workflows."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.logging import get_logger
from vaaet.settings import MODEL_VERSION, TELEMETRY_SCHEMA_VERSION

from vaaet_persistence.connection import require_database_revision
from vaaet_persistence.exceptions import (
    DatabaseOperationError,
    PersistenceConflictError,
    safe_sqlstate,
)

logger = get_logger(__name__)
_APPLICATION_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")

_START_RUN_SQL = """
SELECT vaaet_ops.start_pipeline_run(
    CAST(:id AS UUID), :workflow, :application_name, :application_version, :git_commit,
    :telemetry_schema_version, :feature_schema_version, :model_version,
    :model_revision, :source_kind, :clip_id, :input_rows
)
"""

_FINISH_RUN_SQL = """
SELECT vaaet_ops.finish_pipeline_run(
    CAST(:id AS UUID), :status, :output_rows, :error_category, :model_revision
)
"""

_COMPLETE_RECONCILIATION_SQL = """
SELECT vaaet_ops.complete_verified_reconciliation(
    CAST(:original_run_id AS UUID), CAST(:reconciliation_run_id AS UUID),
    :application_version, :operation, :content_fingerprint,
    :output_rows, :model_revision
)
"""


class PipelineWorkflow(str, Enum):
    """Identifica el workflow propietario de una corrida trazable."""

    COLLECTION = "collection"
    INFERENCE = "inference"
    TRAINING = "training"
    REVIEW = "review"


@dataclass(frozen=True)
class PipelineRunMetadata:
    """Representa metadata segura y portable para iniciar una corrida."""

    workflow: PipelineWorkflow
    application_name: str
    application_version: str
    git_commit: str | None = None
    source_kind: str | None = None
    clip_id: str | None = None
    input_rows: int | None = None
    telemetry_schema_version: str | None = TELEMETRY_SCHEMA_VERSION
    feature_schema_version: str | None = FEATURE_SCHEMA_VERSION
    model_version: str | None = MODEL_VERSION
    model_revision: str | None = None

    def __post_init__(self) -> None:
        if (
            _APPLICATION_COMPONENT.fullmatch(self.application_name) is None
            or _APPLICATION_COMPONENT.fullmatch(self.application_version) is None
        ):
            raise ValueError(
                "Pipeline runs require safe application_name and application_version identifiers."
            )
        if self.input_rows is not None and (
            isinstance(self.input_rows, bool)
            or not isinstance(self.input_rows, int)
            or self.input_rows < 0
        ):
            raise ValueError("Pipeline input_rows must be a non-negative integer.")
        if self.git_commit is not None and not re.fullmatch(r"[0-9a-fA-F]{7,40}", self.git_commit):
            raise ValueError("git_commit must be a 7-40 character hexadecimal revision.")
        if self.model_revision is not None and not re.fullmatch(
            r"[0-9a-f]{64}", self.model_revision
        ):
            raise ValueError("model_revision must be a lowercase SHA-256 value.")
        for value, label in (
            (self.git_commit, "git_commit"),
            (self.source_kind, "source_kind"),
            (self.clip_id, "clip_id"),
            (self.model_revision, "model_revision"),
        ):
            if value is not None and any(token in value.lower() for token in ("password=", "://")):
                raise ValueError(f"{label} may not contain credentials or a connection URL.")
            if (
                value is not None
                and label in {"source_kind", "clip_id"}
                and any(separator in value for separator in ("/", "\\"))
            ):
                raise ValueError(f"{label} must be an identifier, not a filesystem path.")


@dataclass
class PipelineRunHandle:
    """Conserva el identificador y el conteo final durante una corrida activa."""

    id: UUID
    metadata: PipelineRunMetadata
    output_rows: int | None = None
    model_revision: str | None = None
    outcome: PipelineRunOutcome | None = field(default=None, init=False)

    def set_output_rows(self, rows: int) -> None:
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
            raise ValueError("Pipeline output_rows must be a non-negative integer.")
        self.output_rows = rows

    def set_model_revision(self, revision: str) -> None:
        """Asocia el bundle exacto recién validado antes de cerrar la corrida."""

        if not re.fullmatch(r"[0-9a-f]{64}", revision):
            raise ValueError("model_revision must be a lowercase SHA-256 value.")
        self.model_revision = revision

    def set_outcome(
        self,
        *,
        work_succeeded: bool,
        audit_complete: bool,
        audit_error_category: str | None = None,
    ) -> None:
        """Publica una sola conclusión segura del trabajo y su auditoría."""

        self.outcome = PipelineRunOutcome(
            run_id=self.id,
            work_succeeded=work_succeeded,
            audit_complete=audit_complete,
            output_rows=self.output_rows,
            model_revision=self.model_revision,
            audit_error_category=audit_error_category,
        )


@dataclass(frozen=True)
class PipelineRunOutcome:
    """Distingue el resultado confirmado del workflow de su cierre auditable."""

    run_id: UUID
    work_succeeded: bool
    audit_complete: bool
    output_rows: int | None
    model_revision: str | None
    audit_error_category: str | None = None
    reconciliation_run_id: UUID | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_payload(
    handle: PipelineRunHandle,
    *,
    status: str,
    started_at: str,
    error_category: str | None,
) -> dict[str, object]:
    metadata = asdict(handle.metadata)
    metadata["workflow"] = handle.metadata.workflow.value
    metadata["model_revision"] = handle.model_revision
    return {
        "id": str(handle.id),
        "scope": "workflow-processing",
        "status": status,
        "started_at": started_at,
        "completed_at": _utc_now() if status != "running" else None,
        "output_rows": handle.output_rows,
        "error_category": error_category,
        **metadata,
    }


def _write_local_manifest(directory: Path, payload: dict[str, object]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{payload['id']}.json"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        if existing.get("status") in {"succeeded", "failed"}:
            stable_existing = {
                key: value for key, value in existing.items() if key != "completed_at"
            }
            stable_payload = {key: value for key, value in payload.items() if key != "completed_at"}
            if stable_payload == stable_existing:
                return destination
            raise RuntimeError("A terminal local pipeline manifest cannot be overwritten.")
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


def start_pipeline_run(
    metadata: PipelineRunMetadata,
    *,
    engine: Engine | None = None,
    local_manifest_directory: str | Path | None = None,
    run_id: UUID | str | None = None,
) -> tuple[PipelineRunHandle, str]:
    """Inicia una corrida con ID opcional para sellar inputs antes del cómputo."""

    handle = PipelineRunHandle(
        UUID(str(run_id)) if run_id is not None else uuid4(),
        metadata,
        model_revision=metadata.model_revision,
    )
    started_at = _utc_now()
    if engine is not None:
        payload = {
            "id": str(handle.id),
            "workflow": metadata.workflow.value,
            "application_name": metadata.application_name,
            "application_version": metadata.application_version,
            "git_commit": metadata.git_commit,
            "telemetry_schema_version": metadata.telemetry_schema_version,
            "feature_schema_version": metadata.feature_schema_version,
            "model_version": metadata.model_version,
            "model_revision": metadata.model_revision,
            "source_kind": metadata.source_kind,
            "clip_id": metadata.clip_id,
            "input_rows": metadata.input_rows,
        }
        try:
            with engine.begin() as connection:
                require_database_revision(connection)
                connection.execute(text(_START_RUN_SQL), payload).scalar_one()
        except SQLAlchemyError as exc:
            _raise_pipeline_database_error(exc, operation="start-pipeline-run", run_id=handle.id)
    elif local_manifest_directory is None:
        raise ValueError("A local manifest directory is required when PostgreSQL is unavailable.")
    else:
        _write_local_manifest(
            Path(local_manifest_directory),
            _local_payload(
                handle,
                status="running",
                started_at=started_at,
                error_category=None,
            ),
        )
    return handle, started_at


def finish_pipeline_run(
    handle: PipelineRunHandle,
    *,
    status: str,
    started_at: str,
    engine: Engine | None = None,
    local_manifest_directory: str | Path | None = None,
    error_category: str | None = None,
) -> Path | None:
    """Finaliza una corrida sin persistir excepciones ni metadata arbitraria."""
    if status not in {"succeeded", "failed"}:
        raise ValueError("Final pipeline status must be succeeded or failed.")
    if status == "succeeded":
        error_category = None
    if engine is not None:
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(_FINISH_RUN_SQL),
                    {
                        "id": str(handle.id),
                        "status": status,
                        "output_rows": handle.output_rows,
                        "error_category": error_category,
                        "model_revision": handle.model_revision,
                    },
                )
        except SQLAlchemyError as exc:
            _raise_pipeline_database_error(exc, operation="finish-pipeline-run", run_id=handle.id)
        return None
    if local_manifest_directory is None:
        raise ValueError("A local manifest directory is required when PostgreSQL is unavailable.")
    return _write_local_manifest(
        Path(local_manifest_directory),
        _local_payload(
            handle,
            status=status,
            started_at=started_at,
            error_category=error_category,
        ),
    )


def finalize_pipeline_run_outcome(
    handle: PipelineRunHandle,
    *,
    work_succeeded: bool,
    started_at: str,
    engine: Engine | None = None,
    local_manifest_directory: str | Path | None = None,
    error_category: str | None = None,
) -> PipelineRunOutcome:
    """Cierra la auditoría sin convertir su fallo en un fallo del trabajo confirmado."""

    try:
        finish_pipeline_run(
            handle,
            status="succeeded" if work_succeeded else "failed",
            started_at=started_at,
            engine=engine,
            local_manifest_directory=local_manifest_directory,
            error_category=error_category,
        )
        handle.set_outcome(work_succeeded=work_succeeded, audit_complete=True)
    except Exception as audit_error:
        handle.set_outcome(
            work_succeeded=work_succeeded,
            audit_complete=False,
            audit_error_category=type(audit_error).__name__,
        )
        logger.warning(
            "%s pipeline run audit is incomplete: %s",
            "Successful" if work_succeeded else "Failed",
            type(audit_error).__name__,
        )
    assert handle.outcome is not None
    return handle.outcome


@contextmanager
def pipeline_run(
    metadata: PipelineRunMetadata,
    *,
    engine: Engine | None = None,
    local_manifest_directory: str | Path | None = None,
    run_id: UUID | str | None = None,
) -> Iterator[PipelineRunHandle]:
    """Registra el ciclo completo y vuelve a propagar el fallo original."""
    handle, started_at = start_pipeline_run(
        metadata,
        engine=engine,
        local_manifest_directory=local_manifest_directory,
        run_id=run_id,
    )
    try:
        yield handle
    except Exception as error:
        finalize_pipeline_run_outcome(
            handle,
            work_succeeded=False,
            started_at=started_at,
            engine=engine,
            local_manifest_directory=local_manifest_directory,
            error_category=type(error).__name__,
        )
        raise
    else:
        finalize_pipeline_run_outcome(
            handle,
            work_succeeded=True,
            started_at=started_at,
            engine=engine,
            local_manifest_directory=local_manifest_directory,
        )


def complete_reconciled_pipeline_run(
    *,
    run_id: UUID | str,
    output_rows: int,
    engine: Engine,
    workflow: PipelineWorkflow,
    application_version: str,
    operation: str,
    content_fingerprint: str,
    model_revision: str | None = None,
    connection: Connection | None = None,
) -> PipelineRunOutcome:
    """Completa una corrida sólo mediante su comprobante transaccional exacto."""

    original_id = UUID(str(run_id))
    if workflow.value not in {"collection", "inference", "review"}:
        raise ValueError("Only data-writing workflows may reconcile persistence receipts.")
    if len(content_fingerprint) != 64:
        raise ValueError("Reconciliation requires an exact receipt fingerprint.")
    reconciliation_id = uuid5(
        NAMESPACE_URL,
        f"vaaet:persistence-reconciliation:{original_id}:{content_fingerprint}",
    )
    payload = {
        "original_run_id": str(original_id),
        "reconciliation_run_id": str(reconciliation_id),
        "application_version": application_version,
        "operation": operation,
        "content_fingerprint": content_fingerprint,
        "output_rows": output_rows,
        "model_revision": model_revision,
    }
    resolved: object = original_id
    try:
        if connection is not None:
            require_database_revision(connection)
            resolved = connection.execute(text(_COMPLETE_RECONCILIATION_SQL), payload).scalar_one()
        else:
            with engine.begin() as owned_connection:
                require_database_revision(owned_connection)
                resolved = owned_connection.execute(
                    text(_COMPLETE_RECONCILIATION_SQL), payload
                ).scalar_one()
    except SQLAlchemyError as error:
        _raise_pipeline_database_error(
            error,
            operation="complete-verified-reconciliation",
            run_id=original_id,
        )
    resolved_id = UUID(str(resolved))
    return PipelineRunOutcome(
        run_id=original_id,
        work_succeeded=True,
        audit_complete=True,
        output_rows=output_rows,
        model_revision=model_revision,
        reconciliation_run_id=(
            None if resolved_id == original_id else resolved_id
        ),
    )


def _raise_pipeline_database_error(
    error: SQLAlchemyError,
    *,
    operation: str,
    run_id: UUID,
) -> None:
    sqlstate = safe_sqlstate(error)
    if sqlstate == "23505":
        raise PersistenceConflictError("Immutable pipeline run conflict.") from None
    raise DatabaseOperationError(
        "PostgreSQL pipeline lineage operation failed.",
        operation=operation,
        sqlstate=sqlstate,
        run_id=str(run_id),
    ) from None


__all__ = [
    "PipelineRunHandle",
    "PipelineRunMetadata",
    "PipelineRunOutcome",
    "PipelineWorkflow",
    "complete_reconciled_pipeline_run",
    "finalize_pipeline_run_outcome",
    "finish_pipeline_run",
    "pipeline_run",
    "start_pipeline_run",
]
