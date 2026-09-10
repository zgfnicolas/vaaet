# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Regresiones para el aislamiento read-only del auditor PostgreSQL."""

from __future__ import annotations

from typing import Any

from vaaet_persistence.audit import _rows, _scalar


class _NestedTransaction:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_args: object) -> bool:
        return False


class _Result:
    def mappings(self) -> _Result:
        return self

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(({"value": 1},))

    def scalar_one(self) -> int:
        return 1


class _Connection:
    def __init__(self) -> None:
        self.savepoints = 0

    def begin_nested(self) -> _NestedTransaction:
        self.savepoints += 1
        return _NestedTransaction()

    def execute(self, statement: object) -> _Result:
        if "broken" in str(statement):
            raise RuntimeError("simulated catalog permission failure")
        return _Result()


def test_failed_audit_section_does_not_abort_following_sections() -> None:
    connection: Any = _Connection()

    assert _rows(connection, "broken") == [{"audit_error": "RuntimeError"}]
    assert _scalar(connection, "SELECT 1") == 1
    assert connection.savepoints == 2
