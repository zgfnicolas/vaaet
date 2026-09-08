# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = ML_ROOT.parent
REPO_ROOT = ML_ROOT
SCRIPTS_DIR = ML_ROOT / "scripts"
NOTEBOOKS_DIR = REPO_ROOT / "notebooks"
ACTIVE_NOTEBOOKS = [
    NOTEBOOKS_DIR / "data-collection" / "collect_traffic_telemetry.ipynb",
    NOTEBOOKS_DIR / "training" / "train_traffic_state_classifier.ipynb",
    NOTEBOOKS_DIR / "inference" / "analyze_traffic_video.ipynb",
    NOTEBOOKS_DIR / "evaluation" / "evaluate_models_and_eda.ipynb",
]
ALLOWED_SCRIPT_FILES = {
    "README.md",
    "audit-postgres-database.py",
    "convert-postgres-backup.py",
    "evaluate-telemetry-exports.py",
    "export-training-dataset.py",
    "notebook_bootstrap.py",
}


def test_training_and_ingestion_modules_import_without_cycles() -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import vaaet_ml.data.ingestion; import vaaet_ml.training.holdout; "
            "import vaaet_ml.training.partitions; import vaaet.inference.traffic_state; "
            "assert 'vaaet_ml.training.balancing' not in sys.modules",
        ],
        cwd=REPO_ROOT,
        check=True,
    )


def test_dataset_codec_breaks_the_artifacts_ingestion_cycle() -> None:
    artifacts_source = REPO_ROOT.joinpath(
        "src", "vaaet_ml", "data", "dataset_artifacts.py"
    ).read_text(encoding="utf-8")
    codec_source = REPO_ROOT.joinpath("src", "vaaet_ml", "data", "package_codec.py").read_text(
        encoding="utf-8"
    )
    assert "vaaet_ml.data.ingestion" not in artifacts_source
    assert "vaaet_ml.data.dataset_artifacts" not in codec_source


def test_artifact_facade_keeps_cohesive_owners_and_review_uses_the_codec() -> None:
    data_root = REPO_ROOT / "src" / "vaaet_ml" / "data"
    facade = data_root.joinpath("dataset_artifacts.py").read_text(encoding="utf-8")
    review = data_root.joinpath("review.py").read_text(encoding="utf-8")
    review_export = data_root.joinpath("review_export.py").read_text(encoding="utf-8")

    for module in (
        "artifact_serialization.py",
        "seed_artifacts.py",
        "hitl_catalog.py",
        "review_frames.py",
        "review_finalization.py",
        "training_input_lock.py",
    ):
        assert data_root.joinpath(module).is_file()
    assert "from vaaet_ml.data.ingestion import create_dataset_package" not in review
    assert "from vaaet_ml.data.package_codec import create_dataset_package" in review_export
    assert "from vaaet_ml.data.seed_artifacts import" in facade
    assert "from vaaet_ml.data.hitl_catalog import" in facade
    assert "from vaaet_ml.data.review_finalization import" in facade


def test_database_review_and_reporting_keep_presentation_at_the_edge() -> None:
    data_root = REPO_ROOT / "src" / "vaaet_ml" / "data"
    evaluation_root = REPO_ROOT / "src" / "vaaet_ml" / "evaluation"
    for module in (
        "database_settings.py",
        "database_connection.py",
        "database_queries.py",
        "database_backup.py",
        "review_domain.py",
        "review_persistence.py",
        "review_export.py",
        "review_orchestration.py",
        "review_widgets.py",
    ):
        assert data_root.joinpath(module).is_file()
    for module in ("reporting_metrics.py", "reporting_summaries.py", "reporting_visuals.py"):
        assert evaluation_root.joinpath(module).is_file()

    review_service = data_root.joinpath("review_orchestration.py").read_text(encoding="utf-8")
    review_widgets = data_root.joinpath("review_widgets.py").read_text(encoding="utf-8")
    database_facade = data_root.joinpath("database.py").read_text(encoding="utf-8")
    assert "ipywidgets" not in review_service
    assert "ipywidgets" in review_widgets
    assert "from vaaet_ml.data.database_backup import" in database_facade
    assert "from vaaet_ml.data.database_queries import" in database_facade


