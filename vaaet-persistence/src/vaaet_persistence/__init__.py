# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Persistencia PostgreSQL compartida por consumidores VAAET."""

from vaaet_persistence.connection import (
    DatabaseHealth,
    create_admin_engine,
    database_engine,
    dispose_engine,
    get_engine,
    inspect_database,
    require_database_revision,
    test_connection,
)
from vaaet_persistence.constants import (
    DATABASE_SCHEMA_VERSION,
    DATABASE_SCHEMAS,
    REQUIRED_DATABASE_REVISION,
)
from vaaet_persistence.exceptions import (
    DatabaseNotConfiguredError,
    DatabaseOperationError,
    DatabaseSchemaVersionError,
    PersistenceConflictError,
    PersistenceValidationError,
    PipelineAuditIncompleteError,
)
from vaaet_persistence.persistence import (
    PersistResult,
    persist_classified_telemetry,
    persist_raw_telemetry,
    reconcile_classified_telemetry,
    reconcile_raw_telemetry,
)
from vaaet_persistence.pipeline_runs import (
    PipelineRunHandle,
    PipelineRunMetadata,
    PipelineRunOutcome,
    PipelineWorkflow,
    complete_reconciled_pipeline_run,
    finalize_pipeline_run_outcome,
    finish_pipeline_run,
    pipeline_run,
    start_pipeline_run,
)
from vaaet_persistence.queries import (
    TelemetryReadMode,
    load_human_feedback_components,
    load_human_ground_truth,
    load_telemetry,
    load_telemetry_window,
)
from vaaet_persistence.receipts import (
    PERSISTENCE_RECEIPT_ALGORITHM,
    PersistenceReceipt,
    PipelineRunAuditState,
    calculate_persistence_fingerprint,
)
from vaaet_persistence.review_domain import HumanValidation, InferenceReviewSession
from vaaet_persistence.review_persistence import (
    PersistedHumanValidation,
    load_human_validation_record,
    load_review_queue,
    persist_human_validation,
    persist_human_validation_record,
    reconcile_human_validation,
)
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

__version__ = "0.3.0"

__all__ = [
    "DATABASE_SCHEMAS",
    "DATABASE_SCHEMA_VERSION",
    "REQUIRED_DATABASE_REVISION",
    "DatabaseAdminSettings",
    "DatabaseEndpointSettings",
    "DatabaseHealth",
    "DatabaseNotConfiguredError",
    "DatabaseOperationError",
    "DatabasePoolSettings",
    "DatabaseProfile",
    "DatabaseRetrySettings",
    "DatabaseSchemaVersionError",
    "DatabaseSettings",
    "HumanValidation",
    "InferenceReviewSession",
    "PersistResult",
    "PersistedHumanValidation",
    "PersistenceReceipt",
    "PersistenceConflictError",
    "PersistenceValidationError",
    "PipelineRunHandle",
    "PipelineRunAuditState",
    "PipelineRunMetadata",
    "PipelineRunOutcome",
    "PipelineWorkflow",
    "PipelineAuditIncompleteError",
    "TelemetryReadMode",
    "PERSISTENCE_RECEIPT_ALGORITHM",
    "calculate_persistence_fingerprint",
    "create_admin_engine",
    "complete_reconciled_pipeline_run",
    "database_engine",
    "dispose_engine",
    "finalize_pipeline_run_outcome",
    "finish_pipeline_run",
    "get_engine",
    "get_optional_database_settings",
    "inspect_database",
    "require_database_revision",
    "load_database_admin_settings",
    "load_database_settings",
    "load_human_feedback_components",
    "load_human_ground_truth",
    "load_human_validation_record",
    "load_reviewer_id",
    "load_review_queue",
    "load_telemetry",
    "load_telemetry_window",
    "persist_classified_telemetry",
    "persist_human_validation",
    "persist_human_validation_record",
    "persist_raw_telemetry",
    "reconcile_classified_telemetry",
    "reconcile_human_validation",
    "reconcile_raw_telemetry",
    "pipeline_run",
    "start_pipeline_run",
    "test_connection",
]
