# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Contratos de configuración administrativa PostgreSQL sin red ni secretos reales."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.pool import NullPool

from vaaet_ml.data.database_connection import create_admin_engine
from vaaet_ml.data.database_settings import (
    DatabaseAdminSettings,
    DatabaseEndpointSettings,
    DatabasePoolSettings,
    DatabaseProfile,
    DatabaseRetrySettings,
    cleanup_temporary_root_certificate,
    load_database_admin_settings,
    load_database_settings,
)
from vaaet_ml.exceptions import DatabaseNotConfiguredError


def _set_local_admin_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAAET_DB_HOST", "localhost")
    monkeypatch.setenv("VAAET_DB_PORT", "5432")
    monkeypatch.setenv("VAAET_DB_NAME", "vaaet")
    monkeypatch.setenv("VAAET_DB_SSLMODE", "disable")
    monkeypatch.setenv("VAAET_ADMIN_DB_USER", "administrator")
    monkeypatch.setenv("VAAET_ADMIN_DB_PASSWORD", "not-a-real-secret")


def test_administrator_uses_shared_typed_endpoint_outside_colab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_local_admin_environment(monkeypatch)
    monkeypatch.setattr("vaaet_ml.data.database_settings._colab_secret", lambda _: "colab-secret")

    settings = load_database_admin_settings(allow_legacy=False)

    assert settings.host == "localhost"
    assert settings.application == "vaaet-ml-migration/4.7.0"
    assert "not-a-real-secret" not in repr(settings)


def test_administrator_does_not_read_colab_when_environment_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("vaaet_ml.data.database_settings._colab_secret", lambda _: "colab-secret")
    for name in (
        "VAAET_DB_HOST",
        "VAAET_DB_NAME",
        "VAAET_ADMIN_DB_USER",
        "VAAET_ADMIN_DB_PASSWORD",
        "VAAET_DATABASE_ADMIN_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(DatabaseNotConfiguredError, match="outside Colab"):
        load_database_admin_settings(allow_legacy=False)


def test_administrator_releases_temporary_certificate(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_local_admin_environment(monkeypatch)
    monkeypatch.setenv("VAAET_DB_HOST", "db.example.test")
    monkeypatch.setenv("VAAET_DB_SSLMODE", "verify-full")
    monkeypatch.setenv("VAAET_DB_SSLROOTCERT_PEM", "-----BEGIN CERTIFICATE-----\\nvalue")

    settings = load_database_admin_settings(allow_legacy=False)
    certificate = Path(settings.sslrootcert or "")
    assert certificate.is_file()

    cleanup_temporary_root_certificate(settings)

    assert not certificate.exists()


def test_endpoint_rejects_missing_certificate_path(tmp_path: Path) -> None:
    with pytest.raises(DatabaseNotConfiguredError, match="existing CA certificate"):
        DatabaseEndpointSettings(
            "db.example.test",
            5432,
            "vaaet",
            "verify-full",
            sslrootcert=str(tmp_path / "missing-ca.pem"),
        )


def test_administrator_legacy_url_is_validated_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "VAAET_DATABASE_ADMIN_URL",
        "postgresql+psycopg2://admin:p%40ss@localhost:5432/vaaet?sslmode=disable",
    )

    with pytest.warns(FutureWarning, match="removed in VAAET 5.0"):
        settings = load_database_admin_settings()

    assert settings.username == "admin"
    assert settings.password == "p@ss"
    assert "p@ss" not in repr(settings)


def test_legacy_url_does_not_mix_with_an_incomplete_typed_administrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VAAET_DB_HOST", "workflow.example.test")
    monkeypatch.setenv("VAAET_DB_NAME", "workflow")
    monkeypatch.setenv(
        "VAAET_DATABASE_ADMIN_URL",
        "postgresql+psycopg2://admin:secret@localhost:5432/legacy?sslmode=disable",
    )

    with pytest.warns(FutureWarning):
        settings = load_database_admin_settings()

    assert settings.host == "localhost"
    assert settings.database == "legacy"


def test_administrator_legacy_url_rejects_insecure_remote_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "VAAET_DATABASE_ADMIN_URL",
        "postgresql+psycopg2://admin:secret@db.example.test:5432/vaaet",
    )

    with (
        pytest.warns(FutureWarning),
        pytest.raises(DatabaseNotConfiguredError, match="SSLROOTCERT"),
    ):
        load_database_admin_settings()


