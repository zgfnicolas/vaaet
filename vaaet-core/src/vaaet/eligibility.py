# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Contrato portable de evidencia necesaria para declarar producción."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from types import MappingProxyType

MINIMUM_F1_MACRO = 0.88
MINIMUM_PRECISION = MappingProxyType({"normal": 0.93, "reduced": 0.88, "congested": 0.90})
MINIMUM_RECALL = MappingProxyType({"normal": 0.93, "reduced": 0.90, "congested": 0.85})
MAXIMUM_NORMAL_CONGESTED_ERROR = 0.01
MAXIMUM_ECE = 0.05
MINIMUM_TELEMETRY_V3_COVERAGE = 0.95
MINIMUM_CONGESTED_MINUTES = 100
MINIMUM_CONGESTED_CLIPS = 20
MINIMUM_NEGATIVE_EXPOSURE_HOURS = 300.0
MAXIMUM_FALSE_CANDIDATES_PER_HOUR = 0.01


def production_evidence_errors(
    *,
    lifecycle: Mapping[str, object],
    metrics: Mapping[str, object],
    provenance: Mapping[str, object],
    human_holdout: object,
) -> tuple[str, ...]:
    """Devuelve contradicciones que impiden aceptar un bundle de producción."""

    errors: list[str] = []
    if lifecycle.get("training_mode") != "hitl-retraining":
        errors.append("production requires HITL retraining")
    if lifecycle.get("input_policy") != "canonical-v3":
        errors.append("production requires canonical-v3 input policy")
    if not isinstance(human_holdout, Mapping) or not provenance.get("human_holdout"):
        errors.append("production requires a frozen human holdout")
    blockers = provenance.get("promotion_blockers")
    if not isinstance(blockers, list) or blockers:
        errors.append("production requires an empty promotion blocker list")
    _minimum(
        errors,
        provenance.get("telemetry_v3_coverage"),
        MINIMUM_TELEMETRY_V3_COVERAGE,
        "telemetry v3 coverage",
    )
    _exact(errors, metrics.get("automatic_accident_states"), 0, "automatic Accident states")
    _minimum(
        errors, metrics.get("congested_minutes"), MINIMUM_CONGESTED_MINUTES, "Congested minutes"
    )
    _minimum(errors, metrics.get("congested_clips"), MINIMUM_CONGESTED_CLIPS, "Congested clips")
    _minimum(
        errors,
        metrics.get("negative_exposure_hours"),
        MINIMUM_NEGATIVE_EXPOSURE_HOURS,
        "negative exposure hours",
    )
    _maximum(
        errors,
        metrics.get("false_candidates_upper_95"),
        MAXIMUM_FALSE_CANDIDATES_PER_HOUR,
        "false-alert upper bound",
        strict=True,
    )
    _rate_consistency(errors, metrics)
    direct = _interval_errors(errors, metrics.get("grouped_direct_intervals"), "direct")
    final = _interval_errors(errors, metrics.get("grouped_final_intervals"), "final")
    _point_consistency(errors, metrics, direct, final)
    return tuple(errors)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _minimum(errors: list[str], value: object, threshold: float, label: str) -> None:
    number = _number(value)
    if number is None or number < threshold:
        errors.append(f"{label} is missing or below {threshold}")


def _maximum(
    errors: list[str], value: object, threshold: float, label: str, *, strict: bool = False
) -> None:
    number = _number(value)
    failed = number is None or number < 0 or (number >= threshold if strict else number > threshold)
    if failed:
        relation = "below" if strict else "at most"
        errors.append(f"{label} must be {relation} {threshold}")


def _exact(errors: list[str], value: object, expected: int, label: str) -> None:
    if type(value) is not int or value != expected:
        errors.append(f"{label} must equal {expected}")


def _rate_consistency(errors: list[str], metrics: Mapping[str, object]) -> None:
    count = metrics.get("incident_candidate_count")
    exposure = _number(metrics.get("negative_exposure_hours"))
    rate = _number(metrics.get("false_candidates_per_hour"))
    if type(count) is not int or count < 0 or exposure is None or exposure <= 0 or rate is None:
        errors.append("false-alert count, exposure and rate must be valid")
        return
    if not math.isclose(rate, count / exposure, rel_tol=1e-9, abs_tol=1e-12):
        errors.append("false-alert count, exposure and rate are inconsistent")


