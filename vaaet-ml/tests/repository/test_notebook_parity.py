# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Verify that all notebooks orchestrate shared package APIs."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ML_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = ML_ROOT.parent
CORE_ROOT = WORKSPACE_ROOT / "vaaet-core"
REPO_ROOT = ML_ROOT
NOTEBOOKS_DIR = REPO_ROOT / "notebooks"
NOTEBOOKS = {
    "collection": REPO_ROOT / "notebooks/data-collection/collect_traffic_telemetry.ipynb",
    "training": REPO_ROOT / "notebooks/training/train_traffic_state_classifier.ipynb",
    "inference": REPO_ROOT / "notebooks/inference/analyze_traffic_video.ipynb",
}
EVALUATION_NOTEBOOK = REPO_ROOT / "notebooks/evaluation/evaluate_models_and_eda.ipynb"
ALL_NOTEBOOKS = {**NOTEBOOKS, "evaluation": EVALUATION_NOTEBOOK}
NOTEBOOK_AUDITOR = (
    WORKSPACE_ROOT
    / ".codex/skills/vaaet-notebook-orchestration/scripts/audit_notebooks.py"
)
WORKFLOW_CONFIG_MODULE = (ML_ROOT / "src/vaaet_ml/workflow_config.py").read_text(
    encoding="utf-8"
)
WORKFLOW_PRESET_MODULE = (ML_ROOT / "src/vaaet_ml/workflow_presets.py").read_text(
    encoding="utf-8"
)


def _code(path: Path) -> str:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    return "\n".join(
        "".join(cell["source"])
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )


@pytest.mark.parametrize("path", ALL_NOTEBOOKS.values())
def test_notebook_is_versioned_without_execution_outputs(path: Path) -> None:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        assert cell.get("execution_count") is None
        assert cell.get("outputs", []) == []


