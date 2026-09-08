#!/usr/bin/env python
# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Compatibilidad 4.x: delega la auditoría al componente compartido."""

from __future__ import annotations

import warnings

from vaaet_persistence.audit import main

warnings.warn(
    "vaaet-ml/scripts/audit-postgres-database.py is deprecated; "
    "use the vaaet-postgres-audit command.",
    FutureWarning,
    stacklevel=1,
)

if __name__ == "__main__":
    main()
