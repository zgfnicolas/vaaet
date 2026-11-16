# Código de referencia: FastAPI

Ejemplos del módulo `analysis` de `vaaet-app`. Adaptá los nombres al módulo real.
El código es ilustrativo: verificá firmas contra el repo antes de copiarlo.

## Contenido

0. Errores y caso de uso del núcleo
1. Adaptadores driving: HTTP, worker y CLI
2. Adaptadores driven, ACL y decoradores
3. Configurador, perfiles y `create_app()`
4. Traductores de errores por protocolo

## 0. Errores y caso de uso del núcleo

```python
# application/errors.py — sin dependencias externas
class AppError(Exception):
    """Base de los errores que el núcleo expone a los adaptadores."""

class InvalidInputError(AppError): ...
class NotFoundError(AppError): ...
class ConflictError(AppError): ...
class ForbiddenError(AppError): ...
class UnusableBundleError(AppError): ...
class ConfigurationError(AppError):
    """Configuración o contrato inválidos: reintentar no lo arregla."""

class DependencyError(AppError):
    """Una dependencia no respondió antes de escribir; reintentar puede funcionar."""

class AuditPendingError(AppError):
    """Datos confirmados con auditoría pendiente; se cierra con reconcile_* (ADR-0033)."""

    def __init__(self, message: str, *, run_id: str) -> None:
        super().__init__(message)
        self.run_id = run_id

class WriteOutcomeUnknownError(AppError):
    """Escritura sin confirmar: la verifica una persona, nunca se reintenta (ADR-0028)."""

    def __init__(self, message: str, *, run_id: str | None, operation: str | None) -> None:
        super().__init__(message)
        self.run_id = run_id
        self.operation = operation
```

```python
# application/submit_video_analysis.py
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class SubmitVideoAnalysisService:
    bundles: BundleCatalog
    store: AnalysisStore
    queue: AnalysisJobQueue
    new_id: IdGenerator
    clock: Clock

    async def __call__(self, cmd: SubmitVideoAnalysisCommand, /) -> AnalysisJobId:
        bundle = await self.bundles.resolve(cmd.model_revision)   # sólo manifiesto; UnusableBundleError si no es servible
        job = AnalysisJob.submitted(AnalysisJobId(self.new_id()), cmd.video, bundle.revision,
                                    cmd.requested_by, submitted_at=self.clock())
        await self.store.create_job(job)
        await self.queue.enqueue(job.id)
        return job.id
```

El caso de uso es una dataclass con sus puertos; no conoce FastAPI ni el
proveedor de la cola. `SubmitVideoAnalysisService` cumple el `Protocol`
`SubmitVideoAnalysis` estructuralmente, sin heredarlo.

## 1. Adaptadores driving

### 1.1 HTTP

```python
# adapters/driving/http/router.py
from typing import Annotated
from fastapi import APIRouter, Depends, Request, UploadFile, status
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/analyses", tags=["analyses"])

class AnalysisAccepted(BaseModel):
    job_id: str

def analysis_module(request: Request) -> AnalysisWebModule:
    return request.app.state.analysis          # lo construyó el configurador en el lifespan

@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=AnalysisAccepted)
async def submit_analysis(
    video: UploadFile,
    model_revision: str,
    module: Annotated[AnalysisWebModule, Depends(analysis_module)],
    actor: Annotated[Actor, Depends(current_actor)],
) -> AnalysisAccepted:
    stored = await module.video_storage.put(video.file, filename=video.filename)
    job_id = await module.submit_video_analysis(
        SubmitVideoAnalysisCommand(video=stored, model_revision=ModelRevision.parse(model_revision),
                                   requested_by=actor.id)
    )
    return AnalysisAccepted(job_id=str(job_id))     # el handler global traduce los errores (§4)
```

- `Depends` sólo lee de `app.state`; no construye adaptadores ni abre conexiones.
- `ModelRevision.parse` es del núcleo y lanza `InvalidInputError`; el router no
  valida reglas de negocio.
- Guardar el archivo es responsabilidad del adaptador: el núcleo recibe un
  `StoredVideoRef`, no un `UploadFile`.

### 1.2 Worker

```python
# adapters/driving/worker/analysis_consumer.py
async def handle_job_message(message: JobMessage, run_job: RunAnalysisJob) -> Ack:
    try:
        await run_job(AnalysisJobId(message.job_id))
    except (InvalidInputError, UnusableBundleError, ForbiddenError, ConfigurationError):
        return Ack.REJECT          # nunca va a funcionar: a la DLQ con alerta
    except ConflictError:
        return Ack.REJECT          # contenido distinto del almacenado: lo revisa una persona
    except NotFoundError:
        return Ack.ACK             # trabajo inexistente: nada que hacer
    except (WriteOutcomeUnknownError, AuditPendingError):
        return Ack.ACK             # RunAnalysisJob ya guardó el estado y el run_id: nunca se reintenta
    except DependencyError:
        return Ack.RETRY           # falló antes de escribir: backoff y reintento limitado
    return Ack.ACK
```