def test_active_notebooks_have_no_undefined_global_names() -> None:
    """El lint selectivo detecta dependencias ocultas entre celdas de Run All."""

    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "notebooks", "--select", "F821"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_active_notebooks_pass_the_structural_auditor() -> None:
    """Conserva los límites estructurales que el parseo AST no expresa."""

    result = subprocess.run(
        [sys.executable, str(NOTEBOOK_AUDITOR), str(NOTEBOOKS_DIR)],
        cwd=WORKSPACE_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("path", ALL_NOTEBOOKS.values())
def test_notebook_has_one_shared_bootstrap_and_no_import_hacks(path: Path) -> None:
    code = _code(path)
    assert code.count("# Preparación del entorno: ejecutá esta celda una vez por runtime.") == 1
    assert re.search(r"(?m)^\s*# Cell \d", code) is None
    assert code.count("runpy.run_path") == 1
    assert "sys.path.insert" not in code
    assert "install_if_missing" not in code
    assert '"pip", "install"' not in code


@pytest.mark.parametrize("path", ALL_NOTEBOOKS.values())
def test_colab_uses_the_shared_bootstrap_with_explicit_extras(path: Path) -> None:
    code = _code(path)
    assert 'BOOTSTRAP["bootstrap_notebook"](' in code
    assert "in_colab=IN_COLAB" in code
    assert "core_extras=" in code
    assert "ml_extras=" in code


@pytest.mark.parametrize("path", ALL_NOTEBOOKS.values())
def test_notebook_setup_delegates_installation_and_preflight(path: Path) -> None:
    code = _code(path)
    assert "notebook_bootstrap.py" in code
    assert "bootstrap_notebook_runtime(" not in code
    assert "--force-reinstall" not in code


def _markdown(path: Path) -> str:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    return "\n".join(
        "".join(cell["source"])
        for cell in notebook["cells"]
        if cell["cell_type"] == "markdown"
    )


@pytest.mark.parametrize("path", ALL_NOTEBOOKS.values())
def test_notebook_clears_cache_and_validates_package_origin(path: Path) -> None:
    code = _code(path)
    assert "VAAET_PACKAGE_FILE = RUNTIME.package_file" in code
    assert "VAAET_ML_PACKAGE_FILE = RUNTIME.ml_package_file" in code


@pytest.mark.parametrize("path", ALL_NOTEBOOKS.values())
def test_notebook_pip_check_is_visible_but_non_blocking(path: Path) -> None:
    code = _code(path)
    assert 'BOOTSTRAP["bootstrap_notebook"](' in code
    assert 'check_call([sys.executable, "-m", "pip", "check"])' not in code


def test_notebooks_keep_workflow_smoke_imports() -> None:
    expected_imports = {
        "collection": ("cv2", "numpy", "pandas", "psycopg2", "sqlalchemy", "torch", "ultralytics"),
        "training": ("joblib", "numpy", "pandas", "psycopg2", "sqlalchemy", "tensorflow"),
        "inference": ("cv2", "joblib", "numpy", "pandas", "psycopg2", "sqlalchemy", "tensorflow", "ultralytics"),
        "evaluation": ("joblib", "numpy", "pandas", "psycopg2", "sqlalchemy", "tensorflow"),
    }
    for workflow, import_names in expected_imports.items():
        code = _code(ALL_NOTEBOOKS[workflow])
        for import_name in import_names:
            assert import_name in code


def test_collection_uses_shared_analysis_and_data_contracts() -> None:
    code = _code(NOTEBOOKS["collection"])
    assert "from vaaet.vision.analysis import analyze_video" in code
    assert "from vaaet_ml.view_plan import load_video_view_plan" in code
    assert "SELECTED_PRESET = CollectionPreset.LOCAL" in code
    assert "VIEW_PLAN = load_video_view_plan(WORKFLOW_CONFIG.view_plan_path)" in code
    assert "view_plan=VIEW_PLAN" in code
    assert "merge_raw_telemetry_csv" in code
    assert "persist_raw_telemetry" in code
    assert "class VAAET" not in code
    assert "if result.telemetry.empty:" in code
    assert "if not result.telemetry.empty and RAW_CSV.is_file():" in code
    assert "PostgreSQL omitido" in code


def test_notebooks_handle_clips_without_complete_minutes() -> None:
    collection = _code(NOTEBOOKS["collection"])
    inference = _code(NOTEBOOKS["inference"])
    review_module = (ML_ROOT / "src/vaaet_ml/data/review_orchestration.py").read_text(
        encoding="utf-8"
    )

    assert "mínimo: 60.0s" in collection
    assert "mínimo: 60.0s" in inference
    assert "df_classified = empty_classification_result(pd.DataFrame())" in inference
    assert "if df_classified.empty:" in inference
    assert "Se necesitan dos ventanas consecutivas de 60 segundos" in inference
    assert inference.index("if df_classified.empty:") < inference.index(
        'df_classified["traffic_state"].unique()'
    )
    assert "INFERENCE_PIPELINE_RUN_ID = None" in inference
    assert "Se omiten features, clasificación, PostgreSQL y revisión HITL" in inference
    assert "inference_pipeline_run_id is not None" in review_module
    assert "Revisión HITL omitida" in review_module


def test_training_uses_shared_feature_contracts() -> None:
    code = _code(NOTEBOOKS["training"])
    selection_module = (ML_ROOT / "src/vaaet_ml/training/selection.py").read_text(encoding="utf-8")
    assert "FEATURE_COLS" in code
    assert "from vaaet.features.engineering import engineer_features" in code
    assert "from vaaet.features.labeling import assign_stable_traffic_state" in code
    assert "from vaaet_ml.data.database import" in code
    assert "def engineer_features(" not in code
    assert "def assign_traffic_state(" not in code
    assert "from vaaet_ml.training.partitions import build_training_partitions" in code
    assert "build_training_partitions(" in code
    assert "validation_data=(x_validation, y_validation)" in selection_module
    assert "validation_split" not in code
    assert "from vaaet_ml.training.modeling import build_traffic_state_mlp" in selection_module
    assert "build_traffic_state_mlp(" in selection_module
    assert "N_MODEL_STATES" in code
    assert "fit_temperature" in code
    assert "production_eligible" in code
    assert "SMOTE(" not in code
    assert "TrainingIngestionPlan(" in code
    assert "TrainingMode.SEED_BOOTSTRAP" in code
    assert "TrainingMode.HITL_RETRAINING" in code
    assert "SeedDatasetPackageSource" in code
    assert "SELECTED_PRESET = TrainingPreset.SEED_UPLOAD" in code
    assert "WORKFLOW_CONFIG.human_holdout_frozen" in code
    assert "HumanHoldoutAction(WORKFLOW_CONFIG.human_holdout_action)" in code
    assert "WORKFLOW_CONFIG.human_holdout_update_reason" in code
    assert "resolve_human_holdout(" in code
    assert "frozen_holdout=human_holdout_snapshot" in code
    assert "human_holdout_snapshot.descriptor" in code
    assert "/content/drive/MyDrive/vaaet-ml/data/holdouts" in code
    assert "no se usará un fallback efímero" in code
    assert "compose_supervised_dataset(" in code
    assert "VersionedSeedStore" in code
    assert "DatasetArtifactAction(WORKFLOW_CONFIG.seed_artifact_action)" in code
    assert '"reuse_or_create"' in WORKFLOW_PRESET_MODULE
    assert "HitlCatalogSource(HITL_CATALOG_PATH, CatalogSelection.ALL_ACTIVE)" in code
    assert "create_training_input_lock(" in code
    assert "training_input_lock=training_input_lock.descriptor" in code
    assert "data/processed/vaaet-seed-bootstrap-v1.zip" not in code
    assert "data/raw/vaaet-training-dataset-v1.zip" not in code
    assert 'feedback_policy=FeedbackPolicy.VALIDATED_ONLY' in code
    assert "USE_HUMAN_VALIDATED_FEEDBACK" not in code
    assert "persist_traffic_analysis" not in code


def test_training_delegates_grouped_cross_validation() -> None:
    code = _code(NOTEBOOKS["training"])
    cross_validation = (ML_ROOT / "src/vaaet_ml/training/cross_validation.py").read_text(
        encoding="utf-8"
    )

    assert "run_grouped_cross_validation(" in code
    assert "StratifiedGroupKFold" not in code
    assert "fold_model.fit(" not in code
    assert "StratifiedGroupKFold" in cross_validation
    assert "apply_model_input_policy" in cross_validation


def test_training_uses_the_governed_observability_workflow() -> None:
    code = _code(NOTEBOOKS["training"])

    assert "WORKFLOW_CONFIG.write_training_report" in code
    assert "WORKFLOW_CONFIG.reference_training_run_id" in code
    assert "WORKFLOW_CONFIG.run_grouped_cross_validation" in code
    assert "TrainingFitConfig(" in code
    assert "build_training_callbacks(" in code
    assert "evaluate_candidate_eligibility(" in code
    assert "build_training_run_report(" in code
    assert "write_training_run_report(" in code
    assert "save_training_run_diagnostics(" in code
    assert "compare_training_run_reports(" in code
    assert "EarlyStopping(" not in code
    assert "ReduceLROnPlateau(" not in code
    assert code.index("training_input_lock = create_training_input_lock(") < code.index(
        "select_balance_candidate("
    )
    assert code.index("run_grouped_cross_validation(") < code.index(
        "build_training_run_report("
    )


def test_training_prepares_postgres_backup_reader_in_colab() -> None:
    code = _code(NOTEBOOKS["training"])
    assert "SELECTED_PRESET = TrainingPreset.SEED_UPLOAD" in code
    assert "WORKFLOW_CONFIG.enable_data_upload" in code
    restore_module = (ML_ROOT / "src/vaaet_ml/data/postgres_restore.py").read_text(encoding="utf-8")
    assert "resolve_pg_restore_for_backup" in code
    assert 'Path("/usr/lib/postgresql/17/bin/pg_restore")' in restore_module
    assert '["apt-get", "update", "-qq"]' in restore_module
    assert '"postgresql-client-17"' in restore_module
    assert "https://apt.postgresql.org/pub/repos/apt" in restore_module
    assert "https://www.postgresql.org/media/keys/ACCC4CF8.asc" in restore_module
    assert "PostgresBackupSource(RESOLVED_SEED_RAW_SOURCE_PATH" in code
    assert "Path(PG_RESTORE_PATH) if PG_RESTORE_PATH else None" in code
    assert "if len(uploaded) != 1:" in code
    assert "Datos inmutables en Drive" in code
    assert "Detected backup table" in code
    assert "archive_table" in code
    assert "reader_version" in code
    assert "!apt-get" not in code
    assert "shell=True" not in code


def test_inference_finalizes_immutable_hitl_review_sessions() -> None:
    code = _code(NOTEBOOKS["inference"])
    assert "finalize_review_session" in code
    assert "def finalize_current_review" in code
    assert "prepare_inference_review" in code
    assert "/content/drive/MyDrive/vaaet-ml/data/hitl-reviews" in code
    assert "result.sync_status" in code
    assert "export_completed_offline_review" not in code


def test_inference_centralizes_and_documents_supported_workflow_configuration() -> None:
    notebook = json.loads(NOTEBOOKS["inference"].read_text(encoding="utf-8"))
    code = _code(NOTEBOOKS["inference"])
    bundle_module = (CORE_ROOT / "src/vaaet/inference/bundle.py").read_text(encoding="utf-8")
    markdown = "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "markdown"
    )
    assert code.count("SELECTED_PRESET =") == 1
    assert code.count("CUSTOM_CONFIG =") == 1
    assert code.count("WORKFLOW_CONFIG =") == 1
    assert "SELECTED_PRESET = InferencePreset.PILOT_OFFLINE" in code
    assert "resolve_inference_config(" in code
    assert "render_workflow_summary(" in code

    config_index = next(
        index
        for index, cell in enumerate(notebook["cells"])
        if "# Configuración del workflow: editá únicamente esta celda."
        in "".join(cell.get("source", []))
    )
    setup_index = next(
        index
        for index, cell in enumerate(notebook["cells"])
        if "# Preparación del entorno: ejecutá esta celda una vez por runtime."
        in "".join(cell.get("source", []))
    )
    assert setup_index < config_index
    assert "load_traffic_bundle(" in code
    assert 'stage == "candidate" and persist_to_database' in bundle_module
    assert "Los bundles candidatos son sólo offline" in bundle_module
    assert "if IN_COLAB and WORKFLOW_CONFIG.download_annotated_video:" in code
    assert "if not WORKFLOW_CONFIG.show_dashboard" in code
    assert "HudConfig(debug=WORKFLOW_CONFIG.hud_debug)" in code

    for heading in (
        "InferencePreset.PILOT_OFFLINE",
        "InferencePreset.PILOT_HITL",
        "InferencePreset.PERSISTED_INFERENCE",
        "InferencePreset.PERSISTED_HITL",
        "InferencePreset.EXPERIMENTAL_OFFLINE",
        "Personalización tipada",
    ):
        assert heading in markdown
    for legacy_assignment in (
        "ALLOW_PILOT_BUNDLE =",
        "ALLOW_EXPERIMENTAL_BUNDLE =",
        "PERSIST_TO_DATABASE =",
        "ENABLE_HUMAN_REVIEW =",
        "REVIEW_MODE =",
        "DOWNLOAD_ANNOTATED_VIDEO =",
        "SHOW_DASHBOARD =",
        "HUD_DEBUG =",
    ):
        assert legacy_assignment not in code
    assert "try:\n    if df_telemetry" not in markdown


