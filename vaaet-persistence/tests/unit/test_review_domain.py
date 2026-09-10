# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Contratos estrictos de las decisiones humanas persistibles."""

from __future__ import annotations

import pytest

from vaaet_persistence.review_domain import HumanValidation


@pytest.mark.parametrize("review_source", ["postgresql://private", "password=private", "bad path"])
def test_human_validation_rejects_unsafe_review_source(review_source: str) -> None:
    with pytest.raises(ValueError, match="safe non-empty identifier"):
        HumanValidation(1, 0, "reviewer", review_source=review_source)
