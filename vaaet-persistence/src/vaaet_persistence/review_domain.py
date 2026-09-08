# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Contratos y selección pura para la revisión humana persistible."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import pandas as pd
from vaaet.settings import STATE_LABELS


@dataclass(frozen=True)
class HumanValidation:
    """Decisión humana append-only que habilita el único estado ``Accident``."""

    prediction_id: int
    validated_state: int
    reviewer_id: str
    notes: str | None = None
    incident_context_reviewed: bool = False
    supersedes_validation_id: UUID | None = None
    validation_id: UUID | None = None
    review_source: str = "colab"

    def __post_init__(self) -> None:
        if self.validated_state not in STATE_LABELS:
            raise ValueError("validated_state must be one of the four public traffic states.")
        if not self.reviewer_id.strip():
            raise ValueError("A stable reviewer identifier is required.")
        if self.validated_state == 3:
            if not self.incident_context_reviewed:
                raise ValueError("Accident requires explicit temporal-context confirmation.")
            if not self.notes or not self.notes.strip():
                raise ValueError("Accident confirmation requires a non-empty review note.")


@dataclass
class InferenceReviewSession:
    """Decisiones acumuladas y frame inmutable asociado a una revisión explícita."""

    export_frame: pd.DataFrame | None
    validations: list[HumanValidation]


def select_review_queue(frame: pd.DataFrame, *, mode: str = "priority") -> pd.DataFrame:
    """Selecciona filas prioritarias sin persistir ni alterar el DataFrame de entrada."""

    if mode not in {"priority", "all"}:
        raise ValueError("Review mode must be 'priority' or 'all'.")
    if mode == "all" or frame.empty:
        return frame.copy().reset_index(drop=True)
    candidates = frame.loc[frame["latest_validation_id"].isna()].copy() if "latest_validation_id" in frame else frame.copy()
    priority = pd.Series(False, index=candidates.index)
    for column in ("accident_rule_triggered", "decision_abstained"):
        if column in candidates:
            priority |= candidates[column].fillna(False).astype(bool)
    if "probability_margin" in candidates:
        priority |= pd.to_numeric(candidates["probability_margin"], errors="coerce").fillna(0).lt(0.15)
    if "confidence" in candidates:
        priority |= pd.to_numeric(candidates["confidence"], errors="coerce").fillna(0).lt(0.75)
    if "traffic_state" in candidates:
        groups = candidates.get("clip_id", pd.Series("all", index=candidates.index))
        priority |= candidates.groupby(groups)["traffic_state"].diff().fillna(0).ne(0)
    return candidates.loc[priority].reset_index(drop=True)


__all__ = ["HumanValidation", "InferenceReviewSession", "select_review_queue"]