@pytest.mark.parametrize("path", ALL_NOTEBOOKS.values())
def test_notebook_starts_with_colloquial_quick_start(path: Path) -> None:
    markdown = _markdown(path)
    assert "Usá esta notebook" in markdown
    assert "Inicio rápido recomendado" in markdown
    assert "<details>" in markdown
    assert "</details>" in markdown


def test_evaluation_notebook_is_read_only_and_uses_shared_services() -> None:
    code = _code(EVALUATION_NOTEBOOK)
    markdown = _markdown(EVALUATION_NOTEBOOK)

    assert "load_evaluation_bundle" in code
    assert "evaluate_champion_challenger" in code
    assert "build_feature_cohort_from_raw_telemetry" in code
    assert "load_telemetry_window" in code
    assert "DatabaseProfile.TRAINING" in code
    assert "current.json" in WORKFLOW_CONFIG_MODULE
    assert "PipelineRunMetadata" not in code
    assert "pipeline_run(" not in code
    assert "persist_" not in code
    assert "promotion_blockers" in code
    assert "Accident" in markdown


def test_collection_documents_named_safe_presets() -> None:
    markdown = _markdown(NOTEBOOKS["collection"])
    for preset in (
        "CollectionPreset.LOCAL",
        "CollectionPreset.POSTGRES",
        "CollectionPreset.TRACKING_DIAGNOSTIC",
        "CollectionPreset.CUSTOM",
    ):
        assert preset in markdown
    assert "PERSIST_TO_DATABASE =" not in markdown


