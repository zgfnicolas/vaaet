# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.inference.protocols import FeatureScaler as CoreFeatureScaler

from vaaet_ml.evaluation.champion_challenger import (
    EvaluationBundle,
    evaluate_champion_challenger,
    paired_bootstrap_intervals,
    validate_evaluation_pair,
)
from vaaet_ml.evaluation.champion_challenger import FeatureScaler as EvaluationFeatureScaler
from vaaet_ml.settings import FEATURE_COLS
from vaaet_ml.training.holdout import HumanHoldoutConfig, resolve_human_holdout


class _IdentityScaler:
    def transform(self, values: np.ndarray) -> np.ndarray:
        return values


class _FeatureStateModel:
    def __init__(self, *, offset: int = 0) -> None:
        self.offset = offset

    def predict(self, values: np.ndarray, *, verbose: int = 0) -> np.ndarray:
        del verbose
        states = (np.rint(values[:, 0]).astype(int) + self.offset) % 3
        return np.eye(3)[states]


def test_evaluation_reuses_the_portable_feature_scaler_protocol() -> None:
    """La evaluación conserva el alias público del contrato portable compartido."""

    assert EvaluationFeatureScaler is CoreFeatureScaler


def _feedback(*, feature_offset: float = 0.0) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for group in range(15):
        state = group % 3
        for minute in range(2):
            row: dict[str, object] = {
                "clip_id": f"clip-{group:02d}",
                "record_time": pd.Timestamp("2026-01-01T00:00:00Z")
                + pd.Timedelta(days=group, minutes=minute),
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "traffic_state": state,
                "is_human_validated": True,
                "data_origin": "real",
            }
            row.update({feature: float(state) + feature_offset for feature in FEATURE_COLS})
            rows.append(row)
    return pd.DataFrame(rows)


def _holdout(tmp_path: Path, *, feature_offset: float = 0.0):
    return resolve_human_holdout(
        _feedback(feature_offset=feature_offset),
        HumanHoldoutConfig(
            store_root=tmp_path / "holdouts",
            git_commit="a" * 40,
            vaaet_version="4.5.3",
        ),
    )


def _bundle(
    name: str, holdout, *, offset: int = 0, fingerprint: str | None = None
) -> EvaluationBundle:
    descriptor = dict(holdout.descriptor)
    if fingerprint is not None:
        descriptor["fingerprint"] = fingerprint
    manifest: dict[str, object] = {
        "contract_version": 3,
        "model_version": "mlp-v3.0",
        "model_revision": "a" * 64 if name == "champion" else "b" * 64,
        "training_lifecycle": {"input_policy": "canonical-v3"},
        "decision_policy": {
            "temperature": 1.0,
            "class_thresholds": {"0": 0.55, "1": 0.55, "2": 0.55},
            "minimum_probability_margin": 0.05,
        },
        "human_holdout": descriptor,
    }
    return EvaluationBundle(
        name=name,
        path=Path(".").resolve(),
        manifest=manifest,
        model=_FeatureStateModel(offset=offset),
        scaler=_IdentityScaler(),
    )


def test_evaluation_rejects_different_bundle_contract_generations(tmp_path: Path) -> None:
    holdout = _holdout(tmp_path)
    champion = _bundle("champion", holdout)
    challenger = _bundle("challenger", holdout)
    challenger.manifest["contract_version"] = 2

    with pytest.raises(ValueError, match="different bundle contract"):
        validate_evaluation_pair(champion, challenger, holdout)


def test_evaluation_compares_only_stable_states_and_preserves_no_accident(tmp_path: Path) -> None:
    holdout = _holdout(tmp_path)
    comparison = evaluate_champion_challenger(
        _bundle("champion", holdout),
        _bundle("challenger", holdout, offset=1),
        holdout,
        bootstrap_samples=20,
    )

    assert set(comparison.summary["metric"]) >= {
        "direct_f1_macro",
        "final_f1_macro",
        "ece",
        "brier_score",
    }
    assert set(comparison.bootstrap_intervals["metric"]) >= {
        "direct_f1_macro",
        "direct_recall_congested",
        "direct_normal_congested_error",
        "final_f1_macro",
        "final_recall_congested",
        "final_normal_congested_error",
    }
    assert not comparison.champion.classified["traffic_state"].eq(3).any()
    assert not comparison.challenger.classified["traffic_state"].eq(3).any()


def test_evaluation_rejects_bundles_with_different_holdouts(tmp_path: Path) -> None:
    holdout = _holdout(tmp_path)
    champion = _bundle("champion", holdout)
    challenger = _bundle("challenger", holdout, fingerprint="b" * 64)

    with pytest.raises(ValueError, match="different human holdout"):
        validate_evaluation_pair(champion, challenger, holdout)


def test_evaluation_rejects_a_snapshot_other_than_the_manifest_snapshot(tmp_path: Path) -> None:
    first = _holdout(tmp_path / "first")
    second = _holdout(tmp_path / "second", feature_offset=1.0)

    with pytest.raises(ValueError, match="does not match the fingerprint"):
        validate_evaluation_pair(_bundle("champion", first), _bundle("challenger", first), second)


def test_paired_bootstrap_intervals_are_deterministic() -> None:
    truth = np.array([0, 0, 1, 1, 2, 2])
    champion = np.array([0, 1, 1, 1, 2, 0])
    challenger = np.array([0, 0, 1, 2, 2, 2])

    clips = np.array(["a", "a", "a", "b", "b", "b"])
    first = paired_bootstrap_intervals(
        truth, champion, challenger, clip_ids=clips, samples=100, random_state=7
    )
    second = paired_bootstrap_intervals(
        truth, champion, challenger, clip_ids=clips, samples=100, random_state=7
    )

    pd.testing.assert_frame_equal(first, second)
