# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Fachada 4.x para sellar feedback portable mediante el contrato canónico."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID

import pandas as pd

from vaaet_ml.data.review_domain import HumanValidation
from vaaet_ml.data.review_finalization import seal_review_package

_CONTEXT_ATTR = "vaaet_review_export_context"


@dataclass(frozen=True)
class OfflineReviewExportContext:
    """Identifica la corrida y el software que originaron una revisión portable."""

    pipeline_run_id: str
    model_version: str
    git_commit: str
    application_version: str

    def __post_init__(self) -> None:
        try:
            UUID(str(self.pipeline_run_id))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("pipeline_run_id must be a UUID.") from None
        if not self.model_version.strip() or not self.application_version.strip():
            raise ValueError("Review export model and application versions are required.")
        if re.fullmatch(r"[0-9a-fA-F]{7,40}", self.git_commit) is None:
            raise ValueError("Review export git_commit must be a 7-40 character revision.")


def export_offline_review_package(
    output_path: str | Path,
    *,
    classified: pd.DataFrame,
    validations: pd.DataFrame | Sequence[HumanValidation],
    context: OfflineReviewExportContext | None = None,
) -> Path:
    """Conserva la fachada histórica sin mantener otro formato de exportación."""

    if (isinstance(validations, pd.DataFrame) and validations.empty) or (
        not isinstance(validations, pd.DataFrame) and not validations
    ):
        raise ValueError("Complete at least one human validation before exporting feedback.")
    resolved = context or _context_from_frame(classified)
    return seal_review_package(
        output_path,
        classified=classified,
        validations=validations,
        pipeline_run_id=resolved.pipeline_run_id,
        model_version=resolved.model_version,
        git_commit=resolved.git_commit,
        vaaet_version=resolved.application_version,
    )


def _context_from_frame(classified: pd.DataFrame) -> OfflineReviewExportContext:
    value = classified.attrs.get(_CONTEXT_ATTR)
    if not isinstance(value, Mapping):
        raise ValueError(
            "Legacy review export requires OfflineReviewExportContext or the "
            f"DataFrame attribute {_CONTEXT_ATTR!r}; no identities are inferred."
        )
    context = cast(Mapping[str, object], value)
    required = {"pipeline_run_id", "model_version", "git_commit", "application_version"}
    if missing := sorted(required - set(context)):
        raise ValueError(f"Review export context is missing fields: {missing}")
    return OfflineReviewExportContext(
        pipeline_run_id=str(context["pipeline_run_id"]),
        model_version=str(context["model_version"]),
        git_commit=str(context["git_commit"]),
        application_version=str(context["application_version"]),
    )


__all__ = ["OfflineReviewExportContext", "export_offline_review_package"]
