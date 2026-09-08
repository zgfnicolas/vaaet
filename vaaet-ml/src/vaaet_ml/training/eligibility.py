# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Gates actuales de elegibilidad de candidatos, separados del notebook."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isclose, isfinite

import numpy as np
import pandas as pd
from vaaet import eligibility as core_eligibility

from vaaet_ml.data.datasets import build_group_ids
from vaaet_ml.evaluation.reporting_metrics import false_alert_rate_upper_bound
from vaaet_ml.training.lifecycle import TrainingMode

__all__ = ["CandidateEligibility", "evaluate_candidate_eligibility"]

_MINIMUM_F1_MACRO = core_eligibility.MINIMUM_F1_MACRO
_MAXIMUM_DIRECT_NORMAL_CONGESTED_ERROR = core_eligibility.MAXIMUM_NORMAL_CONGESTED_ERROR
_MAXIMUM_ECE = core_eligibility.MAXIMUM_ECE
_MINIMUM_CONGESTED_MINUTES = core_eligibility.MINIMUM_CONGESTED_MINUTES
_MINIMUM_CONGESTED_CLIPS = core_eligibility.MINIMUM_CONGESTED_CLIPS
_MINIMUM_NEGATIVE_EXPOSURE_HOURS = core_eligibility.MINIMUM_NEGATIVE_EXPOSURE_HOURS
_MAXIMUM_FALSE_CANDIDATES_PER_HOUR = core_eligibility.MAXIMUM_FALSE_CANDIDATES_PER_HOUR
_MINIMUM_PRECISION = {
    code: core_eligibility.MINIMUM_PRECISION[label]
    for code, label in enumerate(("normal", "reduced", "congested"))
}
_MINIMUM_RECALL = {
    code: core_eligibility.MINIMUM_RECALL[label]
    for code, label in enumerate(("normal", "reduced", "congested"))
}


@dataclass(frozen=True)
class CandidateEligibility:
    """Resultado explicable de los gates vigentes; no ejecuta una promoción."""

    metric_gates: dict[str, bool]
    promotion_blockers: tuple[str, ...]
    human_holdout: bool
    congested_minutes: int
    congested_clips: int
    production_eligible: bool


