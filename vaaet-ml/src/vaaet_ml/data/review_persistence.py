# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Fachada 4.x de persistencia HITL compartida."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

import pandas as pd
from sqlalchemy.engine import Engine
from vaaet_persistence.connection import dispose_engine
from vaaet_persistence.review_persistence import (
    REVIEW_QUEUE_QUERY,
    PersistedHumanValidation,
)
from vaaet_persistence.review_persistence import load_review_queue as _load_review_queue
from vaaet_persistence.review_persistence import (
    persist_human_validation as _persist_human_validation,
)
from vaaet_persistence.review_persistence import (
    persist_human_validation_record as _persist_human_validation_record,
)
from vaaet_persistence.settings import DatabaseSettings

from vaaet_ml import __version__
from vaaet_ml.data.database_connection import get_engine
from vaaet_ml.data.review_domain import HumanValidation


def load_review_queue(
    *,
    settings: DatabaseSettings | Mapping[str, str] | None = None,
    engine: Engine | None = None,
    pipeline_run_id: UUID | str | None = None,
    mode: str = "priority",
) -> pd.DataFrame:
    owns = engine is None
    active = engine if engine is not None else get_engine(settings)
    try:
        return _load_review_queue(
            engine=active, pipeline_run_id=pipeline_run_id, mode=mode
        )
    finally:
        if owns:
            dispose_engine(active)


def persist_human_validation(
    decision: HumanValidation,
    *,
    settings: DatabaseSettings | Mapping[str, str] | None = None,
    engine: Engine | None = None,
    pipeline_run_id: UUID | str | None = None,
) -> UUID:
    owns = engine is None
    active = engine if engine is not None else get_engine(settings)
    try:
        return _persist_human_validation(
            decision,
            engine=active,
            pipeline_run_id=pipeline_run_id,
            application_name="vaaet-ml-review",
            application_version=__version__,
        )
    finally:
        if owns:
            dispose_engine(active)


def persist_human_validation_record(
    decision: HumanValidation,
    *,
    settings: DatabaseSettings | Mapping[str, str] | None = None,
    engine: Engine | None = None,
    pipeline_run_id: UUID | str | None = None,
) -> PersistedHumanValidation:
    """Devuelve la identidad exacta que comparten PostgreSQL y el paquete HITL."""

    owns = engine is None
    active = engine if engine is not None else get_engine(settings)
    try:
        return _persist_human_validation_record(
            decision,
            engine=active,
            pipeline_run_id=pipeline_run_id,
            application_name="vaaet-ml-review",
            application_version=__version__,
        )
    finally:
        if owns:
            dispose_engine(active)


__all__ = [
    "PersistedHumanValidation",
    "REVIEW_QUEUE_QUERY",
    "load_review_queue",
    "persist_human_validation",
    "persist_human_validation_record",
]
