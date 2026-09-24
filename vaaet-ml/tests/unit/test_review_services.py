# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Servicios de revisión sin dependencia de widgets ni salida de presentación."""

from __future__ import annotations

import sys
import uuid
from types import SimpleNamespace

import pandas as pd
import pytest
from vaaet.artifacts import FEATURE_SCHEMA_VERSION

from vaaet_ml.data.review_domain import HumanValidation, InferenceReviewSession
from vaaet_ml.data.review_orchestration import (
    ReviewSubmissionStatus,
    prepare_review_session,
    recover_pending_review_validation,
)
from vaaet_ml.settings import FEATURE_COLS


def _classified_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "clip_id": "clip-a",
                "record_time": "2026-08-29T12:00:00Z",
                "traffic_state": 1,
                "confidence": 0.5,
                "probability_margin": 0.1,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                **{feature: 1.0 for feature in FEATURE_COLS},
            }
        ]
    )


def test_portable_review_service_accumulates_decisions_without_widgets() -> None:
    sys.modules.pop("ipywidgets", None)
    prepared = prepare_review_session(
        enabled=True,
        classified=_classified_frame(),
        inference_pipeline_run_id=None,
        reviewer_id="reviewer",
        settings=None,
        mode="priority",
    )

    decision = HumanValidation(1, 1, "reviewer")
    prepared.submit(decision)

    assert prepared.session.export_frame is not None
    assert prepared.queue["prediction_id"].tolist() == [1]
    assert prepared.session.validations == [decision]
    assert "ipywidgets" not in sys.modules


def test_disabled_review_service_has_no_presentation_side_effect() -> None:
    prepared = prepare_review_session(
        enabled=False,
        classified=_classified_frame(),
        inference_pipeline_run_id=None,
        reviewer_id=None,
        settings=None,
        mode="priority",
    )

    assert prepared.queue.empty
    assert prepared.session.export_frame is None


def test_service_rejects_missing_reviewer_and_skips_empty_classification() -> None:
    with pytest.raises(ValueError, match="reviewer identifier"):
        prepare_review_session(
            enabled=True,
            classified=_classified_frame(),
            inference_pipeline_run_id=None,
            reviewer_id=None,
            settings=None,
            mode="priority",
        )
    prepared = prepare_review_session(
        enabled=True,
        classified=pd.DataFrame(),
        inference_pipeline_run_id=None,
        reviewer_id="reviewer",
        settings=None,
        mode="priority",
    )
    assert prepared.session.export_frame is None


def test_database_review_service_links_predictions_and_persists_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = pd.DataFrame(
        [
            {
                "prediction_id": 9,
                "clip_id": "clip-a",
                "record_time": "2026-08-29T12:00:00Z",
                "traffic_state": 1,
                "confidence": 0.5,
                "probability_margin": 0.1,
            }
        ]
    )
    persisted: list[HumanValidation] = []
    review_run_id = uuid.uuid4()
    monkeypatch.setattr(
        "vaaet_ml.data.review_orchestration.load_review_queue",
        lambda **_kwargs: queue,
    )
    monkeypatch.setattr(
        "vaaet_ml.data.review_orchestration.persist_human_validation_record",
        lambda decision, **_kwargs: (
            persisted.append(decision)
            or SimpleNamespace(
                decision=decision,
                pipeline_run_id=review_run_id,
                audit_complete=True,
                audit_error_category=None,
            )
        ),
    )

    prepared = prepare_review_session(
        enabled=True,
        classified=_classified_frame(),
        inference_pipeline_run_id="run",
        reviewer_id="reviewer",
        settings={"host": "unused"},
        mode="priority",
    )
    decision = HumanValidation(9, 1, "reviewer")
    prepared.submit(decision)

    assert prepared.session.export_frame is not None
    assert prepared.session.export_frame["prediction_id"].tolist() == [9]
    assert persisted == [decision]
    assert prepared.session.validations[0]["validation_id"] == decision.validation_id
    assert prepared.session.validations[0]["pipeline_run_id"] == str(review_run_id)