def evaluate_candidate_eligibility(  # noqa: C901 - reúne gates regulatorios explícitos.
    *,
    training_mode: TrainingMode | str,
    dataset_blockers: Sequence[str],
    human_holdout: bool,
    test_frame: pd.DataFrame,
    actual: Sequence[int],
    predicted: Sequence[int],
    direct_predicted: Sequence[int] | None = None,
    f1_macro: float,
    direct_normal_congested_error: float,
    final_normal_congested_error: float | None = None,
    expected_calibration_error: float,
    negative_exposure_hours: float,
    false_candidates_per_hour: float,
    direct_intervals: pd.DataFrame | None = None,
    final_intervals: pd.DataFrame | None = None,
    false_candidates_upper_95: float | None = None,
    false_candidate_count: int | None = None,
) -> CandidateEligibility:
    """Aplica gates conservadores sobre límites agrupados del 95 %."""

    mode = TrainingMode(training_mode)
    truth = np.asarray(actual, dtype=int)
    final = np.asarray(predicted, dtype=int)
    direct = final if direct_predicted is None else np.asarray(direct_predicted, dtype=int)
    _validate_eligibility_inputs(test_frame, truth, direct, final)
    final_extreme = (
        direct_normal_congested_error
        if final_normal_congested_error is None
        else final_normal_congested_error
    )
    for name, value in (
        ("f1_macro", f1_macro),
        ("direct_normal_congested_error", direct_normal_congested_error),
        ("final_normal_congested_error", final_extreme),
        ("expected_calibration_error", expected_calibration_error),
        ("negative_exposure_hours", negative_exposure_hours),
    ):
        _validate_metric(name, value)
    if negative_exposure_hours > 0:
        _validate_metric("false_candidates_per_hour", false_candidates_per_hour)
    if false_candidates_upper_95 is not None:
        _validate_metric("false_candidates_upper_95", false_candidates_upper_95)
    if false_candidate_count is not None:
        if type(false_candidate_count) is not int or false_candidate_count < 0:
            raise ValueError("false_candidate_count must be a non-negative integer.")
        if negative_exposure_hours > 0 and not isclose(
            false_candidates_per_hour,
            false_candidate_count / negative_exposure_hours,
            rel_tol=1e-9,
            abs_tol=1e-12,
        ):
            raise ValueError("False-alert count, exposure and rate are inconsistent.")
    if false_candidates_upper_95 is not None:
        if false_candidate_count is None or negative_exposure_hours <= 0:
            raise ValueError(
                "False-alert upper-bound evidence requires a candidate count and positive exposure."
            )
        expected_upper = false_alert_rate_upper_bound(
            false_candidate_count, negative_exposure_hours
        )
        if not isclose(
            false_candidates_upper_95, expected_upper, rel_tol=1e-9, abs_tol=1e-12
        ):
            raise ValueError("False-alert upper bound is inconsistent with count and exposure.")

    metric_gates = _interval_gates(direct_intervals, final_intervals)
    _validate_interval_point_consistency(
        direct_intervals,
        final_intervals,
        f1_macro=f1_macro,
        direct_error=direct_normal_congested_error,
        final_error=final_extreme,
        ece=expected_calibration_error,
    )
    blockers = list(dataset_blockers)
    if mode is TrainingMode.SEED_BOOTSTRAP:
        blockers.append("seed bootstrap uses weak proxy supervision and is pilot-only")
    if not human_holdout:
        blockers.append("validation/test are not a frozen human-validated holdout")
    if direct_intervals is None or final_intervals is None:
        blockers.append("grouped 95% confidence intervals are missing")
    blockers.extend(
        f"metric gate failed: {name}" for name, passed in metric_gates.items() if not passed
    )

    congested_minutes = int((truth == 2).sum())
    congested_clips = _congested_clip_count(test_frame, truth)
    if congested_minutes < _MINIMUM_CONGESTED_MINUTES or congested_clips < _MINIMUM_CONGESTED_CLIPS:
        blockers.append(
            f"Congested support insufficient: {congested_minutes} minutes / {congested_clips} clips"
        )
    if negative_exposure_hours < _MINIMUM_NEGATIVE_EXPOSURE_HOURS:
        blockers.append(
            f"incident negative exposure insufficient: {negative_exposure_hours:.2f}/300 h"
        )
    elif false_candidates_upper_95 is None:
        blockers.append("incident false-alert upper 95% bound is missing")
    elif false_candidates_upper_95 >= _MAXIMUM_FALSE_CANDIDATES_PER_HOUR:
        blockers.append("incident candidate rate is not below 1 per 100 hours")
    return CandidateEligibility(
        metric_gates=metric_gates,
        promotion_blockers=tuple(blockers),
        human_holdout=human_holdout,
        congested_minutes=congested_minutes,
        congested_clips=congested_clips,
        production_eligible=not blockers and mode is TrainingMode.HITL_RETRAINING,
    )


def _congested_clip_count(test_frame: pd.DataFrame, truth: np.ndarray) -> int:
    congested = test_frame.iloc[np.flatnonzero(truth == 2)]
    return 0 if congested.empty else int(build_group_ids(congested).nunique())


def _validate_eligibility_inputs(
    test_frame: pd.DataFrame,
    truth: np.ndarray,
    direct: np.ndarray,
    final: np.ndarray,
) -> None:
    if (
        truth.ndim != 1
        or truth.shape != final.shape
        or direct.shape != truth.shape
        or len(truth) != len(test_frame)
    ):
        raise ValueError(
            "Eligibility requires aligned one-dimensional test targets and predictions."
        )
    if (
        not np.isin(truth, (0, 1, 2)).all()
        or not np.isin(direct, (0, 1, 2)).all()
        or not np.isin(final, (0, 1, 2)).all()
    ):
        raise ValueError("Eligibility is defined only for the three stable model states.")


def _validate_metric(name: str, value: float) -> None:
    if not isfinite(float(value)) or float(value) < 0:
        raise ValueError(f"{name} must be a finite non-negative value.")


