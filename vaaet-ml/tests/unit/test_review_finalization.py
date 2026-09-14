# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Caracterización de la finalización de sesiones de revisión HITL."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from vaaet.artifacts import FEATURE_SCHEMA_VERSION

from vaaet_ml.data.artifact_serialization import (
    legacy_frames_fingerprint,
    read_package_manifest,
)
from vaaet_ml.data.hitl_catalog import (
    HitlCatalogIntegrityError,
    HitlCatalogPublisher,
    HitlCatalogSource,
    HitlCatalogUnavailableError,
    HitlReviewCatalog,
    load_hitl_catalog_feedback,
)
from vaaet_ml.data.package_codec import create_dataset_package
from vaaet_ml.data.review import HumanValidation
from vaaet_ml.data.review_finalization import (
    HITL_FINGERPRINT_ALGORITHM,
    finalize_review_session,
    import_legacy_hitl_package,
    sync_finalized_review_session,
)
from vaaet_ml.data.review_frames import normalize_review_frames
from vaaet_ml.settings import FEATURE_COLS


def _feature_values(value: float = 1.0) -> dict[str, float]:
    return {column: value + index / 100 for index, column in enumerate(FEATURE_COLS)}


def _classified_frame(*, clip_id: str = "clip-a") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "clip_id": clip_id,
                "continuity_id": f"{clip_id}:continuity-0001",
                "record_time": pd.Timestamp("2026-08-10T18:00:00Z") + pd.Timedelta(minutes=index),
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
    catalog = HitlReviewCatalog(tmp_path / "drive" / "hitl-reviews" / "catalog.json")
    with HitlCatalogPublisher(catalog, lock_directory=tmp_path / "locks") as publisher:
        first = finalize_review_session(**kwargs, publisher=publisher)
        second = finalize_review_session(**kwargs, publisher=publisher)

    assert first.sync_status == "synced"
    assert second.canonical_path == first.canonical_path
    assert first.package_id == second.package_id
    metadata = read_package_manifest(first.local_path)["package_metadata"]
    assert metadata["fingerprint_algorithm"] == HITL_FINGERPRINT_ALGORITHM
    assert catalog.load()["revision"] == 1
    assert len(catalog.load()["entries"]) == 1


def test_hitl_package_preserves_high_precision_features(tmp_path: Path) -> None:
    classified = _classified_frame()
    rng = np.random.default_rng(7)
    for column in FEATURE_COLS:
        classified[column] = rng.normal(size=len(classified))
    review_root = tmp_path / "drive" / "hitl-reviews"
    catalog = HitlReviewCatalog(review_root / "catalog.json")
    with HitlCatalogPublisher(catalog, lock_directory=tmp_path / "locks") as publisher:
        finalize_review_session(
            classified=classified,
            validations=[
                HumanValidation(prediction_id=1, validated_state=0, reviewer_id="facundo")
            ],
            pipeline_run_id=str(uuid.uuid4()),
            model_version="mlp-v3.0",
            git_commit="abc",
            vaaet_version="4.5.1",
            local_root=tmp_path / "local",
            canonical_root=review_root,
            publisher=publisher,
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
            {
                "id": 20,
                "telemetry_feature_id": 10,
                "model_version": "mlp-v2.1",
                "model_revision": "b" * 64,
            },
            {
                "id": 21,
                "telemetry_feature_id": 11,
                "model_version": "mlp-v2.1",
                "model_revision": "b" * 64,
            },
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
                "review_source": "legacy-import",
                "incident_context_reviewed": False,
            }
        ]
    )
    legacy = create_dataset_package(
        tmp_path / "legacy-hitl.zip",
        features=classified,
        predictions=predictions,
        validations=validations,
    )
    review_root = tmp_path / "reviews"
    catalog = HitlReviewCatalog(review_root / "catalog.json")
    with HitlCatalogPublisher(catalog, lock_directory=tmp_path / "locks") as publisher:
        result = import_legacy_hitl_package(
            legacy,
            pipeline_run_id=str(uuid.uuid4()),
            git_commit="legacy",
            vaaet_version="4.5.0",
            local_root=tmp_path / "local",
            canonical_root=review_root,
            publisher=publisher,
        )

    feedback, _ = load_hitl_catalog_feedback(HitlCatalogSource(review_root / "catalog.json"))
    assert result.sync_status == "synced"
    assert len(feedback) == 1
    assert feedback.iloc[0]["traffic_state"] == 0


