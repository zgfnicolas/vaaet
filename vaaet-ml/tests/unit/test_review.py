# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for append-only human-review rules."""

from __future__ import annotations

import uuid
from dataclasses import asdict

import pandas as pd
import pytest

from vaaet_ml.data.ingestion import load_dataset_package
from vaaet_ml.data.review import (
    HumanValidation,
    OfflineReviewExportContext,
    export_offline_review_package,
    select_review_queue,
)
from vaaet_ml.settings import FEATURE_COLS


def test_accident_requires_context_and_note() -> None:
    with pytest.raises(ValueError, match="temporal-context"):
        HumanValidation(1, 3, "reviewer")
    with pytest.raises(ValueError, match="non-empty review note"):
        HumanValidation(1, 3, "reviewer", incident_context_reviewed=True)


def test_accident_can_be_confirmed_by_human() -> None:
    decision = HumanValidation(
        1,
        3,
        "reviewer",
        notes="Collision visible in current and adjacent minute.",
        incident_context_reviewed=True,
    )
    assert decision.validated_state == 3


def test_priority_queue_filters_ordinary_high_confidence_rows() -> None:
    frame = pd.DataFrame(
        [
            {
                "clip_id": "a",
                "traffic_state": 0,
                "confidence": 0.98,
                "probability_margin": 0.70,
                "accident_rule_triggered": False,
                "decision_abstained": False,
            },
            {
                "clip_id": "a",
                "traffic_state": 1,
                "confidence": 0.60,
                "probability_margin": 0.10,
                "accident_rule_triggered": False,
                "decision_abstained": False,
            },
            {
                "clip_id": "a",
                "traffic_state": 2,
                "confidence": 0.90,
                "probability_margin": 0.40,
                "accident_rule_triggered": True,
                "decision_abstained": False,
            },
        ]
    )
    priority = select_review_queue(frame, mode="priority")
    assert priority.index.tolist() == [0, 1]
    assert priority["traffic_state"].tolist() == [1, 2]
    assert len(select_review_queue(frame, mode="all")) == 3


def test_priority_excludes_reviewed_but_all_allows_correction() -> None:
    frame = pd.DataFrame(
        [
            {
                "traffic_state": 2,
                "confidence": 0.2,
                "accident_rule_triggered": True,
                "latest_validation_id": "7a8f7af9-6075-4e8b-a579-5fe15707d818",
                "current_validated_state": 1,
            }
        ]
    )
    assert select_review_queue(frame, mode="priority").empty
    assert len(select_review_queue(frame, mode="all")) == 1


def test_unknown_review_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="priority.*all"):
        select_review_queue(pd.DataFrame(), mode="random")


def test_offline_review_exports_importable_contract(tmp_path) -> None:
    row = {column: 1.0 for column in FEATURE_COLS}
    row.update(
        prediction_id=1,
        clip_id="clip-a",
        continuity_id="clip-a:continuity-0001",
        record_time="2026-08-04T12:00:00Z",
        feature_schema_version="traffic-features-v3",
        telemetry_schema_version="traffic-telemetry-v3",
        model_version="mlp-v3.0",
        model_revision="a" * 64,
        traffic_state=1,
    )
    decision = HumanValidation(1, 1, "reviewer")
    package = export_offline_review_package(
        tmp_path / "feedback.zip",
        classified=pd.DataFrame([row]),
        validations=[decision],
        context=OfflineReviewExportContext(
            pipeline_run_id="00000000-0000-0000-0000-000000000123",
            model_version="mlp-v3.0",
            git_commit="abc1234",
            application_version="4.9.0",
        ),
    )
    frames = load_dataset_package(package)
    assert set(frames) == {"features", "predictions", "validations"}
    assert frames["validations"].iloc[0]["validated_state"] == 1
    assert pd.Timestamp(frames["validations"].iloc[0]["reviewed_at"]) == pd.Timestamp(
        decision.reviewed_at
    )

    repeated = export_offline_review_package(
        package,
        classified=pd.DataFrame([row]),
        validations=[decision],
        context=OfflineReviewExportContext(
            pipeline_run_id="00000000-0000-0000-0000-000000000123",
            model_version="mlp-v3.0",
            git_commit="abc1234",
            application_version="4.9.0",
        ),
    )
    assert repeated == package

    with pytest.raises(ValueError, match="different immutable content"):
        export_offline_review_package(
            package,
            classified=pd.DataFrame([row]),
            validations=[HumanValidation(1, 2, "reviewer")],
            context=OfflineReviewExportContext(
                pipeline_run_id="00000000-0000-0000-0000-000000000123",
                model_version="mlp-v3.0",
                git_commit="abc1234",
                application_version="4.9.0",
            ),
        )


def test_offline_review_rejects_pending_postgres_audit(tmp_path) -> None:
    row = {column: 1.0 for column in FEATURE_COLS}
    row.update(
        prediction_id=1,
        clip_id="clip-pending",
        continuity_id="clip-pending:continuity-0001",
        record_time="2026-08-04T12:00:00Z",
        feature_schema_version="traffic-features-v3",
        telemetry_schema_version="traffic-telemetry-v3",
        model_version="mlp-v3.0",
        model_revision="a" * 64,
        traffic_state=1,
    )
    decision = HumanValidation(1, 1, "reviewer")
    pending = {
        **asdict(decision),
        "pipeline_run_id": str(uuid.uuid4()),
        "audit_complete": False,
    }
    destination = tmp_path / "pending.zip"
    with pytest.raises(ValueError, match="audit"):
        export_offline_review_package(
            destination,
            classified=pd.DataFrame([row]),
            validations=pd.DataFrame([pending]),
            context=OfflineReviewExportContext(
                pipeline_run_id=str(uuid.uuid4()),
                model_version="mlp-v3.0",
                git_commit="abc1234",
                application_version="4.9.1",
            ),
        )
    assert not destination.exists()


def test_offline_review_export_rejects_missing_operational_context(tmp_path) -> None:
    row = {column: 1.0 for column in FEATURE_COLS}
    row.update(
        prediction_id=1,
        clip_id="clip-a",
        continuity_id="clip-a:continuity-0001",
        record_time="2026-08-04T12:00:00Z",
        feature_schema_version="traffic-features-v3",
        telemetry_schema_version="traffic-telemetry-v3",
        model_version="mlp-v3.0",
        model_revision="a" * 64,
        traffic_state=1,
    )

    with pytest.raises(ValueError, match="OfflineReviewExportContext"):
        export_offline_review_package(
            tmp_path / "feedback.zip",
            classified=pd.DataFrame([row]),
            validations=[HumanValidation(1, 1, "reviewer")],
        )

    assert not (tmp_path / "feedback.zip").exists()
