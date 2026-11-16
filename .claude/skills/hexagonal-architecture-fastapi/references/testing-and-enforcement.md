# Tests y enforcement

Ejemplos para el módulo `analysis` de `vaaet-app`. Las pruebas usan pytest y
`anyio`; ajustá los fixtures a lo que fije el ADR del componente.

## Contenido

1. Aceptación por el puerto driving
2. Contrato por puerto driven
3. Contratos de import-linter
4. Checklist de revisión de PR

## 1. Aceptación por el puerto driving

La aplicación entera, sin HTTP, base, GPU ni red. El configurador con perfil
`memory` arma los mismos casos de uso que en producción, con adaptadores en
memoria, un reloj fijo e IDs deterministas.

```python
# tests/acceptance/conftest.py
import pytest

FIXED_NOW = datetime(2026, 11, 12, 13, 0, tzinfo=UTC)

@pytest.fixture
def analysis() -> AcceptanceHarness:
    settings = AppSettings(profile=Profile.MEMORY, environment="test")
    infra = Infra.for_tests(clock=lambda: FIXED_NOW, ids=sequential_ids("job"))
    # Une el módulo web y el RunAnalysisJob en memoria sobre los mismos adaptadores.
    return build_acceptance_harness(settings, infra)
```

```python
# tests/acceptance/test_submit_video_analysis.py
pytestmark = pytest.mark.anyio

async def test_queues_an_analysis_with_a_servable_bundle(analysis: AcceptanceHarness) -> None:
    video = await analysis.video_storage.put(io.BytesIO(b"clip"), filename="clip.mp4")

    job_id = await analysis.submit_video_analysis(
        SubmitVideoAnalysisCommand(video=video, model_revision=SERVABLE_REVISION, requested_by=ActorId("ana"))
    )

    view = await analysis.get_analysis(job_id, Actor.reviewer("ana"))
    assert view.status is JobStatus.QUEUED
    assert view.submitted_at == FIXED_NOW

async def test_rejects_an_unservable_bundle_before_queueing(analysis: AcceptanceHarness) -> None:
    video = await analysis.video_storage.put(io.BytesIO(b"clip"), filename="clip.mp4")

    with pytest.raises(UnusableBundleError):
        await analysis.submit_video_analysis(
            SubmitVideoAnalysisCommand(video=video, model_revision=PILOT_REVISION, requested_by=ActorId("ana"))
        )

async def test_automatic_analysis_never_produces_accident(analysis: AcceptanceHarness) -> None:
    job_id = await submitted_job(analysis)
    await analysis.run_analysis_job(job_id)        # el analizador en memoria devuelve minutos fijos

    view = await analysis.get_analysis(job_id, Actor.reviewer("ana"))
    assert all(minute.state in AUTOMATIC_STATES for minute in view.minutes)
```

- En el perfil `memory`, `TrafficAnalyzer` es un fake que devuelve minutos
  predefinidos. El pipeline real se prueba en `vaaet-core`, no acá.
- Parametrizá el fixture con un perfil `postgres` marcado `integration` para
  correr la misma suite contra PostgreSQL 17 en el CI de integración.

## 2. Contrato por puerto driven

Una suite por puerto, escrita una vez y ejecutada contra cada adaptador. Es lo
que mantiene honesto al fake: si el adaptador en memoria acepta algo que
PostgreSQL rechaza, el contrato falla.

```python
# testing/contracts/analysis_store_contract.py
class AnalysisStoreContract:
    """Comportamiento que todo AnalysisStore debe cumplir."""

    @pytest.fixture
    def store(self) -> AnalysisStore:
        raise NotImplementedError

    async def test_create_then_get_returns_the_same_job(self, store: AnalysisStore) -> None:
        job = make_job()
        await store.create_job(job)
        assert await store.get(job.id) == job

    async def test_create_rejects_a_repeated_id(self, store: AnalysisStore) -> None:
        job = make_job()
        await store.create_job(job)
        with pytest.raises(ConflictError):
            await store.create_job(job)

    # Idempotente no significa «se puede reintentar»: el adaptador real distingue
    # ConflictError (ya escrito) de WriteOutcomeUnknownError (reconciliar).
    async def test_save_outcome_is_idempotent_for_equal_content(self, store: AnalysisStore) -> None:
        job = await created_job(store)
        outcome = make_outcome()
        await store.save_outcome(job.id, outcome)
        await store.save_outcome(job.id, outcome)       # no lanza

    async def test_save_outcome_with_different_content_conflicts(self, store: AnalysisStore) -> None:
        job = await created_job(store)
        await store.save_outcome(job.id, make_outcome())
        with pytest.raises(ConflictError):              # PersistenceConflictError en el real
            await store.save_outcome(job.id, make_outcome(congested_minutes=1))

    async def test_get_of_a_missing_id_returns_none(self, store: AnalysisStore) -> None:
        assert await store.get(AnalysisJobId("missing")) is None
```

```python
# tests/contracts/test_analysis_store.py
pytestmark = pytest.mark.anyio

class TestInMemoryAnalysisStore(AnalysisStoreContract):
    @pytest.fixture
    def store(self) -> AnalysisStore:
        return InMemoryAnalysisStore()

@pytest.mark.integration
class TestPersistenceAnalysisStore(AnalysisStoreContract):
    @pytest.fixture
    def store(self, migrated_engine: Engine) -> AnalysisStore:
        return PersistenceAnalysisStore(migrated_engine, app_version="test")
```