def test_postgresql_configuration_is_portable_and_keeps_alembic_as_ddl_authority() -> None:
    settings = REPO_ROOT.joinpath("src", "vaaet_ml", "data", "database_settings.py").read_text(
        encoding="utf-8"
    )
    migration_environment = REPO_ROOT.joinpath("migrations", "env.py").read_text(encoding="utf-8")
    workflow = WORKSPACE_ROOT.joinpath(".github", "workflows", "ci.yml").read_text(encoding="utf-8")
    guide = WORKSPACE_ROOT.joinpath("docs", "operations", "postgresql-guide.md").read_text(
        encoding="utf-8"
    )

    for contract in (
        "DatabaseEndpointSettings",
        "DatabasePoolSettings",
        "DatabaseRetrySettings",
        "DatabaseAdminSettings",
    ):
        assert contract in settings
    assert "load_database_admin_settings" in migration_environment
    assert 'config.attributes.get("connection")' in migration_environment
    assert "VAAET_DATABASE_ADMIN_URL" not in migration_environment
    assert "VAAET_DATABASE_ADMIN_URL" not in workflow
    assert "VAAET_ADMIN_DB_USER" in workflow
    assert "VAAET_DB_SSLMODE" in workflow
    assert "alembic upgrade head" in guide
    assert "endpoint administrativo directo" in guide
    assert "create_all" in guide


def test_pyright_strict_profile_and_ci_job_cover_both_source_roots() -> None:
    configuration = (WORKSPACE_ROOT / "pyrightconfig.json").read_text(encoding="utf-8")
    workflow = (WORKSPACE_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert '"typeCheckingMode": "strict"' in configuration
    assert '"vaaet-core/src"' in configuration
    assert '"vaaet-ml/src"' in configuration
    assert "typing:" in workflow
    assert "pyright --project pyrightconfig.json --level error" in workflow


def _concatenate_code_cells(notebook_path: Path) -> str:
    with notebook_path.open("r", encoding="utf-8") as handle:
        notebook = json.load(handle)
    return "\n\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code"
    )


def test_active_notebooks_compile() -> None:
    for notebook_path in ACTIVE_NOTEBOOKS:
        with notebook_path.open("r", encoding="utf-8") as handle:
            notebook = json.load(handle)
        for index, cell in enumerate(notebook["cells"]):
            if cell.get("cell_type") == "code":
                ast.parse("".join(cell.get("source", [])), filename=f"{notebook_path}:cell-{index}")


def test_active_notebook_folder_has_no_backups() -> None:
    backups = sorted(
        path.relative_to(REPO_ROOT).as_posix() for path in NOTEBOOKS_DIR.rglob("*.ipynb.bak")
    )
    assert backups == []


def test_scripts_directory_only_contains_supported_utilities() -> None:
    files = {path.name for path in SCRIPTS_DIR.iterdir() if path.is_file()}
    assert files == ALLOWED_SCRIPT_FILES


def test_active_sources_do_not_use_legacy_paths_or_import_hacks() -> None:
    forbidden = (
        "archive/bootstrap-v1",
        "notebooks/01_data_prep",
        "notebooks/02_production",
        "docs/adr/",
        "data/samples",
        "src/perception",
        "from src.",
        "import src.",
        "sys.path.insert",
        "install_if_missing",
        "vaaet-ml.git",
    )
    active_docs = [
        path
        for path in WORKSPACE_ROOT.joinpath("docs").rglob("*.md")
        if "architecture/decisions" not in path.relative_to(WORKSPACE_ROOT).as_posix()
    ]
    active_files = [
        ML_ROOT / "AGENTS.md",
        ML_ROOT / "CONTRIBUTING.md",
        ML_ROOT / "README.md",
        ML_ROOT / "llms.txt",
        WORKSPACE_ROOT / "AGENTS.md",
        WORKSPACE_ROOT / "llms.txt",
        WORKSPACE_ROOT / "CONTRIBUTING.md",
        WORKSPACE_ROOT / "README.md",
        WORKSPACE_ROOT / "SECURITY.md",
        WORKSPACE_ROOT / "SUPPORT.md",
        *REPO_ROOT.joinpath("src").rglob("*.py"),
        *REPO_ROOT.joinpath("scripts").rglob("*.py"),
        *ACTIVE_NOTEBOOKS,
        *active_docs,
        WORKSPACE_ROOT / "docs/architecture/decisions/0013-on-demand-data-collection-workflow.md",
        WORKSPACE_ROOT
        / "docs/architecture/decisions/0014-hierarchical-traffic-state-and-incident-policy.md",
        WORKSPACE_ROOT
        / "docs/architecture/decisions/0015-postgresql-namespaces-security-and-hitl.md",
        WORKSPACE_ROOT
        / "docs/architecture/decisions/0016-postgresql-hardening-and-pipeline-runs.md",
        WORKSPACE_ROOT
        / "docs/architecture/decisions/0020-single-git-monorepo-and-application-boundary.md",
    ]
    for path in active_files:
        content = path.read_text(encoding="utf-8")
        for value in forbidden:
            assert value not in content, f"{path.relative_to(REPO_ROOT)} contains {value!r}"
    inference = (NOTEBOOKS_DIR / "inference" / "analyze_traffic_video.ipynb").read_text(
        encoding="utf-8"
    )
    assert "os.path.join(_root" not in inference


