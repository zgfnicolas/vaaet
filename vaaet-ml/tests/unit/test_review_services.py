# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Servicios de revisión sin dependencia de widgets ni salida de presentación."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from vaaet.artifacts import FEATURE_SCHEMA_VERSION

from vaaet_ml.data.review_domain import HumanValidation
from vaaet_ml.data.review_orchestration import (
    ManagedReviewSession,
    ReviewSessionContext,
    ReviewSubmissionStatus,
    _session_feature_contracts,
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
                receipt=SimpleNamespace(content_fingerprint="a" * 64),
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
            receipt=SimpleNamespace(content_fingerprint="a" * 64),
        )

    def reconcile(decision: HumanValidation, **_kwargs: object) -> SimpleNamespace:
        reconciled.append(decision)
        return SimpleNamespace(
            decision=decision,
            pipeline_run_id=review_run_id,
            audit_complete=True,
            audit_error_category=None,
            receipt=SimpleNamespace(content_fingerprint="a" * 64),
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
    inference_run = uuid.uuid4()
    prediction_context = SimpleNamespace(
        prediction_id=9,
        clip_id="clip-a",
        record_time=pd.Timestamp("2026-08-29T12:00:00Z"),
        continuity_id="segment-a",
        model_revision="a" * 64,
        pipeline_run_id=inference_run,
        operational_feature_id=10,
    )
    pending = SimpleNamespace(
        decision=decision,
        pipeline_run_id=run_id,
        audit_complete=False,
        audit_error_category="PipelineAuditIncomplete",
        receipt=SimpleNamespace(content_fingerprint="a" * 64),
        prediction_context=prediction_context,
    )
    confirmed = SimpleNamespace(
        decision=decision,
        pipeline_run_id=run_id,
        audit_complete=True,
        audit_error_category=None,
        receipt=SimpleNamespace(content_fingerprint="a" * 64),
        prediction_context=prediction_context,
    )
    queue = pd.DataFrame([{
        "prediction_id": 9,
        "clip_id": "clip-a",
        "record_time": "2026-08-29T12:00:00Z",
        "continuity_id": "segment-a",
        "model_revision": "a" * 64,
        "pipeline_run_id": str(inference_run),
        "operational_feature_id": 10,
    }])
    export_frame = _classified_frame().assign(prediction_id=9)
    session = ManagedReviewSession(
        export_frame=export_frame,
        validations=[],
        context=ReviewSessionContext(
            "postgresql", str(inference_run), "a" * 64,
            ((9, "clip-a", "2026-08-29T12:00:00+00:00", "segment-a", "a" * 64, str(inference_run), "10"),),
            _session_feature_contracts(export_frame),
        ),
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
    monkeypatch.setattr(
        "vaaet_ml.data.review_orchestration.load_review_queue",
        lambda **_kwargs: queue,
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


def test_recovery_rejects_prediction_outside_original_inference_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inference_run_id = str(uuid.uuid4())
    original_queue = pd.DataFrame([{
        "prediction_id": 9,
        "clip_id": "new-clip",
        "record_time": "2026-08-29T12:00:00Z",
        "continuity_id": "new-clip:continuity-0001",
        "model_revision": "a" * 64,
        "pipeline_run_id": inference_run_id,
        "operational_feature_id": 19,
        "traffic_state": 1,
    }])
    calls = {"count": 0}

    def queue_for_run(**_kwargs: object) -> pd.DataFrame:
        calls["count"] += 1
        return original_queue if calls["count"] == 1 else original_queue.iloc[0:0]

    monkeypatch.setattr(
        "vaaet_ml.data.review_orchestration.load_review_queue", queue_for_run
    )
    prepared = prepare_review_session(
        enabled=True,
        classified=_classified_frame().assign(clip_id="new-clip"),
        inference_pipeline_run_id=inference_run_id,
        reviewer_id="reviewer",
        settings={"host": "unused"},
        mode="all",
    )
    old_decision = HumanValidation(9, 2, "reviewer")
    monkeypatch.setattr(
        "vaaet_ml.data.review_orchestration.load_human_validation_record",
        lambda *_args, **_kwargs: SimpleNamespace(
            decision=old_decision,
            pipeline_run_id=uuid.uuid4(),
            audit_complete=False,
            prediction_context=SimpleNamespace(
                prediction_id=9,
                clip_id="new-clip",
                record_time=pd.Timestamp("2026-08-29T12:00:00Z"),
                continuity_id="new-clip:continuity-0001",
                model_revision="a" * 64,
                pipeline_run_id=uuid.UUID(inference_run_id),
                operational_feature_id=19,
            ),
        ),
    )
    monkeypatch.setattr(
        "vaaet_ml.data.review_orchestration.reconcile_human_validation",
        lambda *_args, **_kwargs: pytest.fail("Wrong-run recovery must not reconcile"),
    )
    with pytest.raises(ValueError, match="original review session"):
        recover_pending_review_validation(
            prepared.session, old_decision.validation_id, settings={"host": "unused"}
        )
    assert prepared.session.validations == []


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("clip_id", "other-clip"),
        ("record_time", "2026-08-29T12:01:00Z"),
        ("continuity_id", "other-continuity"),
        ("model_revision", "b" * 64),
        ("pipeline_run_id", str(uuid.uuid4())),
    ],
)
def test_recovery_rejects_changed_prediction_context_before_reconcile(
    monkeypatch: pytest.MonkeyPatch, field: str, replacement: str
) -> None:
    inference_run = str(uuid.uuid4())
    original = pd.DataFrame([{
        "prediction_id": 9,
        "clip_id": "clip-a",
        "record_time": "2026-08-29T12:00:00Z",
        "continuity_id": "continuity-a",
        "model_revision": "a" * 64,
        "pipeline_run_id": inference_run,
        "operational_feature_id": 19,
        "traffic_state": 1,
    }])
    changed = original.assign(**{field: replacement})
    calls = 0

    def queue(**_kwargs: object) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        return original if calls == 1 else changed

    monkeypatch.setattr("vaaet_ml.data.review_orchestration.load_review_queue", queue)
    frame = _classified_frame().assign(
        continuity_id="continuity-a", model_revision="a" * 64
    )
    prepared = prepare_review_session(
        enabled=True,
        classified=frame,
        inference_pipeline_run_id=inference_run,
        reviewer_id="reviewer",
        settings={"host": "unused"},
        mode="all",
    )
    decision = HumanValidation(9, 1, "reviewer")
    monkeypatch.setattr(
        "vaaet_ml.data.review_orchestration.load_human_validation_record",
        lambda *_args, **_kwargs: SimpleNamespace(
            decision=decision,
            audit_complete=False,
            prediction_context=SimpleNamespace(
                prediction_id=9,
                clip_id="clip-a",
                record_time=pd.Timestamp("2026-08-29T12:00:00Z"),
                continuity_id="continuity-a",
                model_revision="a" * 64,
                pipeline_run_id=uuid.UUID(inference_run),
                operational_feature_id=19,
            ),
        ),
    )
    monkeypatch.setattr(
        "vaaet_ml.data.review_orchestration.reconcile_human_validation",
        lambda *_args, **_kwargs: pytest.fail("Mismatched session must not reconcile"),
    )
    with pytest.raises(ValueError, match="original review session"):
        recover_pending_review_validation(
            prepared.session, decision.validation_id, settings={"host": "unused"}
        )
    assert prepared.session.validations == []


def test_recovery_rejects_mutated_session_features(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = str(uuid.uuid4())
    queue = pd.DataFrame([{
        "prediction_id": 9,
        "clip_id": "clip-a",
        "record_time": "2026-08-29T12:00:00Z",
        "pipeline_run_id": run_id,
        "traffic_state": 1,
    }])
    monkeypatch.setattr("vaaet_ml.data.review_orchestration.load_review_queue", lambda **_kwargs: queue)
    prepared = prepare_review_session(
        enabled=True,
        classified=_classified_frame(),
        inference_pipeline_run_id=run_id,
        reviewer_id="reviewer",
        settings={"host": "unused"},
        mode="all",
    )
    assert prepared.session.export_frame is not None
    prepared.session.export_frame.loc[0, FEATURE_COLS[0]] = 99.0
    monkeypatch.setattr(
        "vaaet_ml.data.review_orchestration.load_human_validation_record",
        lambda *_args, **_kwargs: pytest.fail("Mutated session must not query a decision"),
    )
    with pytest.raises(ValueError, match="features contradict"):
        recover_pending_review_validation(
            prepared.session, uuid.uuid4(), settings={"host": "unused"}
        )


def test_recovered_decision_round_trips_through_zip_to_supervised_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vaaet_persistence.receipts import calculate_persistence_fingerprint

    from vaaet_ml.data.hitl_catalog import resolve_effective_human_feedback
    from vaaet_ml.data.ingestion import DatasetPackageSource, _load_feedback_components
    from vaaet_ml.data.review_finalization import finalize_review_session

    inference_run = uuid.uuid4()
    review_run = uuid.uuid4()
    model_revision = "a" * 64
    classified = _classified_frame().assign(
        continuity_id="continuity-a",
        model_version="mlp-v3.0",
        model_revision=model_revision,
        state_label="Reduced",
        numeric_representation="float64",
    )
    queue = pd.DataFrame([{
        "prediction_id": 9,
        "clip_id": "clip-a",
        "record_time": "2026-08-29T12:00:00Z",
        "continuity_id": "continuity-a",
        "model_revision": model_revision,
        "pipeline_run_id": str(inference_run),
        "operational_feature_id": 20,
        "traffic_state": 1,
    }])
    monkeypatch.setattr(
        "vaaet_ml.data.review_orchestration.load_review_queue", lambda **_kwargs: queue
    )
    prepared = prepare_review_session(
        enabled=True,
        classified=classified,
        inference_pipeline_run_id=str(inference_run),
        reviewer_id="007",
        settings={"host": "unused"},
        mode="all",
    )
    decision = HumanValidation(9, 2, "007", notes="NA")
    receipt_fingerprint = calculate_persistence_fingerprint("human-validation", [{
        "id": str(decision.validation_id),
        "prediction_id": decision.prediction_id,
        "validated_state": decision.validated_state,
        "reviewer_id": decision.reviewer_id,
        "reviewed_at": decision.reviewed_at,
        "notes": decision.notes,
        "review_source": decision.review_source,
        "incident_context_reviewed": decision.incident_context_reviewed,
        "supersedes_validation_id": None,
        "pipeline_run_id": str(review_run),
    }])
    stored = SimpleNamespace(
        decision=decision,
        pipeline_run_id=review_run,
        audit_complete=True,
        receipt=SimpleNamespace(content_fingerprint=receipt_fingerprint),
        prediction_context=SimpleNamespace(
            prediction_id=9,
            clip_id="clip-a",
            record_time=pd.Timestamp("2026-08-29T12:00:00Z"),
            continuity_id="continuity-a",
            model_revision=model_revision,
            pipeline_run_id=inference_run,
            operational_feature_id=20,
        ),
    )
    monkeypatch.setattr(
        "vaaet_ml.data.review_orchestration.load_human_validation_record",
        lambda *_args, **_kwargs: stored,
    )
    assert recover_pending_review_validation(
        prepared.session, decision.validation_id, settings={"host": "unused"}
    ).confirmed
    assert prepared.session.export_frame is not None
    package = finalize_review_session(
        classified=prepared.session.export_frame,
        validations=prepared.session.validations,
        session=prepared.session,
        pipeline_run_id=str(inference_run),
        model_version="mlp-v3.0",
        git_commit="test",
        vaaet_version="4.9.2",
        local_root=tmp_path,
    )
    components, _ = _load_feedback_components(DatasetPackageSource(package.local_path))
    supervised = resolve_effective_human_feedback(
        components["features"], components["predictions"], components["validations"]
    )
    assert supervised["clip_id"].tolist() == ["clip-a"]
    assert supervised["validated_state"].tolist() == [2]
    assert supervised["reviewer_id"].tolist() == ["007"]