def test_inference_documents_named_presets_without_flat_recipes() -> None:
    markdown = _markdown(NOTEBOOKS["inference"])
    for preset in (
        "InferencePreset.PILOT_OFFLINE",
        "InferencePreset.PILOT_HITL",
        "InferencePreset.PERSISTED_INFERENCE",
        "InferencePreset.PERSISTED_HITL",
        "InferencePreset.EXPERIMENTAL_OFFLINE",
        "InferencePreset.CUSTOM",
    ):
        assert preset in markdown
    assert "ALLOW_PILOT_BUNDLE =" not in markdown


def test_training_documents_named_seed_and_hitl_presets() -> None:
    markdown = _markdown(NOTEBOOKS["training"])
    for preset in (
        "TrainingPreset.SEED_UPLOAD",
        "TrainingPreset.SEED_POSTGRES",
        "TrainingPreset.HITL_CATALOG",
        "TrainingPreset.HITL_CATALOG_POSTGRES",
        "TrainingPreset.HITL_FROZEN_HOLDOUT",
        "TrainingPreset.CUSTOM",
    ):
        assert preset in markdown
    assert "TRAINING_MODE =" not in markdown


def test_notebooks_delegate_model_and_dashboard_rendering() -> None:
    inference_code = _code(NOTEBOOKS["inference"])
    training_code = _code(NOTEBOOKS["training"])

    assert "def show_dashboard" not in inference_code
    assert "show_inference_dashboard" in inference_code
    assert "def build_mlp_model" not in training_code
    assert "build_traffic_state_mlp" in training_code
    assert "plot_training_evaluation" in training_code
    assert "plot_training_history" in training_code