def _interval_gates(
    direct: pd.DataFrame | None,
    final: pd.DataFrame | None,
) -> dict[str, bool]:
    gates: dict[str, bool] = {}
    thresholds = {
        "f1_macro": _MINIMUM_F1_MACRO,
        **{
            f"precision_{label}": _MINIMUM_PRECISION[state]
            for state, label in ((0, "normal"), (1, "reduced"), (2, "congested"))
        },
        **{
            f"recall_{label}": _MINIMUM_RECALL[state]
            for state, label in ((0, "normal"), (1, "reduced"), (2, "congested"))
        },
    }
    for scope, intervals in (("direct", direct), ("final", final)):
        lookup = _interval_lookup(intervals)
        required = {*thresholds, "normal_congested_error"}
        if scope == "final":
            required.add("ece")
        if intervals is not None and (missing := sorted(required - set(lookup))):
            raise ValueError(f"{scope} grouped interval evidence is incomplete: {missing}")
        for metric, threshold in thresholds.items():
            row = lookup.get(metric)
            gates[f"{scope}_{metric}"] = bool(
                row is not None and row["sufficient"] and float(row["ci_95_low"]) >= threshold
            )
        extreme = lookup.get("normal_congested_error")
        gates[f"{scope}_normal_congested_error"] = bool(
            extreme is not None
            and extreme["sufficient"]
            and float(extreme["ci_95_high"]) <= _MAXIMUM_DIRECT_NORMAL_CONGESTED_ERROR
        )
    final_lookup = _interval_lookup(final)
    ece = final_lookup.get("ece")
    gates["final_ece"] = bool(
        ece is not None and ece["sufficient"] and float(ece["ci_95_high"]) <= _MAXIMUM_ECE
    )
    return gates


def _interval_lookup(frame: pd.DataFrame | None) -> dict[str, dict[str, object]]:
    if frame is None or frame.empty:
        return {}
    required = {
        "metric",
        "value",
        "ci_95_low",
        "ci_95_high",
        "evaluable_fraction",
        "method",
        "group_count",
        "bootstrap_samples",
        "sufficient",
    }
    if missing := sorted(required - set(frame.columns)):
        raise ValueError(f"Grouped interval evidence is missing fields: {missing}")
    rows: dict[str, dict[str, object]] = {}
    for row in frame.to_dict(orient="records"):
        metric = row["metric"]
        if not isinstance(metric, str) or not metric:
            raise ValueError("Grouped interval metric names must be non-empty strings.")
        if metric in rows:
            raise ValueError(f"Grouped interval evidence duplicates metric: {metric}")
        _validate_interval_row(row, metric)
        rows[metric] = row
    return rows


def _validate_interval_row(row: dict[str, object], metric: str) -> None:
    """Valida la evidencia de una métrica agrupada sin decidir su gate."""

    if type(row["sufficient"]) is not bool:
        raise ValueError(f"Grouped interval sufficiency must be boolean: {metric}")
    if row["method"] != "grouped-bootstrap":
        raise ValueError(f"Grouped interval method is invalid: {metric}")
    if type(row["group_count"]) is not int or row["group_count"] < 2:
        raise ValueError(f"Grouped interval group count is invalid: {metric}")
    if type(row["bootstrap_samples"]) is not int or row["bootstrap_samples"] < 1:
        raise ValueError(f"Grouped interval sample count is invalid: {metric}")
    point = float(row["value"])
    low = float(row["ci_95_low"])
    high = float(row["ci_95_high"])
    fraction = float(row["evaluable_fraction"])
    if (
        not all(isfinite(value) for value in (point, low, high, fraction))
        or low < 0
        or high > 1
        or high < low
        or not low <= point <= high
        or not 0 <= fraction <= 1
    ):
        raise ValueError(f"Grouped interval bounds are invalid: {metric}")


def _validate_interval_point_consistency(
    direct: pd.DataFrame | None,
    final: pd.DataFrame | None,
    *,
    f1_macro: float,
    direct_error: float,
    final_error: float,
    ece: float,
) -> None:
    if direct is None or final is None:
        return
    direct_lookup = _interval_lookup(direct)
    final_lookup = _interval_lookup(final)
    comparisons = (
        ("final f1_macro", f1_macro, final_lookup["f1_macro"]["value"]),
        (
            "direct normal_congested_error",
            direct_error,
            direct_lookup["normal_congested_error"]["value"],
        ),
        (
            "final normal_congested_error",
            final_error,
            final_lookup["normal_congested_error"]["value"],
        ),
        ("final ece", ece, final_lookup["ece"]["value"]),
    )
    for name, declared, measured in comparisons:
        if not isclose(float(declared), float(measured), rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError(f"{name} is inconsistent with grouped interval evidence.")
