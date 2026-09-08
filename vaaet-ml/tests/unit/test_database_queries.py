# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Consultas de laboratorio verificadas con engines falsos y sin PostgreSQL real."""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy.exc import ProgrammingError

from vaaet_ml.data.database_queries import (
    HUMAN_FEATURES_QUERY,
    HUMAN_PREDICTIONS_QUERY,
    HUMAN_VALIDATIONS_QUERY,
    load_human_feedback_components,
    load_human_ground_truth,
    load_telemetry,
    load_telemetry_window,
)


class _DisposableEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def test_load_telemetry_falls_back_to_legacy_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _DisposableEngine()
    calls = {"count": 0}

    def fake_read_sql(statement: object, _engine: object) -> pd.DataFrame:
        calls["count"] += 1
        if calls["count"] == 1:
            raise ProgrammingError(str(statement), {}, RuntimeError("missing v2"))
        return pd.DataFrame({"clip_id": ["legacy"]})

    monkeypatch.setattr("vaaet_ml.data.database_queries.pd.read_sql", fake_read_sql)
    result = load_telemetry(engine=engine)

    assert result["clip_id"].tolist() == ["legacy"]
    assert result["pipeline_run_id"].isna().all()
    assert not engine.disposed


def test_read_only_queries_dispose_owned_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _DisposableEngine()
    monkeypatch.setattr("vaaet_ml.data.database_queries.get_engine", lambda _: engine)
    monkeypatch.setattr(
        "vaaet_ml.data.database_queries.pd.read_sql",
        lambda *_args, **_kwargs: pd.DataFrame({"clip_id": ["clip-a"]}),
    )

    assert len(load_human_ground_truth(settings={"host": "unused"})) == 1
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

    monkeypatch.setattr("vaaet_ml.data.database_queries.pd.read_sql", fake_read_sql)
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
