# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Contract tests for explicit training-data composition."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from vaaet.artifacts import FEATURE_SCHEMA_VERSION

from vaaet_ml.data.ingestion import (
    RAW_REQUIRED_COLUMNS,
    DatasetPackageSource,
    FeedbackPolicy,
    PostgresBackupSource,
    RawCsvSource,
    SeedDatasetPackageSource,
    TrainingIngestionPlan,
    _deduplicate_feedback,
    compose_supervised_dataset,
    create_dataset_package,
    load_dataset_package,
    load_training_inputs,
)
from vaaet_ml.settings import FEATURE_COLS
from vaaet_ml.training.lifecycle import TrainingMode


def _features(state: int = 1) -> pd.DataFrame:
    row: dict[str, object] = {column: 1.0 for column in FEATURE_COLS}
    row.update(
        id="11111111-1111-4111-8111-111111111111",
        clip_id="clip-a",
        continuity_id="clip-a:continuity-0001",
        record_time="2026-08-04T12:00:00Z",
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        traffic_state=state,
        is_human_validated=True,
    )
    return pd.DataFrame([row])


def _package_tables(path: Path, state: int = 1) -> Path:
    features = _features(state).drop(columns=["traffic_state", "is_human_validated"])
    predictions = pd.DataFrame(
        [
            {
                "id": "22222222-2222-4222-8222-222222222222",
                "telemetry_feature_id": "11111111-1111-4111-8111-111111111111",
                "model_version": "mlp-v3.0",
                "model_revision": "a" * 64,
            }
        ]
    )
    validations = pd.DataFrame(
        [
            {
                "id": "d266e373-f8ce-405e-8144-2f508a5bdc85",
                "prediction_id": "22222222-2222-4222-8222-222222222222",
                "validated_state": state,
                "is_human_validated": True,
                "reviewed_at": "2026-08-04T13:00:00Z",
                "supersedes_validation_id": pd.NA,
            }
        ]
    )
    return create_dataset_package(
        path, features=features, predictions=predictions, validations=validations
    )


def test_plan_requires_explicit_source() -> None:
    with pytest.raises(ValueError, match="explicit training source"):
        TrainingIngestionPlan(mode=TrainingMode.SEED_BOOTSTRAP)


def test_only_validated_feedback_policy_exists() -> None:
    assert list(FeedbackPolicy) == [FeedbackPolicy.VALIDATED_ONLY]


def test_feedback_requires_explicit_human_validation_evidence() -> None:
    feedback = _features().drop(columns="is_human_validated")

    with pytest.raises(ValueError, match="explicitly prove human validation"):
        _deduplicate_feedback([feedback])


def test_hitl_mode_requires_validated_feedback_source(tmp_path: Path) -> None:
    seed = create_dataset_package(
        tmp_path / "seed.zip",
        features=_features(),
        provenance={"training_mode": "seed-bootstrap", "supervision": "weak-proxy"},
    )
    with pytest.raises(ValueError, match="HITL retraining requires"):
        TrainingIngestionPlan(
            mode=TrainingMode.HITL_RETRAINING,
            seed_sources=(SeedDatasetPackageSource(seed),),
        )


def test_processed_seed_package_is_loaded_without_raw_engineering(tmp_path: Path) -> None:
    seed_features = _features(state=2)
    seed_features["is_human_validated"] = False
    package = create_dataset_package(
        tmp_path / "vaaet-seed-bootstrap-v1.zip",
        features=seed_features,
        provenance={"training_mode": "seed-bootstrap", "supervision": "weak-proxy"},
    )
    result = load_training_inputs(
        TrainingIngestionPlan(
            mode=TrainingMode.SEED_BOOTSTRAP,
            seed_sources=(SeedDatasetPackageSource(package),),
        )
    )
    assert result.raw.empty
    assert len(result.seed_features) == 1
    assert result.seed_features.iloc[0]["traffic_state"] == 2
    assert not bool(result.seed_features.iloc[0]["is_human_validated"])
    assert result.provenance.iloc[0]["kind"] == "processed_seed"


