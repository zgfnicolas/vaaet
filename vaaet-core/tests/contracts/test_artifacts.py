# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vaaet.artifacts import MANIFEST_FILE, REQUIRED_FILES, create_manifest, validate_manifest
from vaaet.exceptions import ArtifactNotFoundError, ArtifactValidationError
from vaaet.lifecycle import ModelInputPolicy, TrainingMode, build_training_lifecycle


def _passing_interval_rows(*, include_ece: bool) -> list[dict[str, object]]:
    rows = [
        ("f1_macro", 0.95, 0.90, 0.98),
        ("precision_normal", 0.96, 0.94, 0.99),
        ("precision_reduced", 0.94, 0.90, 0.98),
        ("precision_congested", 0.95, 0.92, 0.98),
        ("recall_normal", 0.96, 0.94, 0.99),
        ("recall_reduced", 0.94, 0.92, 0.98),
        ("recall_congested", 0.92, 0.88, 0.96),
        ("normal_congested_error", 0.0, 0.0, 0.005),
    ]
    if include_ece:
        rows.append(("ece", 0.02, 0.0, 0.04))
    return [
        {
            "metric": name,
            "value": value,
            "ci_95_low": low,
            "ci_95_high": high,
            "evaluable_fraction": 1.0,
            "method": "grouped-bootstrap",
            "group_count": 20,
            "bootstrap_samples": 2_000,
            "sufficient": True,
        }
        for name, value, low, high in rows
    ]


@pytest.fixture
def valid_bundle(tmp_path: Path) -> Path:
    for name in REQUIRED_FILES:
        (tmp_path / name).write_bytes(name.encode())
    create_manifest(
        tmp_path,
        metrics={
            "direct_f1_macro": 0.95,
            "final_f1_macro": 0.95,
            "unavailable_metric": float("nan"),
            "automatic_accident_states": 0,
            "congested_minutes": 100,
            "congested_clips": 20,
            "negative_exposure_hours": 300.0,
            "incident_candidate_count": 0,
            "false_candidates_per_hour": 0.0,
            "false_candidates_upper_95": 0.009,
            "grouped_direct_intervals": _passing_interval_rows(include_ece=False),
            "grouped_final_intervals": _passing_interval_rows(include_ece=True),
            "direct_normal_congested_error": 0.0,
            "final_normal_congested_error": 0.0,
            "ece": 0.02,
            "production_eligible": True,
        },
        data_provenance={
            "origin": "test",
            "record_count": 1,
            "synthetic_data_included": False,
            "telemetry_v3_coverage": 1.0,
            "human_holdout": True,
            "production_eligible": True,
            "promotion_blockers": [],
        },
        training_lifecycle=build_training_lifecycle(
            TrainingMode.HITL_RETRAINING,
            ModelInputPolicy.CANONICAL_V3,
            production_eligible=True,
        ),
        human_holdout={
            "contract": "vaaet-human-holdout-v2",
            "snapshot_id": "12345678-1234-5678-1234-567812345678",
            "generation": 1,
            "fingerprint": "a" * 64,
            "validation_rows": 12,
            "test_rows": 15,
        },
        training_input_lock={
            "contract": "vaaet-training-input-lock-v1",
            "lock_id": "87654321-4321-8765-4321-876543218765",
            "fingerprint": "b" * 64,
        },
    )
    return tmp_path


def _manifest(bundle: Path) -> dict[str, object]:
    return json.loads((bundle / MANIFEST_FILE).read_text(encoding="utf-8"))


def _write_manifest(bundle: Path, payload: object) -> None:
    (bundle / MANIFEST_FILE).write_text(json.dumps(payload), encoding="utf-8")


def test_valid_bundle(valid_bundle: Path) -> None:
    manifest = validate_manifest(valid_bundle)
    assert manifest["contract_version"] == 3
    assert len(manifest["model_revision"]) == 64
    assert manifest["model_output_mapping"] == {
        "0": "Normal",
        "1": "Reduced",
        "2": "Congested",
    }
    assert manifest["decision_policy"]["automatic_accident_state_allowed"] is False
    assert manifest["metrics"]["unavailable_metric"] is None
    assert manifest["training_lifecycle"]["deployment_stage"] == "production"
    assert manifest["training_lifecycle"]["input_policy"] == "canonical-v3"
    assert manifest["training_input_lock"]["fingerprint"] == "b" * 64


def test_rejects_invalid_training_input_lock(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["training_input_lock"]["fingerprint"] = "invalid"
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="input lock fingerprint"):
        validate_manifest(valid_bundle)


@pytest.mark.parametrize("delta", [-1, 1])
def test_rejects_feature_schema_drift(valid_bundle: Path, delta: int) -> None:
    payload = _manifest(valid_bundle)
    features = list(payload["feature_columns"])
    payload["feature_columns"] = features[:-1] if delta < 0 else [*features, "unexpected"]
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="feature schema"):
        validate_manifest(valid_bundle)


def test_rejects_missing_manifest(valid_bundle: Path) -> None:
    (valid_bundle / MANIFEST_FILE).unlink()
    with pytest.raises(ArtifactNotFoundError, match="manifest"):
        validate_manifest(valid_bundle)


