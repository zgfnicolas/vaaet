# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from vaaet_ml import runtime
from vaaet_ml.exceptions import RuntimeConfigurationError
from vaaet_ml.runtime import (
    RuntimeDiagnostics,
    _framework_gpu_available,
    _nvidia_smi,
    _pip_check,
    _validate_package_origin,
    _validate_python_version,
    build_training_runtime_evidence,
)


def test_validate_python_version_accepts_supported_bounds() -> None:
    _validate_python_version((3, 10))
    _validate_python_version((3, 13))


def test_validate_python_version_rejects_unsupported_runtime() -> None:
    with pytest.raises(RuntimeConfigurationError, match="supports Python"):
        _validate_python_version((3, 14))


def test_package_origin_rejects_namespace_package(tmp_path: Path) -> None:
    package = SimpleNamespace(__file__=None, __path__=[str(tmp_path / "vaaet")])
    with pytest.raises(RuntimeConfigurationError, match="namespace package"):
        _validate_package_origin(package, tmp_path, "vaaet", True)


def test_package_origin_accepts_colab_wheel(tmp_path: Path) -> None:
    package_file = tmp_path / "site-packages" / "vaaet" / "__init__.py"
    package = SimpleNamespace(__file__=str(package_file), __path__=[str(package_file.parent)])
    assert (
        _validate_package_origin(package, tmp_path / "workspace" / "vaaet-ml", "vaaet", True)
        == package_file.resolve()
    )


def test_gpu_preflight_rejects_an_unknown_framework() -> None:
    with pytest.raises(RuntimeConfigurationError, match="Unsupported runtime framework"):
        _framework_gpu_available("jax")


def test_nvidia_smi_uses_a_bounded_query(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(runtime.shutil, "which", lambda name: "nvidia-smi" if name == "nvidia-smi" else None)
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command) or SimpleNamespace(returncode=0, stdout="T4, 15360, 42\n"),
    )

    assert _nvidia_smi() == "T4, 15360, 42"
    assert calls == [["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"]]


def test_pip_check_keeps_diagnostics_non_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="resolver warning\n", stderr="conflict\n"),
    )

    assert _pip_check() == "resolver warning\nconflict"


def test_training_runtime_evidence_redacts_paths_and_normalizes_gpu_lines(tmp_path: Path) -> None:
    diagnostics = RuntimeDiagnostics(
        in_colab=True,
        workspace_root=tmp_path,
        core_root=tmp_path / "core",
        persistence_root=tmp_path / "persistence",
        ml_root=tmp_path / "ml",
        package_file=tmp_path / "site-packages" / "vaaet" / "__init__.py",
        persistence_package_file=(
            tmp_path / "site-packages" / "vaaet_persistence" / "__init__.py"
        ),
        ml_package_file=tmp_path / "site-packages" / "vaaet_ml" / "__init__.py",
        git_commit="1234abc",
        python_version="3.12.0",
        framework="tensorflow",
        framework_gpu_available=True,
        nvidia_smi="T4, 15360, 42\nT4, 15360, 41",
        total_ram_gib=12.0,
        available_ram_gib=8.0,
        content_free_gib=40.0,
        pip_check_output=None,
    )

    evidence = build_training_runtime_evidence(
        diagnostics,
        tensorflow_version="2.20.0",
        keras_version="3.12.0",
        declared_extras=("training", "visualization"),
    )

    assert "workspace_root" not in evidence
    assert evidence["nvidia_smi"] == "T4, 15360, 42 | T4, 15360, 41"