def test_seed_package_requires_weak_proxy_provenance(tmp_path: Path) -> None:
    features = _features()
    features["is_human_validated"] = False
    package = create_dataset_package(tmp_path / "seed.zip", features=features)
    with pytest.raises(ValueError, match="seed-bootstrap weak-proxy"):
        load_training_inputs(
            TrainingIngestionPlan(
                mode=TrainingMode.SEED_BOOTSTRAP,
                seed_sources=(SeedDatasetPackageSource(package),),
            )
        )


def test_dataset_package_roundtrip_and_checksum(tmp_path: Path) -> None:
    package = _package_tables(tmp_path / "vaaet-training-dataset-v1.zip")
    frames = load_dataset_package(package)
    assert set(frames) == {"features", "predictions", "validations"}

    damaged = tmp_path / "damaged.zip"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(damaged, "w") as target:
        for member in source.infolist():
            payload = source.read(member)
            if member.filename == "telemetry-features.csv":
                payload += b"\ncorruption"
            target.writestr(member, payload)
    with pytest.raises(ValueError, match="checksum de una tabla"):
        load_dataset_package(damaged)


def test_dataset_package_never_overwrites_silently(tmp_path: Path) -> None:
    package = _package_tables(tmp_path / "immutable.zip")
    original = package.read_bytes()
    with pytest.raises(FileExistsError, match="ya existe"):
        _package_tables(package)
    assert package.read_bytes() == original


