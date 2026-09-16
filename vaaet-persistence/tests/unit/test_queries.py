# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Consultas de laboratorio verificadas con engines falsos y sin PostgreSQL real."""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy.exc import ProgrammingError

from vaaet_persistence.queries import (
    HUMAN_FEATURES_QUERY,
    HUMAN_PREDICTIONS_QUERY,
    HUMAN_VALIDATIONS_QUERY,
    LEGACY_TELEMETRY_QUERY,
    TELEMETRY_QUERY,
    TelemetryReadMode,
    load_human_feedback_components,
    load_human_ground_truth,
    load_telemetry,
    load_telemetry_window,
)
from vaaet_persistence.settings import DatabaseProfile, DatabaseSettings


class _DisposableEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True

    def connect(self):
        return _FakeConnection()


class _FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _FakeConnection:
    def execution_options(self, **_kwargs: object):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction()

    def exec_driver_sql(self, _statement: str) -> None:
        return None


def _settings() -> DatabaseSettings:
    return DatabaseSettings(
        DatabaseProfile.TRAINING,
        "localhost",
        5432,
        "vaaet",
        "reader",
        "secret",
        "disable",
        application_name="test-consumer",
        application_version="1.0.0",
    )


def test_load_telemetry_legacy_mode_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _DisposableEngine()

    def fake_read_sql(statement: object, _engine: object) -> pd.DataFrame:
        assert str(statement) == LEGACY_TELEMETRY_QUERY
        return pd.DataFrame({"clip_id": ["legacy"]})

    monkeypatch.setattr("vaaet_persistence.queries.pd.read_sql", fake_read_sql)
    with pytest.warns(UserWarning, match="selected explicitly"):
        result = load_telemetry(engine=engine, mode=TelemetryReadMode.LEGACY)

    assert result["clip_id"].tolist() == ["legacy"]
    assert result["pipeline_run_id"].isna().all()
    assert result.attrs["vaaet_provenance"]["telemetry_read_mode"] == "legacy"
    assert not engine.disposed


def test_current_telemetry_error_never_falls_back_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_read_sql(statement: object, _engine: object) -> pd.DataFrame:
        calls.append(str(statement))
        raise ProgrammingError(str(statement), {}, RuntimeError("permission denied marker"))

    monkeypatch.setattr("vaaet_persistence.queries.pd.read_sql", fake_read_sql)
    with pytest.raises(Exception) as captured:
        load_telemetry(engine=_DisposableEngine())

    assert calls == [TELEMETRY_QUERY]
    assert "permission denied marker" not in str(captured.value)


def test_read_only_queries_dispose_owned_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _DisposableEngine()
    monkeypatch.setattr("vaaet_persistence.queries.get_engine", lambda _: engine)
    monkeypatch.setattr(
        "vaaet_persistence.queries.pd.read_sql",
        lambda *_args, **_kwargs: pd.DataFrame({"clip_id": ["clip-a"]}),
    )

    assert len(load_human_ground_truth(settings=_settings())) == 1
    assert engine.disposed


def test_human_history_queries_are_explicit_and_load_every_component(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _DisposableEngine()
    statements: list[str] = []

    def fake_read_sql(statement: object, _engine: object, *, params: object) -> pd.DataFrame:
        statements.append(str(statement))
        assert params == {"feature_schema_version": "traffic-features-v3"}
        return pd.DataFrame({"id": [len(statements)]})

    monkeypatch.setattr("vaaet_persistence.queries.pd.read_sql", fake_read_sql)
    components = load_human_feedback_components(engine=engine)

    assert set(components) == {"features", "predictions", "validations"}
    assert [int(frame.iloc[0]["id"]) for frame in components.values()] == [1, 2, 3]
    assert not engine.disposed
    assert all(
        "SELECT *" not in query.upper()
        for query in (
            HUMAN_FEATURES_QUERY,
            HUMAN_PREDICTIONS_QUERY,
            HUMAN_VALIDATIONS_QUERY,
        )
    )
    assert "supersedes_validation_id" in HUMAN_VALIDATIONS_QUERY


@pytest.mark.parametrize("filters", [{"pipeline_run_ids": ("",)}, {"clip_ids": ("",)}])
def test_telemetry_window_rejects_blank_filters(filters: dict[str, tuple[str, ...]]) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        load_telemetry_window(
            start=pd.Timestamp("2026-08-29T00:00:00Z"),
            end=pd.Timestamp("2026-08-30T00:00:00Z"),
            engine=_DisposableEngine(),
            **filters,
        )