def test_legacy_hitl_import_does_not_invent_model_revision(tmp_path: Path) -> None:
    classified = _classified_frame().assign(id=[10, 11])
    legacy = create_dataset_package(
        tmp_path / "incomplete-legacy-hitl.zip",
        features=classified,
        predictions=pd.DataFrame(
            [
                {"id": 20, "telemetry_feature_id": 10, "model_version": "mlp-v2.1"},
                {"id": 21, "telemetry_feature_id": 11, "model_version": "mlp-v2.1"},
            ]
        ),
    )

    with pytest.raises(ValueError, match="model_revision"):
        import_legacy_hitl_package(
            legacy,
            pipeline_run_id=str(uuid.uuid4()),
            git_commit="legacy",
            vaaet_version="4.5.0",
            local_root=tmp_path / "local",
            canonical_root=tmp_path / "reviews",
        )


def test_review_finalization_without_designated_publisher_remains_pending(tmp_path: Path) -> None:
    result = finalize_review_session(
        classified=_classified_frame(),
        validations=[],
        pipeline_run_id=str(uuid.uuid4()),
        model_version="mlp-v3.0",
        git_commit="abc",
        vaaet_version="4.5.0",
        local_root=tmp_path / "local",
        canonical_root=tmp_path / "drive",
    )

    assert result.sync_status == "pending-sync"
    assert result.reviewed_rows == 0
    assert result.pending_rows == 2
    assert result.local_path.is_file()
    assert "designated publisher" in str(result.sync_error)
    assert not (tmp_path / "drive" / "catalog.json").exists()


def test_review_finalization_preserves_pending_package_when_sync_fails(tmp_path: Path) -> None:
    blocked_root = tmp_path / "blocked"
    blocked_root.write_text("not a directory", encoding="utf-8")
    blocked_catalog = HitlReviewCatalog(blocked_root / "catalog.json")
    with HitlCatalogPublisher(blocked_catalog, lock_directory=tmp_path / "locks") as publisher:
        result = finalize_review_session(
            classified=_classified_frame(),
            validations=[],
            pipeline_run_id=str(uuid.uuid4()),
            model_version="mlp-v3.0",
            git_commit="abc",
            vaaet_version="4.5.0",
            local_root=tmp_path / "local",
            canonical_root=blocked_root,
            publisher=publisher,
        )

    assert result.sync_status == "pending-sync"
    assert result.sync_error
    assert result.local_path.is_file()
    assert not (blocked_root / "catalog.json").exists()

    original_bytes = result.local_path.read_bytes()
    available_root = tmp_path / "available-drive"
    catalog = HitlReviewCatalog(available_root / "catalog.json")
    with HitlCatalogPublisher(catalog, lock_directory=tmp_path / "locks") as publisher:
        synced = sync_finalized_review_session(
            result.local_path,
            canonical_root=available_root,
            publisher=publisher,
        )
    assert synced.sync_status == "synced"
    assert synced.package_id == result.package_id
    assert synced.fingerprint == result.fingerprint
    assert synced.package_sha256 == result.package_sha256
    assert result.local_path.read_bytes() == original_bytes


def test_catalog_integrity_failure_is_not_downgraded_to_pending_sync(tmp_path: Path) -> None:
    pending = finalize_review_session(
        classified=_classified_frame(),
        validations=[],
        pipeline_run_id=str(uuid.uuid4()),
        model_version="mlp-v3.0",
        git_commit="abc",
        vaaet_version="4.8.2",
        local_root=tmp_path / "local",
    )
    original_bytes = pending.local_path.read_bytes()
    review_root = tmp_path / "drive"
    review_root.mkdir()
    catalog = HitlReviewCatalog(review_root / "catalog.json")
    catalog.path.write_text("{not-json", encoding="utf-8")

    with HitlCatalogPublisher(catalog, lock_directory=tmp_path / "locks") as publisher:
        with pytest.raises(HitlCatalogIntegrityError, match="Invalid HITL catalog"):
            sync_finalized_review_session(
                pending.local_path,
                canonical_root=review_root,
                publisher=publisher,
            )

    assert pending.local_path.read_bytes() == original_bytes