def test_pool_settings_are_bounded_and_reused_by_workflow_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_local_admin_environment(monkeypatch)
    monkeypatch.setenv("VAAET_TRAINING_DB_USER", "trainer")
    monkeypatch.setenv("VAAET_TRAINING_DB_PASSWORD", "not-a-real-secret")
    monkeypatch.setenv("VAAET_DB_POOL_SIZE", "3")
    monkeypatch.setenv("VAAET_DB_MAX_OVERFLOW", "1")
    monkeypatch.setenv("VAAET_DB_POOL_RECYCLE_SECONDS", "600")
    monkeypatch.setenv("VAAET_DB_RETRY_ATTEMPTS", "2")
    monkeypatch.setenv("VAAET_DB_RETRY_BASE_DELAY_SECONDS", "0.25")

    settings = load_database_settings(DatabaseProfile.TRAINING, allow_legacy=False)

    assert settings.pool == DatabasePoolSettings(pool_size=3, max_overflow=1, recycle_seconds=600)
    assert settings.retry == DatabaseRetrySettings(attempts=2, base_delay_seconds=0.25)
    with pytest.raises(ValueError, match="pool size"):
        DatabasePoolSettings(pool_size=0)
    with pytest.raises(ValueError, match="must not exceed"):
        DatabasePoolSettings(pool_size=3, max_overflow=3)
    with pytest.raises(ValueError, match="retry attempts"):
        DatabaseRetrySettings(attempts=0)


def test_admin_engine_uses_null_pool_and_common_tls_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_create_engine(url: object, **kwargs: object) -> object:
        captured["url"] = url
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("vaaet_persistence.connection.create_engine", fake_create_engine)
    settings = DatabaseAdminSettings(
        endpoint=DatabaseEndpointSettings("localhost", 5432, "vaaet", "disable"),
        username="administrator",
        password="not-a-real-secret",
    )

    assert create_admin_engine(settings) is not None
    assert captured["poolclass"] is NullPool
    assert captured["connect_args"] == {
        "connect_timeout": 10,
        "application_name": "vaaet-migration",
        "sslmode": "disable",
    }


def test_alembic_environment_uses_typed_admin_settings_and_injected_connections() -> None:
    workspace = Path(__file__).parents[3]
    environment = (
        workspace
        / "vaaet-persistence"
        / "src"
        / "vaaet_persistence"
        / "migrations"
        / "env.py"
    )
    source = environment.read_text(encoding="utf-8")

    assert "load_database_admin_settings" in source
    assert 'config.attributes.get("connection")' in source
    assert "create_admin_engine" in source
    assert "VAAET_DATABASE_ADMIN_URL" not in source
    legacy_environment = Path(__file__).parents[2] / "migrations" / "env.py"
    assert "vaaet_persistence.migrations" in legacy_environment.read_text(encoding="utf-8")


def test_role_provisioning_matches_v3_functions_and_immutable_inference() -> None:
    provisioning = (
        Path(__file__).parents[3]
        / "vaaet-persistence"
        / "src"
        / "vaaet_persistence"
        / "migrations"
        / "provision-roles.sql"
    )
    source = provisioning.read_text(encoding="utf-8")

    assert (
        "start_pipeline_run(UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, "
        "TEXT, BIGINT)" in source
    )
    assert "finish_pipeline_run(UUID, TEXT, BIGINT, TEXT, TEXT)" in source
    assert "REVOKE UPDATE, DELETE ON vaaet_ml.telemetry_features" in source
    assert "GRANT SELECT, INSERT ON vaaet_ml.telemetry_features" in source
    assert "GRANT SELECT, INSERT, UPDATE ON vaaet_ml.telemetry_features" not in source