def test_active_notebooks_use_canonical_feature_count_and_repository_root() -> None:
    for notebook_path in ACTIVE_NOTEBOOKS:
        content = notebook_path.read_text(encoding="utf-8")
        code = _concatenate_code_cells(notebook_path)
        assert "14 features" not in content
        assert "vaaet-ml.git" not in content
        assert 'WORKSPACE_DIR = Path("/content/vaaet")' in code
        assert 'ML_ROOT = WORKSPACE_DIR / "vaaet-ml"' in code
        assert "REPO_ROOT" in code
        assert code.count("runpy.run_path") == 1
    diagram = (
        WORKSPACE_ROOT / "docs" / "architecture" / "diagrams" / "intelligence-pipeline.md"
    ).read_text(encoding="utf-8")
    assert "14 features" not in diagram
    assert "19 features" in diagram


def test_notebooks_do_not_own_database_schema_or_legacy_credentials() -> None:
    for notebook_path in ACTIVE_NOTEBOOKS:
        code = _concatenate_code_cells(notebook_path)
        assert "CREATE TABLE" not in code.upper()
        assert "ALTER TABLE" not in code.upper()
        assert "getpass(" not in code
        assert "hydrate_db_environment_from_colab" not in code


def test_internal_markdown_links_resolve() -> None:
    link_pattern = re.compile(r"\[[^]]*\]\((?!https?://|mailto:)([^)]+)\)")
    broken: list[str] = []
    for markdown_path in WORKSPACE_ROOT.rglob("*.md"):
        relative = markdown_path.relative_to(WORKSPACE_ROOT).as_posix()
        if relative.startswith(("plantillas_docs/", ".venv/", ".tmp-tests/")) or any(
            part in {".pytest_cache", ".tmp-tests"} for part in markdown_path.parts
        ):
            continue
        for target_text in link_pattern.findall(markdown_path.read_text(encoding="utf-8")):
            clean_target = target_text.split("#", 1)[0].split("?", 1)[0]
            if clean_target and not (markdown_path.parent / clean_target).resolve().exists():
                broken.append(f"{relative} -> {clean_target}")
    assert broken == []


def test_removed_directories_are_absent() -> None:
    removed = (
        "archive",
        "models",
        "notebooks/01_data_prep",
        "notebooks/02_production",
        "docs/adr",
        "docs/diagrams",
        "docs/KPIs",
        "src/perception",
        "data/samples",
        "data/interim",
    )
    assert [path for path in removed if (REPO_ROOT / path).exists()] == []


def test_notebook_extras_match_workflows() -> None:
    expected = {
        "collect_traffic_telemetry.ipynb": (("vision",), ("database",)),
        "train_traffic_state_classifier.ipynb": (
            ("inference",),
            ("training", "visualization", "database"),
        ),
        "analyze_traffic_video.ipynb": (
            ("vision", "inference"),
            ("visualization", "database"),
        ),
        "evaluate_models_and_eda.ipynb": (
            ("inference",),
            ("visualization", "database"),
        ),
    }
    for notebook in ACTIVE_NOTEBOOKS:
        code = _concatenate_code_cells(notebook)
        core_extras, ml_extras = expected[notebook.name]
        assert f"core_extras={core_extras!r}" in code
        assert f"ml_extras={ml_extras!r}" in code