El worker es un proceso propio: arranca con su configurador (perfil con el
adaptador de visión) y ejecuta `TrafficAnalyzer.analyze` de forma síncrona, en
línea con el pipeline Pipe-and-Filter. Un error inesperado se propaga para que
el runtime de la cola lo reintente con límite y lo mande a la DLQ. Eso es seguro sólo
porque `RunAnalysisJob` marca el trabajo como «escribiendo» antes de persistir: si
un reintento encuentra esa marca, no vuelve a escribir y deja el trabajo para
verificar.

### 1.3 CLI

```python
# adapters/driving/cli/commands.py
import asyncio
import typer

app = typer.Typer()

@app.command()
def reprocess(job_id: str) -> None:
    """Reejecuta un análisis existente."""
    asyncio.run(_reprocess(job_id))

async def _reprocess(job_id: str) -> None:
    async with build_worker_runtime(load_settings()) as runtime:  # el configurador del worker
        try:
            await runtime.run_analysis_job(AnalysisJobId(job_id))
        except AppError as exc:
            raise typer.Exit(code=exit_code_for(exc)) from exc  # §4
```

## 2. Adaptadores driven, ACL y decoradores

### 2.1 Persistencia: síncrono detrás de un puerto async

```python
# adapters/driven/persistence/analysis_store.py
from dataclasses import dataclass
import anyio
from sqlalchemy.engine import Engine
from vaaet_persistence import (
    DatabaseNotConfiguredError, DatabaseOperationError, DatabaseSchemaVersionError,
    PersistenceConflictError, PersistenceValidationError, PipelineAuditIncompleteError,
    persist_classified_telemetry, persist_raw_telemetry,
)

APP_NAME = "vaaet-app-worker"

@dataclass(frozen=True, slots=True)
class PersistenceAnalysisStore:
    engine: Engine
    app_version: str

    async def save_outcome(self, job_id: AnalysisJobId, outcome: AnalysisOutcome, /) -> None:
        raw, classified = outcome_to_frames(job_id, outcome)       # ACL: núcleo → DataFrames
        try:
            await anyio.to_thread.run_sync(self._persist, raw, classified, outcome)
        except PersistenceConflictError as exc:
            raise ConflictError("stored analysis differs from this outcome") from exc
        except PipelineAuditIncompleteError as exc:
            # Los datos quedaron confirmados: el run_id permite reconciliar sin reinsertar.
            raise AuditPendingError("persistence audit pending", run_id=exc.run_id) from exc
        except DatabaseOperationError as exc:
            # Sin confirmar: ADR-0028 prohíbe repetirla. Sin el mensaje del driver.
            raise WriteOutcomeUnknownError("telemetry write not confirmed",
                                           run_id=exc.run_id, operation=exc.operation) from exc
        except (PersistenceValidationError, DatabaseSchemaVersionError,
                DatabaseNotConfiguredError, ValueError) as exc:
            raise ConfigurationError("telemetry rejected by the persistence contract") from exc

    def _persist(self, raw, classified, outcome: AnalysisOutcome) -> None:
        # Si la raw termina con auditoría pendiente, la excepción corta acá y la
        # clasificada queda sin escribir: el trabajo lo registra así.
        persist_raw_telemetry(raw, engine=self.engine, application_name=APP_NAME,
                              application_version=self.app_version)
        persist_classified_telemetry(classified, engine=self.engine, model_version=outcome.model_version,
                                     model_revision=str(outcome.model_revision), application_name=APP_NAME,
                                     application_version=self.app_version)
```

- `vaaet-persistence` es síncrono. Llamarlo directo desde un endpoint `async`
  bloquea el event loop para todas las requests.
- Los DataFrames nacen y mueren dentro del adaptador. `outcome_to_frames`
  reconstruye las 19 `FEATURE_COLS`, `continuity_id` y las versiones de schema
  desde el payload opaco del `AnalysisOutcome`, sin redondear.
- El `DependencyError` de persistencia sale sólo de la sonda previa: el worker
  abre el engine con `database_engine`, que falla antes de escribir.

### 2.2 Visión y bundle: la ACL más gruesa