def test_combines_raw_and_human_feedback(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.csv"
    pd.DataFrame(
        [
            {
                "clip_id": "raw-clip",
                "record_time": "2026-08-04T11:00:00Z",
                "avg_speed": 50,
                "count_car": 1,
                "count_truck": 0,
                "count_bus": 0,
                "count_motorcycle": 0,
                "count_bicycle": 0,
                "total_vehicles": 1,
            }
        ]
    ).to_csv(raw_path, index=False)
    package = _package_tables(tmp_path / "feedback.zip")
    result = load_training_inputs(
        TrainingIngestionPlan(
            mode=TrainingMode.HITL_RETRAINING,
            raw_sources=(RawCsvSource(raw_path),),
            feedback_sources=(DatasetPackageSource(package),),
        )
    )
    assert len(result.raw) == 1
    assert len(result.validated_feedback) == 1
    assert result.validated_feedback.iloc[0]["traffic_state"] == 1
    assert result.confirmed_incidents.empty
    assert set(result.provenance["kind"]) == {"raw", "validated_feedback"}


def test_legacy_raw_csv_is_localized_and_reports_temporal_assumption(tmp_path: Path) -> None:
    raw_path = tmp_path / "legacy.csv"
    pd.DataFrame(
        [
            {
                "clip_id": "legacy-clip",
                "record_time": "2025-04-28 10:00:00",
                "avg_speed": 50,
                "count_car": 1,
                "count_truck": 0,
                "count_bus": 0,
                "count_motorcycle": 0,
                "count_bicycle": 0,
                "total_vehicles": 1,
            }
        ]
    ).to_csv(raw_path, index=False)

    result = load_training_inputs(
        TrainingIngestionPlan(
            mode=TrainingMode.SEED_BOOTSTRAP,
            raw_sources=(RawCsvSource(raw_path),),
        )
    )

    assert result.raw.iloc[0]["record_time"] == pd.Timestamp("2025-04-28 13:00:00Z")
    source = result.provenance.iloc[0]
    assert source["timestamp_timezone"] == "UTC"
    assert source["naive_timezone_assumption"] == "America/Argentina/Buenos_Aires"
    assert source["naive_timestamps_localized"] == 1


def test_accident_is_reserved_for_incident_evaluation(tmp_path: Path) -> None:
    package = _package_tables(tmp_path / "accident.zip", state=3)
    result = load_training_inputs(
        TrainingIngestionPlan(
            mode=TrainingMode.HITL_RETRAINING,
            feedback_sources=(DatasetPackageSource(package),),
        )
    )
    assert result.validated_feedback.empty
    assert len(result.confirmed_incidents) == 1


def test_conflicting_human_labels_stop_ingestion(tmp_path: Path) -> None:
    first = _package_tables(tmp_path / "first.zip", state=0)
    second = _package_tables(tmp_path / "second.zip", state=2)
    with pytest.raises(ValueError, match="Conflicting human labels"):
        load_training_inputs(
            TrainingIngestionPlan(
                mode=TrainingMode.HITL_RETRAINING,
                feedback_sources=(DatasetPackageSource(first), DatasetPackageSource(second)),
            )
        )


def test_feedback_rejects_reordered_feature_contract(tmp_path: Path) -> None:
    features = _features().drop(columns=["traffic_state", "is_human_validated"])
    metadata = [column for column in features if column not in FEATURE_COLS]
    reversed_features = features[[*metadata, *reversed(FEATURE_COLS)]]
    package = create_dataset_package(
        tmp_path / "reordered.zip",
        features=reversed_features,
        predictions=pd.DataFrame(
            [
                {
                    "id": "22222222-2222-4222-8222-222222222222",
                    "telemetry_feature_id": "11111111-1111-4111-8111-111111111111",
                    "model_version": "mlp-v3.0",
                    "model_revision": "a" * 64,
                }
            ]
        ),
        validations=pd.DataFrame(
            [
                {
                    "id": "d266e373-f8ce-405e-8144-2f508a5bdc85",
                    "prediction_id": "22222222-2222-4222-8222-222222222222",
                    "validated_state": 1,
                    "is_human_validated": True,
                    "reviewed_at": "2026-08-04T13:00:00Z",
                    "supersedes_validation_id": pd.NA,
                }
            ]
        ),
    )
    with pytest.raises(ValueError, match="exact 19-feature order"):
        load_training_inputs(
            TrainingIngestionPlan(
                mode=TrainingMode.HITL_RETRAINING,
                feedback_sources=(DatasetPackageSource(package),),
            )
        )


def test_rejects_wrong_package_contract(tmp_path: Path) -> None:
    package = _package_tables(tmp_path / "package.zip")
    rewritten = tmp_path / "wrong-contract.zip"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(rewritten, "w") as target:
        for member in source.infolist():
            payload = source.read(member)
            if member.filename == "dataset-manifest.json":
                manifest = json.loads(payload)
                manifest["contract_version"] = "unsupported"
                payload = json.dumps(manifest).encode()
            target.writestr(member, payload)
    with pytest.raises(ValueError, match="contrato de paquete no admitida"):
        load_dataset_package(rewritten)


def test_dataset_package_rejects_missing_and_unsafe_archives(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="No se encontró"):
        load_dataset_package(tmp_path / "missing.zip")

    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../escape.csv", "unsafe")
    with pytest.raises(ValueError, match="ruta insegura"):
        load_dataset_package(unsafe)


def test_human_label_precedes_proxy_for_same_minute() -> None:
    proxy = _features(state=0)
    proxy["is_human_validated"] = False
    human = _features(state=2)
    result = compose_supervised_dataset(proxy, human)
    assert len(result) == 1
    assert result.iloc[0]["traffic_state"] == 2
    assert bool(result.iloc[0]["is_human_validated"])


def test_raw_backup_extracts_only_requested_raw_table(tmp_path: Path) -> None:
    backup = tmp_path / "full.backup"
    backup.write_bytes(b"PGDMP")
    restored = tmp_path / "restored.sql"
    restored.write_text("restored", encoding="utf-8")
    raw = pd.DataFrame(
        [
            {
                "clip_id": "clip",
                "record_time": "2026-08-04T12:00:00Z",
                "avg_speed": 1,
                "count_car": 1,
                "count_truck": 0,
                "count_bus": 0,
                "count_motorcycle": 0,
                "count_bicycle": 0,
                "total_vehicles": 1,
            }
        ]
    )
    catalog = (
        "vaaet_raw.traffic_data",
        "vaaet_ml.telemetry_features",
        "vaaet_ml.traffic_predictions",
        "vaaet_feedback.human_validations",
    )
    with (
        patch("vaaet_ml.data.ingestion.inspect_backup_catalog", return_value=catalog),
        patch(
            "vaaet_ml.data.ingestion.get_pg_restore_version",
            return_value="pg_restore (PostgreSQL) 17.10",
        ),
        patch("vaaet_ml.data.ingestion.restore_backup_to_sql", return_value=restored) as restore,
        patch(
            "vaaet_ml.data.ingestion.parse_sql_dump_tables",
            return_value={"vaaet_raw.traffic_data": raw},
        ),
    ):
        result = load_training_inputs(
            TrainingIngestionPlan(
                mode=TrainingMode.SEED_BOOTSTRAP,
                raw_sources=(PostgresBackupSource(backup),),
            )
        )
    assert len(result.raw) == 1
    assert restore.call_args.kwargs["tables"] == ("vaaet_raw.traffic_data",)
    assert result.provenance.iloc[0]["archive_table"] == "vaaet_raw.traffic_data"
    assert result.provenance.iloc[0]["backup_layout"] == "modern"
    assert result.provenance.iloc[0]["reader_version"] == "pg_restore (PostgreSQL) 17.10"


def test_legacy_raw_backup_reports_table_and_preserves_columns(tmp_path: Path) -> None:
    backup = tmp_path / "legacy.backup"
    backup.write_bytes(b"PGDMP")
    restored = tmp_path / "legacy.sql"
    restored.write_text("restored", encoding="utf-8")
    raw = pd.DataFrame(
        [
            {
                "id": 1,
                "clip_id": "legacy-clip",
                "record_time": "2025-04-21T12:00:00Z",
                "avg_speed": 45.5,
                "count_car": 10,
                "count_truck": 2,
                "count_bus": 1,
                "count_motorcycle": 3,
                "count_bicycle": 0,
                "total_vehicles": 16,
            }
        ]
    )
    with (
        patch(
            "vaaet_ml.data.ingestion.inspect_backup_catalog",
            return_value=("public.traffic_data",),
        ),
        patch(
            "vaaet_ml.data.ingestion.get_pg_restore_version",
            return_value="pg_restore (PostgreSQL) 17.10",
        ),
        patch("vaaet_ml.data.ingestion.restore_backup_to_sql", return_value=restored),
        patch(
            "vaaet_ml.data.ingestion.parse_sql_dump_tables",
            return_value={"public.traffic_data": raw},
        ),
    ):
        result = load_training_inputs(
            TrainingIngestionPlan(
                mode=TrainingMode.SEED_BOOTSTRAP,
                raw_sources=(PostgresBackupSource(backup),),
            )
        )

    assert list(result.raw.columns) == list(raw.columns)
    assert result.provenance.iloc[0]["archive_table"] == "public.traffic_data"
    assert result.provenance.iloc[0]["backup_layout"] == "legacy"


def test_explicit_empty_raw_backup_fails_with_specific_table(tmp_path: Path) -> None:
    backup = tmp_path / "empty.backup"
    backup.write_bytes(b"PGDMP")
    restored = tmp_path / "empty.sql"
    restored.write_text("restored", encoding="utf-8")
    empty_raw = pd.DataFrame(columns=sorted(RAW_REQUIRED_COLUMNS))
    with (
        patch(
            "vaaet_ml.data.ingestion.inspect_backup_catalog",
            return_value=("public.traffic_data",),
        ),
        patch(
            "vaaet_ml.data.ingestion.get_pg_restore_version",
            return_value="pg_restore (PostgreSQL) 17.10",
        ),
        patch("vaaet_ml.data.ingestion.restore_backup_to_sql", return_value=restored),
        patch(
            "vaaet_ml.data.ingestion.parse_sql_dump_tables",
            return_value={"public.traffic_data": empty_raw},
        ),
    ):
        with pytest.raises(ValueError, match=r"public\.traffic_data.*zero telemetry rows"):
            load_training_inputs(
                TrainingIngestionPlan(
                    mode=TrainingMode.SEED_BOOTSTRAP,
                    raw_sources=(PostgresBackupSource(backup),),
                )
            )
