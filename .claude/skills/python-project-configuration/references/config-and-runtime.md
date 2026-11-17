# Configuración, imagen y ciclo de vida (modo aplicación)

Ejemplos para el backend de `vaaet-app`. La estructura de módulos y el
`lifespan` vienen de la skill `hexagonal-architecture-fastapi`; acá está la
parte de configuración, la imagen y el proceso.

## Contenido

1. Archivos
2. Configuración validada
3. Dockerfile
4. Apagado ordenado

## 1. Archivos

`.gitignore` del backend (el de la raíz ya excluye `.env` y `.venv/`; sumá lo
propio del componente):

```text
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/
dist/
build/
*.egg-info/
.env.*
!.env.example
.audit-requirements.txt
```

`.env.example` versionado, con valores ficticios y un comentario por variable:

```bash
# Obligatoria. development | test | production
VAAET_APP_ENVIRONMENT=development
# Opcional (local). Perfil de adaptadores: memory | local | production
VAAET_APP_PROFILE=memory
# Opcional (8000)
VAAET_APP_PORT=8000
# Obligatoria con profile=local/production. Identidad propia del servicio (ADR-0028)
VAAET_APP_DB_USER=vaaet_app_example
# Secreta. Nunca en Git: la inyecta la plataforma o el secret manager (vacía en el ejemplo)
VAAET_APP_DB_PASSWORD=
```

## 2. Configuración validada

```python
# vaaet_app/bootstrap/settings.py
from enum import Enum
from functools import cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Profile(str, Enum):
    MEMORY = "memory"
    LOCAL = "local"
    PRODUCTION = "production"


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VAAET_APP_",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,   # sin esto, ValidationError incluye input_value con el secreto
    )

    environment: Literal["development", "test", "production"]
    profile: Profile = Profile.LOCAL
    port: int = Field(default=8000, ge=1, le=65_535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    db_user: str | None = None
    db_password: SecretStr | None = None          # repr y logs muestran '**********'
    vision_license: Literal["agpl-public-demo", "enterprise"] | None = None   # ADR-0022

    @model_validator(mode="after")
    def check_profile(self) -> "AppSettings":
        if self.environment == "production" and self.profile is Profile.MEMORY:
            raise ValueError("the memory profile is not allowed in production")
        if self.profile is not Profile.MEMORY and (self.db_user is None or self.db_password is None):
            raise ValueError("database credentials are required outside the memory profile")
        return self


@cache
def get_settings() -> AppSettings:
    return AppSettings()      # falla al arrancar con los campos inválidos; hide_input_in_errors oculta los valores
```

```python
# tests/bootstrap/test_settings.py
import pytest
from pydantic import ValidationError

from vaaet_app.bootstrap.settings import AppSettings


def test_rejects_memory_profile_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAAET_APP_ENVIRONMENT", "production")
    monkeypatch.setenv("VAAET_APP_PROFILE", "memory")
    with pytest.raises(ValidationError, match="memory profile"):
        AppSettings()


def test_secret_is_not_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAAET_APP_ENVIRONMENT", "test")
    monkeypatch.setenv("VAAET_APP_PROFILE", "local")
    monkeypatch.setenv("VAAET_APP_DB_USER", "user")
    monkeypatch.setenv("VAAET_APP_DB_PASSWORD", "not-a-real-secret")
    assert "not-a-real-secret" not in repr(AppSettings())


def test_validation_error_does_not_leak_the_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAAET_APP_ENVIRONMENT", "production")
    monkeypatch.setenv("VAAET_APP_PROFILE", "memory")              # dispara el model_validator
    monkeypatch.setenv("VAAET_APP_DB_PASSWORD", "not-a-real-secret")
    with pytest.raises(ValidationError) as excinfo:
        AppSettings()
    assert "not-a-real-secret" not in str(excinfo.value)
```

- La conexión a PostgreSQL la arma `vaaet-persistence` desde sus propias
  settings (`load_database_settings`). El backend no construye DSN a mano: le
  pasa su perfil, cuando el ADR lo cree.
- `get_secret_value()` sólo en el punto de uso.
- En desarrollo, `uvicorn … --env-file .env` (con `python-dotenv` sólo en
  `requirements-dev.in`) o las variables exportadas en la shell; con uv,
  `uv run --env-file .env -- …`. Nunca `python-dotenv` en producción.

## 3. Dockerfile

El contexto es la **raíz del repo**, porque el backend instala las librerías
por ruta.