def test_collection_centralizes_safe_workflow_configuration() -> None:
    notebook = json.loads(NOTEBOOKS["collection"].read_text(encoding="utf-8"))
    code = _code(NOTEBOOKS["collection"])

    assert code.count("SELECTED_PRESET =") == 1
    assert code.count("CUSTOM_CONFIG =") == 1
    assert code.count("WORKFLOW_CONFIG =") == 1
    assert "SELECTED_PRESET = CollectionPreset.LOCAL" in code
    assert "resolve_collection_config(" in code
    assert "resolve_video_input(" in code
    assert "_video_uploader = files.upload" in code
    config_index = next(
        index
        for index, cell in enumerate(notebook["cells"])
        if "# Configuración del workflow: editá únicamente esta celda."
        in "".join(cell.get("source", []))
    )
    setup_index = next(
        index
        for index, cell in enumerate(notebook["cells"])
        if "# Preparación del entorno: ejecutá esta celda una vez por runtime."
        in "".join(cell.get("source", []))
    )
    assert setup_index < config_index


def test_notebook_transfers_require_explicit_configuration() -> None:
    collection = _code(NOTEBOOKS["collection"])
    inference = _code(NOTEBOOKS["inference"])
    training = _code(NOTEBOOKS["training"])

    assert (
        "CollectionPreset.LOCAL: CollectionWorkflowConfig(False, False)"
        in WORKFLOW_PRESET_MODULE
    )
    assert "if IN_COLAB and WORKFLOW_CONFIG.download_outputs:" in collection
    assert "if IN_COLAB and not WORKFLOW_CONFIG.download_outputs:" in collection
    assert "elif IN_COLAB:" not in collection
    assert "InferencePreset.PILOT_OFFLINE" in WORKFLOW_PRESET_MODULE
    assert "if IN_COLAB and WORKFLOW_CONFIG.download_annotated_video:" in inference
    assert "TrainingPreset.SEED_UPLOAD" in WORKFLOW_PRESET_MODULE
    assert "elif not WORKFLOW_CONFIG.copy_bundle_to_drive:" in training
    assert "build_and_publish_bundle(" in training
    assert "publish_bundle_copy(_bundle_directory, _drive_destination)" in training
    assert "No se pudo copiar el bundle validado a Drive" in training
    assert "except Exception as e:" not in training


