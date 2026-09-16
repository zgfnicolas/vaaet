# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Contratos de la validación cruzada agrupada extraída del notebook."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.settings import FEATURE_COLS

from vaaet_ml.training.cross_validation import run_grouped_cross_validation
from vaaet_ml.training.lifecycle import ModelInputPolicy


class _IdentityScaler:
    def fit_transform(self, features: np.ndarray) -> np.ndarray:
        return features

    def transform(self, features: np.ndarray) -> np.ndarray:
        return features


class _PredictingModel:
    def fit(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        return _History()

    def predict(self, features: np.ndarray, *, verbose: int) -> np.ndarray:
        del verbose
        states = features[:, 0].astype(int)
        return np.eye(3, dtype=float)[states]


class _InvalidProbabilityModel(_PredictingModel):
    def predict(self, features: np.ndarray, *, verbose: int) -> np.ndarray:
        del verbose
        return np.zeros((len(features), 3), dtype=float)


class _History:
    history = {
        "loss": [0.4],
        "val_loss": [0.4],
        "accuracy": [1.0],
        "val_accuracy": [1.0],
    }


def _frame(groups: int = 6) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for group in range(groups):
        for state in range(3):
            row = {column: float(state) for column in FEATURE_COLS}
            row.update(
                clip_id=f"clip-{group}",
                record_time=pd.Timestamp("2026-01-01T00:00:00Z")
                + pd.Timedelta(days=group, minutes=state),
                traffic_state=state,
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                data_origin="real",
            )
            rows.append(row)
    return pd.DataFrame(rows)


def test_cross_validation_is_grouped_and_reports_each_fold() -> None:
    result = run_grouped_cross_validation(
        _frame(),
        input_policy=ModelInputPolicy.CANONICAL_V2,
        random_seed=42,
        model_factory=lambda **_: _PredictingModel(),
        callbacks_factory=lambda: (),
        scaler_factory=_IdentityScaler,
        requested_folds=3,
        epochs=1,
    )

    assert len(result.folds) == 3
    assert all(not fold.missing_labels for fold in result.folds)
    assert result.mean_f1_macro == pytest.approx(1.0)
    assert result.std_f1_macro == pytest.approx(0.0)
    assert result.report_evidence()["requested"] is True


def test_cross_validation_requires_multiple_real_groups() -> None:
    with pytest.raises(RuntimeError, match="al menos dos grupos reales"):
        run_grouped_cross_validation(
            _frame(groups=1),
            input_policy=ModelInputPolicy.CANONICAL_V2,
            random_seed=42,
            model_factory=lambda **_: _PredictingModel(),
            callbacks_factory=lambda: (),
            scaler_factory=_IdentityScaler,
        )


def test_cross_validation_rejects_non_probability_model_output() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        run_grouped_cross_validation(
            _frame(),
            input_policy=ModelInputPolicy.CANONICAL_V2,
            random_seed=42,
            model_factory=lambda **_: _InvalidProbabilityModel(),
            callbacks_factory=lambda: (),
            scaler_factory=_IdentityScaler,
            requested_folds=3,
            epochs=1,
        )
