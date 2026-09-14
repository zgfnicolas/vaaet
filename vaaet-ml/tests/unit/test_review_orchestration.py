# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import logging

import pandas as pd
import pytest
from pytest import LogCaptureFixture

from vaaet_ml.data.review import HumanValidation, prepare_inference_review
from vaaet_ml.data.review_orchestration import prepare_review_session
from vaaet_ml.workflow_state import StaleInferenceExecutionError


def test_disabled_review_has_no_queue_or_persistence(caplog: LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="vaaet_ml.data.review")
    session = prepare_inference_review(
        enabled=False,
        classified=pd.DataFrame(),
        inference_pipeline_run_id=None,
        reviewer_id=None,
        settings=None,
        mode="priority",
    )

    assert session.export_frame is None
    assert session.validations == []
    assert "Revisión humana desactivada" in caplog.text


def test_stale_review_callback_cannot_mutate_previous_session() -> None:
    current = {"value": True}
    prepared = prepare_review_session(
        enabled=True,
        classified=pd.DataFrame({"traffic_state": [0]}),
        inference_pipeline_run_id=None,
        reviewer_id="reviewer",
        settings=None,
        mode="all",
        is_current=lambda: current["value"],
    )
    current["value"] = False

    with pytest.raises(StaleInferenceExecutionError, match="earlier"):
        prepared.submit(HumanValidation(1, 0, "reviewer"))

    assert prepared.session.validations == []
