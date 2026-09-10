# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Persistencia append-only de revisión probada con un engine transaccional falso."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest

from vaaet_persistence.review_domain import HumanValidation
from vaaet_persistence.review_persistence import load_review_queue, persist_human_validation
from vaaet_persistence.settings import DatabaseProfile, DatabaseSettings


class _Connection:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []
        self.isolation_level: str | None = None
        self.read_only = False

    def execution_options(self, *, isolation_level: str):
        self.isolation_level = isolation_level
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    @contextmanager
    def begin(self):
        yield self

    def exec_driver_sql(self, statement: str) -> None:
        self.read_only = statement == "SET TRANSACTION READ ONLY"

    def execute(self, statement: object, payload: dict[str, object] | None = None):
        if "alembic_version" in str(statement):
            return _Result({"version_num": "20260909_0004"})
        assert payload is not None
        self.payloads.append(payload)
        return _Result(payload)


class _Mappings:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def one_or_none(self) -> dict[str, object]:
        return self.payload

    def one(self) -> dict[str, object]:
        return self.payload


class _Result:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def mappings(self) -> _Mappings:
        return _Mappings(self.payload)

    def scalar_one_or_none(self) -> object:
        return self.payload.get("version_num")


class _Engine:
    def __init__(self) -> None:
        self.connection = _Connection()
        self.disposed = False

    @contextmanager
    def begin(self):
        yield self.connection

    def connect(self) -> _Connection:
        return self.connection

    def dispose(self) -> None:
        self.disposed = True


def _settings() -> DatabaseSettings:
    return DatabaseSettings(
        DatabaseProfile.REVIEW,
        "localhost",
        5432,
        "vaaet",
        "reviewer",
        "secret",
        "disable",
        application_name="test-review",
        application_version="1.0.0",
    )


def test_load_review_queue_is_read_only_and_filters_in_memory(monkeypatch) -> None:
    frame = pd.DataFrame(
        [{"prediction_id": 1, "traffic_state": 1, "confidence": 0.5, "clip_id": "clip"}]
    )
    monkeypatch.setattr("vaaet_persistence.review_persistence.pd.read_sql", lambda *_args, **_kwargs: frame)

    engine = _Engine()
    result = load_review_queue(engine=engine, pipeline_run_id=uuid4(), mode="priority")

    assert result["prediction_id"].tolist() == [1]
    assert engine.connection.isolation_level == "REPEATABLE READ"
    assert engine.connection.read_only


def test_persist_validation_uses_supplied_pipeline_run_and_disposes_owned_engine(monkeypatch) -> None:
    engine = _Engine()
    monkeypatch.setattr("vaaet_persistence.review_persistence.get_engine", lambda _: engine)
    decision = HumanValidation(1, 1, "reviewer", validation_id=uuid4())

    run_id = uuid4()
    identifier = persist_human_validation(decision, settings=_settings(), pipeline_run_id=run_id)

    assert identifier == decision.validation_id
    assert engine.connection.payloads[0]["pipeline_run_id"] == str(run_id)
    assert engine.disposed


def test_persist_validation_creates_review_lineage_when_run_is_missing(monkeypatch) -> None:
    engine = _Engine()
    run = SimpleNamespace(id=uuid4(), set_output_rows=lambda rows: setattr(run, "rows", rows))

    @contextmanager
    def fake_pipeline_run(*_args, **_kwargs):
        yield run

    monkeypatch.setattr("vaaet_persistence.review_persistence.get_engine", lambda _: engine)
    monkeypatch.setattr("vaaet_persistence.review_persistence.pipeline_run", fake_pipeline_run)

    identifier = persist_human_validation(
        HumanValidation(1, 2, "reviewer"),
        settings=_settings(),
        application_name="test-review",
        application_version="1.0.0",
    )

    assert identifier
    assert run.rows == 1
    assert engine.disposed


def test_missing_lineage_identity_fails_before_creating_an_engine(monkeypatch) -> None:
    created = False

    def unexpected_engine(_settings):
        nonlocal created
        created = True
        return _Engine()

    monkeypatch.setattr("vaaet_persistence.review_persistence.get_engine", unexpected_engine)

    with pytest.raises(ValueError, match="application_name"):
        persist_human_validation(HumanValidation(1, 1, "reviewer"), settings=_settings())

    assert not created
