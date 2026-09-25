# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Evidencia de auditoría en fuentes portables y backups PostgreSQL."""

from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest
from vaaet.artifacts import FEATURE_SCHEMA_VERSION
from vaaet.settings import FEATURE_COLS
from vaaet_persistence.receipts import (
    PERSISTENCE_RECEIPT_ALGORITHM,
    build_persistence_receipt,
)

from vaaet_ml.data.ingestion import (
    DatasetPackageSource,
    TrainingIngestionPlan,
    load_training_inputs,
)
from vaaet_ml.data.review_audit import (
    ReviewAuditOrigin,
    build_review_audit_manifest,
    validate_review_audit,
    validate_review_audit_manifest,
    verify_backup_review_audit,
)
from vaaet_ml.data.review_domain import HumanValidation
from vaaet_ml.data.review_finalization import seal_review_package
from vaaet_ml.training.lifecycle import TrainingMode


def test_pending_and_unknown_reviews_remain_inspection_only() -> None:
    decision_id = str(uuid4())
    with pytest.raises(ValueError, match="inspection only"):
        validate_review_audit(pd.DataFrame([{"id": decision_id}]))
    with pytest.raises(ValueError, match="status is unknown"):
        validate_review_audit(
            pd.DataFrame([{"id": decision_id, "review_audit_origin": "portable"}]),
            declared_origin=ReviewAuditOrigin.PORTABLE,
        )
    with pytest.raises(ValueError, match="incomplete"):
        validate_review_audit(
            pd.DataFrame(
                [
                    {
                        "id": decision_id,
                        "review_audit_origin": "postgresql",
                        "audit_complete": False,
                        "pipeline_run_id": str(uuid4()),
                        "persistence_receipt_fingerprint": "a" * 64,
                    }
                ]
            )
        )


def test_backup_decision_requires_exact_committed_receipt() -> None:
    decision = HumanValidation(1, 1, "reviewer")
    run_id = uuid4()
    payload = {**asdict(decision), "id": str(decision.validation_id)}
    del payload["validation_id"]
    payload["pipeline_run_id"] = str(run_id)
    receipt = build_persistence_receipt(
        pipeline_run_id=run_id,
        operation="human-validation",
        observations=[payload],
        processed_counts={"human_validations": 1},
        inserted_counts={"human_validations": 1},
    )
    components = {
        "validations": pd.DataFrame([payload]),
        "runs": pd.DataFrame(
            [
                {
                    "id": str(run_id),
                    "workflow": "review",
                    "status": "succeeded",
                    "input_rows": 1,
                    "output_rows": 1,
                    "database_user": "review-user",
                }
            ]
        ),
        "receipts": pd.DataFrame(
            [
                {
                    "pipeline_run_id": str(run_id),
                    "operation": "human-validation",
                    "fingerprint_algorithm": PERSISTENCE_RECEIPT_ALGORITHM,
                    "content_fingerprint": receipt.content_fingerprint,
                    "processed_counts": {"human_validations": 1},
                    "inserted_counts": {"human_validations": 1},
                    "database_user": "review-user",
                }
            ]
        ),
    }
    verified = verify_backup_review_audit(components)
    assert verified["validations"].iloc[0]["persistence_receipt_fingerprint"] == (
        receipt.content_fingerprint
    )
    altered = {
        **components,
        "validations": components["validations"].assign(validated_state=2),
    }
    with pytest.raises(ValueError, match="does not match"):
        verify_backup_review_audit(altered)
    incomplete = {**components, "runs": components["runs"].drop(columns="database_user")}
    with pytest.raises(ValueError, match="inspection only"):
        verify_backup_review_audit(incomplete)


def test_portable_postgres_review_proves_receipt_and_manifest(tmp_path: Path) -> None:
    decision = HumanValidation(17, 2, "reviewer")
    review_run_id = uuid4()
    portable_prediction_id = str(uuid4())
    payload = {**asdict(decision), "id": str(decision.validation_id)}
    del payload["validation_id"]
    payload["pipeline_run_id"] = str(review_run_id)
    receipt = build_persistence_receipt(
        pipeline_run_id=review_run_id,
        operation="human-validation",
        observations=[payload],
        processed_counts={"human_validations": 1},
        inserted_counts={"human_validations": 1},
    )
    validations = pd.DataFrame(
        [
            {
                **payload,
                "prediction_id": portable_prediction_id,
                "review_audit_origin": "postgresql",
                "audit_complete": True,
                "persistence_receipt_fingerprint": receipt.content_fingerprint,
            }
        ]
    )
    predictions = pd.DataFrame(
        [{"id": portable_prediction_id, "operational_prediction_id": 17}]
    )
    verified = validate_review_audit(validations, predictions=predictions)
    metadata = {"review_audit_evidence": build_review_audit_manifest(verified)}
    validate_review_audit_manifest(verified, metadata)

    with pytest.raises(ValueError, match="contradicts the decision"):
        validate_review_audit(
            validations.assign(validated_state=1), predictions=predictions
        )
    with pytest.raises(ValueError, match="contradicts its audit evidence"):
        validate_review_audit_manifest(
            verified,
            {
                "review_audit_evidence": [
                    {**metadata["review_audit_evidence"][0], "audit_complete": False}
                ]
            },
        )
    classified = pd.DataFrame(
        [
            {
                "clip_id": "audit-clip",
                "continuity_id": "audit-clip:continuity-0001",
                "record_time": "2026-09-24T12:00:00Z",
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "model_version": "mlp-v3.0",
                "model_revision": "a" * 64,
                "traffic_state": 2,
                "state_label": "Congested",
                "confidence": 0.8,
                "prediction_id": 17,
                **{feature: 1.0 for feature in FEATURE_COLS},
            }
        ]
    )
    package = seal_review_package(
        tmp_path / "review.zip",
        classified=classified,
        validations=validations.assign(prediction_id=17),
        pipeline_run_id=str(uuid4()),
        model_version="mlp-v3.0",
        git_commit="test",
        vaaet_version="4.9.1",
    )
    loaded = load_training_inputs(
        TrainingIngestionPlan(
            mode=TrainingMode.HITL_RETRAINING,
            feedback_sources=(DatasetPackageSource(package),),
        )
    )
    assert loaded.validated_feedback.iloc[0]["traffic_state"] == 2
