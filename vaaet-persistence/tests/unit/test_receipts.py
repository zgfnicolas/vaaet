# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Comprobantes tipados, estables e inmutables para escrituras confirmadas."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pandas as pd
import pytest

from vaaet_persistence.receipts import (
    PERSISTENCE_RECEIPT_ALGORITHM,
    PersistenceReceipt,
    build_persistence_receipt,
    calculate_persistence_fingerprint,
    receipts_match,
)


def test_fingerprint_is_stable_for_order_utc_and_float64_equivalents() -> None:
    run_id = uuid4()
    first = {
        "pipeline_run_id": run_id,
        "clip_id": "clip-a",
        "record_time": datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
        "avg_speed": Decimal("20.125"),
        "total_vehicles": 3,
        "measurement_reliable": True,
    }
    same = {
        "measurement_reliable": True,
        "total_vehicles": 3,
        "avg_speed": 20.125,
        "record_time": pd.Timestamp("2026-09-20T09:00:00-03:00"),
        "clip_id": "clip-a",
        "pipeline_run_id": run_id,
    }
    other = {
        **same,
        "clip_id": "clip-b",
        "record_time": pd.Timestamp("2026-09-20T12:01:00Z"),
    }

    direct = calculate_persistence_fingerprint("raw-telemetry", [first, other])
    reversed_rows = calculate_persistence_fingerprint(
        "raw-telemetry", [other, same]
    )

    assert direct == reversed_rows
    assert direct != calculate_persistence_fingerprint(
        "raw-telemetry", [{**first, "avg_speed": 20.126}, other]
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), Decimal("NaN")])
def test_fingerprint_rejects_non_finite_values(value: object) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        calculate_persistence_fingerprint("raw-telemetry", [{"value": value}])


def test_receipt_idempotency_ignores_only_first_insert_counts() -> None:
    run_id = uuid4()
    observation = {"pipeline_run_id": run_id, "clip_id": "clip-a"}
    stored = build_persistence_receipt(
        pipeline_run_id=run_id,
        operation="raw-telemetry",
        observations=[observation],
        processed_counts={"raw_telemetry": 1},
        inserted_counts={"raw_telemetry": 1},
        telemetry_schema_version="traffic-telemetry-v3",
    )
    retried = build_persistence_receipt(
        pipeline_run_id=run_id,
        operation="raw-telemetry",
        observations=[observation],
        processed_counts={"raw_telemetry": 1},
        inserted_counts={"raw_telemetry": 0},
        telemetry_schema_version="traffic-telemetry-v3",
    )

    assert receipts_match(stored, retried, include_inserted_counts=False)
    assert not receipts_match(stored, retried, include_inserted_counts=True)


def test_receipt_rejects_invalid_counts_and_algorithm() -> None:
    with pytest.raises(ValueError, match="algorithm"):
        PersistenceReceipt(
            pipeline_run_id=uuid4(),
            operation="raw-telemetry",
            fingerprint_algorithm="legacy",
            content_fingerprint="a" * 64,
            processed_counts={"raw_telemetry": 1},
            inserted_counts={"raw_telemetry": 1},
        )
    with pytest.raises(ValueError, match="processed_counts"):
        PersistenceReceipt(
            pipeline_run_id=uuid4(),
            operation="raw-telemetry",
            fingerprint_algorithm=PERSISTENCE_RECEIPT_ALGORITHM,
            content_fingerprint="a" * 64,
            processed_counts={"raw_telemetry": -1},
            inserted_counts={"raw_telemetry": 0},
        )
    with pytest.raises(ValueError, match="same entities"):
        PersistenceReceipt(
            pipeline_run_id=uuid4(),
            operation="raw-telemetry",
            fingerprint_algorithm=PERSISTENCE_RECEIPT_ALGORITHM,
            content_fingerprint="a" * 64,
            processed_counts={"raw_telemetry": 1},
            inserted_counts={"traffic_predictions": 0},
        )
    with pytest.raises(ValueError, match="cannot exceed"):
        PersistenceReceipt(
            pipeline_run_id=uuid4(),
            operation="raw-telemetry",
            fingerprint_algorithm=PERSISTENCE_RECEIPT_ALGORITHM,
            content_fingerprint="a" * 64,
            processed_counts={"raw_telemetry": 1},
            inserted_counts={"raw_telemetry": 2},
        )
