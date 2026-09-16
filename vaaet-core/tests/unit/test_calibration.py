# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for src/calibration.py — lightweight speed validation helpers."""

from __future__ import annotations

import numpy as np
import pytest

from vaaet.calibration import (
    CalibrationSegment,
    aggregate_pixels_per_meter,
    apply_temperature_scaling,
    build_calibration_table,
    fit_temperature,
    multiclass_brier_score,
    pixels_per_meter_from_segment,
    pseudo_ground_truth_speed_kmh,
    validate_probability_matrix,
)


class TestCalibrationHelpers:
    def test_pixels_per_meter_from_segment(self) -> None:
        segment = CalibrationSegment(
            name="lane_mark",
            pixel_start=(0.0, 0.0),
            pixel_end=(120.0, 0.0),
            meters=10.0,
        )
        assert pixels_per_meter_from_segment(segment) == 12.0

    def test_aggregate_pixels_per_meter_uses_median(self) -> None:
        segments = [
            CalibrationSegment("a", (0.0, 0.0), (120.0, 0.0), meters=10.0),
            CalibrationSegment("b", (0.0, 0.0), (132.0, 0.0), meters=11.0),
            CalibrationSegment("c", (0.0, 0.0), (300.0, 0.0), meters=10.0),
        ]
        assert aggregate_pixels_per_meter(segments) == 12.0

    def test_pseudo_ground_truth_speed_kmh(self) -> None:
        assert pseudo_ground_truth_speed_kmh(distance_m=100.0, elapsed_seconds=10.0) == 36.0

    def test_build_calibration_table_includes_optional_speed(self) -> None:
        segments = [
            CalibrationSegment(
                name="bridge_segment",
                pixel_start=(0.0, 0.0),
                pixel_end=(120.0, 0.0),
                meters=10.0,
                elapsed_seconds=2.0,
            )
        ]
        table = build_calibration_table(segments)
        assert table.loc[0, "pixels_per_meter"] == 12.0
        assert table.loc[0, "pseudo_ground_truth_speed_kmh"] == 18.0

    def test_invalid_distance_raises(self) -> None:
        with pytest.raises(ValueError):
            pseudo_ground_truth_speed_kmh(distance_m=0.0, elapsed_seconds=1.0)

    def test_temperature_scaling_preserves_probability_rows(self) -> None:
        probabilities = np.array([[0.9, 0.08, 0.02], [0.2, 0.7, 0.1]])
        calibrated = apply_temperature_scaling(probabilities, 1.5)
        np.testing.assert_allclose(calibrated.sum(axis=1), 1.0)
        assert calibrated[0, 0] < probabilities[0, 0]

    def test_temperature_is_fit_only_from_supplied_validation_data(self) -> None:
        probabilities = np.array([[0.99, 0.005, 0.005], [0.99, 0.005, 0.005]])
        temperature = fit_temperature(probabilities, np.array([0, 1]))
        assert 0.5 <= temperature <= 3.0

    def test_multiclass_brier_is_zero_for_perfect_predictions(self) -> None:
        probabilities = np.eye(3)
        assert multiclass_brier_score(np.array([0, 1, 2]), probabilities) == 0.0

    @pytest.mark.parametrize(
        "probabilities",
        [
            [[2.0, 0.0, 0.0]],
            [[0.0, 0.0, 0.0]],
            [[0.5, 0.4, 0.0]],
            [[-0.1, 0.5, 0.6]],
            [[np.nan, 0.5, 0.5]],
            [[np.inf, 0.0, 0.0]],
        ],
    )
    def test_probability_contract_rejects_invalid_distributions(
        self, probabilities: list[list[float]]
    ) -> None:
        with pytest.raises(ValueError, match="probabilit"):
            validate_probability_matrix(probabilities)

    def test_probability_contract_accepts_float32_and_boundary_zeros(self) -> None:
        probabilities = np.array([[1.0, 0.0, 0.0], [0.2, 0.3, 0.5]], dtype=np.float32)
        validated = validate_probability_matrix(probabilities, rows=2)

        assert validated.dtype == np.float64
        np.testing.assert_allclose(validated, probabilities)

    @pytest.mark.parametrize(
        "probabilities",
        (
            [[True, False, False]],
            [["1", "0", "0"]],
        ),
    )
    def test_probability_contract_rejects_non_numeric_values(
        self, probabilities: object
    ) -> None:
        with pytest.raises(ValueError, match="numeric matrix"):
            validate_probability_matrix(probabilities)
