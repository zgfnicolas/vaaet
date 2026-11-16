# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Valida la configuración versionada de Claude Code del monorepo."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ML_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = ML_ROOT.parent
CLAUDE_DIR = WORKSPACE_ROOT / ".claude"


def _settings() -> dict[str, object]:
    return json.loads((CLAUDE_DIR / "settings.json").read_text(encoding="utf-8"))


def _permissions() -> dict[str, list[str]]:
    permissions = _settings()["permissions"]
    assert isinstance(permissions, dict)
    return {key: list(value) for key, value in permissions.items()}


def test_settings_deny_secrets_private_data_and_destructive_commands() -> None:
    deny = set(_permissions()["deny"])
    for rule in (
        "Read(./**/.env)",
        "Edit(./**/.env)",
        "Read(./.dvc/config.local)",
        "Read(./**/*.private.json)",
        "Read(./vaaet-ml/data/private/**)",
        "Edit(./**/*.keras)",
        "Edit(./**/*.joblib)",
        "Edit(./**/*.pt)",
        "Bash(git push --force*)",
        "Bash(git reset --hard*)",
        "Bash(dvc gc*)",
        "Bash(alembic * downgrade*)",
        "Bash(rm -rf *)",
    ):
        assert rule in deny, rule


def test_settings_keep_outward_actions_behind_confirmation() -> None:
    permissions = _permissions()
    ask = set(permissions["ask"])
    for rule in (
        "Bash(git commit *)",
        "Bash(git push *)",
        "Bash(gh pr create *)",
        "Bash(alembic *)",
    ):
        assert rule in ask, rule
    allowed = " ".join(permissions["allow"])
    for outward in ("git commit", "git push", "gh pr create", "gh pr merge", "alembic", "dvc push"):
        assert outward not in allowed, outward


def test_settings_rules_use_current_syntax_and_keep_env_example_readable() -> None:
    rules = [rule for values in _permissions().values() for rule in values]
    assert rules
    assert not [rule for rule in rules if ":*)" in rule]
    # `deny` gana siempre: un patrón `.env.*` bloquearía también `.env.example`.
    assert not [rule for rule in rules if rule.startswith(("Read(", "Edit(")) and ".env.*" in rule]
    assert not [
        rule
        for rule in rules
        if rule.startswith("Bash(cat") and rule.endswith((".env*)", ".env.*)"))
    ]


def test_gitignore_excludes_personal_and_temporary_claude_files() -> None:
    gitignore = (WORKSPACE_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for entry in ("CLAUDE.local.md", ".claude/settings.local.json", ".claude/worktrees/"):
        assert entry in gitignore, entry


MIGRATIONS = "vaaet-persistence/src/vaaet_persistence/migrations/versions"
HOOK_COMMAND = re.compile(r"\$CLAUDE_PROJECT_DIR/(?P<script>\.claude/hooks/[\w.]+\.py)")


def _run_hook(script: str, event: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLAUDE_DIR / "hooks" / script)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(WORKSPACE_ROOT)},
        timeout=30,
        check=False,
    )


