# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for src/reporting.py — balance and support summaries."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from vaaet_ml.evaluation.reporting import (
    build_class_support_notes,
    build_classification_support_table,
    expected_calibration_error,
    expected_confusion_cost,
    false_alert_rate_upper_bound,
    grouped_classification_intervals,
    select_validation_decision_policy,
    summarize_data_origin,
    summarize_resampled_balance,
    summarize_state_balance,
)


def test_classification_support_includes_intervals() -> None:
    table = build_classification_support_table([0, 0, 1, 2], [0, 1, 1, 2])
    assert table["support"].tolist() == [2, 1, 1]
    assert table["interval_method"].eq("unavailable").all()
    assert table["interval_sufficient"].eq(False).all()
    assert all(interval == (None, None) for interval in table["recall_ci_95"])


def test_classification_support_reuses_grouped_intervals() -> None:
    table = build_classification_support_table(
        [0, 1, 2, 0, 1, 2],
        [0, 1, 2, 0, 1, 2],
        clip_ids=["a", "a", "a", "b", "b", "b"],
    )

    assert table["interval_method"].eq("grouped-bootstrap").all()
    assert table["interval_sufficient"].all()


def test_extreme_confusion_costs_more_than_adjacent() -> None:
    assert expected_confusion_cost([0], [2]) > expected_confusion_cost([0], [1])


def test_metrics_reject_invalid_shapes_and_compute_calibration_error() -> None:
    probabilities = np.array([[0.8, 0.1, 0.1], [0.2, 0.7, 0.1]])
    assert expected_calibration_error([0, 1], probabilities, bins=2) >= 0.0
    with pytest.raises(ValueError, match="shape"):
        expected_calibration_error([0], probabilities)
    with pytest.raises(ValueError, match="equally sized"):
        expected_confusion_cost([0], [0, 1])
    with pytest.raises(ValueError, match="Normal/Reduced/Congested"):
        expected_confusion_cost([3], [3])


def test_decision_policy_is_selected_from_validation_probabilities() -> None:
    frame = pd.DataFrame(
        {
            "clip_id": ["a"] * 4,
            "continuity_id": ["a:continuity-0001"] * 4,
            "record_time": pd.date_range("2026-01-01T00:00:00Z", periods=4, freq="1min"),
        }
    )
    probabilities = np.array(
        [[0.9, 0.08, 0.02], [0.1, 0.85, 0.05], [0.05, 0.1, 0.85], [0.05, 0.1, 0.85]]
    )
    policy = select_validation_decision_policy(frame, [0, 1, 2, 2], probabilities, temperature=1.2)
    assert set(policy["class_thresholds"]) == {"0", "1", "2"}
    assert policy["temperature"] == 1.2


def test_grouped_intervals_are_deterministic_and_report_calibration() -> None:
    truth = np.array([0, 1, 2, 0, 1, 2])
    predicted = truth.copy()
    clips = np.array(["a", "a", "a", "b", "b", "b"])
    probabilities = np.eye(3)[truth] * 0.9 + (1 - np.eye(3)[truth]) * 0.05

    first = grouped_classification_intervals(
        truth, predicted, clips, probabilities=probabilities, samples=50, random_state=7
    )
    second = grouped_classification_intervals(
        truth, predicted, clips, probabilities=probabilities, samples=50, random_state=7
    )

    pd.testing.assert_frame_equal(first, second)
    assert {"ece", "brier_score"}.issubset(set(first["metric"]))
    assert first["sufficient"].all()


def test_grouped_intervals_mark_rare_class_as_insufficient() -> None:
    intervals = grouped_classification_intervals(
        [0, 0, 1, 2],
        [0, 0, 1, 2],
        ["normal", "normal", "reduced", "congested"],
        samples=100,
        random_state=11,
    ).set_index("metric")

    assert not bool(intervals.loc["recall_congested", "sufficient"])


def test_zero_false_alerts_need_about_three_hundred_negative_hours() -> None:
    assert false_alert_rate_upper_bound(0, 300.0) < 0.01
    assert false_alert_rate_upper_bound(0, 299.0) > 0.01


class TestSummarizeDataOrigin:
    def test_origin_summary_counts_records(self) -> None:
        df = pd.DataFrame(
            {
                "data_origin": ["real", "real", "synthetic", "synthetic"],
                "synthetic_scenario": [
                    "observed",
                    "observed",
                    "accident",
                    "congestion",
                ],
            }
        )
        summary = summarize_data_origin(df)
        assert int(summary["records"].sum()) == len(df)
        assert set(summary["data_origin"]) == {"real", "synthetic"}


class TestSummarizeStateBalance:
    def test_state_balance_splits_real_and_synthetic(self) -> None:
        df = pd.DataFrame(
            {
                "traffic_state": [0, 0, 2, 3, 3],
                "data_origin": ["real", "real", "synthetic", "synthetic", "synthetic"],
            }
        )
        summary = summarize_state_balance(df)
        accident = summary[summary["traffic_state"] == 3].iloc[0]
        assert accident["real"] == 0
        assert accident["synthetic"] == 2
        assert accident["total"] == 2


class TestSummarizeResampledBalance:
    def test_resampled_delta_is_reported(self) -> None:
        summary = summarize_resampled_balance([0, 0, 1], [0, 0, 1, 1, 1])
        reduced = summary[summary["traffic_state"] == 1].iloc[0]
        assert reduced["before"] == 1
        assert reduced["after"] == 3
        assert reduced["delta"] == 2


class TestBuildClassSupportNotes:
    def test_accident_note_mentions_synthetic_support(self) -> None:
        df = pd.DataFrame(
            {
                "traffic_state": [0, 0, 3, 3],
                "data_origin": ["real", "real", "synthetic", "synthetic"],
            }
        )
        notes = build_class_support_notes(df)
        assert any("Accident" in note and "synthetic" in note for note in notes)

    def test_real_only_data_returns_generic_note(self) -> None:
        df = pd.DataFrame(
            {
                "traffic_state": [0, 0, 1, 1],
                "data_origin": ["real", "real", "real", "real"],
            }
        )
        notes = build_class_support_notes(df)
        assert len(notes) == 1
        assert "real support" in notes[0]
