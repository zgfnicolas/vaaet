# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Delegación temporal 4.x hacia la cadena Alembic de vaaet-persistence."""

import warnings

warnings.warn(
    "vaaet-ml/alembic.ini is deprecated; use vaaet-persistence/alembic.ini.",
    FutureWarning,
    stacklevel=2,
)

from vaaet_persistence.migrations import env as _canonical_environment  # noqa: E402,F401
