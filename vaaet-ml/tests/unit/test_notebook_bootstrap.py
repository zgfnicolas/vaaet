# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ML_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_PATH = ML_ROOT / "scripts" / "notebook_bootstrap.py"
RUNTIME_PREFIXES = ("PIL", "ultralytics", "vaaet", "vaaet_persistence", "vaaet_ml")


@pytest.fixture(autouse=True)
def preserve_imported_runtime_modules():
    """Aísla la limpieza deliberada de módulos que realiza el bootstrap."""

    originals = {
        name: loaded_module
        for name, loaded_module in sys.modules.items()
        if any(
            name == prefix or name.startswith(f"{prefix}.") for prefix in RUNTIME_PREFIXES
        )
    }
    yield
    for name in tuple(sys.modules):
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in RUNTIME_PREFIXES):
            sys.modules.pop(name, None)
    sys.modules.update(originals)


def _bootstrap_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("vaaet_notebook_bootstrap", BOOTSTRAP_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def install_spec(tmp_path: Path) -> object:
    module = _bootstrap_module()
    workspace = tmp_path / "vaaet"
    core = workspace / "vaaet-core"
    persistence = workspace / "vaaet-persistence"
    ml = workspace / "vaaet-ml"
    (workspace / ".git").mkdir(parents=True)
    core.mkdir()
    persistence.mkdir()
    ml.mkdir()
    (core / "pyproject.toml").write_text("[project]\nname='core'\n", encoding="utf-8")
    (persistence / "pyproject.toml").write_text(
        "[project]\nname='persistence'\n", encoding="utf-8"
    )
    (ml / "pyproject.toml").write_text("[project]\nname='ml'\n", encoding="utf-8")
    return module.NotebookInstallSpec(
        workspace_root=workspace,
        core_root=core,
        persistence_root=persistence,
        ml_root=ml,
        core_extras=("vision",),
        ml_extras=("database",),
        in_colab=True,
    )


def _successful_runner(calls: list[list[str]]):
    def runner(command: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return runner


def test_first_install_preserves_compatible_runtime_packages(
    install_spec: object, tmp_path: Path
) -> None:
    module = _bootstrap_module()
    calls: list[list[str]] = []

    module.install_notebook_components(
        install_spec,
        state_path=tmp_path / "state.json",
        runner=_successful_runner(calls),
        runtime_validator=lambda _spec: None,
    )

    assert len(calls) == 1
    assert "--force-reinstall" not in calls[0]
    assert "--no-deps" not in calls[0]
    assert "--editable" not in calls[0]


def test_unchanged_dependencies_only_refresh_code(install_spec: object, tmp_path: Path) -> None:
    module = _bootstrap_module()
    state_path = tmp_path / "state.json"
    initial_calls: list[list[str]] = []
    module.install_notebook_components(
        install_spec,
        state_path=state_path,
        runner=_successful_runner(initial_calls),
        runtime_validator=lambda _spec: None,
    )
    refresh_calls: list[list[str]] = []

    module.install_notebook_components(
        install_spec,
        state_path=state_path,
        runner=_successful_runner(refresh_calls),
        runtime_validator=lambda _spec: None,
    )

    assert len(refresh_calls) == 1
    assert "--force-reinstall" in refresh_calls[0]
    assert "--no-deps" in refresh_calls[0]


def test_local_development_uses_editable_components(tmp_path: Path) -> None:
    module = _bootstrap_module()
    workspace = tmp_path / "vaaet"
    core = workspace / "vaaet-core"
    persistence = workspace / "vaaet-persistence"
    ml = workspace / "vaaet-ml"
    (workspace / ".git").mkdir(parents=True)
    core.mkdir()
    persistence.mkdir()
    ml.mkdir()
    (core / "pyproject.toml").write_text("[project]\nname='core'\n", encoding="utf-8")
    (persistence / "pyproject.toml").write_text(
        "[project]\nname='persistence'\n", encoding="utf-8"
    )
    (ml / "pyproject.toml").write_text("[project]\nname='ml'\n", encoding="utf-8")
    spec = module.NotebookInstallSpec(
        workspace_root=workspace,
        core_root=core,
        persistence_root=persistence,
        ml_root=ml,
        core_extras=("inference",),
        ml_extras=("training",),
        in_colab=False,
    )
    calls: list[list[str]] = []

    module.install_notebook_components(
        spec,
        state_path=tmp_path / "local-state.json",
        runner=_successful_runner(calls),
        runtime_validator=lambda _spec: None,
    )

    assert all(call.count("--editable") == 3 for call in calls)


def test_pyproject_change_resolves_dependencies_again(install_spec: object, tmp_path: Path) -> None:
    module = _bootstrap_module()
    state_path = tmp_path / "state.json"
    module.install_notebook_components(
        install_spec,
        state_path=state_path,
        runner=_successful_runner([]),
        runtime_validator=lambda _spec: None,
    )
    install_spec.core_root.joinpath("pyproject.toml").write_text(
        "[project]\nname='core'\nversion='2'\n", encoding="utf-8"
    )
    calls: list[list[str]] = []

    module.install_notebook_components(
        install_spec,
        state_path=state_path,
        runner=_successful_runner(calls),
        runtime_validator=lambda _spec: None,
    )

    assert len(calls) == 1
    assert "--force-reinstall" not in calls[0]
    assert "--no-deps" not in calls[0]


def test_install_failure_does_not_write_state(install_spec: object, tmp_path: Path) -> None:
    module = _bootstrap_module()
    state_path = tmp_path / "state.json"

    with pytest.raises(module.NotebookBootstrapError, match="instalación de VAAET falló"):
        module.install_notebook_components(
            install_spec,
            state_path=state_path,
            runner=lambda *_args, **_kwargs: SimpleNamespace(
                returncode=1, stdout="resolver output", stderr="dependency conflict"
            ),
            runtime_validator=lambda _spec: None,
        )

    assert not state_path.exists()


def test_failed_visual_smoke_test_does_not_write_state(
    install_spec: object, tmp_path: Path
) -> None:
    module = _bootstrap_module()
    state_path = tmp_path / "state.json"

    def fail_validation(_spec: object) -> None:
        raise module.NotebookBootstrapError("runtime visual inconsistente")

    with pytest.raises(module.NotebookBootstrapError, match="runtime visual inconsistente"):
        module.install_notebook_components(
            install_spec,
            state_path=state_path,
            runner=_successful_runner([]),
            runtime_validator=fail_validation,
        )

    assert not state_path.exists()


def test_visual_install_clears_loaded_pillow_and_ultralytics_modules(
    install_spec: object, tmp_path: Path
) -> None:
    module = _bootstrap_module()
    sentinel_modules = {
        "PIL": ModuleType("PIL"),
        "PIL._typing": ModuleType("PIL._typing"),
        "ultralytics": ModuleType("ultralytics"),
        "ultralytics.models": ModuleType("ultralytics.models"),
        "vaaet": ModuleType("vaaet"),
        "vaaet_persistence": ModuleType("vaaet_persistence"),
        "vaaet_ml": ModuleType("vaaet_ml"),
    }
    prefixes = RUNTIME_PREFIXES
    originals = {
        name: loaded_module
        for name, loaded_module in sys.modules.items()
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes)
    }
    observed: dict[str, bool] = {}

    def validate(_spec: object) -> None:
        observed.update({name: name in sys.modules for name in sentinel_modules})

    try:
        sys.modules.update(sentinel_modules)
        module.install_notebook_components(
            install_spec,
            state_path=tmp_path / "state.json",
            runner=_successful_runner([]),
            runtime_validator=validate,
        )
    finally:
        for name in tuple(sys.modules):
            if any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes):
                sys.modules.pop(name, None)
        sys.modules.update(originals)

    assert observed == dict.fromkeys(sentinel_modules, False)


