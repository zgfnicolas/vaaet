# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import pandas as pd
import pytest

from vaaet.inference.bundle import authorize_bundle
from vaaet.inference.engine import TrafficStateEngine


def test_candidate_bundle_cannot_persist() -> None:
    manifest = {
        "training_lifecycle": {"deployment_stage": "candidate", "input_policy": "canonical-v2"}
    }

    with pytest.raises(RuntimeError, match="sólo offline"):
        authorize_bundle(
            manifest,
            allow_pilot=True,
            allow_experimental=True,
            persist_to_database=True,
        )


def test_predict_latest_propagates_real_classification_errors() -> None:
    class BrokenEngine:
        def classify(self, telemetry: pd.DataFrame) -> pd.DataFrame:
            raise ValueError("invalid scaler input")

    with pytest.raises(ValueError, match="invalid scaler input"):
        TrafficStateEngine.predict_latest(BrokenEngine(), pd.DataFrame())  # type: ignore[arg-type]