def test_collection_invalidates_stale_results_and_guards_persistence() -> None:
    collection = _code(NOTEBOOKS["collection"])

    assert "from vaaet_ml.notebook_io import resolve_video_input" in collection
    assert "EXPLICIT_VIDEO_PATH: Path | None = None" in collection
    assert 'staging_directory=Path("/content") if IN_COLAB' in collection
    assert collection.count("result = None") >= 2
    assert collection.count("COLLECTION_PIPELINE_RUN_ID = None") >= 2
    assert "PROCESSED_VIDEO_PATH = VIDEO_PATH.resolve()" in collection
    assert (
        "result is None or COLLECTION_PIPELINE_RUN_ID is None "
        "or PROCESSED_VIDEO_PATH != VIDEO_PATH.resolve()"
    ) in collection


def test_training_resolves_postgres_only_after_explicit_opt_in() -> None:
    notebook = json.loads(NOTEBOOKS["training"].read_text(encoding="utf-8"))
    code = _code(NOTEBOOKS["training"])

    assert "SELECTED_PRESET = TrainingPreset.SEED_UPLOAD" in code
    assert code.count(
        "get_optional_database_settings(DatabaseProfile.TRAINING)"
    ) == 1
    guard_index = code.index("if WORKFLOW_CONFIG.enable_postgres_ingestion:")
    settings_index = code.index(
        "get_optional_database_settings(DatabaseProfile.TRAINING)"
    )
    assert guard_index < settings_index
    assert "PostgreSQL ingestion is enabled, but the read-only training profile" in code
    assert "PERSIST_TO_DATABASE =" not in code

    setup_index = next(
        index
        for index, cell in enumerate(notebook["cells"])
        if "# Preparación del entorno: ejecutá esta celda una vez por runtime."
        in "".join(cell.get("source", []))
    )
    config_index = next(
        index
        for index, cell in enumerate(notebook["cells"])
        if "# Configuración del workflow: editá únicamente esta celda."
        in "".join(cell.get("source", []))
    )
    upload_index = next(
        index
        for index, cell in enumerate(notebook["cells"])
        if '_backup_dest = os.path.join(DATA_RAW_DIR, "traffic_data.backup")'
        in "".join(cell.get("source", []))
    )
    assert setup_index < config_index < upload_index


def test_training_augmentation_handles_raw_and_feedback_inputs() -> None:
    code = _code(NOTEBOOKS["training"])
    guard = 'if "df_raw" not in globals() or not isinstance(df_raw, pd.DataFrame):'
    assert guard in code
    assert code.index(guard) < code.index("_n_before = len(df_raw)")
    assert "Datos sintéticos omitidos: sólo se agregan durante el inicio semilla" in code
    assert "from vaaet.timestamps import normalize_timestamp_series" in code
    assert "Zona horaria canónica" in code


def test_training_documents_actual_synthetic_record_count() -> None:
    notebook = NOTEBOOKS["training"].read_text(encoding="utf-8")
    assert "200 registros" in notebook
    assert "100 registros de entrenamiento" in notebook


def test_training_compares_conservative_balance_candidates() -> None:
    code = _code(NOTEBOOKS["training"])
    selection_module = (ML_ROOT / "src/vaaet_ml/training/selection.py").read_text(encoding="utf-8")
    assert "build_balance_candidates(" in code
    assert "select_balance_candidate(" in code
    assert "BalanceStrategy.CLASS_WEIGHTS" not in code
    assert "BalanceStrategy.SYNTHETIC_CONGESTION" in selection_module
    assert "validation_false_congested_rate" in selection_module
    assert "selection_score" in selection_module
    assert "SELECTED_BALANCE_STRATEGY" in code
    assert "expired proxy-memory rows before scaling" in code
    assert "labels=[0, 1, 2]" in code


def test_training_applies_same_legacy_policy_as_inference() -> None:
    training = _code(NOTEBOOKS["training"])
    inference = _code(NOTEBOOKS["inference"])
    assert "ModelInputPolicy.LEGACY_V1_BOOTSTRAP" in training
    assert "apply_model_input_policy(" in training
    assert "input_policy=MODEL_INPUT_POLICY" in training
    assert "bundle.deployment_stage, bundle.input_policy" in inference
    assert "input_policy=MODEL_INPUT_POLICY" in inference