def test_visual_runtime_validator_imports_real_yolo_boundary(install_spec: object) -> None:
    module = _bootstrap_module()
    imported: list[str] = []
    ultralytics_module = ModuleType("ultralytics")
    ultralytics_module.YOLO = object()  # type: ignore[attr-defined]

    def import_module(name: str) -> ModuleType:
        imported.append(name)
        return ultralytics_module if name == "ultralytics" else ModuleType(name)

    original_import_module = module.importlib.import_module
    original_version = module.metadata.version
    try:
        module.importlib.import_module = import_module
        module.metadata.version = lambda _distribution: "test-version"
        module._validate_declared_runtime(install_spec)
    finally:
        module.importlib.import_module = original_import_module
        module.metadata.version = original_version

    assert imported == ["PIL.ImageDraw", "ultralytics"]


def test_visual_runtime_failure_reports_versions_and_recovery(install_spec: object) -> None:
    module = _bootstrap_module()
    original_import_module = module.importlib.import_module
    original_version = module.metadata.version
    try:
        module.importlib.import_module = lambda _name: (_ for _ in ()).throw(
            ImportError("mixed Pillow modules")
        )
        module.metadata.version = lambda distribution: {
            "Pillow": "12.0.0",
            "ultralytics-opencv-headless": "8.4.123",
        }[distribution]
        with pytest.raises(module.NotebookBootstrapError) as captured:
            module._validate_declared_runtime(install_spec)
    finally:
        module.importlib.import_module = original_import_module
        module.metadata.version = original_version

    message = str(captured.value)
    assert "Pillow=12.0.0" in message
    assert "Ultralytics=8.4.123" in message
    assert "reabrí el notebook actualizado desde GitHub" in message
    assert "Run All" in message


def test_invalid_component_layout_fails_fast(tmp_path: Path) -> None:
    module = _bootstrap_module()
    workspace = tmp_path / "vaaet"
    (workspace / ".git").mkdir(parents=True)

    with pytest.raises(module.NotebookBootstrapError, match="pyproject.toml"):
        module.NotebookInstallSpec(
            workspace_root=workspace,
            core_root=workspace / "vaaet-core",
            persistence_root=workspace / "vaaet-persistence",
            ml_root=workspace / "vaaet-ml",
            core_extras=("vision",),
            ml_extras=("database",),
            in_colab=False,
        )
