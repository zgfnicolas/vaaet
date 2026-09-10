# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Caracterización de la finalización de sesiones de revisión HITL."""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from vaaet.artifacts import FEATURE_SCHEMA_VERSION

from vaaet_ml.data.hitl_catalog import (
    HitlCatalogSource,
    HitlReviewCatalog,
    load_hitl_catalog_feedback,
)
from vaaet_ml.data.package_codec import create_dataset_package
from vaaet_ml.data.review import HumanValidation
from vaaet_ml.data.review_finalization import (
    finalize_review_session,
    import_legacy_hitl_package,
)
from vaaet_ml.settings import FEATURE_COLS


def _feature_values(value: float = 1.0) -> dict[str, float]:
    return {column: value + index / 100 for index, column in enumerate(FEATURE_COLS)}


def _classified_frame(*, clip_id: str = "clip-a") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "clip_id": clip_id,
                "continuity_id": f"{clip_id}:continuity-0001",
                "record_time": pd.Timestamp("2026-08-10T18:00:00Z")
                + pd.Timedelta(minutes=index),
                "traffic_state": state,
                "state_label": ("Normal", "Reduced")[state],
                "confidence": 0.9,
                "model_version": "mlp-v3.0",
                "model_revision": "a" * 64,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "numeric_representation": "float64",
                **_feature_values(10.0 + index),
            }
            for index, state in enumerate((0, 1))
        ]
    )


def test_review_finalization_is_idempotent_and_cataloged(tmp_path: Path) -> None:
    run_id = str(uuid.uuid4())
    classified = _classified_frame()
    decision = HumanValidation(prediction_id=1, validated_state=0, reviewer_id="facundo")
    kwargs = {
        "classified": classified,
        "validations": [decision],
        "pipeline_run_id": run_id,
        "model_version": "mlp-v3.0",
        "git_commit": "abc",
        "vaaet_version": "4.5.0",
        "local_root": tmp_path / "local",
        "canonical_root": tmp_path / "drive" / "hitl-reviews",
    }
    first = finalize_review_session(**kwargs)
    second = finalize_review_session(**kwargs)

    assert first.sync_status == "synced"
    assert second.canonical_path == first.canonical_path
    assert first.package_id == second.package_id
    catalog = HitlReviewCatalog(tmp_path / "drive" / "hitl-reviews" / "catalog.json")
    assert catalog.load()["revision"] == 1
    assert len(catalog.load()["entries"]) == 1


def test_hitl_package_preserves_high_precision_features(tmp_path: Path) -> None:
    classified = _classified_frame()
    rng = np.random.default_rng(7)
    for column in FEATURE_COLS:
        classified[column] = rng.normal(size=len(classified))
    review_root = tmp_path / "drive" / "hitl-reviews"
    finalize_review_session(
        classified=classified,
        validations=[HumanValidation(prediction_id=1, validated_state=0, reviewer_id="facundo")],
        pipeline_run_id=str(uuid.uuid4()),
        model_version="mlp-v3.0",
        git_commit="abc",
        vaaet_version="4.5.1",
        local_root=tmp_path / "local",
        canonical_root=review_root,
    )

    feedback, _ = load_hitl_catalog_feedback(HitlCatalogSource(review_root / "catalog.json"))
    expected = classified.iloc[0]
    assert len(feedback) == 1
    for column in FEATURE_COLS:
        assert feedback.iloc[0][column] == expected[column]


def test_review_finalization_rejects_non_sha_model_revision(tmp_path: Path) -> None:
    classified = _classified_frame()
    classified["model_revision"] = "x" * 64

    with pytest.raises(ValueError, match="SHA-256 model_revision"):
        finalize_review_session(
            classified=classified,
            validations=[],
            pipeline_run_id=str(uuid.uuid4()),
            model_version="mlp-v3.0",
            git_commit="abc",
            vaaet_version="4.6.0",
            local_root=tmp_path / "local",
        )


def test_legacy_hitl_package_is_imported_explicitly(tmp_path: Path) -> None:
    classified = _classified_frame()
    classified["id"] = [10, 11]
    predictions = pd.DataFrame(
        [
            {"id": 20, "telemetry_feature_id": 10, "model_version": "mlp-v2.1"},
            {"id": 21, "telemetry_feature_id": 11, "model_version": "mlp-v2.1"},
        ]
    )
    validations = pd.DataFrame(
        [
            {
                "id": str(uuid.uuid4()),
                "prediction_id": 20,
                "validated_state": 0,
                "reviewer_id": "legacy-reviewer",
                "reviewed_at": "2026-08-10T20:00:00Z",
            }
        ]
    )
    legacy = create_dataset_package(
        tmp_path / "legacy-hitl.zip",
        features=classified,
        predictions=predictions,
        validations=validations,
    )
    result = import_legacy_hitl_package(
        legacy,
        pipeline_run_id=str(uuid.uuid4()),
        git_commit="legacy",
        vaaet_version="4.5.0",
        local_root=tmp_path / "local",
        canonical_root=tmp_path / "reviews",
    )

    feedback, _ = load_hitl_catalog_feedback(HitlCatalogSource(tmp_path / "reviews" / "catalog.json"))
    assert result.sync_status == "synced"
    assert len(feedback) == 1
    assert feedback.iloc[0]["traffic_state"] == 0


def test_review_finalization_without_canonical_store_remains_pending(tmp_path: Path) -> None:
    result = finalize_review_session(
        classified=_classified_frame(),
        validations=[],
        pipeline_run_id=str(uuid.uuid4()),
        model_version="mlp-v3.0",
        git_commit="abc",
        vaaet_version="4.5.0",
        local_root=tmp_path / "local",
    )

    assert result.sync_status == "pending-sync"
    assert result.reviewed_rows == 0
    assert result.pending_rows == 2
    assert result.local_path.is_file()


def test_review_finalization_preserves_pending_package_when_sync_fails(tmp_path: Path) -> None:
    blocked_root = tmp_path / "blocked"
    blocked_root.write_text("not a directory", encoding="utf-8")
    result = finalize_review_session(
        classified=_classified_frame(),
        validations=[],
        pipeline_run_id=str(uuid.uuid4()),
        model_version="mlp-v3.0",
        git_commit="abc",
        vaaet_version="4.5.0",
        local_root=tmp_path / "local",
        canonical_root=blocked_root,
    )

    assert result.sync_status == "pending-sync"
    assert result.sync_error
    assert result.local_path.is_file()
    assert not (blocked_root / "catalog.json").exists()
