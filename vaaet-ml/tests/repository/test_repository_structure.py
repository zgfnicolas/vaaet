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
    assert "from vaaet_ml.data.review_finalization import seal_review_package" in review_export
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
    persistence_root = WORKSPACE_ROOT / "vaaet-persistence"
    settings = persistence_root.joinpath("src", "vaaet_persistence", "settings.py").read_text(
        encoding="utf-8"
    )
    migration_environment = persistence_root.joinpath(
        "src", "vaaet_persistence", "migrations", "env.py"
    ).read_text(encoding="utf-8")
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
    assert "alembic -c alembic.ini upgrade head" in guide
    assert "identidad administrativa" in guide
    assert "create_all" in guide


def test_pyright_strict_profile_and_ci_job_cover_all_source_roots() -> None:
    configuration = (WORKSPACE_ROOT / "pyrightconfig.json").read_text(encoding="utf-8")
    workflow = (WORKSPACE_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert '"typeCheckingMode": "strict"' in configuration
    assert '"vaaet-core/src"' in configuration
    assert '"vaaet-persistence/src"' in configuration
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
        ML_ROOT / "README.md",
        WORKSPACE_ROOT / ".github/pull_request_template.md",
        WORKSPACE_ROOT / "AGENTS.md",
        WORKSPACE_ROOT / "CLAUDE.md",
        WORKSPACE_ROOT / ".github/copilot-instructions.md",
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
    assert "vaaet-core[inference]==0.2.2" in pyproject
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
    assert (WORKSPACE_ROOT / "CLAUDE.md").is_file()
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
    """Mantiene AGENTS.md como única fuente de contexto, breve y sin duplicados."""

    root_rules = (WORKSPACE_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    core_rules = (WORKSPACE_ROOT / "vaaet-core" / "AGENTS.md").read_text(encoding="utf-8")
    persistence_rules = (WORKSPACE_ROOT / "vaaet-persistence" / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    ml_rules = (ML_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    normalized_core_rules = " ".join(core_rules.split())

    assert len(root_rules.splitlines()) < 150
    for import_name in ("`vaaet`", "`vaaet_persistence`", "`vaaet_ml`"):
        assert import_name in root_rules
    assert "cuatro notebooks" in root_rules
    assert "ADR-0025" in root_rules
    assert "business-rules.md" in root_rules
    assert "decisions/README.md" in root_rules
    assert "No puede importar `vaaet_ml`, PostgreSQL, DVC, Google Drive" in normalized_core_rules
    assert "Pipe-and-Filter síncrono" in core_rules
    assert "`vaaet_ml`" in ml_rules
    assert "`src/vaaet_ml/`" in ml_rules
    assert "Los cuatro notebooks" in ml_rules
    assert "Tres workflows Colab" not in ml_rules
    assert "paquete: `vaaet`" not in ml_rules

    assert not (WORKSPACE_ROOT / "llms.txt").exists()
    assert not (ML_ROOT / "llms.txt").exists()
    assert (WORKSPACE_ROOT / "CLAUDE.md").read_text(encoding="utf-8").strip() == "@AGENTS.md"
    copilot = (WORKSPACE_ROOT / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    assert "AGENTS.md" in copilot
    assert len(copilot.splitlines()) <= 3
    for rules in (root_rules, core_rules, persistence_rules, ml_rules):
        assert "llms.txt" not in rules
        assert re.search(r"vaaet-(core|persistence|ml)==\d", rules) is None


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
        "docs/operations/postgresql-guide.md",
        "docs/operations/user-guide.md",
        "docs/product/product-requirements.md",
        "docs/product/roles.md",
        "docs/product/business-rules.md",
        "docs/architecture/data-model.md",
        "docs/architecture/decisions/README.md",
        "docs/roadmap.md",
        "CONTRIBUTING.md",
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

    prd = documents["docs/product/product-requirements.md"]
    assert "Normativo y vigente" in prd
    assert "se instala `vaaet-core`, luego `vaaet-persistence` y por último `vaaet-ml`" in prd
    assert "fuera de alcance" in prd
    assert "Cuatro notebooks" in prd
    assert not (WORKSPACE_ROOT / "docs/product/software-requirements.md").exists()
    assert not (WORKSPACE_ROOT / "docs/product/use-cases.md").exists()
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


def test_management_documents_live_in_the_shared_root() -> None:
    """Ubica changelog, contribución y plantillas de GitHub en un único lugar."""

    assert (WORKSPACE_ROOT / "CHANGELOG.md").is_file()
    assert (WORKSPACE_ROOT / "CONTRIBUTING.md").is_file()
    assert not (ML_ROOT / "CHANGELOG.md").exists()
    assert not (ML_ROOT / "CONTRIBUTING.md").exists()
    assert "## [Unreleased]" in (WORKSPACE_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    github = WORKSPACE_ROOT / ".github"
    assert (github / "pull_request_template.md").is_file()
    assert (github / "ISSUE_TEMPLATE" / "bug_report.md").is_file()
    assert (github / "ISSUE_TEMPLATE" / "feature_request.md").is_file()
    assert (WORKSPACE_ROOT / "docs" / "roadmap.md").is_file()


def test_current_documents_do_not_stamp_versions_or_context_headers() -> None:
    """Evita sellos que se desactualizan: la versión vive en pyproject.toml."""

    historical = ("docs/archive/", "docs/governance/plans/", "docs/architecture/decisions/0")
    current = [
        path
        for path in (WORKSPACE_ROOT / "docs").rglob("*.md")
        if not path.relative_to(WORKSPACE_ROOT).as_posix().startswith(historical)
    ]
    current += [WORKSPACE_ROOT / "README.md", *WORKSPACE_ROOT.glob("vaaet-*/README.md")]
    title_version = re.compile(r"^# .*\b\d+\.\d+\.\d+\s*$", re.MULTILINE)
    offenders = [
        path.relative_to(WORKSPACE_ROOT).as_posix()
        for path in current
        if "<!-- context:" in (text := path.read_text(encoding="utf-8"))
        or title_version.search(text)
        or "Última revisión" in text
    ]
    assert offenders == []
    assert not (WORKSPACE_ROOT / "docs" / "operations" / "deployment.md").exists()


def test_adr_index_lists_every_decision_record() -> None:
    """Mantiene el índice de ADRs como único listado completo de decisiones."""

    decisions_dir = WORKSPACE_ROOT / "docs" / "architecture" / "decisions"
    index = (decisions_dir / "README.md").read_text(encoding="utf-8")
    records = sorted(
        path.name
        for path in decisions_dir.glob("[0-9][0-9][0-9][0-9]-*.md")
        if not path.name.startswith("0000-")
    )
    assert records
    assert [name for name in records if f"]({name})" not in index] == []
    assert (decisions_dir / "0000-template.md").is_file()


def test_future_product_documents_are_explicitly_non_normative() -> None:
    future_documents = {
        "docs/archive/business-model-canvas.md": "Hipótesis de producto futura",
        "docs/archive/statement-of-work.md": "no es una oferta ni un contrato",
        "docs/archive/user-personas.md": "Hipótesis de producto futura",
        "docs/archive/feasibility.md": "No normativo",
        "docs/archive/non-disclosure-agreement.md": "No normativo",
        "docs/archive/risk-matrix.md": "No normativo",
        "docs/archive/project-plan.md": "No normativo",
    }
    for relative, status in future_documents.items():
        content = (WORKSPACE_ROOT / relative).read_text(encoding="utf-8")
        assert status in content
        assert "No normativo" in content
        assert "$" not in content
        assert "GPU T4/V100" not in content


def test_component_ruff_configuration_enforces_complexity_and_naming_rules() -> None:
    for component_root in (WORKSPACE_ROOT / "vaaet-core", ML_ROOT):
        pyproject = (component_root / "pyproject.toml").read_text(encoding="utf-8")
        assert '"C901"' in pyproject
        assert '"N"' in pyproject
        assert '"A"' in pyproject
        assert "max-complexity = 10" in pyproject