def test_rejects_missing_artifact(valid_bundle: Path) -> None:
    (valid_bundle / REQUIRED_FILES[0]).unlink()
    with pytest.raises(ArtifactNotFoundError, match="artifact file"):
        validate_manifest(valid_bundle)


def test_rejects_corrupt_json(valid_bundle: Path) -> None:
    (valid_bundle / MANIFEST_FILE).write_text("{broken", encoding="utf-8")
    with pytest.raises(ArtifactValidationError, match="Invalid artifact manifest"):
        validate_manifest(valid_bundle)


def test_rejects_incompatible_mapping(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["class_mapping"] = {"0": "Unknown"}
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="class mapping"):
        validate_manifest(valid_bundle)


def test_rejects_four_mlp_outputs(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["model_output_mapping"]["3"] = "Accident"
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="MLP output mapping"):
        validate_manifest(valid_bundle)


def test_rejects_unsupported_contract(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["contract_version"] = 999
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="contract version"):
        validate_manifest(valid_bundle)


def test_rejects_policy_that_allows_automatic_accident(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["decision_policy"]["automatic_accident_state_allowed"] = True
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="prohibit automatic Accident"):
        validate_manifest(valid_bundle)


def test_rejects_invalid_calibration_temperature(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["decision_policy"]["temperature"] = 0
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="temperature"):
        validate_manifest(valid_bundle)


def test_rejects_missing_required_field(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    del payload["data_provenance"]
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="Missing manifest fields"):
        validate_manifest(valid_bundle)


def test_rejects_invalid_file_entry(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["files"][REQUIRED_FILES[0]] = "not-an-object"
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="manifest file entry"):
        validate_manifest(valid_bundle)


def test_rejects_invalid_provenance_types(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["data_provenance"]["synthetic_data_included"] = "false"
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="must be a boolean"):
        validate_manifest(valid_bundle)


def test_rejects_inconsistent_production_eligibility(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["metrics"]["production_eligible"] = False
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="eligibility"):
        validate_manifest(valid_bundle)


def test_rejects_seed_bundle_marked_as_production(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["training_lifecycle"].update(
        {
            "training_mode": "seed-bootstrap",
            "supervision": "weak-proxy",
            "deployment_stage": "production",
            "input_policy": "legacy-v1-bootstrap",
            "production_eligible": True,
        }
    )
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="weak-proxy pilots"):
        validate_manifest(valid_bundle)


def test_rejects_unknown_model_input_policy(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["training_lifecycle"]["input_policy"] = "guess-columns"
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="lifecycle mode or input policy"):
        validate_manifest(valid_bundle)


def test_rejects_seed_bundle_without_legacy_input_policy(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["training_lifecycle"].update(
        {
            "training_mode": "seed-bootstrap",
            "supervision": "weak-proxy",
            "deployment_stage": "pilot",
            "input_policy": "canonical-v2",
            "production_eligible": False,
        }
    )
    payload["metrics"]["production_eligible"] = False
    payload["data_provenance"]["production_eligible"] = False
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="legacy-policy"):
        validate_manifest(valid_bundle)


def test_rejects_hitl_bundle_marked_as_pilot(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["training_lifecycle"]["deployment_stage"] = "pilot"
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="HITL bundles"):
        validate_manifest(valid_bundle)


def test_rejects_changed_bundle_file(valid_bundle: Path) -> None:
    (valid_bundle / REQUIRED_FILES[0]).write_bytes(b"changed")
    with pytest.raises(ArtifactValidationError, match="Checksum"):
        validate_manifest(valid_bundle)


def test_rejects_frozen_holdout_without_snapshot_descriptor(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["human_holdout"] = None
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="snapshot descriptor"):
        validate_manifest(valid_bundle)


def test_rejects_invalid_holdout_fingerprint(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["human_holdout"]["fingerprint"] = "invalid"
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="fingerprint"):
        validate_manifest(valid_bundle)


def test_rejects_manifest_that_is_not_an_object(valid_bundle: Path) -> None:
    _write_manifest(valid_bundle, [])
    with pytest.raises(ArtifactValidationError, match="JSON object"):
        validate_manifest(valid_bundle)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("", "generated_at must be a non-empty"),
        ("not-a-timestamp", "valid ISO-8601"),
        ("2026-08-28T12:00:00", "must include a timezone"),
    ],
)
def test_rejects_invalid_generated_at(valid_bundle: Path, value: str, message: str) -> None:
    payload = _manifest(valid_bundle)
    payload["generated_at"] = value
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match=message):
        validate_manifest(valid_bundle)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("git_commit", "", "git_commit"),
        ("feature_schema_version", "traffic-feature-v99", "feature schema version"),
        ("model_version", "unknown", "model version"),
    ],
)
def test_rejects_invalid_identity_value(
    valid_bundle: Path, field: str, value: str, message: str
) -> None:
    payload = _manifest(valid_bundle)
    payload[field] = value
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match=message):
        validate_manifest(valid_bundle)


