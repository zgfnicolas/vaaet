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

from vaaet_ml.data.review_domain import HumanValidation
from vaaet_ml.data.review_orchestration import prepare_review_session
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
            or SimpleNamespace(decision=decision, pipeline_run_id=review_run_id)
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
