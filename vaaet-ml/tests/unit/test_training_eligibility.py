# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Regresión de gates vigentes, extraídos del notebook de entrenamiento."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from vaaet_ml.evaluation.reporting import false_alert_rate_upper_bound
from vaaet_ml.training.eligibility import evaluate_candidate_eligibility
from vaaet_ml.training.lifecycle import TrainingMode


def _human_test_frame() -> tuple[pd.DataFrame, np.ndarray]:
    rows: list[dict[str, object]] = []
    labels: list[int] = []
    for state, records in ((0, 100), (1, 100), (2, 100)):
        for index in range(records):
            rows.append(
                {
                    "clip_id": f"{state}-{index % 20}",
                    "record_time": pd.Timestamp("2026-01-01T00:00:00Z")
                    + pd.Timedelta(minutes=len(labels)),
                }
            )
            labels.append(state)
    return pd.DataFrame(rows), np.asarray(labels, dtype=int)


def _passing_intervals() -> pd.DataFrame:
    metrics = [
        "f1_macro",
        "precision_normal",
        "precision_reduced",
        "precision_congested",
        "recall_normal",
        "recall_reduced",
        "recall_congested",
        "normal_congested_error",
        "ece",
    ]
    return pd.DataFrame(
        {
            "metric": metrics,
            "value": [1.0] * 7 + [0.0, 0.0],
            "ci_95_low": [1.0] * 7 + [0.0, 0.0],
            "ci_95_high": [1.0] * 7 + [0.0, 0.0],
            "evaluable_fraction": [1.0] * len(metrics),
            "method": ["grouped-bootstrap"] * len(metrics),
            "group_count": [20] * len(metrics),
            "bootstrap_samples": [2_000] * len(metrics),
            "sufficient": [True] * len(metrics),
        }
    )


def test_human_candidate_uses_existing_gates_without_new_blockers() -> None:
    test_frame, truth = _human_test_frame()

    eligibility = evaluate_candidate_eligibility(
        training_mode=TrainingMode.HITL_RETRAINING,
        dataset_blockers=(),
        human_holdout=True,
        test_frame=test_frame,
        actual=truth,
        predicted=truth,
        f1_macro=1.0,
        direct_normal_congested_error=0.0,
        expected_calibration_error=0.0,
        negative_exposure_hours=300.0,
        false_candidates_per_hour=0.0,
        direct_intervals=_passing_intervals(),
        final_intervals=_passing_intervals(),
        false_candidates_upper_95=false_alert_rate_upper_bound(0, 300.0),
        false_candidate_count=0,
    )

    assert all(eligibility.metric_gates.values())
    assert eligibility.congested_minutes == 100
    assert eligibility.congested_clips == 20
    assert eligibility.production_eligible is True
    assert not eligibility.promotion_blockers


def test_seed_candidate_remains_pilot_even_when_metrics_pass() -> None:
    test_frame, truth = _human_test_frame()

    eligibility = evaluate_candidate_eligibility(
        training_mode=TrainingMode.SEED_BOOTSTRAP,
        dataset_blockers=(),
        human_holdout=True,
        test_frame=test_frame,
        actual=truth,
        predicted=truth,
        f1_macro=1.0,
        direct_normal_congested_error=0.0,
        expected_calibration_error=0.0,
        negative_exposure_hours=300.0,
        false_candidates_per_hour=0.0,
    )

    assert eligibility.production_eligible is False
    assert "seed bootstrap uses weak proxy supervision and is pilot-only" in (
        eligibility.promotion_blockers
    )


@pytest.mark.parametrize("invalid_bound", [float("nan"), -1.0, float("inf")])
def test_invalid_false_alert_upper_bound_is_rejected(invalid_bound: float) -> None:
    test_frame, truth = _human_test_frame()

    with pytest.raises(ValueError, match="false_candidates_upper_95"):
        evaluate_candidate_eligibility(
            training_mode=TrainingMode.HITL_RETRAINING,
            dataset_blockers=(),
            human_holdout=True,
            test_frame=test_frame,
            actual=truth,
            predicted=truth,
            f1_macro=1.0,
            direct_normal_congested_error=0.0,
            expected_calibration_error=0.0,
            negative_exposure_hours=300.0,
            false_candidates_per_hour=0.0,
            direct_intervals=_passing_intervals(),
            final_intervals=_passing_intervals(),
            false_candidates_upper_95=invalid_bound,
            false_candidate_count=0,
        )


def test_direct_predictions_cannot_include_accident() -> None:
    test_frame, truth = _human_test_frame()
    direct = truth.copy()
    direct[0] = 3

    with pytest.raises(ValueError, match="three stable model states"):
        evaluate_candidate_eligibility(
            training_mode=TrainingMode.HITL_RETRAINING,
            dataset_blockers=(),
            human_holdout=True,
            test_frame=test_frame,
            actual=truth,
            predicted=truth,
            direct_predicted=direct,
            f1_macro=1.0,
            direct_normal_congested_error=0.0,
            final_normal_congested_error=0.0,
            expected_calibration_error=0.0,
            negative_exposure_hours=300.0,
            false_candidates_per_hour=0.0,
            direct_intervals=_passing_intervals(),
            final_intervals=_passing_intervals(),
            false_candidates_upper_95=false_alert_rate_upper_bound(0, 300.0),
            false_candidate_count=0,
        )


def test_incomplete_or_inconsistent_grouped_evidence_is_rejected() -> None:
    test_frame, truth = _human_test_frame()
    incomplete = _passing_intervals().query("metric != 'recall_congested'")

    with pytest.raises(ValueError, match="evidence is incomplete"):
        evaluate_candidate_eligibility(
            training_mode=TrainingMode.HITL_RETRAINING,
            dataset_blockers=(),
            human_holdout=True,
            test_frame=test_frame,
            actual=truth,
            predicted=truth,
            f1_macro=1.0,
            direct_normal_congested_error=0.0,
            expected_calibration_error=0.0,
            negative_exposure_hours=300.0,
            false_candidates_per_hour=0.0,
            direct_intervals=incomplete,
            final_intervals=_passing_intervals(),
            false_candidates_upper_95=false_alert_rate_upper_bound(0, 300.0),
            false_candidate_count=0,
        )


def test_declared_metric_must_match_grouped_evidence() -> None:
    test_frame, truth = _human_test_frame()

    with pytest.raises(ValueError, match="final f1_macro is inconsistent"):
        evaluate_candidate_eligibility(
            training_mode=TrainingMode.HITL_RETRAINING,
            dataset_blockers=(),
            human_holdout=True,
            test_frame=test_frame,
            actual=truth,
            predicted=truth,
            f1_macro=0.99,
            direct_normal_congested_error=0.0,
            expected_calibration_error=0.0,
            negative_exposure_hours=300.0,
            false_candidates_per_hour=0.0,
            direct_intervals=_passing_intervals(),
            final_intervals=_passing_intervals(),
            false_candidates_upper_95=false_alert_rate_upper_bound(0, 300.0),
            false_candidate_count=0,
        )
