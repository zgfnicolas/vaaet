# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Utilidades livianas de calibración para validar velocidades académicamente."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from statistics import median

import numpy as np
import pandas as pd

__all__ = [
    "CalibrationSegment",
    "aggregate_pixels_per_meter",
    "build_calibration_table",
    "pixels_per_meter_from_segment",
    "pseudo_ground_truth_speed_kmh",
    "apply_temperature_scaling",
    "fit_temperature",
    "multiclass_brier_score",
    "validate_probability_matrix",
]


def validate_probability_matrix(
    probabilities: object,
    *,
    rows: int | None = None,
    classes: int = 3,
) -> np.ndarray:
    """Valida una distribución multiclase sin corregir salidas inválidas."""

    raw_values = np.asarray(probabilities)
    if np.issubdtype(raw_values.dtype, np.bool_) or raw_values.dtype.kind in {"U", "S"}:
        raise ValueError("probabilities must be a numeric matrix, not booleans or text.")
    values = np.asarray(probabilities, dtype=float)
    expected_rows = len(values) if rows is None and values.ndim == 2 else rows
    if expected_rows is None or values.shape != (expected_rows, classes):
        raise ValueError(
            f"probabilities must have shape ({expected_rows if expected_rows is not None else 'N'}, "
            f"{classes})."
        )
    if not np.isfinite(values).all():
        raise ValueError("probabilities must contain only finite values.")
    if (values < 0).any() or (values > 1).any():
        raise ValueError("probabilities must remain between 0 and 1.")
    if not np.allclose(values.sum(axis=1), 1.0, rtol=0.0, atol=1e-6):
        raise ValueError("Each probability row must sum to 1 within absolute tolerance 1e-6.")
    return values


def apply_temperature_scaling(probabilities: np.ndarray, temperature: float) -> np.ndarray:
    """Calibra probabilidades multiclase mediante una temperatura escalar."""
    values = validate_probability_matrix(probabilities)
    if not np.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be a finite positive number.")
    logits = np.log(np.clip(values, 1e-12, 1.0)) / float(temperature)
    logits -= logits.max(axis=1, keepdims=True)
    calibrated = np.exp(logits)
    return calibrated / calibrated.sum(axis=1, keepdims=True)


def fit_temperature(probabilities: np.ndarray, y_true: np.ndarray) -> float:
    """Selecciona la temperatura usando sólo la log-verosimilitud de validación."""
    values = validate_probability_matrix(probabilities)
    truth = np.asarray(y_true, dtype=int)
    if len(truth) == 0 or len(values) != len(truth):
        raise ValueError("Validation probabilities must have shape (records, 3).")
    candidates = np.geomspace(0.5, 3.0, 80)
    losses = []
    for candidate in candidates:
        calibrated = apply_temperature_scaling(values, float(candidate))
        losses.append(-np.log(np.clip(calibrated[np.arange(len(truth)), truth], 1e-12, 1)).mean())
    return round(float(candidates[int(np.argmin(losses))]), 6)


def multiclass_brier_score(y_true: np.ndarray, probabilities: np.ndarray) -> float:
    """Calcula el error cuadrático medio sobre los tres estados estables."""
    truth = np.asarray(y_true, dtype=int)
    values = validate_probability_matrix(probabilities)
    if len(values) != len(truth):
        raise ValueError("probabilities must have shape (records, 3).")
    one_hot = np.eye(3)[truth]
    return float(np.mean(np.sum((values - one_hot) ** 2, axis=1)))


@dataclass(frozen=True)
class CalibrationSegment:
    """Representa un tramo conocido del puente para calibración manual."""

    name: str
    pixel_start: tuple[float, float]
    pixel_end: tuple[float, float]
    meters: float
    elapsed_seconds: float | None = None


def _pixel_distance(segment: CalibrationSegment) -> float:
    return hypot(
        float(segment.pixel_end[0]) - float(segment.pixel_start[0]),
        float(segment.pixel_end[1]) - float(segment.pixel_start[1]),
    )


def pixels_per_meter_from_segment(segment: CalibrationSegment) -> float:
    """Calcula la relación entre píxeles y metros de un tramo."""
    if segment.meters <= 0:
        raise ValueError("meters must be > 0")
    px_distance = _pixel_distance(segment)
    if px_distance <= 0:
        raise ValueError("pixel distance must be > 0")
    return px_distance / float(segment.meters)


def aggregate_pixels_per_meter(
    segments: list[CalibrationSegment],
) -> float:
    """Agrega en forma robusta relaciones obtenidas de varios tramos."""
    if not segments:
        raise ValueError("at least one calibration segment is required")
    ratios = [pixels_per_meter_from_segment(segment) for segment in segments]
    return round(float(median(ratios)), 4)


def pseudo_ground_truth_speed_kmh(
    *,
    distance_m: float,
    elapsed_seconds: float,
) -> float:
    """Convierte un tiempo manual entre referencias a kilómetros por hora."""
    if distance_m <= 0:
        raise ValueError("distance_m must be > 0")
    if elapsed_seconds <= 0:
        raise ValueError("elapsed_seconds must be > 0")
    return round((distance_m / elapsed_seconds) * 3.6, 4)


def build_calibration_table(
    segments: list[CalibrationSegment],
) -> pd.DataFrame:
    """Construye una tabla apta para revisar la calibración en un notebook."""
    rows: list[dict[str, float | str | None]] = []
    for segment in segments:
        ppm = pixels_per_meter_from_segment(segment)
        speed_kmh = None
        if segment.elapsed_seconds is not None:
            speed_kmh = pseudo_ground_truth_speed_kmh(
                distance_m=segment.meters,
                elapsed_seconds=segment.elapsed_seconds,
            )
        rows.append(
            {
                "name": segment.name,
                "meters": float(segment.meters),
                "pixel_distance": round(_pixel_distance(segment), 4),
                "pixels_per_meter": round(ppm, 4),
                "elapsed_seconds": segment.elapsed_seconds,
                "pseudo_ground_truth_speed_kmh": speed_kmh,
            }
        )
    return pd.DataFrame(rows)
