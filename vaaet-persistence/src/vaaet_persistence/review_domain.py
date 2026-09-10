# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Contratos y selección pura para la revisión humana persistible."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from numbers import Integral
from uuid import UUID, uuid4

import pandas as pd
from vaaet.settings import STATE_LABELS

_REVIEW_SOURCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


@dataclass(frozen=True)
class HumanValidation:
    """Decisión humana append-only que habilita el único estado ``Accident``."""

    prediction_id: int
    validated_state: int
    reviewer_id: str
    notes: str | None = None
    incident_context_reviewed: bool = False
    supersedes_validation_id: UUID | None = None
    validation_id: UUID = field(default_factory=uuid4)
    reviewed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    review_source: str = "colab"

    def __post_init__(self) -> None:  # noqa: C901 - valida el contrato externo completo.
        if isinstance(self.prediction_id, bool) or not isinstance(self.prediction_id, Integral):
            raise ValueError("prediction_id must be a positive integer.")
        object.__setattr__(self, "prediction_id", int(self.prediction_id))
        if self.prediction_id < 1:
            raise ValueError("prediction_id must be a positive integer.")
        if isinstance(self.validated_state, bool) or not isinstance(
            self.validated_state, Integral
        ):
            raise ValueError("validated_state must be an integer public state.")
        object.__setattr__(self, "validated_state", int(self.validated_state))
        if self.validated_state not in STATE_LABELS:
            raise ValueError("validated_state must be one of the four public traffic states.")
        if not isinstance(self.reviewer_id, str) or not self.reviewer_id.strip():
            raise ValueError("A stable reviewer identifier is required.")
        if not isinstance(self.incident_context_reviewed, bool):
            raise ValueError("incident_context_reviewed must be a boolean value.")
        if self.notes is not None and not isinstance(self.notes, str):
            raise ValueError("notes must be text when supplied.")
        if (
            not isinstance(self.review_source, str)
            or _REVIEW_SOURCE.fullmatch(self.review_source) is None
        ):
            raise ValueError("review_source must be a safe non-empty identifier.")
        if not isinstance(self.validation_id, UUID):
            raise ValueError("validation_id must be a UUID.")
        if self.supersedes_validation_id is not None and not isinstance(
            self.supersedes_validation_id, UUID
        ):
            raise ValueError("supersedes_validation_id must be a UUID when supplied.")
        if not isinstance(self.reviewed_at, datetime):
            raise ValueError("reviewed_at must be a timezone-aware datetime.")
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware.")
        object.__setattr__(self, "reviewed_at", self.reviewed_at.astimezone(timezone.utc))
        if self.validated_state == 3:
            if not self.incident_context_reviewed:
                raise ValueError("Accident requires explicit temporal-context confirmation.")
            if not self.notes or not self.notes.strip():
                raise ValueError("Accident confirmation requires a non-empty review note.")


@dataclass
class InferenceReviewSession:
    """Decisiones acumuladas y frame inmutable asociado a una revisión explícita."""

    export_frame: pd.DataFrame | None
    validations: list[HumanValidation | Mapping[str, object]]


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