@pytest.mark.parametrize("stage", ["catalog-read", "copy", "catalog-register"])
def test_each_remote_availability_failure_preserves_exact_pending_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    pending = finalize_review_session(
        classified=_classified_frame(),
        validations=[],
        pipeline_run_id=str(uuid.uuid4()),
        model_version="mlp-v3.0",
        git_commit="abc",
        vaaet_version="4.8.2",
        local_root=tmp_path / "local",
    )
    original_bytes = pending.local_path.read_bytes()
    review_root = tmp_path / "drive"
    catalog = HitlReviewCatalog(review_root / "catalog.json")
    if stage == "catalog-read":
        monkeypatch.setattr(
            HitlReviewCatalog,
            "find",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                HitlCatalogUnavailableError("offline")
            ),
        )
    elif stage == "copy":
        monkeypatch.setattr(
            "vaaet_ml.data.review_finalization._copy_immutable",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")),
        )
    else:
        monkeypatch.setattr(
            HitlReviewCatalog,
            "register",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                HitlCatalogUnavailableError("offline")
            ),
        )

    with HitlCatalogPublisher(catalog, lock_directory=tmp_path / "locks") as publisher:
        result = sync_finalized_review_session(
            pending.local_path,
            canonical_root=review_root,
            publisher=publisher,
        )

    assert result.sync_status == "pending-sync"
    assert result.canonical_path is None
    assert pending.local_path.read_bytes() == original_bytes


def test_pending_package_without_algorithm_uses_historical_fingerprint(tmp_path: Path) -> None:
    run_id = str(uuid.uuid4())
    finalized_at = datetime(2026, 8, 10, 20, tzinfo=timezone.utc)
    frames = normalize_review_frames(
        _classified_frame(),
        [HumanValidation(prediction_id=1, validated_state=0, reviewer_id="facundo")],
        pipeline_run_id=run_id,
        model_version="mlp-v3.0",
        finalized_at=finalized_at,
    )
    fingerprint = legacy_frames_fingerprint(frames)
    package_id = str(uuid.uuid4())
    local_package = create_dataset_package(
        tmp_path / "legacy-pending.zip",
        features=frames["features"],
        predictions=frames["predictions"],
        validations=frames["validations"],
        package_metadata={
            "package_id": package_id,
            "pipeline_run_id": run_id,
            "fingerprint": fingerprint,
            "vaaet_version": "4.8.0",
            "reviewed_rows": 1,
            "pending_rows": 1,
            "human_support": {"Normal": 1},
            "model_revision": "a" * 64,
            "finalized_at": finalized_at.isoformat(),
        },
    )

    review_root = tmp_path / "reviews"
    catalog = HitlReviewCatalog(review_root / "catalog.json")
    with HitlCatalogPublisher(catalog, lock_directory=tmp_path / "locks") as publisher:
        synced = sync_finalized_review_session(
            local_package, canonical_root=review_root, publisher=publisher
        )

    assert synced.sync_status == "synced"
    assert synced.package_id == package_id


@pytest.mark.parametrize(
    "mutation",
    [
        {"is_human_validated": False},
        {"review_source": "unsafe source"},
        {"supersedes_validation_id": "not-a-uuid"},
    ],
)
def test_review_finalization_rejects_incomplete_tabular_decisions(
    tmp_path: Path, mutation: dict[str, object]
) -> None:
    decision = {
        "id": str(uuid.uuid4()),
        "prediction_id": 1,
        "validated_state": 0,
        "is_human_validated": True,
        "reviewer_id": "facundo",
        "reviewed_at": "2026-08-10T20:00:00Z",
        "review_source": "colab",
        "incident_context_reviewed": False,
        "supersedes_validation_id": None,
    }
    decision.update(mutation)

    with pytest.raises(ValueError):
        finalize_review_session(
            classified=_classified_frame(),
            validations=pd.DataFrame([decision]),
            pipeline_run_id=str(uuid.uuid4()),
            model_version="mlp-v3.0",
            git_commit="abc",
            vaaet_version="4.8.2",
            local_root=tmp_path / "local",
        )