```dockerfile
# syntax=docker/dockerfile:1
# vaaet-app/Dockerfile (pip + pip-tools, por defecto) — docker build -f vaaet-app/Dockerfile .
FROM python:3.13-slim-bookworm@sha256:<digest> AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INPUT=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /repo
# 1. Terceros: sólo wheels y con hash, en una capa que se reutiliza mientras no cambie el lock.
COPY vaaet-app/requirements.txt vaaet-app/build-requirements.txt ./vaaet-app/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --require-hashes --no-deps --only-binary :all: \
      -r vaaet-app/requirements.txt -r vaaet-app/build-requirements.txt
# 2. Locales: sin hash ni dependencias; setuptools ya está fijado con hash, sin aislamiento de build.
COPY vaaet-core ./vaaet-core
COPY vaaet-persistence ./vaaet-persistence
COPY vaaet-app ./vaaet-app
RUN pip install --no-deps --no-build-isolation ./vaaet-core ./vaaet-persistence ./vaaet-app \
 && pip check \
 && python -m compileall -q /opt/venv \
 && pip uninstall -y setuptools pip                 # la imagen final no necesita instalar nada

FROM python:3.13-slim-bookworm@sha256:<digest> AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --uid 10001 --no-create-home app
COPY --from=build /opt/venv /opt/venv              # de root y sólo lectura para el proceso
USER app
EXPOSE 8000
CMD ["uvicorn", "vaaet_app.bootstrap.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "20", "--proxy-headers"]
```

- `build-requirements.txt` es otro lock de pip-compile (`build-requirements.in`
  con `setuptools>=77.0`), con hashes. Sin `--no-build-isolation`, pip
  descargaría setuptools para construir las librerías locales sin verificar su
  hash.
- La imagen final no tiene pip ni setuptools: el venv se copia ya armado.

Variante uv (alternativa, sólo en los casos de §0.1 del `SKILL.md`):

```dockerfile
FROM python:3.13-slim-bookworm@sha256:<digest> AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.<patch>@sha256:<digest> /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /repo
COPY vaaet-core ./vaaet-core
COPY vaaet-persistence ./vaaet-persistence
COPY vaaet-app/pyproject.toml vaaet-app/uv.lock ./vaaet-app/
WORKDIR /repo/vaaet-app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-local --no-build   # sólo wheels de terceros
COPY vaaet-app ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable
# La etapa runtime es igual, copiando /repo/vaaet-app/.venv en lugar de /opt/venv.
```

```text
# .dockerignore (raíz)
.git
**/.venv
**/.env*
**/__pycache__
**/.pytest_cache
**/.ruff_cache
vaaet-ml
.dvc
**/*.keras
**/*.joblib
**/*.pt
**/*.mp4
```

- La imagen web no lleva `vaaet-core[vision]`. La del worker es otro target,
  con su propio lock (o `uv sync --extra worker` con uv). No la distribuyas
  sin una vía de licencia de
  ADR-0022.
- Los pesos de YOLO y el bundle se montan o se descargan del registro en el
  arranque, verificados. Nunca entran a la imagen por `COPY` desde el repo.
- Secretos de build (credenciales de un índice) con `--mount=type=secret`,
  nunca con `ARG` ni `ENV`.
- Endurecimiento adicional: FS de sólo lectura, sin shell si es posible,
  escaneo y SBOM en el pipeline.

## 4. Apagado ordenado

- El servidor maneja SIGTERM (`uvicorn --timeout-graceful-shutdown`), y el
  `lifespan` libera los recursos (`database_engine` cierra el engine, ver la
  skill hexagonal). El `CMD` va en forma exec para que la señal llegue al
  proceso.
- El timeout es menor que el `terminationGracePeriodSeconds` del
  orquestador, o que su equivalente.
- Worker propio:

```python
# vaaet_app/bootstrap/worker.py
import asyncio
import signal

SHUTDOWN_TIMEOUT_S = 20


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    async with build_worker_runtime(get_settings()) as runtime:   # cierra recursos aunque haya error
        consumer = runtime.consumer
        task = asyncio.create_task(consumer.run())
        await stop.wait()
        consumer.stop_accepting()                                  # termina el trabajo en curso
        try:
            await asyncio.wait_for(task, timeout=SHUTDOWN_TIMEOUT_S)
        except TimeoutError:
            task.cancel()
            raise


if __name__ == "__main__":
    asyncio.run(main())
```

- Desde Python 3.11, `asyncio.wait_for` lanza el `TimeoutError` builtin; en
  3.10 lanza `asyncio.TimeoutError`, que es otra clase: capturá ese.
  `asyncio.timeout` y `TaskGroup` también requieren 3.11.
- Un análisis de video es síncrono y largo. El worker termina el trabajo en
  curso dentro del timeout, o lo deja reintentable según la tabla de errores
  de la skill hexagonal, nunca a mitad de una escritura.
- Una excepción no manejada en el proceso principal sale con código distinto
  de 0, y el orquestador reinicia. Sin `except Exception: pass` globales.
