# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Consumidor independiente contra el contrato PostgreSQL real."""

from __future__ import annotations

import pandas as pd
import pytest

from vaaet_persistence.connection import database_engine, inspect_database
from vaaet_persistence.persistence import persist_raw_telemetry
from vaaet_persistence.queries import load_telemetry_window
from vaaet_persistence.settings import DatabaseProfile, load_database_settings

pytestmark = pytest.mark.postgres


def _settings():
    try:
        return load_database_settings(
            DatabaseProfile.COLLECTION,
            application_name="independent-backend-consumer-test",
            application_version="0.1.0",
        )
    except RuntimeError:
        pytest.skip("PostgreSQL integration profile is not configured")


def test_installed_component_inspects_migrated_schema_without_ml() -> None:
    settings = _settings()
    with database_engine(settings) as engine:
        health = inspect_database(engine, DatabaseProfile.COLLECTION)
    assert "vaaet_raw" in health.available_schemas


def test_independent_consumer_can_persist_and_read_raw_telemetry() -> None:
    settings = _settings()
    record_time = pd.Timestamp("2026-09-08T12:34:00Z")
    frame = pd.DataFrame(
        [
            {
                "clip_id": "persistence-consumer-contract",
                "record_time": record_time,
                "avg_speed": 20.0,
                "count_car": 1,
                "count_truck": 0,
                "count_bus": 0,
                "count_motorcycle": 0,
                "count_bicycle": 0,
                "total_vehicles": 1,
            }
        ]
    )
    inserted = persist_raw_telemetry(
        frame,
        settings=settings,
        application_name="independent-backend-consumer-test",
        application_version="0.1.0",
    )
    loaded = load_telemetry_window(
        start=record_time,
        end=record_time + pd.Timedelta(minutes=1),
        clip_ids=("persistence-consumer-contract",),
        settings=settings,
    )

    assert inserted in {0, 1}
    assert len(loaded) == 1

    repeated = persist_raw_telemetry(
        frame,
        settings=settings,
        application_name="independent-backend-consumer-test",
        application_version="0.1.0",
    )
    assert repeated == 0

    with pytest.raises(ValueError, match="idempotency conflict"):
        persist_raw_telemetry(
            frame.assign(avg_speed=21.0),
            settings=settings,
            application_name="independent-backend-consumer-test",
            application_version="0.1.0",
        )
