# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Clasificación jerárquica de tránsito compartida entre entrenamiento y serving."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from vaaet.calibration import apply_temperature_scaling, validate_probability_matrix
from vaaet.features.engineering import engineer_features
from vaaet.features.labeling import assign_instant_state
from vaaet.inference.policy import (
    CLASSIFICATION_RESULT_COLUMNS,
    apply_conservative_accident_gate,
    apply_stable_state_policy,
    empty_classification_result,
)
from vaaet.inference.protocols import FeatureScaler, TrafficStateModel
from vaaet.lifecycle import ModelInputPolicy, apply_model_input_policy
from vaaet.settings import (
    DEFAULT_MIN_PROBABILITY_MARGIN,
    FEATURE_COLS,
    MODEL_STATE_LABELS,
    MODEL_VERSION,
    RECOVERY_PERSISTENCE_MINUTES,
    STATE_LABELS,
    WORSENING_PERSISTENCE_MINUTES,
)

__all__ = [
    "CLASSIFICATION_RESULT_COLUMNS",
    "apply_conservative_accident_gate",
    "apply_stable_state_policy",
    "classify_raw_telemetry",
    "classify_telemetry_dataframe",
    "assert_progressive_batch_parity",
]


def assert_progressive_batch_parity(
    progressive: pd.DataFrame,
    batch: pd.DataFrame,
) -> None:
    """Detiene la inferencia si el HUD y la salida persistible no coinciden."""

    if progressive.empty and batch.empty:
        return
    if len(progressive) != len(batch):
        raise RuntimeError(
            "Progressive HUD and batch inference produced a different number of states."
        )
    required_progressive = {
        "clip_id",
        "continuity_id",
        "record_time",
        "traffic_state",
        "state_label",
        "confidence",
        "incident_candidate",
    }
    if missing := sorted(required_progressive - set(progressive.columns)):
        raise RuntimeError(f"Progressive HUD output is missing parity fields: {missing}")
    left = progressive.loc[:, sorted(required_progressive)].copy()
    right = batch.assign(
        incident_candidate=batch["accident_rule_triggered"].astype(bool)
    ).loc[:, sorted(required_progressive)]
    for frame in (left, right):
        frame["record_time"] = pd.to_datetime(frame["record_time"], utc=True)
        frame["confidence"] = pd.to_numeric(frame["confidence"], errors="raise").round(4)
        frame["traffic_state"] = pd.to_numeric(
            frame["traffic_state"], errors="raise"
        ).astype(int)
    left = left.sort_values(["clip_id", "continuity_id", "record_time"]).reset_index(drop=True)
    right = right.sort_values(["clip_id", "continuity_id", "record_time"]).reset_index(drop=True)
    if not left.equals(right):
        raise RuntimeError(
            "Progressive HUD state diverged from batch inference; results were not persisted."
        )


def _empty_classification_result(frame: pd.DataFrame) -> pd.DataFrame:
    """Conserva el helper privado para consumidores internos de VAAET 4.x."""

    return empty_classification_result(frame)


def _ensure_feature_compatibility(scaler: FeatureScaler, feature_cols: list[str]) -> None:
    expected = getattr(scaler, "n_features_in_", None)
    if expected is not None and int(expected) != len(feature_cols):
        raise ValueError(
            "Scaler feature count does not match FEATURE_COLS. Re-run training with bundle v3."
        )


def _validate_probabilities(probabilities: object, rows: int) -> np.ndarray:
    try:
        return validate_probability_matrix(
            probabilities,
            rows=rows,
            classes=len(MODEL_STATE_LABELS),
        )
    except ValueError as exc:
        detail = str(exc)
        if "shape" in detail:
            message = (
                "The bundle model must return exactly three probabilities per row "
                "in the order Normal, Reduced, Congested."
            )
        else:
            message = (
                "The bundle model returned invalid values; every row must be a finite "
                "probability distribution between 0 and 1 whose sum is 1."
            )
        raise ValueError(message) from exc


def classify_telemetry_dataframe(
    df_features: pd.DataFrame,
    model: TrafficStateModel,
    scaler: FeatureScaler,
    *,
    label_mapping: Mapping[int, str] | None = None,
    feature_cols: list[str] | None = None,
    model_version: str = MODEL_VERSION,
    model_revision: str | None = None,
    decision_policy: Mapping[str, object] | None = None,
    input_policy: ModelInputPolicy | str = ModelInputPolicy.CANONICAL_V3,
) -> pd.DataFrame:
    """Ejecuta el MLP de tres clases y la cadena de decisión de producción."""

    del label_mapping  # Las etiquetas públicas se gobiernan centralmente.
    if df_features.empty:
        return _empty_classification_result(df_features)
    active_features = feature_cols or FEATURE_COLS
    _ensure_feature_compatibility(scaler, active_features)
    if active_features != FEATURE_COLS:
        raise ValueError("Custom feature order is not supported by bundle v3.")
    model_matrix = apply_model_input_policy(df_features, input_policy)
    probabilities = _validate_probabilities(
        model.predict(scaler.transform(model_matrix.to_numpy()), verbose=0), len(df_features)
    )
    policy = dict(decision_policy or {})
    calibrated_probabilities = apply_temperature_scaling(
        probabilities, float(policy.get("temperature", 1.0))
    )
    result = apply_stable_state_policy(
        df_features,
        calibrated_probabilities,
        class_thresholds=policy.get("class_thresholds"),
        minimum_margin=float(
            policy.get("minimum_probability_margin", DEFAULT_MIN_PROBABILITY_MARGIN)
        ),
        worsening_persistence=int(
            policy.get("worsening_persistence_minutes", WORSENING_PERSISTENCE_MINUTES)
        ),
        recovery_persistence=int(
            policy.get("recovery_persistence_minutes", RECOVERY_PERSISTENCE_MINUTES)
        ),
    )
    result["model_version"] = model_version
    result["model_revision"] = model_revision
    result = apply_conservative_accident_gate(result)
    result["traffic_state"] = result["traffic_state"].astype(int)
    result["state_label"] = result["traffic_state"].map(STATE_LABELS)
    return result


def classify_raw_telemetry(
    df_telemetry: pd.DataFrame,
    model: TrafficStateModel,
    scaler: FeatureScaler,
    *,
    label_mapping: Mapping[int, str] | None = None,
    feature_cols: list[str] | None = None,
    model_version: str = MODEL_VERSION,
    model_revision: str | None = None,
    inference_mode: str = "stable",
    decision_policy: Mapping[str, object] | None = None,
    input_policy: ModelInputPolicy | str = ModelInputPolicy.CANONICAL_V3,
) -> pd.DataFrame:
    """Genera features de minutos completos y los clasifica de manera segura."""

    if df_telemetry.empty:
        return _empty_classification_result(df_telemetry)
    if inference_mode == "sprint":
        result = df_telemetry.copy()
        result["traffic_state"] = assign_instant_state(result).astype(int)
        result["state_label"] = result["traffic_state"].map(STATE_LABELS)
        result["confidence"] = 0.0
        result["model_version"] = "sprint_heuristic_non_production"
        result["accident_rule_triggered"] = False
        return result
    features = engineer_features(df_telemetry)
    if features.empty:
        return _empty_classification_result(features)
    return classify_telemetry_dataframe(
        features,
        model,
        scaler,
        label_mapping=label_mapping,
        feature_cols=feature_cols,
        model_version=model_version,
        model_revision=model_revision,
        decision_policy=decision_policy,
        input_policy=input_policy,
    )
