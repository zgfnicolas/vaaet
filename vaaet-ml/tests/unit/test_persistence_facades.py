# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Las fachadas 4.x conservan contratos mientras delegan en una implementación."""

from __future__ import annotations

import pytest
from vaaet_persistence import DatabaseProfile as SharedDatabaseProfile
from vaaet_persistence import HumanValidation as SharedHumanValidation

from vaaet_ml.data.database import DatabaseProfile, get_engine
from vaaet_ml.data.review_domain import HumanValidation


def test_shared_contracts_keep_object_identity() -> None:
    assert DatabaseProfile is SharedDatabaseProfile
    assert HumanValidation is SharedHumanValidation


def test_legacy_mapping_remains_explicitly_deprecated() -> None:
    with pytest.warns(DeprecationWarning):
        engine = get_engine(
            {
                "host": "localhost",
                "port": "5432",
                "database": "vaaet",
                "username": "user",
                "password": "secret",
                "sslmode": "disable",
            }
        )
    engine.dispose()
