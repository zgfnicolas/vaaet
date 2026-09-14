# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Fachada compatible 4.x para revisión humana y su adaptador de notebook."""

from __future__ import annotations

from collections.abc import Callable, Mapping

import pandas as pd

from vaaet_ml.data.database import DatabaseSettings
from vaaet_ml.data.dataset_artifacts import (
    HITL_CATALOG_FILE,
    HitlCatalogPublisher,
    HitlReviewCatalog,
    finalize_review_session,
    sync_finalized_review_session,
)
from vaaet_ml.data.review_domain import HumanValidation, InferenceReviewSession, select_review_queue
from vaaet_ml.data.review_export import export_offline_review_package
from vaaet_ml.data.review_orchestration import prepare_review_session
from vaaet_ml.data.review_persistence import load_review_queue, persist_human_validation
from vaaet_ml.data.review_widgets import build_review_widget


def prepare_inference_review(
    *,
    enabled: bool,
    classified: pd.DataFrame | None,
    inference_pipeline_run_id: str | None,
    reviewer_id: str | None,
    settings: DatabaseSettings | Mapping[str, str] | None,
    mode: str,
    is_current: Callable[[], bool] | None = None,
) -> InferenceReviewSession:
    """Conserva la UI 4.x delegando reglas y persistencia a servicios sin widgets."""

    prepared = prepare_review_session(
        enabled=enabled,
        classified=classified,
        inference_pipeline_run_id=inference_pipeline_run_id,
        reviewer_id=reviewer_id,
        settings=settings,
        mode=mode,
        is_current=is_current,
    )
    if enabled and reviewer_id is not None and prepared.session.export_frame is not None:
        build_review_widget(prepared.queue, reviewer_id=reviewer_id, on_submit=prepared.submit)
    return prepared.session


__all__ = [
    "HumanValidation",
    "HITL_CATALOG_FILE",
    "HitlCatalogPublisher",
    "HitlReviewCatalog",
    "InferenceReviewSession",
    "build_review_widget",
    "export_offline_review_package",
    "finalize_review_session",
    "load_review_queue",
    "prepare_inference_review",
    "persist_human_validation",
    "select_review_queue",
    "sync_finalized_review_session",
]
