# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Pruebas del contrato temporal compartido por features y políticas."""

from __future__ import annotations

import pandas as pd
import pytest

from vaaet.continuity import normalize_continuity_frame
from vaaet.features.engineering import engineer_features


def _raw_frame(times: list[str]) -> pd.DataFrame:
    rows = len(times)
    return pd.DataFrame(
        {
            "clip_id": ["clip"] * rows,
            "record_time": pd.to_datetime(times),
            "avg_speed": [10.0] * rows,
            "total_vehicles": [2] * rows,
            "count_car": [2] * rows,
            "count_truck": [0] * rows,
            "count_bus": [0] * rows,
            "count_motorcycle": [0] * rows,
            "count_bicycle": [0] * rows,
        }
    )


def test_long_gap_creates_a_new_continuity_and_feature_baseline() -> None:
    raw = _raw_frame(
        [
            "2026-09-05T12:00:00Z",
            "2026-09-05T12:01:00Z",
            "2026-09-05T12:05:00Z",
            "2026-09-05T12:06:00Z",
        ]
    )

    normalized = normalize_continuity_frame(raw)
    features = engineer_features(raw)

    assert normalized["continuity_id"].nunique() == 2
    assert features["record_time"].tolist() == [
        pd.Timestamp("2026-09-05T12:01:00Z"),
        pd.Timestamp("2026-09-05T12:06:00Z"),
    ]


def test_continuity_normalization_is_idempotent_across_a_gap() -> None:
    raw = _raw_frame(["2026-09-05T12:00:00Z", "2026-09-05T12:04:00Z", "2026-09-05T12:05:00Z"])
    raw["continuity_id"] = "camera-a"

    first = normalize_continuity_frame(raw)
    second = normalize_continuity_frame(first)

    pd.testing.assert_frame_equal(first, second)
    assert first.loc[1, "continuity_id"].endswith("20260905T120400000000Z")


@pytest.mark.parametrize(
    "times, message",
    [
        (
            ["2026-09-05T12:00:00Z", "2026-09-05T12:00:00Z"],
            "Duplicate",
        ),
        (
            ["2026-09-05T12:01:00Z", "2026-09-05T12:00:00Z"],
            "monotonic",
        ),
    ],
)
def test_invalid_temporal_identity_is_rejected(times: list[str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_continuity_frame(_raw_frame(times))


def test_invalid_timestamp_is_rejected() -> None:
    raw = _raw_frame(["2026-09-05T12:00:00Z"])
    raw["record_time"] = raw["record_time"].astype(object)
    raw.loc[0, "record_time"] = "not-a-time"

    with pytest.raises(ValueError, match="invalid"):
        normalize_continuity_frame(raw)
