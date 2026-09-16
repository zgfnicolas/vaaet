# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Validación cruzada agrupada, sin presentación ni estado de notebook."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_class_weight
from vaaet.calibration import validate_probability_matrix
from vaaet.settings import N_MODEL_STATES, STATE_LABELS

from vaaet_ml.data.datasets import build_group_ids
from vaaet_ml.training.execution import (
    TrainingFitConfig,
    reset_training_state,
    validate_training_history,
    validate_training_inputs,
)
from vaaet_ml.training.lifecycle import ModelInputPolicy, apply_model_input_policy


class _FoldModel(Protocol):
    """Superficie mínima del modelo usada para evaluar un fold temporal."""

    def fit(
        self,
        features: np.ndarray,
        labels: np.ndarray,
        *,
        epochs: int,
        batch_size: int,
        validation_data: tuple[np.ndarray, np.ndarray],
        sample_weight: np.ndarray,
        callbacks: Sequence[object],
        verbose: int,
    ) -> object: ...

    def predict(self, features: np.ndarray, *, verbose: int) -> np.ndarray: ...


class _FeatureScaler(Protocol):
    """Contrato pequeño para aislar el escalado de cada fold."""

    def fit_transform(self, features: np.ndarray) -> np.ndarray: ...

    def transform(self, features: np.ndarray) -> np.ndarray: ...


@dataclass(frozen=True)
class CrossValidationFold:
    """Resultado inmutable de un fold, incluso cuando carece de una clase estable."""

    index: int
    support: dict[int, int]
    missing_labels: tuple[str, ...]
    f1_macro: float | None


@dataclass(frozen=True)
class CrossValidationResult:
    """Evidencia agregada para que el notebook la presente sin recalcularla."""

    folds: tuple[CrossValidationFold, ...]
    mean_f1_macro: float
    std_f1_macro: float

    def report_evidence(self) -> dict[str, object]:
        """Serializa evidencia adicional sin filas, modelos ni decisiones de promoción."""

        return {
            "requested": True,
            "mean_f1_macro": self.mean_f1_macro,
            "std_f1_macro": self.std_f1_macro,
            "folds": [
                {
                    "index": fold.index,
                    "support": fold.support,
                    "missing_labels": list(fold.missing_labels),
                    "f1_macro": fold.f1_macro,
                }
                for fold in self.folds
            ],
        }


def run_grouped_cross_validation(
    frame: pd.DataFrame,
    *,
    input_policy: ModelInputPolicy,
    random_seed: int,
    model_factory: Callable[..., _FoldModel],
    callbacks_factory: Callable[[], Sequence[object]],
    scaler_factory: Callable[[], _FeatureScaler] = StandardScaler,
    requested_folds: int = 5,
    epochs: int = 200,
    batch_size: int = 32,
    clear_session: Callable[[], None] | None = None,
    set_random_seed: Callable[[int], None] | None = None,
) -> CrossValidationResult:
    """Ejecuta folds reales agrupados sin sustituir el split final exportable.

    El entrenamiento y escalado se reinician por fold; por eso la evidencia no
    filtra estadísticas de entrenamiento al grupo de validación correspondiente.
    """

    if (clear_session is None) != (set_random_seed is None):
        raise ValueError("Cross-validation requires both session and seed callbacks together.")
    source = _real_cross_validation_source(frame)
    features = apply_model_input_policy(source, input_policy).to_numpy(dtype=float)
    labels = pd.to_numeric(source["traffic_state"], errors="raise").to_numpy(dtype=int)
    groups = build_group_ids(source).to_numpy(dtype=str)
    folds = _fold_count(groups, requested_folds)
    splitter = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=random_seed)
    results = tuple(
        _evaluate_fold(
            index=index,
            train_indices=train_indices,
            validation_indices=validation_indices,
            features=features,
            labels=labels,
            model_factory=model_factory,
            callbacks_factory=callbacks_factory,
            scaler_factory=scaler_factory,
            epochs=epochs,
            batch_size=batch_size,
            clear_session=clear_session,
            set_random_seed=set_random_seed,
            random_seed=random_seed,
        )
        for index, (train_indices, validation_indices) in enumerate(
            splitter.split(features, labels, groups), start=1
        )
    )
    evaluable = np.asarray([fold.f1_macro for fold in results if fold.f1_macro is not None])
    return CrossValidationResult(
        folds=results,
        mean_f1_macro=float(np.nanmean(evaluable)) if evaluable.size else float("nan"),
        std_f1_macro=float(np.nanstd(evaluable)) if evaluable.size else float("nan"),
    )


