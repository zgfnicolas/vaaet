# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Valida el SQL de cada revisión Alembic sin una base PostgreSQL."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import ClauseElement

VERSIONS_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "vaaet_persistence" / "migrations" / "versions"
)
REVISION_FILES = sorted(VERSIONS_DIR.glob("2026*.py"))


class _RecordingOperations:
    """Registra las sentencias que una revisión envía a `op.execute()`."""

    def __init__(self) -> None:
        self.statements: list[str | ClauseElement] = []

    def execute(self, statement: str | ClauseElement, *_args: object, **_kwargs: object) -> None:
        self.statements.append(statement)


def _load_revision(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"revision_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _recorded_statements(path: Path) -> list[str | ClauseElement]:
    module = _load_revision(path)
    recorder = _RecordingOperations()
    module.op = recorder  # type: ignore[attr-defined]
    # Las revisiones son forward-only: `downgrade()` rechaza sin emitir SQL.
    module.upgrade()
    return recorder.statements


def test_every_revision_is_covered() -> None:
    assert len(REVISION_FILES) >= 6


@pytest.mark.parametrize("path", REVISION_FILES, ids=lambda path: path.stem)
def test_revision_sql_has_no_unbound_parameters(path: Path) -> None:
    """Rechaza `:nombre` sin valor: SQLAlchemy lo trata como parámetro (ADR-0037)."""

    statements = _recorded_statements(path)
    assert statements
    dialect = postgresql.dialect()
    for statement in statements:
        clause = text(statement) if isinstance(statement, str) else statement
        compiled = clause.compile(dialect=dialect)
        compiled.construct_params({})
        offline = str(clause.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
        assert "'NULL-" not in offline


def test_legacy_continuity_literal_reaches_postgresql_unchanged() -> None:
    path = VERSIONS_DIR / "20260905_0003_temporal_continuity_model_revision.py"
    dialect = postgresql.dialect()
    rendered = [
        str(text(statement).compile(dialect=dialect))
        for statement in _recorded_statements(path)
        if isinstance(statement, str) and "continuity_id = segmented.clip_id" in statement
    ]
    assert len(rendered) == 2
    assert all("|| ':legacy-' ||" in sql for sql in rendered)
