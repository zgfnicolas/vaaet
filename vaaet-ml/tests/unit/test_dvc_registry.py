# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Pruebas offline del adaptador DVC y sus límites manifest-first."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from vaaet_ml.dvc_registry.models import (
    CommandResult,
    RegistryMaterializationPurpose,
    RegistryProvider,
    RemoteConfiguration,
)
from vaaet_ml.dvc_registry.service import REGISTRY_REMOTE, DvcRegistryService
from vaaet_ml.exceptions import DvcRegistryConfigurationError, DvcRegistryOperationError


class _FakeRunner:
    def __init__(self, *, history: str = "", tracked_local: bool = False) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.history = history
        self.tracked_local = tracked_local
        self.failures: set[tuple[str, ...]] = set()

    def run(self, arguments: Sequence[str], *, cwd: Path) -> CommandResult:
        command = tuple(arguments)
        self.commands.append(command)
        if command in self.failures:
            return CommandResult(1, stderr="private://token@storage/secret")
        if command[:3] == ("git", "ls-files", "--error-unmatch"):
            if command[-1] == ".dvc/config.local":
                return CommandResult(0 if self.tracked_local else 1)
            return CommandResult(0)
        if command[:3] == ("git", "diff", "--quiet"):
            return CommandResult(0)
        if command[:3] == ("git", "log", "--format=%H"):
            return CommandResult(0, self.history)
        if command[:2] == ("dvc", "get"):
            Path(command[-1]).mkdir(parents=True, exist_ok=True)
        return CommandResult(0)


