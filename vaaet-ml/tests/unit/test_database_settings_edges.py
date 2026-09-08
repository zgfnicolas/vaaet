# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Bordes de secretos y perfiles PostgreSQL sin exponer credenciales."""

from __future__ import annotations

from pathlib import Path

import pytest

from vaaet_ml.data.database_settings import (
    DatabaseProfile,
    DatabaseSettings,
    get_optional_database_settings,
    load_reviewer_id,
)
from vaaet_ml.exceptions import DatabaseNotConfiguredError


def test_optional_settings_and_reviewer_id_fail_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vaaet_ml.data.database_settings._notebook_value", lambda _: None)

    assert get_optional_database_settings(DatabaseProfile.REVIEW) is None
    with pytest.raises(DatabaseNotConfiguredError, match="REVIEWER_ID"):
        load_reviewer_id()


def test_settings_validate_tls_port_and_redact_password() -> None:
    with pytest.raises(ValueError, match="between 1 and 65535"):
        DatabaseSettings(DatabaseProfile.REVIEW, "localhost", 0, "db", "user", "secret", "disable")
    with pytest.raises(DatabaseNotConfiguredError, match="requires VAAET_DB_SSLROOTCERT"):
        DatabaseSettings(DatabaseProfile.REVIEW, "db.example.test", 5432, "db", "user", "secret")

    settings = DatabaseSettings(
        DatabaseProfile.REVIEW,
        "localhost",
        5432,
        "db",
        "user",
        "secret",
        "disable",
        application_name="review-test",
    )
    assert settings.application == "review-test"
    assert "secret" not in repr(settings)


def test_explicit_certificate_path_satisfies_verify_full(tmp_path: Path) -> None:
    certificate = tmp_path / "certificate.pem"
    certificate.write_text("certificate", encoding="utf-8")
    settings = DatabaseSettings(
        DatabaseProfile.REVIEW,
        "db.example.test",
        5432,
        "db",
        "user",
        "secret",
        "verify-full",
        sslrootcert=str(certificate),
    )
    assert settings.sslrootcert == str(certificate)