def test_rejects_missing_lifecycle_field(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    del payload["training_lifecycle"]["supervision"]
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="Missing training lifecycle fields"):
        validate_manifest(valid_bundle)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("deployment_stage", "unknown", "Unsupported bundle deployment stage"),
        ("supervision", "", "supervision must be non-empty"),
        ("production_eligible", "false", "eligibility must be boolean"),
    ],
)
def test_rejects_invalid_lifecycle_value(
    valid_bundle: Path, field: str, value: object, message: str
) -> None:
    payload = _manifest(valid_bundle)
    payload["training_lifecycle"][field] = value
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match=message):
        validate_manifest(valid_bundle)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("automatic_accident_state_allowed", "false", "prohibit automatic Accident"),
        ("human_confirmation_required_for_accident", False, "require human confirmation"),
        ("class_thresholds", {"0": True, "1": 0.6, "2": 0.7}, "thresholds must be numeric"),
        ("class_thresholds", {"0": 0.6}, "class thresholds are incompatible"),
        ("class_thresholds", {"0": 1.1, "1": 0.6, "2": 0.7}, "between 0 and 1"),
        ("temperature", 11.0, "outside the supported range"),
        ("temperature", "1.0", "temperature must be numeric"),
    ],
)
def test_rejects_invalid_decision_policy(
    valid_bundle: Path, field: str, value: object, message: str
) -> None:
    payload = _manifest(valid_bundle)
    payload["decision_policy"][field] = value
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match=message):
        validate_manifest(valid_bundle)


def test_rejects_invalid_dependency_version(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["dependencies"]["joblib"] = ""
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="dependency version"):
        validate_manifest(valid_bundle)


def test_rejects_invalid_f1_metric(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["metrics"]["direct_f1_macro"] = 2.0
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="f1_macro"):
        validate_manifest(valid_bundle)


def test_rejects_invalid_provenance_coverage(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["data_provenance"]["telemetry_v3_coverage"] = True
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="coverage must be numeric"):
        validate_manifest(valid_bundle)


def test_rejects_invalid_holdout_generation(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["human_holdout"]["generation"] = 0
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="generation must be positive"):
        validate_manifest(valid_bundle)


def test_rejects_incomplete_training_input_lock(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["training_input_lock"] = {"contract": "vaaet-training-input-lock-v1"}
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="Missing training input lock fields"):
        validate_manifest(valid_bundle)


def test_rejects_inconsistent_lifecycle_eligibility(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["training_lifecycle"]["production_eligible"] = False
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="lifecycle eligibility"):
        validate_manifest(valid_bundle)


def test_rejects_invalid_artifact_file_hash(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["files"][REQUIRED_FILES[0]]["sha256"] = "invalid"
    _write_manifest(valid_bundle, payload)
    with pytest.raises(ArtifactValidationError, match="Invalid SHA-256"):
        validate_manifest(valid_bundle)


def test_model_revision_changes_with_input_policy(valid_bundle: Path) -> None:
    original = _manifest(valid_bundle)["model_revision"]
    payload = _manifest(valid_bundle)
    payload["training_lifecycle"]["input_policy"] = "legacy-v1-bootstrap"
    payload["training_lifecycle"]["deployment_stage"] = "pilot"
    payload["training_lifecycle"]["training_mode"] = "seed-bootstrap"
    payload["training_lifecycle"]["supervision"] = "weak-proxy"
    payload["training_lifecycle"]["production_eligible"] = False
    payload["metrics"]["production_eligible"] = False
    payload["data_provenance"]["production_eligible"] = False
    payload["data_provenance"]["human_holdout"] = False
    payload["data_provenance"]["promotion_blockers"] = ["historical comparison"]
    payload["human_holdout"] = None
    _write_manifest(valid_bundle, payload)

    with pytest.raises(ArtifactValidationError, match="model_revision"):
        validate_manifest(valid_bundle)

    assert original == payload["model_revision"]


def test_old_revision_algorithm_is_historical_only(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    del payload["model_revision_algorithm"]
    _write_manifest(valid_bundle, payload)

    with pytest.raises(ArtifactValidationError, match="historical evaluation"):
        validate_manifest(valid_bundle)
    assert validate_manifest(valid_bundle, allow_historical_revision=True)


def test_rejects_production_evidence_with_declared_blockers(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["data_provenance"]["promotion_blockers"] = ["insufficient evidence"]
    _write_manifest(valid_bundle, payload)

    with pytest.raises(ArtifactValidationError, match="contradictory"):
        validate_manifest(valid_bundle)


def test_rejects_production_point_outside_grouped_interval(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["metrics"]["direct_f1_macro"] = 0.91
    _write_manifest(valid_bundle, payload)

    with pytest.raises(ArtifactValidationError, match="inconsistent with grouped evidence"):
        validate_manifest(valid_bundle)


def test_rejects_production_interval_without_group_evidence(valid_bundle: Path) -> None:
    payload = _manifest(valid_bundle)
    payload["metrics"]["grouped_final_intervals"][0]["group_count"] = 1
    _write_manifest(valid_bundle, payload)

    with pytest.raises(ArtifactValidationError, match="grouped-bootstrap evidence"):
        validate_manifest(valid_bundle)