def _load_hook(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"hook_{name}", CLAUDE_DIR / "hooks" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_registered_hook_runs_an_existing_python_script() -> None:
    hooks = _settings()["hooks"]
    assert isinstance(hooks, dict)
    assert {"PreToolUse", "SessionStart"} <= set(hooks)
    commands = [
        hook["command"] for groups in hooks.values() for group in groups for hook in group["hooks"]
    ]
    assert commands
    for command in commands:
        match = HOOK_COMMAND.search(command)
        assert match, command
        assert (WORKSPACE_ROOT / match["script"]).is_file(), command
    guard = next(group for group in hooks["PreToolUse"] if "guard_paths.py" in str(group))
    assert set(guard["matcher"].split("|")) == {"Edit", "Write", "NotebookEdit"}


@pytest.mark.parametrize(
    ("target", "blocked"),
    [
        (".env", True),
        ("vaaet-ml/.env.local", True),
        ("certs/provider-ca.pem", True),
        (".dvc/config.local", True),
        ("calibration/cam.vaaet-view-plan.private.json", True),
        ("vaaet-ml/data/private/notes.md", True),
        ("vaaet-ml/artifacts/traffic-state/traffic_classifier.keras", True),
        ("vaaet-ml/artifacts/traffic-state/feature_scaler.joblib", True),
        ("vaaet-ml/artifacts/traffic-state.dvc", True),
        (f"{MIGRATIONS}/20260905_0003_temporal_continuity_model_revision.py", True),
        (f"{MIGRATIONS}/20991231_9999_future_revision.py", False),
        ("vaaet-ml/.env.example", False),
        ("vaaet-ml/src/vaaet_ml/data/ingestion.py", False),
        ("docs/index.md", False),
    ],
)
def test_guard_paths_blocks_only_protected_targets(target: str, blocked: bool) -> None:
    result = _run_hook("guard_paths.py", {"tool_name": "Edit", "tool_input": {"file_path": target}})
    assert result.returncode == (2 if blocked else 0), result.stderr
    if blocked:
        assert "bloqueada" in result.stderr


def test_guard_paths_handles_absolute_notebook_and_malformed_events() -> None:
    absolute = WORKSPACE_ROOT / MIGRATIONS / "20260804_0001_postgres_schemas_hitl.py"
    assert _run_hook("guard_paths.py", {"tool_input": {"file_path": str(absolute)}}).returncode == 2
    notebook = {"tool_input": {"notebook_path": "vaaet-ml/notebooks/inference/x.ipynb"}}
    assert _run_hook("guard_paths.py", notebook).returncode == 0
    assert _run_hook("guard_paths.py", ["not", "an", "event"]).returncode == 0


def test_session_context_lists_only_plans_in_progress(tmp_path: Path) -> None:
    plans = tmp_path / "docs" / "governance" / "plans"
    plans.mkdir(parents=True)
    (plans / "2026-01-01-open.md").write_text(
        "# Plan\n\n- Estado global: En progreso\n", encoding="utf-8"
    )
    (plans / "2026-01-02-done.md").write_text(
        "# Plan\n\n- Estado global: Completado\n", encoding="utf-8"
    )
    (plans / "TEMPLATE.md").write_text(
        "- Estado global: Propuesto / En progreso / Completado\n", encoding="utf-8"
    )

    assert _load_hook("session_context").open_plans(tmp_path) == [
        "docs/governance/plans/2026-01-01-open.md"
    ]
    result = _run_hook("session_context.py", {"hook_event_name": "SessionStart"})
    assert result.returncode == 0
    assert "Rama actual" in result.stdout


def test_guard_paths_treats_only_revisions_on_main_as_published(tmp_path: Path) -> None:
    guard = _load_hook("guard_paths")
    versions = tmp_path / MIGRATIONS
    versions.mkdir(parents=True)
    published = versions / "20260101_0001_published.py"
    published.write_text("revision = '20260101_0001'\n", encoding="utf-8")

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    git("init", "-q", "-b", "main")
    git("add", ".")
    git("commit", "-q", "-m", "published revision")
    git("checkout", "-q", "-b", "feature/new-revision")
    branch_only = versions / "20260102_0002_branch_only.py"
    branch_only.write_text("revision = '20260102_0002'\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "branch revision")
    untracked = versions / "20260103_0003_untracked.py"
    untracked.write_text("revision = '20260103_0003'\n", encoding="utf-8")

    assert guard.blocked_reason(str(published), tmp_path) is not None
    assert guard.blocked_reason(str(branch_only), tmp_path) is None
    assert guard.blocked_reason(str(untracked), tmp_path) is None


def _frontmatter(path: Path) -> dict[str, str]:
    """Lee los pares `clave: valor` del frontmatter sin depender de YAML."""

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---", path
    end = lines.index("---", 1)
    fields: dict[str, str] = {}
    current = ""
    for line in lines[1:end]:
        if line.startswith((" ", "-")) and current:
            fields[current] += "\n" + line.strip()
        elif ":" in line:
            current, value = line.split(":", 1)
            fields[current.strip()] = value.strip()
    return fields


def test_rules_are_path_scoped_and_point_to_existing_codex_skills() -> None:
    rules = sorted((CLAUDE_DIR / "rules").glob("*.md"))
    assert len(rules) >= 5
    for rule in rules:
        assert _frontmatter(rule).get("paths"), rule.name
        content = rule.read_text(encoding="utf-8")
        assert len(content.splitlines()) <= 30, rule.name
        for skill in re.findall(r"\.codex/skills/[\w-]+/SKILL\.md", content):
            assert (WORKSPACE_ROOT / skill).is_file(), f"{rule.name} -> {skill}"


def test_skills_declare_purpose_and_gate_side_effects() -> None:
    skills = {path.parent.name: path for path in (CLAUDE_DIR / "skills").glob("*/SKILL.md")}
    assert {"validate", "pg-integration", "open-pr", "governed-plan"} <= set(skills)
    for name, path in skills.items():
        fields = _frontmatter(path)
        assert fields.get("name") == name
        assert len(fields.get("description", "")) >= 60, name
    for effectful in ("pg-integration", "open-pr"):
        assert _frontmatter(skills[effectful]).get("disable-model-invocation") == "true"
    for script in ("setup_pg.sh", "run_ci_steps.sh"):
        assert (CLAUDE_DIR / "skills" / "pg-integration" / "scripts" / script).is_file()


def test_subagents_are_read_only_reviewers() -> None:
    agents = {path.stem: path for path in (CLAUDE_DIR / "agents").glob("*.md")}
    assert {"vaaet-reviewer", "ci-investigator"} <= set(agents)
    for name, path in agents.items():
        fields = _frontmatter(path)
        assert fields.get("name") == name
        assert fields.get("description"), name
        tools = {tool.strip() for tool in fields.get("tools", "").split(",")}
        assert tools and not tools & {"Edit", "Write", "NotebookEdit"}, name
        assert "isolation" not in fields, name


def test_governed_plan_template_has_a_single_source() -> None:
    template = WORKSPACE_ROOT / "docs" / "governance" / "plans" / "TEMPLATE.md"
    assert template.read_text(encoding="utf-8").startswith("# Plan de ejecución:")
    codex = (WORKSPACE_ROOT / ".codex/skills/vaaet-context-engineering/SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "docs/governance/plans/TEMPLATE.md" in codex
    assert "## 3. Fases de ejecución HITL" not in codex
    skill = (CLAUDE_DIR / "skills" / "governed-plan" / "SKILL.md").read_text(encoding="utf-8")
    assert "docs/governance/plans/TEMPLATE.md" in skill


def test_ci_runs_when_claude_code_configuration_changes() -> None:
    workflow = (WORKSPACE_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert workflow.count('      - ".claude/**"') == 2


def test_claude_scripts_do_not_hardcode_credentials() -> None:
    """Las credenciales del PostgreSQL local se generan; nunca se versionan."""

    literal = re.compile(r"(PASSWORD|PGPASSWORD)=['\"]?(?!\$)[\w-]+|PASSWORD '[\w-]+'")
    offenders = [
        f"{path.relative_to(WORKSPACE_ROOT).as_posix()}:{number}"
        for path in CLAUDE_DIR.rglob("*")
        if path.suffix in {".sh", ".py", ".json", ".md"}
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if literal.search(line)
    ]
    assert offenders == []
