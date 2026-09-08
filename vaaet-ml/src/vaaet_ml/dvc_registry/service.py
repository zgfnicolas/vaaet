# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Operaciones DVC del laboratorio con límites explícitos y manifest-first."""

from __future__ import annotations

import configparser
import importlib.util
import re
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from urllib.parse import urlparse

from vaaet.artifacts import (
    MODEL_REVISION_ALGORITHM,
    TrafficBundleManifest,
    validate_manifest,
)
from vaaet.exceptions import VAAETError

from vaaet_ml.exceptions import DvcRegistryConfigurationError, DvcRegistryOperationError

from .models import (
    CommandResult,
    CommandRunner,
    ModuleFinder,
    RegistryEntry,
    RegistryHealth,
    RegistryMaterializationPurpose,
    RegistryProvider,
    RemoteConfiguration,
)

REGISTRY_REMOTE = "vaaet-registry"
BUNDLE_RELATIVE_PATH = Path("vaaet-ml/artifacts/traffic-state")
POINTER_RELATIVE_PATH = Path("vaaet-ml/artifacts/traffic-state.dvc")
_REMOTE_SECTION = f'remote "{REGISTRY_REMOTE}"'
_PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class SubprocessCommandRunner:
    """Adaptador de `subprocess` que nunca invoca un shell."""

    def run(self, arguments: Sequence[str], *, cwd: Path) -> CommandResult:
        """Ejecuta el comando indicado y captura una salida que no se reexpone."""

        result = subprocess.run(
            list(arguments), cwd=cwd, capture_output=True, check=False, text=True
        )
        return CommandResult(result.returncode, result.stdout, result.stderr)


def _module_is_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


