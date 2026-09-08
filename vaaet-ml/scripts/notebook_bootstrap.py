# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Instalación idempotente de paquetes para las celdas de entorno VAAET.

Usa deliberadamente sólo la biblioteca estándar porque debe ejecutarse desde
un checkout nuevo antes de que las distribuciones VAAET puedan importarse.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from vaaet_ml.runtime import RuntimeDiagnostics


class NotebookBootstrapError(RuntimeError):
    """Indica que el runtime del notebook no pudo prepararse de forma segura."""


class ProcessResult(Protocol):
    """Define el resultado mínimo de subprocess requerido por el bootstrap."""

    returncode: int
    stdout: str | None
    stderr: str | None


CommandRunner = Callable[..., ProcessResult]
RuntimeValidator = Callable[["NotebookInstallSpec"], None]


@dataclass(frozen=True)
class NotebookInstallSpec:
    """Representa requisitos inmutables de instalación para un workflow."""

    workspace_root: Path
    core_root: Path
    persistence_root: Path
    ml_root: Path
    core_extras: tuple[str, ...]
    ml_extras: tuple[str, ...]
    in_colab: bool

    def __post_init__(self) -> None:
        if not self.core_extras or not self.ml_extras:
            raise NotebookBootstrapError("Cada workflow debe declarar extras para core y ML.")
        if not (self.workspace_root / ".git").is_dir():
            raise NotebookBootstrapError("No se encontró el checkout Git de VAAET.")
        for component_root in (self.core_root, self.persistence_root, self.ml_root):
            if not (component_root / "pyproject.toml").is_file():
                raise NotebookBootstrapError(
                    f"No se encontró pyproject.toml en el componente: {component_root.name}."
                )

    def requirements(self) -> tuple[str, str, str]:
        return (
            _format_requirement(self.core_root, self.core_extras),
            _format_requirement(self.persistence_root, ()),
            _format_requirement(self.ml_root, self.ml_extras),
        )


def _format_requirement(project_root: Path, extras: tuple[str, ...]) -> str:
    return f"{project_root}[{','.join(extras)}]" if extras else str(project_root)


def _dependency_fingerprint(spec: NotebookInstallSpec) -> str:
    """Calcula un fingerprint de dependencias y extras, nunca del código fuente."""

    digest = hashlib.sha256()
    for project_root, extras in (
        (spec.core_root, spec.core_extras),
        (spec.persistence_root, ()),
        (spec.ml_root, spec.ml_extras),
    ):
        digest.update((project_root / "pyproject.toml").read_bytes())
        digest.update("\0".join(extras).encode("utf-8"))
        digest.update(b"\0")
    digest.update(b"colab" if spec.in_colab else b"local-editable")
    return digest.hexdigest()


def _default_state_path(workspace_root: Path) -> Path:
    workspace_id = hashlib.sha256(str(workspace_root.resolve()).encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / "vaaet-notebook-bootstrap" / workspace_id / "state.json"


def _read_state(state_path: Path) -> dict[str, str] | None:
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("dependency_fingerprint"), str):
        return None
    return {"dependency_fingerprint": payload["dependency_fingerprint"]}


def _write_state(state_path: Path, fingerprint: str) -> None:
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = state_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps({"dependency_fingerprint": fingerprint}, sort_keys=True), encoding="utf-8"
        )
        temporary_path.replace(state_path)
    except OSError as error:
        raise NotebookBootstrapError("No se pudo registrar el estado efímero de instalación.") from error


def _pip_command(spec: NotebookInstallSpec, *options: str) -> list[str]:
    command = [sys.executable, "-m", "pip", "install", "-q", *options]
    for requirement in spec.requirements():
        if spec.in_colab:
            command.append(requirement)
        else:
            command.extend(["--editable", requirement])
    return command


def _run_pip(command: list[str], runner: CommandRunner) -> None:
    result = runner(command, capture_output=True, text=True, check=False)
    if result.returncode:
        stdout = str(getattr(result, "stdout", "") or "").strip()
        stderr = str(getattr(result, "stderr", "") or "").strip()
        diagnostic = "\n".join(part for part in (stdout, stderr) if part)
        raise NotebookBootstrapError(
            "La instalación de VAAET falló. Verificá conectividad, espacio libre y los "
            "extras declarados antes de reintentar."
            + (f"\n\nDiagnóstico de pip:\n{diagnostic}" if diagnostic else "")
        )