```python
# adapters/driven/vision/traffic_analyzer.py — sólo se instala en el worker
from vaaet.inference import TrafficStateEngine
from vaaet.vision.analysis import analyze_video
from vaaet.exceptions import VideoOpenError, VideoValidationError

@dataclass(frozen=True, slots=True)
class VaaetCoreTrafficAnalyzer:
    bundles: LoadedBundleRegistry           # mapea BundleHandle → LoadedTrafficBundle ya validado

    def analyze(self, video: LocalVideo, bundle: BundleHandle, /) -> AnalysisOutcome:
        engine = TrafficStateEngine(self.bundles.loaded(bundle))
        try:
            # Sin output_path, analyze_video escribiría el video anotado junto al original.
            result = analyze_video(video.path, video.annotated_target,
                                   prediction_provider=engine.predict_latest)
        except VideoValidationError as exc:
            raise InvalidInputError("video rejected") from exc
        except VideoOpenError as exc:
            raise DependencyError("video could not be opened") from exc
        return outcome_from_result(result, engine.classify(result.telemetry), bundle.revision)
```

`video` es un `LocalVideo` que entrega `VideoStorage.open_local`: su nombre
conserva el patrón contractual (de ahí salen `clip_id` y la hora de captura) y
`annotated_target` es una ruta que el mismo storage publica después, para que el
`AnalysisOutcome` guarde la referencia al video anotado (ADR-0021). La copia
local de trabajo se borra al terminar; los videos nunca van a Git ni a logs
(RN-24). `LoadedBundleRegistry` es el `BundleLoader` del worker: llama a
`load_traffic_bundle()` una vez por revisión. `outcome_from_result` convierte los DataFrames de `vaaet-core` en
`AnalysisOutcome` con `MinuteState` del núcleo, y verifica que ningún estado
automático sea `ACCIDENT` (RN-02) antes de devolverlo.

### 2.3 Adaptador en memoria con comportamiento real

```python
# adapters/driven/memory/analysis_store.py
@dataclass(slots=True)
class InMemoryAnalysisStore:
    jobs: dict[AnalysisJobId, AnalysisJob] = field(default_factory=dict)
    outcomes: dict[AnalysisJobId, AnalysisOutcome] = field(default_factory=dict)

    async def create_job(self, job: AnalysisJob, /) -> None:
        if job.id in self.jobs:
            raise ConflictError("job already exists")          # igual que la clave única real
        self.jobs[job.id] = job

    async def save_outcome(self, job_id: AnalysisJobId, outcome: AnalysisOutcome, /) -> None:
        if job_id in self.outcomes and self.outcomes[job_id] != outcome:
            raise ConflictError("analysis already stored")     # idempotente con contenido igual
        self.outcomes[job_id] = outcome

    async def get(self, job_id: AnalysisJobId, /) -> AnalysisJob | None:
        return self.jobs.get(job_id)
```

### 2.4 Decoradores de puerto

```python
# adapters/driven/decorators.py
@dataclass(frozen=True, slots=True)
class RetryingVideoStorage:
    inner: VideoStorage
    attempts: int = 3

    async def put(self, stream: BinaryIO, /, *, filename: str | None) -> StoredVideoRef:
        for attempt in range(1, self.attempts + 1):
            try:
                return await self.inner.put(stream, filename=filename)
            except DependencyError:
                if attempt == self.attempts:
                    raise
                stream.seek(0)
                await anyio.sleep(0.1 * 2**attempt)
        raise AssertionError("unreachable")

P = ParamSpec("P")
R = TypeVar("R")

def timed(name: str, fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        started = time.perf_counter()
        try:
            return await fn(*args, **kwargs)
        finally:
            metrics.observe(name, time.perf_counter() - started)
    return wrapper
```

El decorador implementa el mismo puerto: el caso de uso no sabe si recibe el
adaptador original o uno decorado.

## 3. Configurador, perfiles y `create_app()`

```python
# modules/analysis/configuration.py — el único lugar que nombra adaptadores concretos
from enum import Enum

class Profile(str, Enum):                  # StrEnum recién existe desde Python 3.11
    MEMORY = "memory"
    LOCAL = "local"
    PRODUCTION = "production"

@dataclass(frozen=True)
class AnalysisWebModule:
    submit_video_analysis: SubmitVideoAnalysis
    get_analysis: GetAnalysis
    video_storage: VideoStorage            # lo usa el router para guardar el archivo

def _shared_adapters(settings: AppSettings, infra: Infra) -> tuple[AnalysisStore, AnalysisJobQueue, VideoStorage]:
    if settings.profile is Profile.MEMORY:
        return InMemoryAnalysisStore(), InMemoryJobQueue(), InMemoryVideoStorage()
    return (
        PersistenceAnalysisStore(infra.engine, settings.app_version),
        build_job_queue(settings.queue),                            # tecnología del ADR
        RetryingVideoStorage(build_video_storage(settings.storage)),
    )

def build_web_analysis_module(settings: AppSettings, infra: Infra) -> AnalysisWebModule:
    store, queue, storage = _shared_adapters(settings, infra)
    bundles = VaaetBundleCatalog(settings.bundles_dir, allow_pilot=settings.allow_pilot_bundles)
    submit = SubmitVideoAnalysisService(bundles, store, queue, new_id=new_job_id, clock=utc_now)
    return AnalysisWebModule(
        submit_video_analysis=timed("analysis.submit", submit),
        get_analysis=GetAnalysisService(store),
        video_storage=storage,
    )
```

