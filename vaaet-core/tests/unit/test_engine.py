# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import numpy as np
import pandas as pd

from vaaet.inference.bundle import LoadedTrafficBundle
from vaaet.inference.engine import TrafficStateEngine
from vaaet.settings import FEATURE_COLS, STATE_LABELS


class _IdentityScaler:
    n_features_in_ = len(FEATURE_COLS)

    def transform(self, values: object) -> np.ndarray:
        return np.asarray(values, dtype=float)


class _NormalModel:
    def predict(self, values: object, verbose: int = 0) -> np.ndarray:
        return np.tile(np.array([0.94, 0.04, 0.02]), (len(values), 1))


def _raw_minutes(count: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "clip_id": ["clip-a"] * count,
            "continuity_id": ["clip-a:continuity-0001"] * count,
            "record_time": pd.date_range("2025-05-01T11:00:00Z", periods=count, freq="1min"),
            "avg_speed": [30.0] * count,
            "total_vehicles": [5] * count,
            "count_car": [4] * count,
            "count_truck": [1] * count,
            "count_bus": [0] * count,
            "count_motorcycle": [0] * count,
            "count_bicycle": [0] * count,
            "speed_sample_count": [5] * count,
            "rejected_speed_count": [0] * count,
            "near_zero_motion_count": [0] * count,
            "stationary_confirmed_count": [0] * count,
            "speed_measurement_quality": [1.0] * count,
            "optical_flow_tracking_ratio": [1.0] * count,
        }
    )


def _engine() -> TrafficStateEngine:
    return TrafficStateEngine(
        LoadedTrafficBundle(
            manifest={
                "model_version": "mlp-v3.0",
                "decision_policy": {
                    "class_thresholds": {"0": 0.5, "1": 0.5, "2": 0.5},
                    "minimum_probability_margin": 0.05,
                    "worsening_persistence_minutes": 2,
                    "recovery_persistence_minutes": 2,
                    "temperature": 1.0,
                },
            },
            model=_NormalModel(),
            scaler=_IdentityScaler(),
            label_mapping=dict(STATE_LABELS),
            deployment_stage="production",
            input_policy="canonical-v3",
            model_revision="a" * 64,
            historical_only=False,
        )
    )


def test_engine_returns_no_prediction_before_two_complete_minutes() -> None:
    assert _engine().predict_latest(_raw_minutes(1)) is None


def test_engine_returns_a_typed_stable_prediction() -> None:
    prediction = _engine().predict_latest(_raw_minutes(2))
    assert prediction is not None
    assert prediction.state == 0
    assert prediction.label == "Normal"
    assert prediction.incident_candidate is False
