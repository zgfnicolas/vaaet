# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Pruebas aisladas de conexión PostgreSQL, sin servidor ni credenciales reales."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import URL
from sqlalchemy.exc import OperationalError

from vaaet_persistence.connection import (
    database_engine,
    execute_with_retry,
    get_engine,
    inspect_database,
)
from vaaet_persistence.connection import (
    test_connection as check_connection,
)
from vaaet_persistence.exceptions import DatabaseOperationError
from vaaet_persistence.settings import DatabaseProfile, DatabaseSettings


def _settings() -> DatabaseSettings:
    return DatabaseSettings(
        DatabaseProfile.TRAINING,
        "db.example.test",
        5432,
        "vaaet",
        "trainer",
        "secret",
        "require",
    )


def _operational_error() -> OperationalError:
    return OperationalError("SELECT 1", {}, RuntimeError("offline"))


def test_get_engine_configures_a_bounded_redacted_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_create_engine(url: URL, **kwargs: object) -> object:
        captured["url"] = url
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("vaaet_persistence.connection.create_engine", fake_create_engine)

    assert get_engine(_settings()) is not None
    assert captured["pool_size"] == 2
    assert captured["max_overflow"] == 0
    assert captured["hide_parameters"] is True


def test_execute_with_retry_retries_only_operational_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"count": 0}
    monkeypatch.setattr("vaaet_persistence.connection.time.sleep", lambda _: None)

    def eventually_available() -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise _operational_error()
        return "ok"

    assert execute_with_retry(eventually_available) == "ok"
    assert attempts["count"] == 2
    with pytest.raises(ValueError, match="positive"):
        execute_with_retry(lambda: None, attempts=0)
    with pytest.raises(ValueError, match="non-negative"):
        execute_with_retry(lambda: None, initial_delay_seconds=-0.1)
    with pytest.raises(DatabaseOperationError, match="bounded retries"):
        execute_with_retry(lambda: (_ for _ in ()).throw(_operational_error()), attempts=1)


class _FakeResult:
    def __init__(self, *, row: tuple[object, ...] | None = None, scalar: object = None) -> None:
        self._row = row
        self._scalar = scalar

    def one(self) -> tuple[object, ...]:
        assert self._row is not None
        return self._row

    def scalar(self) -> object:
        return self._scalar


class _FakeConnection:
    def execute(self, statement: object, params: object = None) -> _FakeResult:
        statement_text = str(statement)
        if "server_version" in statement_text:
            return _FakeResult(row=("17.2", "vaaet_reader", True))
        return _FakeResult(scalar=params == {"schema": "vaaet_raw"})


class _FakeEngine:
    url = URL.create("postgresql+psycopg2", host="db.example.test", port=5432, database="vaaet")

    def __init__(self) -> None:
        self.disposed = False

    @contextmanager
    def connect(self):
        yield _FakeConnection()

    def dispose(self) -> None:
        self.disposed = True


def test_database_engine_and_inspection_release_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _FakeEngine()
    monkeypatch.setattr("vaaet_persistence.connection.get_engine", lambda _: engine)
    monkeypatch.setattr(
        "vaaet_persistence.connection._probe_connection", lambda *_args, **_kwargs: None
    )

    with database_engine(_settings()) as active_engine:
        health = inspect_database(active_engine, DatabaseProfile.TRAINING)

    assert health.server_version == "17.2"
    assert health.available_schemas == ("vaaet_raw",)
    assert engine.disposed


def test_connection_returns_false_only_for_expected_database_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "vaaet_persistence.connection.execute_with_retry",
        lambda _: (_ for _ in ()).throw(DatabaseOperationError("offline")),
    )

    assert not check_connection(_FakeEngine())