def test_database_review_keeps_same_decision_pending_until_reconciled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = pd.DataFrame(
        [
            {
                "prediction_id": 9,
                "clip_id": "clip-a",
                "record_time": "2026-08-29T12:00:00Z",
                "traffic_state": 1,
                "confidence": 0.5,
                "probability_margin": 0.1,
            }
        ]
    )
    review_run_id = uuid.uuid4()
    submitted: list[HumanValidation] = []
    reconciled: list[HumanValidation] = []
    monkeypatch.setattr(
        "vaaet_ml.data.review_orchestration.load_review_queue",
        lambda **_kwargs: queue,
    )

    def pending(decision: HumanValidation, **_kwargs: object) -> SimpleNamespace:
        submitted.append(decision)
        return SimpleNamespace(
            decision=decision,
            pipeline_run_id=review_run_id,
            audit_complete=False,
            audit_error_category="PipelineAuditIncomplete",
        )

    def reconcile(decision: HumanValidation, **_kwargs: object) -> SimpleNamespace:
        reconciled.append(decision)
        return SimpleNamespace(
            decision=decision,
            pipeline_run_id=review_run_id,
            audit_complete=True,
            audit_error_category=None,
        )

    monkeypatch.setattr(
        "vaaet_ml.data.review_orchestration.persist_human_validation_record", pending
    )
    monkeypatch.setattr(
        "vaaet_ml.data.review_orchestration.reconcile_human_validation", reconcile
    )
    prepared = prepare_review_session(
        enabled=True,
        classified=_classified_frame(),
        inference_pipeline_run_id="run",
        reviewer_id="reviewer",
        settings={"host": "unused"},
        mode="priority",
    )
    decision = HumanValidation(9, 1, "reviewer")

    first = prepared.submit(decision)
    assert first.status is ReviewSubmissionStatus.AUDIT_PENDING
    assert prepared.session.validations == []
    assert len(prepared.session.pending_validations) == 1

    second = prepared.submit(decision)
    assert second.status is ReviewSubmissionStatus.CONFIRMED
    assert submitted == [decision]
    assert reconciled == [decision]
    assert prepared.session.pending_validations == []
    assert prepared.session.validations[0]["validation_id"] == decision.validation_id


def test_database_review_requires_classified_rows() -> None:
    with pytest.raises(ValueError, match="Classified telemetry"):
        prepare_review_session(
            enabled=True,
            classified=None,
            inference_pipeline_run_id="run",
            reviewer_id="reviewer",
            settings={"host": "unused"},
            mode="priority",
        )


def test_explicit_recovery_moves_original_decision_from_pending_to_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision = HumanValidation(9, 1, "reviewer")
    run_id = uuid.uuid4()
    pending = SimpleNamespace(
        decision=decision,
        pipeline_run_id=run_id,
        audit_complete=False,
        audit_error_category="PipelineAuditIncomplete",
    )
    confirmed = SimpleNamespace(
        decision=decision,
        pipeline_run_id=run_id,
        audit_complete=True,
        audit_error_category=None,
    )
    session = InferenceReviewSession(
        export_frame=_classified_frame(),
        validations=[],
        pending_validations=[
            {
                "validation_id": decision.validation_id,
                "pipeline_run_id": str(run_id),
                "audit_complete": False,
            }
        ],
    )
    monkeypatch.setattr(
        "vaaet_ml.data.review_orchestration.load_human_validation_record",
        lambda *_args, **_kwargs: pending,
    )
    monkeypatch.setattr(
        "vaaet_ml.data.review_orchestration.reconcile_human_validation",
        lambda *_args, **_kwargs: confirmed,
    )

    result = recover_pending_review_validation(
        session,
        decision.validation_id,
        settings={"host": "unused"},
    )

    assert result.confirmed
    assert session.pending_validations == []
    assert session.validations[0]["validation_id"] == decision.validation_id
    assert session.validations[0]["pipeline_run_id"] == str(run_id)