```python
# modules/analysis/worker_configuration.py — sólo lo importa bootstrap/worker.py
def build_worker_analysis_module(settings: AppSettings, infra: Infra) -> RunAnalysisJob:
    require_vision_license(settings)                                # ADR-0022, antes de cargar YOLO
    from .adapters.driven.vision import LoadedBundleRegistry, VaaetCoreTrafficAnalyzer

    store, _queue, storage = _shared_adapters(settings, infra)
    loader = LoadedBundleRegistry(settings.bundles_dir, allow_pilot=settings.allow_pilot_bundles)
    return RunAnalysisJobService(store, storage, VaaetCoreTrafficAnalyzer(loader), clock=utc_now)
```

`new_job_id` envuelve `uuid4` o una implementación de UUIDv7: `uuid.uuid7` recién
está en la biblioteca estándar desde Python 3.14. En el perfil `memory`, el
worker usa un `TrafficAnalyzer` en memoria y no llama a
`build_worker_analysis_module`.

```python
# bootstrap/settings.py — validación al arranque, fuera del núcleo
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VAAET_APP_")
    profile: Profile = Profile.LOCAL
    environment: str = "development"
    vision_license: str | None = None      # "agpl-public-demo" | "enterprise" (ADR-0022)

    @model_validator(mode="after")
    def reject_unsafe_production(self) -> "AppSettings":
        if self.environment == "production" and self.profile is Profile.MEMORY:
            raise ValueError("the memory profile is not allowed in production")
        return self
```

```python
# bootstrap/app.py
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextlib import AsyncExitStack
from fastapi import FastAPI

def create_app(settings: AppSettings | None = None) -> FastAPI:
    settings = settings or AppSettings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            # Infra.start entra a database_engine(settings): sondea al abrir y
            # llama a dispose_engine al cerrar el stack.
            infra = await Infra.start(settings, stack)
            app.state.analysis = build_web_analysis_module(settings, infra)
            app.state.review = build_review_module(settings, infra)
            yield

    app = FastAPI(title="VAAET API", version="1", lifespan=lifespan)
    app.include_router(analysis_router)
    install_error_handlers(app)                              # §4
    return app
```

- La API web no habilita el adaptador de visión: `build_web_analysis_module`
  no importa `adapters/driven/vision/`. El worker tiene su propio
  `bootstrap/worker.py` con `build_worker_analysis_module`, que verifica
  `vision_license` antes de construir `VaaetCoreTrafficAnalyzer`.
- Los tests llaman a `create_app(AppSettings(profile=Profile.MEMORY))`: la misma
  app, con otros adaptadores.

## 4. Traductores de errores por protocolo

```python
# adapters/driving/http/errors.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

HTTP_STATUS: dict[type[AppError], int] = {
    InvalidInputError: 422, UnusableBundleError: 422, NotFoundError: 404,
    ConflictError: 409, AuditPendingError: 409, ForbiddenError: 403, DependencyError: 503,
    WriteOutcomeUnknownError: 503, ConfigurationError: 500,
}

def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        status = next((code for kind, code in HTTP_STATUS.items() if isinstance(exc, kind)), 500)
        retryable = isinstance(exc, DependencyError)             # nunca invitar a repetir una escritura dudosa
        headers = {"Retry-After": "30"} if retryable else None
        body = {"error": type(exc).__name__, "message": str(exc) if status < 500 else "internal error"}
        return JSONResponse(status_code=status, content=body, headers=headers)
```

```python
# adapters/driving/cli/errors.py
EXIT_CODES: dict[type[AppError], int] = {
    InvalidInputError: 2, UnusableBundleError: 2, NotFoundError: 1, ConflictError: 1,
    ForbiddenError: 77, DependencyError: 75, AuditPendingError: 75, WriteOutcomeUnknownError: 75,
    ConfigurationError: 78,
}

def exit_code_for(exc: AppError) -> int:
    return next((code for kind, code in EXIT_CODES.items() if isinstance(exc, kind)), 70)
```

Un traductor por protocolo, en un solo lugar. Los mensajes de los errores del
núcleo se escriben pensando en que pueden llegar al cliente: sin DSN, rutas
privadas ni PII.