def _real_cross_validation_source(frame: pd.DataFrame) -> pd.DataFrame:
    if "traffic_state" not in frame:
        raise ValueError("Cross-validation source requires traffic_state.")
    origins = frame.get("data_origin", pd.Series("real", index=frame.index))
    source = frame.loc[~origins.eq("synthetic")].copy()
    if source.empty:
        raise ValueError("Grouped cross-validation requires at least one real record.")
    return source


def _fold_count(groups: np.ndarray, requested_folds: int) -> int:
    if requested_folds < 2:
        raise ValueError("Grouped cross-validation requires at least two requested folds.")
    folds = min(requested_folds, len(np.unique(groups)))
    if folds < 2:
        raise RuntimeError("La validación cruzada agrupada necesita al menos dos grupos reales.")
    return folds


def _evaluate_fold(
    *,
    index: int,
    train_indices: np.ndarray,
    validation_indices: np.ndarray,
    features: np.ndarray,
    labels: np.ndarray,
    model_factory: Callable[..., _FoldModel],
    callbacks_factory: Callable[[], Sequence[object]],
    scaler_factory: Callable[[], _FeatureScaler],
    epochs: int,
    batch_size: int,
    clear_session: Callable[[], None] | None,
    set_random_seed: Callable[[int], None] | None,
    random_seed: int,
) -> CrossValidationFold:
    scaler = scaler_factory()
    train_features = scaler.fit_transform(features[train_indices])
    validation_features = scaler.transform(features[validation_indices])
    train_labels = labels[train_indices]
    validation_labels = labels[validation_indices]
    validate_training_inputs(
        train_features,
        train_labels,
        validation_features,
        validation_labels,
        input_features=train_features.shape[1],
        output_classes=N_MODEL_STATES,
    )
    if clear_session is not None and set_random_seed is not None:
        reset_training_state(
            TrainingFitConfig(random_seed=random_seed, epochs=epochs, batch_size=batch_size),
            clear_session=clear_session,
            set_random_seed=set_random_seed,
        )
    model = model_factory(input_features=train_features.shape[1], output_classes=N_MODEL_STATES)
    history = model.fit(
        train_features,
        train_labels,
        epochs=epochs,
        batch_size=batch_size,
        validation_data=(validation_features, validation_labels),
        sample_weight=_balanced_sample_weights(train_labels),
        callbacks=callbacks_factory(),
        verbose=0,
    )
    validate_training_history(history)
    probabilities = validate_probability_matrix(
        model.predict(validation_features, verbose=0),
        rows=len(validation_features),
        classes=N_MODEL_STATES,
    )
    predictions = probabilities.argmax(axis=1).astype(int)
    support = {state: int((validation_labels == state).sum()) for state in range(N_MODEL_STATES)}
    missing_labels = tuple(STATE_LABELS[state] for state, count in support.items() if count == 0)
    f1_macro = None if missing_labels else _macro_f1(validation_labels, predictions)
    return CrossValidationFold(index, support, missing_labels, f1_macro)


def _balanced_sample_weights(labels: np.ndarray) -> np.ndarray:
    classes = np.unique(labels)
    balanced = compute_class_weight(class_weight="balanced", classes=classes, y=labels)
    weights = {int(code): min(float(weight), 4.0) for code, weight in zip(classes, balanced, strict=True)}
    return np.asarray([weights[int(code)] for code in labels], dtype=float)


def _macro_f1(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(f1_score(actual, predicted, labels=[0, 1, 2], average="macro", zero_division=0))


__all__ = ["CrossValidationFold", "CrossValidationResult", "run_grouped_cross_validation"]
