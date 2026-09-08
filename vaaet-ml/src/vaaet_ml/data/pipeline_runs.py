# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Fachada 4.x para el registro compartido de ejecuciones."""

from __future__ import annotations

from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.settings import MODEL_VERSION, TELEMETRY_SCHEMA_VERSION
from vaaet_persistence.pipeline_runs import (
    PipelineRunHandle,
    PipelineWorkflow,
    finish_pipeline_run,
    pipeline_run,
    start_pipeline_run,
)
from vaaet_persistence.pipeline_runs import (
    PipelineRunMetadata as _PipelineRunMetadata,
)

from vaaet_ml import __version__


class PipelineRunMetadata(_PipelineRunMetadata):
    """Conserva la firma 4.x y agrega la identidad real del laboratorio."""

    def __init__(
        self,
        workflow: PipelineWorkflow,
        git_commit: str | None = None,
        source_kind: str | None = None,
        clip_id: str | None = None,
        input_rows: int | None = None,
        telemetry_schema_version: str | None = TELEMETRY_SCHEMA_VERSION,
        feature_schema_version: str | None = FEATURE_SCHEMA_VERSION,
        model_version: str | None = MODEL_VERSION,
        model_revision: str | None = None,
        *,
        application_name: str = "vaaet-ml",
        application_version: str = __version__,
    ) -> None:
        super().__init__(
            workflow=workflow,
            application_name=application_name,
            application_version=application_version,
            git_commit=git_commit,
            source_kind=source_kind,
            clip_id=clip_id,
            input_rows=input_rows,
            telemetry_schema_version=telemetry_schema_version,
            feature_schema_version=feature_schema_version,
            model_version=model_version,
            model_revision=model_revision,
        )


__all__ = [
    "PipelineRunHandle",
    "PipelineRunMetadata",
    "PipelineWorkflow",
    "finish_pipeline_run",
    "pipeline_run",
    "start_pipeline_run",
]