class DvcRegistryService:
    """Coordina DVC y Git sin convertirlos en una dependencia del core."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        runner: CommandRunner | None = None,
        module_finder: ModuleFinder = _module_is_available,
        manifest_validator: Callable[[str | Path], TrafficBundleManifest] = validate_manifest,
        historical_manifest_validator: Callable[[str | Path], TrafficBundleManifest] | None = None,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self._runner = runner or SubprocessCommandRunner()
        self._module_finder = module_finder
        self._manifest_validator = manifest_validator
        self._historical_manifest_validator = historical_manifest_validator or (
            (lambda directory: validate_manifest(directory, allow_historical_revision=True))
            if manifest_validator is validate_manifest
            else manifest_validator
        )

    @property
    def bundle_path(self) -> Path:
        """Directorio canónico del único bundle DVC del laboratorio."""

        return self.workspace_root / BUNDLE_RELATIVE_PATH

    @property
    def pointer_path(self) -> Path:
        """Metadata DVC que enlaza el bundle con una revisión Git."""

        return self.workspace_root / POINTER_RELATIVE_PATH

    def configure_remote(self, configuration: RemoteConfiguration) -> None:
        """Configura un proveedor sólo dentro del archivo local ignorado por Git."""

        self._ensure_workspace()
        self._validate_remote_configuration(configuration)
        local_config = self._read_config(self.workspace_root / ".dvc" / "config.local")
        configured = local_config.has_section(_REMOTE_SECTION)
        if configured and not configuration.replace:
            raise DvcRegistryConfigurationError(
                "El remoto local ya existe; usá --replace para cambiarlo conscientemente."
            )

        if configured:
            self._run(("dvc", "remote", "remove", "--local", REGISTRY_REMOTE), "configure")
        self._run(
            ("dvc", "remote", "add", "--local", "--default", REGISTRY_REMOTE, configuration.url),
            "configure",
        )

        for option, value in self._remote_options(configuration):
            self._run(
                ("dvc", "remote", "modify", "--local", REGISTRY_REMOTE, option, value),
                "configure",
            )

    def doctor(self) -> RegistryHealth:
        """Verifica configuración local y plugins sin autenticar ni acceder a red."""

        self._ensure_workspace()
        tracked_config = self._read_config(self.workspace_root / ".dvc" / "config")
        if tracked_config.has_section("core") or any(
            section.startswith("remote ") for section in tracked_config.sections()
        ):
            raise DvcRegistryConfigurationError(
                "La configuración versionada de DVC debe permanecer neutral."
            )

        local_config = self._read_config(self.workspace_root / ".dvc" / "config.local")
        if local_config.get("core", "remote", fallback=None) != REGISTRY_REMOTE:
            raise DvcRegistryConfigurationError("No se configuró el remoto local vaaet-registry.")
        if not local_config.has_option(_REMOTE_SECTION, "url"):
            raise DvcRegistryConfigurationError("El remoto local no declara una URL válida.")

        provider = self._provider_from_config(local_config)
        plugin = "dvc_gdrive" if provider is RegistryProvider.GOOGLE_DRIVE else "dvc_s3"
        if not self._module_finder(plugin):
            raise DvcRegistryConfigurationError(
                "Falta el plugin DVC del proveedor; instalá el extra declarado correspondiente."
            )
        tracked_local = self._try_run(("git", "ls-files", "--error-unmatch", ".dvc/config.local"))
        if tracked_local.returncode == 0:
            raise DvcRegistryConfigurationError(
                ".dvc/config.local no puede estar versionado por Git."
            )
        self._run(("dvc", "version"), "doctor")
        return RegistryHealth(provider=provider, remote_name=REGISTRY_REMOTE)

    def stage_bundle(self) -> str:
        """Valida el bundle completo antes de delegar su tracking a DVC."""

        self._ensure_workspace()
        if (self.bundle_path / ".gitkeep").exists():
            raise DvcRegistryOperationError(
                "El bundle todavía es un placeholder; exportá los cuatro archivos requeridos primero."
            )
        manifest = self._validate_bundle(self.bundle_path, "stage")
        self._run(("dvc", "add", BUNDLE_RELATIVE_PATH.as_posix()), "stage")
        return str(manifest["model_version"])

    def push_bundle(self) -> None:
        """Publica sólo metadata DVC ya consolidada en la revisión Git actual."""

        self.doctor()
        self._validate_bundle(self.bundle_path, "push")
        self._ensure_committed_pointer()
        pointer = POINTER_RELATIVE_PATH.as_posix()
        self._run(("dvc", "status", "-c", pointer), "push")
        self._run(("dvc", "push", "-r", REGISTRY_REMOTE, pointer), "push")

    def list_entries(
        self, *, limit: int = 20, model_version: str | None = None
    ) -> tuple[RegistryEntry, ...]:
        """Resume revisiones Git de bundles sin cambiar el bundle activo."""

        if limit < 1:
            raise DvcRegistryConfigurationError("El límite de revisiones debe ser positivo.")
        self.doctor()
        history = self._run(
            ("git", "log", "--format=%H", "--", POINTER_RELATIVE_PATH.as_posix()), "list"
        ).stdout.splitlines()
        revisions = tuple(revision.strip() for revision in history if revision.strip())[:limit]
        with tempfile.TemporaryDirectory(prefix="vaaet-registry-") as temporary_directory:
            temporary_root = Path(temporary_directory)
            entries = tuple(
                self._inspect_revision(revision, temporary_root / revision)
                for revision in revisions
            )
        return tuple(
            entry
            for entry in entries
            if model_version is None or entry.model_version == model_version
        )

    def get_bundle(
        self,
        revision: str,
        destination: Path,
        *,
        purpose: RegistryMaterializationPurpose | str = RegistryMaterializationPurpose.INFERENCE,
    ) -> str:
        """Materializa y valida una revisión en un directorio nuevo fuera del bundle activo."""

        self.doctor()
        if not revision.strip():
            raise DvcRegistryConfigurationError("La revisión Git no puede estar vacía.")
        target = destination.resolve()
        if target.exists():
            raise DvcRegistryOperationError("El directorio de salida ya existe; elegí uno nuevo.")
        if self._is_within(target, self.bundle_path):
            raise DvcRegistryConfigurationError(
                "La salida no puede ubicarse dentro del bundle activo."
            )
        if not target.parent.is_dir():
            raise DvcRegistryConfigurationError("El directorio padre de salida debe existir.")
        active_purpose = RegistryMaterializationPurpose(purpose)

        with tempfile.TemporaryDirectory(
            prefix=".vaaet-registry-", dir=target.parent
        ) as temporary_directory:
            temporary_bundle = Path(temporary_directory) / "bundle"
            self._get_revision(revision, temporary_bundle, "get")
            manifest = self._validate_bundle(
                temporary_bundle,
                "get",
                allow_historical=(
                    active_purpose is RegistryMaterializationPurpose.HISTORICAL_EVALUATION
                ),
            )
            temporary_bundle.replace(target)
        return str(manifest["model_version"])

    def _inspect_revision(self, revision: str, destination: Path) -> RegistryEntry:
        result = self._try_get_revision(revision, destination)
        if result is None:
            return RegistryEntry(
                revision, None, None, None, None, None, None, None, None, (), False, False
            )
        try:
            manifest = self._validate_bundle(destination, "list", allow_historical=True)
        except (OSError, ValueError, VAAETError):
            return RegistryEntry(
                revision, None, None, None, None, None, None, None, None, (), False, False
            )
        return self._entry_from_manifest(revision, manifest)

    def _get_revision(self, revision: str, destination: Path, stage: str) -> None:
        self._run(
            (
                "dvc",
                "get",
                ".",
                BUNDLE_RELATIVE_PATH.as_posix(),
                "--rev",
                revision,
                "--out",
                str(destination),
            ),
            stage,
        )

    def _try_get_revision(self, revision: str, destination: Path) -> CommandResult | None:
        result = self._try_run(
            (
                "dvc",
                "get",
                ".",
                BUNDLE_RELATIVE_PATH.as_posix(),
                "--rev",
                revision,
                "--out",
                str(destination),
            )
        )
        return result if result.returncode == 0 else None

    def _ensure_committed_pointer(self) -> None:
        pointer = POINTER_RELATIVE_PATH.as_posix()
        if self._try_run(("git", "ls-files", "--error-unmatch", pointer)).returncode != 0:
            raise DvcRegistryOperationError(
                "El puntero DVC debe estar versionado antes de publicar."
            )
        if self._try_run(("git", "diff", "--quiet", "HEAD", "--", pointer)).returncode != 0:
            raise DvcRegistryOperationError(
                "El puntero DVC debe estar consolidado en HEAD antes de publicar."
            )

    def _validate_bundle(
        self, directory: Path, stage: str, *, allow_historical: bool = False
    ) -> TrafficBundleManifest:
        try:
            validator = (
                self._historical_manifest_validator
                if allow_historical
                else self._manifest_validator
            )
            return validator(directory)
        except (OSError, ValueError, VAAETError) as error:
            raise DvcRegistryOperationError(
                f"El bundle no supera la validación manifest-first durante {stage}."
            ) from error

    def _entry_from_manifest(self, revision: str, manifest: Mapping[str, object]) -> RegistryEntry:
        lifecycle = self._mapping(manifest.get("training_lifecycle"))
        provenance = self._mapping(manifest.get("data_provenance"))
        input_lock = self._mapping(manifest.get("training_input_lock"))
        blockers = provenance.get("promotion_blockers", ())
        return RegistryEntry(
            revision=revision,
            model_version=self._text(manifest.get("model_version")),
            deployment_stage=self._text(lifecycle.get("deployment_stage")),
            production_eligible=self._boolean(lifecycle.get("production_eligible")),
            training_mode=self._text(lifecycle.get("training_mode")),
            input_policy=self._text(lifecycle.get("input_policy")),
            supervision=self._text(lifecycle.get("supervision")),
            provenance_origin=self._text(provenance.get("origin")),
            input_lock_id=self._text(input_lock.get("lock_id")),
            promotion_blockers=tuple(value for value in blockers if isinstance(value, str))
            if isinstance(blockers, (list, tuple))
            else (),
            historical_only=(manifest.get("model_revision_algorithm") != MODEL_REVISION_ALGORITHM),
            available=True,
        )

    def _ensure_workspace(self) -> None:
        if (
            not (self.workspace_root / ".dvc").is_dir()
            or not (self.workspace_root / "vaaet-ml" / "pyproject.toml").is_file()
        ):
            raise DvcRegistryConfigurationError("Se requiere la raíz del monorepo VAAET con DVC.")

    def _run(self, arguments: Sequence[str], stage: str) -> CommandResult:
        result = self._try_run(arguments)
        if result.returncode != 0:
            raise DvcRegistryOperationError(
                f"La operación {stage} no pudo completarse; ejecutá vaaet-registry doctor."
            )
        return result

    def _try_run(self, arguments: Sequence[str]) -> CommandResult:
        try:
            return self._runner.run(arguments, cwd=self.workspace_root)
        except OSError as error:
            raise DvcRegistryOperationError(
                "No se encontró el ejecutable requerido para operar el registro DVC."
            ) from error

    def _validate_remote_configuration(self, configuration: RemoteConfiguration) -> None:
        parsed = urlparse(configuration.url)
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise DvcRegistryConfigurationError(
                "La URL del remoto no puede incluir credenciales ni tokens."
            )
        self._validate_storage_url(configuration.provider, parsed.scheme, parsed.netloc)
        self._validate_profile(configuration.profile)
        self._validate_endpoint(configuration)
        self._validate_service_account(configuration)

    @staticmethod
    def _validate_storage_url(provider: RegistryProvider, scheme: str, host: str) -> None:
        if provider is RegistryProvider.GOOGLE_DRIVE and (scheme != "gdrive" or not host):
            raise DvcRegistryConfigurationError(
                "Google Drive requiere una URL gdrive://<folder-id>."
            )
        if provider is not RegistryProvider.GOOGLE_DRIVE and (scheme != "s3" or not host):
            raise DvcRegistryConfigurationError(
                "El almacenamiento S3 requiere s3://<bucket>/<prefijo>."
            )

    @staticmethod
    def _validate_profile(profile: str | None) -> None:
        if profile and not _PROFILE_PATTERN.fullmatch(profile):
            raise DvcRegistryConfigurationError(
                "El perfil sólo admite letras, números, punto, guion y guion bajo."
            )

    @staticmethod
    def _validate_endpoint(configuration: RemoteConfiguration) -> None:
        if configuration.provider is RegistryProvider.CLOUDFLARE_R2:
            if configuration.region:
                raise DvcRegistryConfigurationError(
                    "R2 usa la región fija auto; no indiques --region."
                )
            endpoint = configuration.endpoint_url
            endpoint_host = urlparse(endpoint or "").hostname or ""
            if urlparse(endpoint or "").scheme != "https" or not endpoint_host.endswith(
                ".r2.cloudflarestorage.com"
            ):
                raise DvcRegistryConfigurationError(
                    "R2 requiere un endpoint HTTPS oficial de Cloudflare."
                )
        elif configuration.endpoint_url:
            raise DvcRegistryConfigurationError(
                "Sólo R2 acepta un endpoint personalizado en esta interfaz."
            )

    def _validate_service_account(self, configuration: RemoteConfiguration) -> None:
        if configuration.service_account_file:
            if configuration.provider is not RegistryProvider.GOOGLE_DRIVE:
                raise DvcRegistryConfigurationError(
                    "La cuenta de servicio sólo corresponde a Google Drive."
                )
            service_file = configuration.service_account_file.resolve()
            if not service_file.is_file() or self._is_within(service_file, self.workspace_root):
                raise DvcRegistryConfigurationError(
                    "La clave de servicio debe existir fuera del workspace y permanecer privada."
                )

    def _remote_options(self, configuration: RemoteConfiguration) -> tuple[tuple[str, str], ...]:
        options: list[tuple[str, str]] = []
        if configuration.profile:
            options.append(("profile", configuration.profile))
        if configuration.region and configuration.provider is not RegistryProvider.CLOUDFLARE_R2:
            options.append(("region", configuration.region))
        if configuration.provider is RegistryProvider.CLOUDFLARE_R2:
            options.extend((("endpointurl", configuration.endpoint_url or ""), ("region", "auto")))
        if configuration.service_account_file:
            options.extend(
                (
                    ("gdrive_use_service_account", "true"),
                    (
                        "gdrive_service_account_json_file_path",
                        str(configuration.service_account_file.resolve()),
                    ),
                )
            )
        return tuple(options)

    @staticmethod
    def _read_config(path: Path) -> configparser.ConfigParser:
        parser = configparser.ConfigParser()
        if path.exists():
            parser.read(path, encoding="utf-8")
        return parser

    @staticmethod
    def _provider_from_config(config: configparser.ConfigParser) -> RegistryProvider:
        url = config.get(_REMOTE_SECTION, "url")
        if urlparse(url).scheme == "gdrive":
            return RegistryProvider.GOOGLE_DRIVE
        endpoint = config.get(_REMOTE_SECTION, "endpointurl", fallback="")
        return (
            RegistryProvider.CLOUDFLARE_R2
            if (urlparse(endpoint).hostname or "").endswith(".r2.cloudflarestorage.com")
            else RegistryProvider.AMAZON_S3
        )

    @staticmethod
    def _mapping(value: object) -> Mapping[str, object]:
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _text(value: object) -> str | None:
        return value if isinstance(value, str) else None

    @staticmethod
    def _boolean(value: object) -> bool | None:
        return value if isinstance(value, bool) else None

    @staticmethod
    def _is_within(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent.resolve())
        except ValueError:
            return False
        return True
