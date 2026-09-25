# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Prepara corridas de escritura cuando el conjunto persistible ya es conocido."""

from __future__ import annotations

import pandas as pd

from vaaet_persistence.pipeline_runs import PipelineRunMetadata, PipelineWorkflow


def prepare_persistence_run_metadata(  # noqa: C901 - valida identidad de dos workflows.
    frame: pd.DataFrame,
    *,
    workflow: PipelineWorkflow,
    application_name: str,
    application_version: str,
    git_commit: str | None = None,
    source_kind: str = "video",
    model_version: str | None = None,
    model_revision: str | None = None,
) -> PipelineRunMetadata:
    """Deriva conteos y schemas exactos de un frame destinado a PostgreSQL."""

    if frame.empty or "clip_id" not in frame:
        raise ValueError("A persistence run requires non-empty telemetry with clip IDs.")
    clip_values = [str(value) for value in frame["clip_id"].tolist()]
    if frame["clip_id"].isna().any() or any(not value.strip() for value in clip_values):
        raise ValueError("A persistence run requires a clip ID on every row.")
    clips = set(clip_values)
    if len(clips) != 1:
        raise ValueError("A video persistence run must belong to one clip.")
    if workflow not in {PipelineWorkflow.COLLECTION, PipelineWorkflow.INFERENCE}:
        raise ValueError("Only video data-writing workflows use this preparation API.")

    def schema(column: str) -> str | None:
        if column not in frame or frame[column].isna().any():
            raise ValueError(f"Persistence telemetry requires {column} on every row.")
        values = frame[column].astype(str).unique()
        if len(values) != 1 or not values[0]:
            raise ValueError(f"Persistence telemetry has incompatible {column} values.")
        return str(values[0])

    telemetry_schema = schema("telemetry_schema_version")
    if workflow is PipelineWorkflow.COLLECTION:
        if model_revision is not None or model_version is not None:
            raise ValueError("Raw collection must not declare a model.")
        feature_schema = None
    else:
        feature_schema = schema("feature_schema_version")
        if not model_version or not model_revision:
            raise ValueError("Classified persistence requires the exact model identity.")
    return PipelineRunMetadata(
        workflow=workflow,
        application_name=application_name,
        application_version=application_version,
        git_commit=git_commit,
        source_kind=source_kind,
        clip_id=next(iter(clips)),
        input_rows=len(frame),
        telemetry_schema_version=telemetry_schema,
        feature_schema_version=feature_schema,
        model_version=model_version,
        model_revision=model_revision,
    )


__all__ = ["prepare_persistence_run_metadata"]