def test_dvc_registry_uses_declared_provider_extras_and_neutral_configuration() -> None:
    workflow = (WORKSPACE_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    dvc_config = (WORKSPACE_ROOT / ".dvc" / "config").read_text(encoding="utf-8")
    gitignore = (WORKSPACE_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert 'python -m pip install "./vaaet-core"' in workflow
    assert 'python -m pip install "./vaaet-ml[dvc,dvc-gdrive,dvc-s3,dev]"' in workflow
    assert "vaaet-registry --help" in workflow
    assert "pytest vaaet-ml/tests/unit/test_dvc_registry.py" in workflow
    assert "dvc pull" not in workflow
    assert "dvc push" not in workflow
    assert "dvc-gdrive" in pyproject
    assert "dvc-s3" in pyproject
    assert "remote =" not in dvc_config
    assert "['remote" not in dvc_config
    assert "gdrive://" not in dvc_config
    assert "s3://" not in dvc_config
    assert "endpointurl" not in dvc_config
    assert ".dvc/config.local" in gitignore
    assert not (SCRIPTS_DIR / "setup-dvc.sh").exists()


def test_ci_preserves_the_workspace_quality_gates() -> None:
    """Evita que los controles de integración se degraden por cambios de workflow."""

    workflow = (WORKSPACE_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert '".codex/skills/**"' in workflow
    assert "repository-quality:" in workflow
    assert "git diff --check" in workflow
    assert "package-smoke:" in workflow
    assert "ruff check notebooks --select F821" in workflow
    assert "audit_notebooks.py notebooks" in workflow
    assert 'python -m venv "$RUNNER_TEMP/vaaet-core-base"' in workflow
    assert 'python -m venv "$RUNNER_TEMP/vaaet-workspace-base"' in workflow


def test_python_313_is_declared_and_exercised_by_ci() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    core_pyproject = (WORKSPACE_ROOT / "vaaet-core" / "pyproject.toml").read_text(encoding="utf-8")
    workflow = (WORKSPACE_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert 'requires-python = ">=3.10,<3.14"' in pyproject
    assert '"Programming Language :: Python :: 3.13"' in pyproject
    assert "tensorflow" not in pyproject
    assert "vaaet-core[inference]==0.2.1" in pyproject
    assert "python_version >= '3.13'" in core_pyproject
    assert 'python-version: ["3.10", "3.11", "3.12", "3.13"]' in workflow


def test_active_code_uses_semantic_telemetry_contract_names() -> None:
    active_python = [
        *REPO_ROOT.joinpath("src").rglob("*.py"),
        *REPO_ROOT.joinpath("tests").rglob("*.py"),
    ]
    forbidden = ("RAW_TELEMETRY_" + "V2_COLUMNS", "MODERN_" + "TELEMETRY_COLUMNS")
    for path in active_python:
        content = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in content, f"{path.relative_to(REPO_ROOT)} contains {name}"


def test_active_database_queries_do_not_select_star() -> None:
    for path in REPO_ROOT.joinpath("src", "vaaet_ml", "data").glob("*.py"):
        assert "SELECT *" not in path.read_text(encoding="utf-8").upper()


def test_monorepo_keeps_single_shared_workspace_roots() -> None:
    assert (WORKSPACE_ROOT / ".git").is_dir()
    assert (WORKSPACE_ROOT / ".dvc").is_dir()
    assert (WORKSPACE_ROOT / "docs").is_dir()
    assert (WORKSPACE_ROOT / "AGENTS.md").is_file()
    assert (WORKSPACE_ROOT / "llms.txt").is_file()
    assert (WORKSPACE_ROOT / "vaaet-app" / "README.md").is_file()
    assert (WORKSPACE_ROOT / "vaaet-core" / "pyproject.toml").is_file()
    assert (WORKSPACE_ROOT / "vaaet-core" / "AGENTS.md").is_file()
    assert (WORKSPACE_ROOT / "vaaet-core" / "src" / "vaaet").is_dir()
    assert (ML_ROOT / "pyproject.toml").is_file()
    assert (ML_ROOT / "src" / "vaaet_ml").is_dir()
    assert (ML_ROOT / "artifacts" / "traffic-state").is_dir()


def test_video_view_plans_remain_portable_and_private_to_the_consumer() -> None:
    core_plan = WORKSPACE_ROOT / "vaaet-core" / "src" / "vaaet" / "vision" / "view_plan.py"
    ml_adapter = ML_ROOT / "src" / "vaaet_ml" / "view_plan.py"
    gitignore = (WORKSPACE_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert core_plan.is_file()
    assert ml_adapter.is_file()
    assert "vaaet_ml" not in core_plan.read_text(encoding="utf-8")
    assert "*.vaaet-view-plan.private.json" in gitignore


def test_portable_agent_context_describes_the_active_monorepo() -> None:
    root_context = (WORKSPACE_ROOT / "llms.txt").read_text(encoding="utf-8")
    core_rules = (WORKSPACE_ROOT / "vaaet-core" / "AGENTS.md").read_text(encoding="utf-8")
    ml_context = (ML_ROOT / "llms.txt").read_text(encoding="utf-8")
    normalized_core_rules = " ".join(core_rules.split())

    assert "vaaet-core==0.2.1" in root_context
    assert "vaaet-ml==4.6.1" in root_context
    assert "import `vaaet_ml`" in root_context
    assert "cuatro notebooks" in root_context
    assert "No puede importar `vaaet_ml`, PostgreSQL, DVC, Google Drive" in normalized_core_rules
    assert "Pipe-and-Filter síncrono" in core_rules
    assert "ADR-0025" in root_context
    assert "con import `vaaet_ml`" in ml_context
    assert "`src/vaaet_ml/`" in ml_context
    assert "Los cuatro notebooks" in ml_context
    assert "Tres workflows Colab" not in ml_context
    assert "paquete: `vaaet`" not in ml_context


def test_normative_documentation_matches_the_active_monorepo() -> None:
    """Keep high-risk operational claims out of active, non-historical guides."""
    active_documents = {
        "docs/index.md",
        "docs/architecture/software-architecture.md",
        "docs/architecture/data-lineage.md",
        "docs/architecture/diagrams/colab-postgresql-architecture.md",
        "docs/ml/model-artifact-contract.md",
        "docs/ml/bias-and-limitations.md",
        "docs/operations/colab-guide.md",
        "docs/operations/multi-view-calibration-guide.md",
        "docs/operations/deployment.md",
        "docs/operations/user-guide.md",
        "docs/product/product-requirements.md",
        "docs/product/software-requirements.md",
        "docs/product/use-cases.md",
        "docs/quality/risk-matrix.md",
        "SECURITY.md",
        "SUPPORT.md",
    }
    documents = {
        relative: (WORKSPACE_ROOT / relative).read_text(encoding="utf-8")
        for relative in active_documents
    }
    combined = "\n".join(documents.values())

    for stale_claim in (
        "T4/V100",
        "Fallback a CPU",
        "CPU (~10x",
        "requirements-lock.txt",
        "getpass(",
        "9 campos crudos",
        "9 → 19",
        "futuro repositorio web",
        "Three Colab notebooks",
        "tres notebooks",
        "Python 3.8+",
        "Sin SSL por defecto",
        "Sin connection pooling",
        "Degradación silenciosa",
    ):
        assert stale_claim not in combined

    assert "Normativo y vigente" in documents["docs/product/product-requirements.md"]
    assert "`vaaet-core==0.2.1`" in documents["docs/product/software-requirements.md"]
    assert "fuera de alcance" in documents["docs/product/software-requirements.md"]
    assert "Cuatro notebooks" in documents["docs/product/product-requirements.md"]
    assert "cuarto\nnotebook" in documents["docs/operations/user-guide.md"]
    assert (
        "no se garantiza un modelo de acelerador concreto"
        in documents["docs/operations/colab-guide.md"]
    )
    assert "mismo monorepo" in documents["docs/ml/model-artifact-contract.md"]
    assert "VIEW_PLAN_PATH = None" in documents["docs/operations/colab-guide.md"]
    assert "vaaet-view-plan-v1" in documents["docs/operations/multi-view-calibration-guide.md"]
    assert "GitHub Private Vulnerability Reporting" in documents["SECURITY.md"]
    assert "No se promete un SLA" in documents["SUPPORT.md"]


def test_future_product_documents_are_explicitly_non_normative() -> None:
    future_documents = {
        "docs/product/business-model-canvas.md": "Hipótesis de producto futura",
        "docs/governance/statement-of-work.md": "no es una oferta ni un contrato",
        "docs/product/user-personas.md": "Hipótesis de producto futura",
    }
    for relative, status in future_documents.items():
        content = (WORKSPACE_ROOT / relative).read_text(encoding="utf-8")
        assert status in content
        assert "$" not in content
        assert "GPU T4/V100" not in content


def test_component_ruff_configuration_enforces_complexity_and_naming_rules() -> None:
    for component_root in (WORKSPACE_ROOT / "vaaet-core", ML_ROOT):
        pyproject = (component_root / "pyproject.toml").read_text(encoding="utf-8")
        assert '"C901"' in pyproject
        assert '"N"' in pyproject
        assert '"A"' in pyproject
        assert "max-complexity = 10" in pyproject