def _clear_installed_modules(spec: NotebookInstallSpec) -> None:
    """Descarta módulos que podrían haber quedado cargados antes de la instalación."""

    prefixes = ["vaaet", "vaaet_persistence", "vaaet_ml"]
    if "vision" in spec.core_extras:
        prefixes.extend(("PIL", "ultralytics"))
    for module_name in tuple(sys.modules):
        if any(module_name == prefix or module_name.startswith(f"{prefix}.") for prefix in prefixes):
            sys.modules.pop(module_name, None)
    importlib.invalidate_caches()


def _installed_version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return "no instalada"


def _validate_declared_runtime(spec: NotebookInstallSpec) -> None:
    """Importa el borde visual real sin descargar pesos de modelos."""

    if "vision" not in spec.core_extras:
        return
    try:
        importlib.import_module("PIL.ImageDraw")
        ultralytics_module = importlib.import_module("ultralytics")
        _ = ultralytics_module.YOLO
    except (AttributeError, ImportError, OSError, RuntimeError) as error:
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        raise NotebookBootstrapError(
            "El runtime visual quedó inconsistente y no es seguro iniciar YOLO. "
            f"Python={python_version} | Pillow={_installed_version('Pillow')} | "
            "Ultralytics="
            f"{_installed_version('ultralytics-opencv-headless')}. "
            "Reiniciá el runtime, reabrí el notebook actualizado desde GitHub y ejecutá "
            "Run All. No continúes con instalaciones manuales dentro de esta sesión."
        ) from error
    print(
        "✅ Runtime visual validado | "
        f"Pillow={_installed_version('Pillow')} | "
        f"Ultralytics={_installed_version('ultralytics-opencv-headless')}"
    )


def install_notebook_components(
    spec: NotebookInstallSpec,
    *,
    state_path: Path | None = None,
    runner: CommandRunner = subprocess.run,
    runtime_validator: RuntimeValidator | None = None,
) -> None:
    """Resuelve dependencias, valida imports y recién entonces registra el runtime."""

    fingerprint = _dependency_fingerprint(spec)
    state_path = state_path or _default_state_path(spec.workspace_root)
    state = _read_state(state_path)
    if state is None or state["dependency_fingerprint"] != fingerprint:
        print("📦 Resolviendo los extras declarados para este workflow...")
        _run_pip(_pip_command(spec), runner)
    else:
        print("✅ Extras sin cambios; se reutilizan las dependencias del runtime.")
        print("🔄 Actualizando core, persistence y ML desde el checkout actual...")
        _run_pip(_pip_command(spec, "--force-reinstall", "--no-deps"), runner)
    _clear_installed_modules(spec)
    validator = runtime_validator or _validate_declared_runtime
    validator(spec)
    _write_state(state_path, fingerprint)


def _clear_vaaet_modules() -> None:
    for module_name in tuple(sys.modules):
        if module_name in {"vaaet", "vaaet_persistence", "vaaet_ml"} or module_name.startswith(
            ("vaaet.", "vaaet_persistence.", "vaaet_ml.")
        ):
            sys.modules.pop(module_name, None)
    importlib.invalidate_caches()


def bootstrap_notebook(
    *,
    workspace_root: Path,
    core_root: Path,
    persistence_root: Path,
    ml_root: Path,
    core_extras: tuple[str, ...],
    ml_extras: tuple[str, ...],
    in_colab: bool,
    framework: str | None,
    require_gpu: bool,
) -> RuntimeDiagnostics:
    """Instala extras, actualiza el código y ejecuta el preflight de VAAET."""

    spec = NotebookInstallSpec(
        workspace_root=workspace_root,
        core_root=core_root,
        persistence_root=persistence_root,
        ml_root=ml_root,
        core_extras=core_extras,
        ml_extras=ml_extras,
        in_colab=in_colab,
    )
    install_notebook_components(spec)
    _clear_vaaet_modules()

    from vaaet_ml.runtime import bootstrap_notebook_runtime

    return bootstrap_notebook_runtime(
        workspace_root=workspace_root,
        core_root=core_root,
        persistence_root=persistence_root,
        ml_root=ml_root,
        in_colab=in_colab,
        framework=framework,
        require_gpu=require_gpu,
    )