def _workspace(tmp_path: Path, *, provider_url: str | None = None, endpoint: str = "") -> Path:
    workspace = tmp_path / "workspace"
    dvc_root = workspace / ".dvc"
    dvc_root.mkdir(parents=True)
    (dvc_root / "config").write_text("# provider-neutral\n", encoding="utf-8")
    (workspace / "vaaet-ml").mkdir()
    (workspace / "vaaet-ml" / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    if provider_url:
        suffix = f"    endpointurl = {endpoint}\n" if endpoint else ""
        (dvc_root / "config.local").write_text(
            "[core]\n"
            f"    remote = {REGISTRY_REMOTE}\n"
            f'[remote "{REGISTRY_REMOTE}"]\n'
            f"    url = {provider_url}\n{suffix}",
            encoding="utf-8",
        )
    return workspace


def _manifest(_: Path) -> dict[str, object]:
    return {
        "model_version": "mlp-v3.0",
        "model_revision_algorithm": "sha256-inference-contract-v2",
        "training_lifecycle": {
            "deployment_stage": "candidate",
            "production_eligible": False,
            "training_mode": "hitl_retraining",
            "input_policy": "canonical-v2",
            "supervision": "human-validated",
        },
        "data_provenance": {
            "origin": "human-reviewed-telemetry",
            "promotion_blockers": ["pending-review"],
        },
        "training_input_lock": {"lock_id": "lock-123"},
    }


def _service(workspace: Path, runner: _FakeRunner) -> DvcRegistryService:
    return DvcRegistryService(
        workspace,
        runner=runner,
        module_finder=lambda _: True,
        manifest_validator=_manifest,  # type: ignore[arg-type]
    )


def test_configure_writes_only_local_dvc_commands_and_requires_replace(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runner = _FakeRunner()
    service = _service(workspace, runner)

    service.configure_remote(
        RemoteConfiguration(
            RegistryProvider.AMAZON_S3, "s3://vaaet-bucket/registry", profile="vaaet"
        )
    )

    assert runner.commands[0] == (
        "dvc",
        "remote",
        "add",
        "--local",
        "--default",
        REGISTRY_REMOTE,
        "s3://vaaet-bucket/registry",
    )
    assert all("--local" in command for command in runner.commands)

    (workspace / ".dvc" / "config.local").write_text(
        f'[remote "{REGISTRY_REMOTE}"]\n    url = s3://old\n', encoding="utf-8"
    )
    with pytest.raises(DvcRegistryConfigurationError, match="--replace"):
        service.configure_remote(RemoteConfiguration(RegistryProvider.AMAZON_S3, "s3://new"))

    service.configure_remote(
        RemoteConfiguration(RegistryProvider.AMAZON_S3, "s3://new", replace=True)
    )
    assert ("dvc", "remote", "remove", "--local", REGISTRY_REMOTE) in runner.commands


def test_configure_r2_rejects_unsafe_endpoints_and_keeps_secrets_out_of_arguments(
    tmp_path: Path,
) -> None:
    service = _service(_workspace(tmp_path), _FakeRunner())

    with pytest.raises(DvcRegistryConfigurationError, match="endpoint HTTPS"):
        service.configure_remote(
            RemoteConfiguration(RegistryProvider.CLOUDFLARE_R2, "s3://bucket/registry")
        )
    with pytest.raises(DvcRegistryConfigurationError, match="credenciales"):
        service.configure_remote(
            RemoteConfiguration(RegistryProvider.AMAZON_S3, "s3://access:secret@bucket/registry")
        )
    with pytest.raises(DvcRegistryConfigurationError, match="región fija"):
        service.configure_remote(
            RemoteConfiguration(
                RegistryProvider.CLOUDFLARE_R2,
                "s3://bucket/registry",
                endpoint_url="https://account.r2.cloudflarestorage.com",
                region="us-east-1",
            )
        )


def test_doctor_requires_neutral_tracked_config_and_local_provider_plugin(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, provider_url="s3://bucket/registry")
    runner = _FakeRunner()
    service = _service(workspace, runner)

    health = service.doctor()

    assert health.remote_name == REGISTRY_REMOTE
    assert health.provider is RegistryProvider.AMAZON_S3
    assert ("dvc", "version") in runner.commands

    (workspace / ".dvc" / "config").write_text("[core]\nremote = legacy\n", encoding="utf-8")
    with pytest.raises(DvcRegistryConfigurationError, match="neutral"):
        service.doctor()


def test_doctor_rejects_a_local_configuration_tracked_by_git(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, provider_url="s3://bucket/registry")
    tracked_service = _service(workspace, _FakeRunner(tracked_local=True))
    with pytest.raises(DvcRegistryConfigurationError, match="no puede estar versionado"):
        tracked_service.doctor()


def test_stage_validates_before_dvc_add_and_rejects_placeholder(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    bundle = workspace / "vaaet-ml" / "artifacts" / "traffic-state"
    bundle.mkdir(parents=True)
    runner = _FakeRunner()
    service = _service(workspace, runner)

    (bundle / ".gitkeep").touch()
    with pytest.raises(DvcRegistryOperationError, match="placeholder"):
        service.stage_bundle()
    assert runner.commands == []

    (bundle / ".gitkeep").unlink()
    assert service.stage_bundle() == "mlp-v3.0"
    assert runner.commands == [("dvc", "add", "vaaet-ml/artifacts/traffic-state")]


def test_push_requires_committed_pointer_before_remote_commands(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, provider_url="gdrive://folder-id")
    runner = _FakeRunner()
    service = _service(workspace, runner)

    runner.failures.add(
        ("git", "ls-files", "--error-unmatch", "vaaet-ml/artifacts/traffic-state.dvc")
    )
    with pytest.raises(DvcRegistryOperationError, match="versionado"):
        service.push_bundle()
    assert not any(command[:2] == ("dvc", "push") for command in runner.commands)


def test_push_redacts_provider_output_and_runs_only_after_git_checks(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, provider_url="gdrive://folder-id")
    runner = _FakeRunner()
    service = _service(workspace, runner)
    status_command = ("dvc", "status", "-c", "vaaet-ml/artifacts/traffic-state.dvc")
    runner.failures.add(status_command)

    with pytest.raises(DvcRegistryOperationError) as captured:
        service.push_bundle()

    assert "private://" not in str(captured.value)
    assert "token" not in str(captured.value)
    assert not any(command[:2] == ("dvc", "push") for command in runner.commands)

    runner.failures.clear()
    service.push_bundle()
    assert (
        "dvc",
        "push",
        "-r",
        REGISTRY_REMOTE,
        "vaaet-ml/artifacts/traffic-state.dvc",
    ) in runner.commands


def test_list_materializes_each_revision_temporarily_and_validates_manifest(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, provider_url="s3://bucket/registry")
    runner = _FakeRunner(history="first\nsecond\n")
    service = _service(workspace, runner)

    entries = service.list_entries(limit=1)

    assert len(entries) == 1
    assert entries[0].revision == "first"
    assert entries[0].model_version == "mlp-v3.0"
    assert entries[0].historical_only is False
    assert entries[0].provenance_origin == "human-reviewed-telemetry"
    assert entries[0].input_lock_id == "lock-123"
    assert entries[0].promotion_blockers == ("pending-review",)
    assert entries[0].as_dict()["provenance_origin"] == "human-reviewed-telemetry"
    assert entries[0].as_dict()["input_lock_id"] == "lock-123"
    assert any(command[:2] == ("dvc", "get") for command in runner.commands)
    assert service.list_entries(limit=2, model_version="other") == ()


def test_get_refuses_existing_or_active_output_and_promotes_only_validated_bundle(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path, provider_url="s3://bucket/registry")
    runner = _FakeRunner()
    service = _service(workspace, runner)
    output_root = tmp_path / "outputs"
    output_root.mkdir()

    destination = output_root / "candidate"
    assert service.get_bundle("model/mlp-v3.0", destination) == "mlp-v3.0"
    assert destination.is_dir()
    with pytest.raises(DvcRegistryOperationError, match="ya existe"):
        service.get_bundle("model/mlp-v3.0", destination)
    with pytest.raises(DvcRegistryConfigurationError, match="bundle activo"):
        service.get_bundle("model/mlp-v3.0", service.bundle_path / "nested")


def test_historical_bundle_requires_explicit_materialization_purpose(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, provider_url="s3://bucket/registry")
    runner = _FakeRunner(history="legacy\n")

    def reject_operational(_: Path) -> dict[str, object]:
        raise ValueError("historical only")

    def historical_manifest(path: Path) -> dict[str, object]:
        manifest = _manifest(path)
        del manifest["model_revision_algorithm"]
        return manifest

    service = DvcRegistryService(
        workspace,
        runner=runner,
        module_finder=lambda _: True,
        manifest_validator=reject_operational,  # type: ignore[arg-type]
        historical_manifest_validator=historical_manifest,  # type: ignore[arg-type]
    )
    output_root = tmp_path / "outputs"
    output_root.mkdir()

    entries = service.list_entries(limit=1)
    assert entries[0].available is True
    assert entries[0].historical_only is True
    with pytest.raises(DvcRegistryOperationError, match="manifest-first"):
        service.get_bundle("legacy", output_root / "operational")
    assert (
        service.get_bundle(
            "legacy",
            output_root / "historical",
            purpose=RegistryMaterializationPurpose.HISTORICAL_EVALUATION,
        )
        == "mlp-v3.0"
    )