def _interval_errors(  # noqa: C901 - valida evidencia estadística contractual.
    errors: list[str], value: object, scope: str
) -> dict[str, Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        errors.append(f"{scope} grouped intervals are missing")
        return {}
    rows: dict[str, Mapping[str, object]] = {}
    for item in value:
        if not isinstance(item, Mapping) or not isinstance(item.get("metric"), str):
            errors.append(f"{scope} grouped intervals are malformed")
            return {}
        name = str(item["metric"])
        if name in rows:
            errors.append(f"{scope} grouped intervals contain duplicate metric {name}")
            return {}
        rows[name] = item
    thresholds = {
        "f1_macro": ("low", MINIMUM_F1_MACRO),
        **{
            f"precision_{name}": ("low", threshold) for name, threshold in MINIMUM_PRECISION.items()
        },
        **{f"recall_{name}": ("low", threshold) for name, threshold in MINIMUM_RECALL.items()},
        "normal_congested_error": ("high", MAXIMUM_NORMAL_CONGESTED_ERROR),
    }
    if scope == "final":
        thresholds["ece"] = ("high", MAXIMUM_ECE)
    for metric, (bound, threshold) in thresholds.items():
        row = rows.get(metric)
        if row is None or type(row.get("sufficient")) is not bool or not row["sufficient"]:
            errors.append(f"{scope} interval {metric} is missing or insufficient")
            continue
        point = _number(row.get("value"))
        low = _number(row.get("ci_95_low"))
        high = _number(row.get("ci_95_high"))
        fraction = _number(row.get("evaluable_fraction"))
        groups = row.get("group_count")
        samples = row.get("bootstrap_samples")
        if (
            row.get("method") != "grouped-bootstrap"
            or type(groups) is not int
            or groups < 2
            or type(samples) is not int
            or samples < 1
            or fraction is None
            or not 0.95 <= fraction <= 1.0
        ):
            errors.append(f"{scope} interval {metric} lacks grouped-bootstrap evidence")
        if (
            point is None
            or low is None
            or high is None
            or low < 0
            or high > 1
            or high < low
            or not low <= point <= high
        ):
            errors.append(f"{scope} interval {metric} has invalid bounds")
        elif (bound == "low" and low < threshold) or (bound == "high" and high > threshold):
            errors.append(f"{scope} interval {metric} does not pass its gate")
    return rows


def _point_consistency(
    errors: list[str],
    metrics: Mapping[str, object],
    direct: Mapping[str, Mapping[str, object]],
    final: Mapping[str, Mapping[str, object]],
) -> None:
    comparisons = (
        ("direct_f1_macro", direct, "f1_macro"),
        ("final_f1_macro", final, "f1_macro"),
        ("direct_normal_congested_error", direct, "normal_congested_error"),
        ("final_normal_congested_error", final, "normal_congested_error"),
        ("ece", final, "ece"),
    )
    for field, intervals, metric in comparisons:
        declared = _number(metrics.get(field))
        row = intervals.get(metric)
        measured = _number(row.get("value")) if row is not None else None
        if (
            declared is None
            or measured is None
            or not math.isclose(declared, measured, rel_tol=1e-9, abs_tol=1e-12)
        ):
            errors.append(f"{field} is missing or inconsistent with grouped evidence")


__all__ = [
    "MAXIMUM_ECE",
    "MAXIMUM_FALSE_CANDIDATES_PER_HOUR",
    "MAXIMUM_NORMAL_CONGESTED_ERROR",
    "MINIMUM_CONGESTED_CLIPS",
    "MINIMUM_CONGESTED_MINUTES",
    "MINIMUM_F1_MACRO",
    "MINIMUM_NEGATIVE_EXPOSURE_HOURS",
    "MINIMUM_PRECISION",
    "MINIMUM_RECALL",
    "MINIMUM_TELEMETRY_V3_COVERAGE",
    "production_evidence_errors",
]
