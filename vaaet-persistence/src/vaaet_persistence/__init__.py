# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Persistencia PostgreSQL compartida por consumidores VAAET."""

from vaaet_persistence.connection import (
    DatabaseHealth,
    create_admin_engine,
    database_engine,
    get_engine,
    inspect_database,
    test_connection,
)
from vaaet_persistence.constants import DATABASE_SCHEMA_VERSION, DATABASE_SCHEMAS
from vaaet_persistence.exceptions import DatabaseNotConfiguredError, DatabaseOperationError
from vaaet_persistence.persistence import (
    PersistResult,
    persist_classified_telemetry,
    persist_raw_telemetry,
)
from vaaet_persistence.pipeline_runs import (
    PipelineRunHandle,
    PipelineRunMetadata,
    PipelineWorkflow,
    finish_pipeline_run,
    pipeline_run,
    start_pipeline_run,
)
from vaaet_persistence.queries import (
    load_human_feedback_components,
    load_human_ground_truth,
    load_telemetry,
    load_telemetry_window,
)
from vaaet_persistence.review_domain import HumanValidation, InferenceReviewSession
from vaaet_persistence.review_persistence import load_review_queue, persist_human_validation
from vaaet_persistence.settings import (
    DatabaseAdminSettings,
    DatabaseEndpointSettings,
    DatabasePoolSettings,
    DatabaseProfile,
    DatabaseRetrySettings,
    DatabaseSettings,
    get_optional_database_settings,
    load_database_admin_settings,
    load_database_settings,
    load_reviewer_id,
)

__version__ = "0.1.0"

__all__ = [
    "DATABASE_SCHEMAS",
    "DATABASE_SCHEMA_VERSION",
    "DatabaseAdminSettings",
    "DatabaseEndpointSettings",
    "DatabaseHealth",
    "DatabaseNotConfiguredError",
    "DatabaseOperationError",
    "DatabasePoolSettings",
    "DatabaseProfile",
    "DatabaseRetrySettings",
    "DatabaseSettings",
    "HumanValidation",
    "InferenceReviewSession",
    "PersistResult",
    "PipelineRunHandle",
    "PipelineRunMetadata",
    "PipelineWorkflow",
    "create_admin_engine",
    "database_engine",
    "finish_pipeline_run",
    "get_engine",
    "get_optional_database_settings",
    "inspect_database",
    "load_database_admin_settings",
    "load_database_settings",
    "load_human_feedback_components",
    "load_human_ground_truth",
    "load_reviewer_id",
    "load_review_queue",
    "load_telemetry",
    "load_telemetry_window",
    "persist_classified_telemetry",
    "persist_human_validation",
    "persist_raw_telemetry",
    "pipeline_run",
    "start_pipeline_run",
    "test_connection",
]
