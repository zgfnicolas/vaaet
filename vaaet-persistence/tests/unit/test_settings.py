# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Configuración compartida probada sin Colab ni secretos reales."""

from __future__ import annotations

import pytest

from vaaet_persistence.exceptions import DatabaseNotConfiguredError
from vaaet_persistence.settings import (
    DatabaseProfile,
    get_optional_database_settings,
    load_database_settings,
)


def _values(name: str) -> str | None:
    return {
        "VAAET_DB_HOST": "localhost",
        "VAAET_DB_PORT": "5432",
        "VAAET_DB_NAME": "vaaet",
        "VAAET_DB_SSLMODE": "disable",
        "VAAET_INFERENCE_DB_USER": "inference-user",
        "VAAET_INFERENCE_DB_PASSWORD": "not-a-real-secret",
    }.get(name)


def test_loader_requires_explicit_profile_and_consumer_identity() -> None:
    settings = load_database_settings(
        DatabaseProfile.INFERENCE,
        application_name="vaaet-api-worker",
        application_version="0.1.0",
        value_provider=_values,
    )

    assert settings.profile is DatabaseProfile.INFERENCE
    assert settings.application == "vaaet-api-worker/0.1.0"
    assert "not-a-real-secret" not in repr(settings)


def test_loader_does_not_translate_legacy_variables() -> None:
    legacy = {
        "DB_HOST": "localhost",
        "DB_NAME": "vaaet",
        "DB_USER": "legacy",
        "DB_PASSWORD": "secret",
    }

    with pytest.raises(DatabaseNotConfiguredError, match="profile=training"):
        load_database_settings(
            DatabaseProfile.TRAINING,
            application_name="independent-consumer",
            application_version="1.0.0",
            value_provider=legacy.get,
        )


def test_loader_rejects_missing_consumer_identity() -> None:
    with pytest.raises(ValueError, match="application_name"):
        load_database_settings(
            DatabaseProfile.INFERENCE,
            application_name="",
            application_version="0.1.0",
            value_provider=_values,
        )


def test_optional_profile_distinguishes_absent_from_partial_configuration() -> None:
    assert (
        get_optional_database_settings(
            DatabaseProfile.TRAINING,
            application_name="independent-consumer",
            application_version="1.0.0",
            value_provider=lambda _name: None,
        )
        is None
    )

    partial = {"VAAET_TRAINING_DB_USER": "reader"}
    with pytest.raises(DatabaseNotConfiguredError, match="VAAET_DB_HOST"):
        get_optional_database_settings(
            DatabaseProfile.TRAINING,
            application_name="independent-consumer",
            application_version="1.0.0",
            value_provider=partial.get,
        )