- `migrated_engine` apunta a una base PostgreSQL 17 desechable con las
  migraciones de `vaaet-persistence` aplicadas por Alembic, nunca por el test.
  En la máquina local usá la skill `pg-integration`.
- El contrato de `TrafficAnalyzer` contra `VaaetCoreTrafficAnalyzer` necesita
  un clip corto y un bundle de prueba: corre sólo donde haya GPU y licencia, y
  se valida manualmente. No lo presentes como hecho sin ese entorno.
- Sumá el test de paridad de estados de
  [vaaet-hexagon.md](vaaet-hexagon.md) §5 a esta misma carpeta.

### Adaptador HTTP

```python
# tests/http/test_analyses_api.py
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.anyio

@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app(AppSettings(profile=Profile.MEMORY, environment="test"))
    async with LifespanManager(app):                          # asgi-lifespan
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http

async def test_unservable_bundle_returns_422(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/analyses",
        params={"model_revision": PILOT_REVISION_HEX},
        files={"video": ("clip.mp4", b"clip", "video/mp4")},
        headers=auth_headers("ana"),
    )
    assert response.status_code == 422
    assert response.json()["error"] == "UnusableBundleError"
```

Probá acá lo que es del protocolo: validación de forma, autenticación,
códigos de estado y `Retry-After`. Las reglas de negocio ya están cubiertas por
la aceptación.

## 3. Contratos de import-linter

```ini
# vaaet-app/.importlinter
[importlinter]
root_packages =
    vaaet_app
include_external_packages = True

[importlinter:contract:core-pure]
name = El núcleo no conoce adaptadores ni tecnología
type = forbidden
source_modules =
    vaaet_app.modules.analysis.domain
    vaaet_app.modules.analysis.application
    vaaet_app.modules.review.domain
    vaaet_app.modules.review.application
forbidden_modules =
    vaaet_app.modules.analysis.adapters
    vaaet_app.modules.review.adapters
    vaaet_app.bootstrap
    fastapi
    starlette
    pydantic
    pydantic_settings
    sqlalchemy
    pandas
    typer
    httpx
    boto3
    vaaet
    vaaet_persistence

[importlinter:contract:adapters-independent]
name = Los adaptadores driving y driven no se importan entre sí
type = independence
modules =
    vaaet_app.modules.analysis.adapters.driving
    vaaet_app.modules.analysis.adapters.driven

[importlinter:contract:no-lab]
name = El backend nunca importa el laboratorio
type = forbidden
source_modules =
    vaaet_app
forbidden_modules =
    vaaet_ml

[importlinter:contract:web-without-vision]
name = El proceso web no carga el pipeline de visión ni TensorFlow
type = forbidden
source_modules =
    vaaet_app.bootstrap.app
    vaaet_app.modules.analysis.configuration
    vaaet_app.modules.analysis.adapters.driving.http
forbidden_modules =
    vaaet_app.modules.analysis.adapters.driven.vision
    vaaet_app.modules.analysis.worker_configuration
    ultralytics
    cv2
    tensorflow
```

import-linter sólo admite paquetes externos de primer nivel en
`forbidden_modules`: `vaaet.vision` no es válido ahí. Por eso el contrato prohíbe
el paquete interno que envuelve la visión (`adapters/driven/vision/`, el único
que importa `vaaet.vision` y `vaaet.inference`), el configurador del worker y
las bibliotecas pesadas.

El contrato no ve lo que pasa dentro de los paquetes externos: para grimp,
`vaaet` y `vaaet_persistence` son hojas del grafo, así que un import transitivo
de TensorFlow desde ellos no aparece. Completalo con un test en subproceso, como
`vaaet-core/tests/repository/test_core_isolation.py`:

```python
# tests/bootstrap/test_web_process_isolation.py
import subprocess
import sys

def test_create_app_does_not_load_heavy_vision_modules() -> None:
    probe = (
        "import sys\n"
        "from vaaet_app.bootstrap.app import create_app\n"
        "from vaaet_app.bootstrap.settings import AppSettings, Profile\n"
        "create_app(AppSettings(profile=Profile.MEMORY, environment='test'))\n"
        "print(sorted({'tensorflow', 'cv2', 'ultralytics'} & set(sys.modules)))\n"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"
```

- `vaaet` completo está prohibido en el núcleo: el núcleo define sus tipos y la
  paridad se verifica con un test de contrato. Si una decisión aprobada permite
  importar un submódulo liviano, documentala en el ADR y ajustá el contrato.
- Agregá `lint-imports` como paso del job de `vaaet-app` en
  `.github/workflows/ci.yml`. Un cambio de CI se revisa como cualquier otro
  cambio de la raíz.

## 4. Checklist de revisión de PR

Lo que import-linter no detecta:

- reglas de negocio en routers, consumidores o comandos del CLI;
- puertos con forma de la tecnología o con nombres del proveedor;
- `Depends`, `Request` o `BackgroundTasks` en casos de uso;
- un adaptador que traga una excepción o la deja subir sin traducir;
- mensajes de error con DSN, rutas privadas o PII;
- llamadas síncronas a `vaaet-persistence` desde código `async` sin threadpool;
- fakes sin test de contrato, o mocks por método donde correspondía un fake;
- el perfil `memory` alcanzable con la configuración de producción;
- `Accident` producido por cualquier camino que no sea una decisión humana;
- un reintento automático después de que una escritura empezó (ADR-0028);
- `load_traffic_bundle()` alcanzable desde el proceso web;
- videos guardados con nombre aleatorio, o un video anotado escrito junto al
  original en lugar de una ubicación de `VideoStorage`;
- `PersistenceConflictError` tratado como «ya procesado».
