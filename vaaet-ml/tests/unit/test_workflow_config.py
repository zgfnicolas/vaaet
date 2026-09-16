# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import pytest

from vaaet_ml.exceptions import RuntimeConfigurationError
from vaaet_ml.workflow_config import (
    CollectionWorkflowConfig,
    EvaluationWorkflowConfig,
    InferenceWorkflowConfig,
    TrainingWorkflowConfig,
)


def test_view_plan_path_requires_a_non_empty_string_when_configured() -> None:
    with pytest.raises(RuntimeConfigurationError, match="view_plan_path"):
        CollectionWorkflowConfig(False, False, "")


def test_collection_config_requires_an_explicit_boolean_for_downloads() -> None:
    with pytest.raises(RuntimeConfigurationError, match="download_outputs"):
        CollectionWorkflowConfig(False, False, None, "yes")  # type: ignore[arg-type]


def test_inference_config_rejects_unknown_review_mode() -> None:
    with pytest.raises(RuntimeConfigurationError, match="review_mode"):
        InferenceWorkflowConfig(False, False, False, False, "random", False, False, False)  # type: ignore[arg-type]


def test_training_config_requires_reason_for_versioned_holdout() -> None:
    with pytest.raises(RuntimeConfigurationError, match="human_holdout_update_reason"):
        TrainingWorkflowConfig(
            "hitl_retraining", False, False, True, "create_new_version", None,
            "reuse_or_create", None,
        )


def test_training_config_requires_an_immutable_reference_run_id() -> None:
    with pytest.raises(RuntimeConfigurationError, match="reference_training_run_id"):
        TrainingWorkflowConfig(
            "seed_bootstrap", False, True, False, "reuse_or_create", None,
            "reuse_or_create", None, reference_training_run_id="latest",
        )


def test_training_config_requires_an_explicit_boolean_for_drive_copy() -> None:
    with pytest.raises(RuntimeConfigurationError, match="copy_bundle_to_drive"):
        TrainingWorkflowConfig(
            "seed_bootstrap",
            False,
            True,
            False,
            "reuse_or_create",
            None,
            "reuse_or_create",
            None,
            copy_bundle_to_drive="yes",  # type: ignore[arg-type]
        )


def test_training_config_allows_legacy_read_only_for_seed_postgres() -> None:
    config = TrainingWorkflowConfig(
        "seed_bootstrap",
        True,
        False,
        False,
        "reuse_or_create",
        None,
        "reuse_or_create",
        None,
        postgres_telemetry_read_mode="legacy",
    )

    assert config.postgres_telemetry_read_mode == "legacy"


def test_training_config_rejects_legacy_read_for_hitl_feedback() -> None:
    with pytest.raises(RuntimeConfigurationError, match="only for raw seed"):
        TrainingWorkflowConfig(
            "hitl_retraining",
            True,
            False,
            False,
            "reuse_or_create",
            None,
            "reuse_or_create",
            None,
            postgres_telemetry_read_mode="legacy",
        )


def test_evaluation_config_requires_exact_holdout() -> None:
    with pytest.raises(RuntimeConfigurationError, match="must not be current.json"):
        EvaluationWorkflowConfig(
            True, "champion", "challenger", "current.json", 1, False, "", "", False, "", ""
        )


def test_evaluation_config_validates_immutable_filters() -> None:
    with pytest.raises(RuntimeConfigurationError, match="postgres_clip_ids"):
        EvaluationWorkflowConfig(
            False,
            "",
            "",
            "",
            1,
            False,
            "",
            "",
            False,
            "",
            "",
            postgres_clip_ids=("clip-1", "clip-1"),
        )