def test_inference_uses_shared_analysis_and_validates_bundle() -> None:
    code = _code(NOTEBOOKS["inference"])
    bundle_module = (CORE_ROOT / "src/vaaet/inference/bundle.py").read_text(encoding="utf-8")
    assert "from vaaet.vision.analysis import analyze_video" in code
    assert "from vaaet_ml.view_plan import load_video_view_plan" in code
    assert "SELECTED_PRESET = InferencePreset.PILOT_OFFLINE" in code
    assert "VIEW_PLAN = load_video_view_plan(WORKFLOW_CONFIG.view_plan_path)" in code
    assert "view_plan=VIEW_PLAN" in code
    assert "TrafficStateEngine" in code
    assert "load_traffic_bundle(" in code
    assert "prediction_provider=traffic_engine.predict_latest" in code
    assert (
        "manifest = validate_manifest(directory, allow_historical_revision=historical_only)"
        in bundle_module
    )
    assert "from sqlalchemy import text as sa_text" not in code
    assert "load_review_queue" in code
    assert "build_review_widget" in code
    assert "finalize_current_review" in code
    assert "DatabaseProfile.REVIEW" in code
    assert "WORKFLOW_CONFIG.enable_human_review" in code
    assert "WORKFLOW_CONFIG.persist_to_database" in code
    assert "validation_split" not in code
    assert "SMOTE" not in code
    assert "def estimate_speed(" not in code
    assert "def generate_annotated_video(" not in code
    assert 'decision_policy=manifest["decision_policy"]' in code
    assert "WORKFLOW_CONFIG.allow_experimental_bundle" in code
    assert "WORKFLOW_CONFIG.allow_pilot_bundle" in code
    assert "DEPLOYMENT_STAGE" in code
    assert 'model_version=manifest["model_version"]' in code
    assert "retrain_with_feedback" not in code
    assert "model.output_shape[-1]" in bundle_module
    assert "dict(label_mapping) != dict(STATE_LABELS)" in bundle_module


def test_annotated_video_workflows_default_to_public_shared_hud() -> None:
    collection = _code(NOTEBOOKS["collection"])
    inference = _code(NOTEBOOKS["inference"])
    for code in (collection, inference):
        assert "from vaaet.vision.hud import HudConfig" in code
        assert "hud_config=HudConfig(debug=WORKFLOW_CONFIG.hud_debug)" in code
    engine = (CORE_ROOT / "src/vaaet/inference/engine.py").read_text(encoding="utf-8")
    assert "prediction_provider=traffic_engine.predict_latest" in inference
    assert 'incident_candidate=bool(latest.get("accident_rule_triggered", False))' in engine


def test_notebooks_use_profile_specific_database_api() -> None:
    collection = _code(NOTEBOOKS["collection"])
    inference = _code(NOTEBOOKS["inference"])
    training = _code(NOTEBOOKS["training"])

    assert "DatabaseProfile.COLLECTION" in collection
    assert "DatabaseProfile.INFERENCE" in inference
    assert "DatabaseProfile.REVIEW" in inference
    assert "DatabaseProfile.TRAINING" in training
    for code in (collection, inference, training):
        assert "hydrate_db_environment_from_colab" not in code
        assert 'os.environ["DB_PASSWORD"]' not in code
        assert "getpass(" not in code


def test_inference_secrets_never_enable_review_persistence_implicitly() -> None:
    inference = _code(NOTEBOOKS["inference"])

    assert "if _review_enabled and WORKFLOW_CONFIG.persist_to_database:" in inference
    assert "settings=review_settings" in inference
    assert (
        "settings=get_optional_database_settings(DatabaseProfile.REVIEW) "
        "if _review_enabled else None"
    ) not in inference
    assert "falta el perfil review" in inference
    assert "La persistencia PostgreSQL solicitada no puede comenzar" in inference


def test_all_workflows_record_redacted_pipeline_runs() -> None:
    for workflow, path in NOTEBOOKS.items():
        code = _code(path)
        assert "PipelineRunMetadata" in code, workflow
        assert "PipelineWorkflow" in code, workflow
        assert "pipeline_run(" in code, workflow
        assert "data/processed/pipeline-runs" in code, workflow
