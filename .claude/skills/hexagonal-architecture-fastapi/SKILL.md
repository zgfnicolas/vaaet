---
name: hexagonal-architecture-fastapi
description: Diseña, revisa o refactoriza backends Python con FastAPI usando Arquitectura Hexagonal (Ports & Adapters), adaptada al futuro backend de VAAET (vaaet-app). Cubre cuándo conviene y cuándo no, puertos driving y driven, varios adaptadores por puerto (HTTP, worker de cola, CLI, scheduler, tests), configurador o composition root con perfiles en el lifespan de FastAPI, inyección sin contaminar el núcleo, decoradores de puerto (métricas, retries, caché), traducción de errores en ambos bordes, ACL, comunicación entre módulos, tests de aceptación y de contrato, e import-linter en CI. Usala siempre que se diseñe o revise la API, los workers o los módulos de vaaet-app; cuando se pregunte cómo exponer vaaet-core o vaaet-persistence detrás de FastAPI; cuando un endpoint, un consumidor o un CLI mezcle lógica de negocio con SQLAlchemy, Pydantic o un SDK; o cuando aparezcan Depends, lifespan, composition root, inyección de dependencias, puertos, adaptadores o «arquitectura limpia» en un backend Python, aunque no se nombre «hexagonal». No la uses para reestructurar vaaet-core, vaaet-persistence ni vaaet-ml: esos componentes quedan como están, detrás de adaptadores, y cambiarlos es una refactorización que requiere plan y ADR.
---

# Arquitectura Hexagonal con FastAPI (VAAET)

Baseline: Python 3.10+ (el rango del monorepo; `typing.Protocol`, `TypeAlias`) · FastAPI ·
Pydantic v2 · Typer · AnyIO · pytest · import-linter. Si el ADR de `vaaet-app`
fija otra versión, prevalece el ADR.

Principio rector: la aplicación se maneja igual desde cualquier actor (la web, un
worker, un CLI, un test) y usa cualquier tecnología del otro lado sin cambiar el
núcleo. Los **puertos** conectan ambos mundos, los **adaptadores** traducen y el
**configurador** elige qué adaptador va en cada puerto.

Esta skill define la frontera del sistema. No reemplaza las fuentes de VAAET:
`AGENTS.md`, las [reglas de negocio](../../../docs/product/business-rules.md) y
los ADRs (en especial 0021, 0022 y 0028) prevalecen ante cualquier contradicción.

## Antes de escribir código en `vaaet-app/`

`vaaet-app/` está reservado: no admite código, dependencias ni frameworks sin
alcance aprobado y contrato HTTP versionado (`AGENTS.md`). Por eso:

1. Si el pedido implica crear o modificar `vaaet-app/`, proponé primero el diseño
   (el mapa del hexágono de §0.2) y un plan gobernado con la skill `governed-plan`,
   y esperá la aprobación.
2. El diseño necesita un ADR para las decisiones que esta skill no fija. ADR-0021
   todavía no habilita API ni framework, así que el primero tiene que decidir:
   - FastAPI, el estilo hexagonal y las dependencias nuevas (Pydantic,
     pydantic-settings, Typer, AnyIO, import-linter), que `AGENTS.md` pone en
     «Ask»;
   - la versión de Python de `vaaet-app` (si fija 3.12+, podés usar `type` y
     PEP 695);
   - cola de trabajos, almacenamiento y retención de videos, identidad
     PostgreSQL del servicio y vía de licencia de YOLO.
3. Para revisar un diseño o código existente, aplicá la skill directamente. Un
   spike va fuera del repo; no escribas el backend en otra carpeta del monorepo
   para esquivar la reserva de `vaaet-app/`.

## 0. Modo de trabajo

### 0.1 ¿Corresponde hexagonal?

Sí, en un módulo o servicio que cumpla al menos una condición:

- más de un actor driving para los mismos casos de uso (API web, worker, CLI,
  scheduler);
- tecnologías driven intercambiables o reemplazables (cola, almacenamiento,
  proveedor de email, base);
- necesidad de correr la aplicación entera en tests sin infraestructura;
- integraciones cuyo modelo no debe filtrarse al núcleo (ACL).

El backend de VAAET cumple las cuatro: la web y un worker manejan el mismo
análisis, el pipeline de visión y PostgreSQL son tecnología pesada que no puede
estar en los tests de aceptación, y `vaaet-core` y `vaaet-persistence` trabajan
con DataFrames y modelos propios que no deben cruzar el núcleo.

No, si el módulo es un CRUD con un solo actor y una sola base, por ejemplo un
catálogo de cámaras editable desde la web. Ahí alcanza un router con un servicio
simple; hexagonal sin pluralidad de adaptadores es ceremonia. Decilo
explícitamente cuando lo desaconsejes, con el motivo.

### 0.2 Qué entregar

1. **Mapa del hexágono**: actores driving y driven, puertos de cada lado y
   adaptadores por puerto, incluido el adaptador en memoria.
2. **Código** de puertos, adaptadores y configurador.
3. **Tabla de traducción de errores** por borde: infraestructura → núcleo y
   núcleo → HTTP, worker y CLI.
4. **Tests**: aceptación por puerto driving con perfil en memoria y contrato por
   puerto driven.
5. **Contratos de import-linter** listos para CI.

Ajustá la entrega al pedido: una revisión de código no necesita el mapa completo,
pero sí los hallazgos con archivo, línea y corrección.

### 0.3 Reglas duras

Cada regla tiene un motivo. Si una no aplica, decí por qué en vez de ignorarla.

1. **El núcleo no importa tecnología.** `domain/` y `application/` no importan
   `fastapi`, `pydantic`, `sqlalchemy`, `pandas`, `typer`, SDKs, `vaaet` ni
   `vaaet_persistence`. Así el núcleo corre en un test sin GPU ni
   base, y cambiar una tecnología no lo toca. Se verifica en CI (§10).
2. **`vaaet_ml` nunca entra al backend.** Es el laboratorio y no es dependencia
   de serving (ADR-0021).
3. **Puertos en el lenguaje del núcleo.** Los driving expresan intenciones
   (`SubmitVideoAnalysis`); los driven, lo que la aplicación necesita
   (`TrafficAnalyzer`), no lo que ofrece la tecnología (`VaaetCoreClient`).
4. **Los adaptadores dependen de los puertos, nunca entre sí.** Sólo el
   configurador nombra clases concretas.
5. **Casos de uso puros.** Sin `Depends`, sin `Request`, sin decoradores del
   framework. FastAPI registra lo que el configurador construyó.
6. **Cada adaptador traduce** datos (Pydantic ↔ comando o vista, DataFrame ↔
   dominio) y errores (excepción de infraestructura → error del núcleo; error del
   núcleo → protocolo).
7. **Cada puerto driven tiene un adaptador en memoria** con comportamiento real y
   un test de contrato que corre contra él y contra el real.
8. **Los casos de uso se prueban por su puerto driving**, sin HTTP ni base.
9. **Entre módulos, sólo puertos driving públicos o eventos con outbox**; nunca
   tablas ni adaptadores ajenos.
10. **Reglas de VAAET en el borde correcto**:
    - el análisis de video nunca corre en el request HTTP: se encola y lo ejecuta
      el worker;
    - el bundle se carga sólo con `load_traffic_bundle()`, que valida el
      manifiesto antes de deserializar (RN-08). Esa función importa TensorFlow,
      así que únicamente la llama el worker. El proceso web valida la revisión
      leyendo sólo el manifiesto (`vaaet.artifacts.validate_manifest` y
      `authorize_bundle`), sin cargar binarios;
    - `analyze_video` toma `clip_id` y la hora de captura del nombre del
      archivo, y si no recibe `output_path` escribe un video anotado junto al
      original. El adaptador de almacenamiento conserva un nombre contractual, y
      el de visión escribe el video anotado en una ubicación que controla
      `VideoStorage` y guarda su referencia: ADR-0021 prevé que la API almacene
      referencias a resultados, telemetría y video anotado. Los videos nunca van
      a Git ni a logs (RN-24); la retención la fija el ADR de almacenamiento;
    - las escrituras en PostgreSQL no se reintentan automáticamente
      (ADR-0028). Sólo se reintenta lo que falló antes de escribir; el resto se
      resuelve como indica §7;
    - `Accident` sólo existe como decisión humana con nota y contexto revisado
      (RN-02);
    - el configurador rechaza perfiles en memoria en producción y exige la vía de
      licencia de YOLO de ADR-0022 antes de habilitar el adaptador de visión.

## 1. El hexágono de VAAET

```text
        DRIVING                                                    DRIVEN
 Web ─► router HTTP v1 ─► SubmitVideoAnalysis ┐        ┌─► VideoStorage     ─► S3 / disco / memoria
 Worker ─► consumidor ──► RunAnalysisJob      │ NÚCLEO │─► AnalysisJobQueue ─► cola (ADR) / memoria
 CLI ─► Typer ──────────► GetAnalysis         │ casos  │─► TrafficAnalyzer  ─► vaaet-core (visión + bundle)
 Revisor ─► router HTTP ► RecordReviewDecision│ de uso │─► BundleCatalog    ─► validate_manifest (web) / load_traffic_bundle (worker)
 Test ─► harness ───────► (todos)             │   +    │─► AnalysisStore    ─► vaaet-persistence / memoria
                                              │dominio │─► ReviewLedger     ─► vaaet-persistence / memoria
                                              ┘        └─► Clock, IdGenerator ─► sistema / fijo
                    configurador (lifespan): perfil → adaptadores → puertos
```

| Elemento | Qué es | Lo define | Lo implementa | Lo usa |
|---|---|---|---|---|
| Puerto driving | Contrato de un caso de uso o consulta | Aplicación | El caso de uso | Adaptadores driving |
| Puerto driven | Algo que la aplicación necesita | Aplicación | Adaptadores driven | Casos de uso |
| Adaptador driving | Protocolo → llamada al puerto | Infraestructura | — | Actor externo |
| Adaptador driven | Llamada del puerto → tecnología | Infraestructura | — | Núcleo, vía puerto |
| Configurador | Construye y conecta adaptadores | Raíz de la app | — | Arranque y tests |

Asimetría: el adaptador driving conoce el puerto driving y lo invoca; el núcleo
conoce el puerto driven y el adaptador driven lo implementa. Las dependencias
siempre apuntan al hexágono.

El detalle de cada puerto de VAAET y qué API real de `vaaet-core` y
`vaaet-persistence` envuelve cada adaptador está en
[references/vaaet-hexagon.md](references/vaaet-hexagon.md). Leelo antes de
diseñar un módulo concreto del backend.

## 2. Estructura y nombres

Propuesta para `vaaet-app/`, que confirma el ADR del componente:

```text
vaaet-app/src/vaaet_app/
├── modules/analysis/
│   ├── __init__.py              # API pública del módulo: puertos driving y build_*
│   ├── domain/                  # tipos y reglas propias (TrafficState, AnalysisJob…)
│   ├── application/
│   │   ├── ports/driving.py     # SubmitVideoAnalysis, GetAnalysis…
│   │   ├── ports/driven.py      # VideoStorage, TrafficAnalyzer, AnalysisStore…
│   │   ├── errors.py            # errores del núcleo
│   │   └── submit_video_analysis.py
│   ├── adapters/
│   │   ├── driving/http/router.py
│   │   ├── driving/worker/analysis_consumer.py
│   │   ├── driving/cli/commands.py
│   │   └── driven/{storage,queue,vision,persistence,memory}/…
│   ├── configuration.py         # build_web_analysis_module(settings, infra)
│   └── worker_configuration.py  # build_worker_analysis_module: sólo el worker
├── bootstrap/app.py             # create_app(): lifespan, routers, error handlers
└── testing/contracts/           # suites de contrato por puerto driven
```

| Concepto | Nombre | Ejemplo |
|---|---|---|
| Puerto driving | Intención | `SubmitVideoAnalysis`, `RecordReviewDecision` |
| Puerto driven | Rol para el núcleo | `TrafficAnalyzer`, `AnalysisStore`; nunca `PostgresRepo` |
| Adaptador driven | Tecnología + puerto | `VaaetCoreTrafficAnalyzer`, `InMemoryAnalysisStore` |
| Configurador | `configuration.py`, `worker_configuration.py` | `build_web_analysis_module`, `build_worker_analysis_module` |

Sin prefijo `I` y sin sufijo `UseCase` si el nombre ya expresa la intención.
Elegí un estilo por repo; el de Cockburn (`ForAnalyzingVideos`) también es válido.

## 3. Puertos

### 3.1 Driving: el contrato del caso de uso

```python
# application/ports/driving.py
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True, slots=True)
class SubmitVideoAnalysisCommand:
    video: StoredVideoRef        # referencia ya almacenada, nunca UploadFile
    model_revision: ModelRevision
    requested_by: ActorId

class SubmitVideoAnalysis(Protocol):
    async def __call__(self, cmd: SubmitVideoAnalysisCommand, /) -> AnalysisJobId: ...

class GetAnalysis(Protocol):
    async def __call__(self, job_id: AnalysisJobId, actor: Actor, /) -> AnalysisView: ...
```

- Entrada: comandos inmutables del lenguaje del negocio. Nunca `Request`,
  `UploadFile` ni modelos Pydantic del borde.
- Salida: IDs o vistas propias; nunca DataFrames, filas ni entidades mutables.
- Un puerto por intención: un consumidor depende sólo de lo que usa.

### 3.2 Driven: lo que la aplicación necesita

```python
# application/ports/driven.py
class TrafficAnalyzer(Protocol):
    def analyze(self, video: LocalVideo, bundle: BundleHandle, /) -> AnalysisOutcome: ...

class AnalysisStore(Protocol):
    async def create_job(self, job: AnalysisJob, /) -> None: ...
    async def save_outcome(self, job_id: AnalysisJobId, outcome: AnalysisOutcome, /) -> None: ...
    async def get(self, job_id: AnalysisJobId, /) -> AnalysisJob | None: ...

Clock: TypeAlias = Callable[[], datetime]
```

- Granularidad por necesidad del caso de uso, no por tabla ni por API del
  proveedor: `AnalysisStore.save_outcome`, no `execute(sql)`.
- `async` si algún adaptador real hace I/O. `TrafficAnalyzer.analyze` es
  síncrono a propósito: lo usa sólo el worker, en su proceso, y el pipeline de
  visión es Pipe-and-Filter síncrono.
- Reloj, IDs y aleatoriedad también son puertos, para que los tests sean
  deterministas.
- `Protocol` (estructural) por defecto; `ABC` sólo si hay comportamiento
  compartido real.

## 4. Adaptadores driving

Varios actores, mismo puerto. El adaptador driving valida la forma (Pydantic),
obtiene el actor autenticado, arma el comando, invoca el puerto y traduce el
resultado a su protocolo. No contiene reglas de negocio: si dos adaptadores
repiten una regla, esa regla va al núcleo.

- **HTTP**: router FastAPI bajo `/api/v1/`; `Depends` sólo lee el puerto de
  `request.app.state`, nunca construye adaptadores.
- **Worker**: consume trabajos, ejecuta el análisis en su proceso y decide
  `ack`, `retry` o `reject` según el error del núcleo.
- **CLI**: Typer, con el mismo configurador; útil para reprocesos y operación.

Código completo de los tres en
[references/fastapi-code.md](references/fastapi-code.md) §1.

## 5. Adaptadores driven, ACL y decoradores

- Implementan el puerto con una tecnología y traducen datos y errores. El
  adaptador de `vaaet-persistence` es síncrono por dentro: envolvelo con
  `anyio.to_thread.run_sync` para no bloquear el event loop.
- **ACL**: los DataFrames, `VideoAnalysisResult`, `HumanValidation` y las
  excepciones de `vaaet-core` y `vaaet-persistence` no cruzan el puerto. El
  adaptador los convierte a tipos del núcleo.
- **Varios adaptadores por puerto**: real, en memoria (tests y desarrollo) y
  alternativo (S3 o disco local). El configurador elige.
- **Decoradores de puerto** para métricas, retries y caché: implementan el mismo
  puerto, y el núcleo no distingue el adaptador decorado del original.

Código en [references/fastapi-code.md](references/fastapi-code.md) §2.

## 6. Configurador y lifespan

- Un `build_<módulo>_module(settings, infra)` por módulo es el único lugar que
  nombra adaptadores concretos. `create_app()` compone los módulos dentro del
  `lifespan` y los guarda en `app.state`.
- Perfiles validados al arranque (`memory`, `local`, `production`). En
  producción se rechazan los adaptadores en memoria y se exige la licencia de
  YOLO configurada (ADR-0022). Un error de configuración corta el arranque, no
  la primera request.
- Manual primero. Un contenedor de DI (`dependency-injector` o similar) es
  opcional y sólo en el configurador; nunca decoradores de DI en el núcleo.

Código en [references/fastapi-code.md](references/fastapi-code.md) §3.

## 7. Traducción de errores en ambos bordes

| Error del núcleo | Origen típico (driven) | HTTP | Worker | CLI (exit) |
|---|---|---|---|---|
| `InvalidInputError` | Comando inválido, `VideoValidationError` | 422 | `reject` → DLQ | 2 |
| `NotFoundError` | Trabajo o predicción inexistente | 404 | `ack` + log | 1 |
| `ConflictError` | `PersistenceConflictError`: misma clave con contenido **distinto** del ya almacenado | 409 | `reject` + alerta | 1 |
| `ForbiddenError` | Actor sin permiso | 403 | `reject` + alerta | 77 |
| `UnusableBundleError` | `ArtifactValidationError`, bundle `pilot` sin autorizar | 422 | `reject` + alerta | 2 |
| `DependencyError` | `VideoOpenError`, storage caído, timeout, o la sonda de base **antes** de escribir (`database_engine`) | 503 + `Retry-After` | `retry` con backoff | 75 |
| `WriteOutcomeUnknownError` | `DatabaseOperationError` **durante** una escritura | 503 sin `Retry-After` | `ack` + trabajo «para verificar» + alerta | 75 |
| `AuditPendingError` | `PipelineAuditIncompleteError`: datos confirmados, auditoría pendiente | 409 | `ack` + trabajo «para reconciliar» con su `run_id` | 75 |
| `ConfigurationError` | `PersistenceValidationError`, `DatabaseSchemaVersionError`, `DatabaseNotConfiguredError`, `ValueError` de contrato | 500 sin detalle | `reject` + alerta | 78 |
| Inesperado | — | 500 sin detalle | `retry` limitado → DLQ, sólo si no empezó a escribir | 70 |

ADR-0028 no permite repetir escrituras automáticamente. Hay dos casos distintos:

- **Auditoría pendiente** (`PipelineAuditIncompleteError`): los datos ya están
  confirmados y falta cerrar la corrida. El adaptador conserva `exc.run_id` en
  el trabajo y se resuelve con `reconcile_raw_telemetry` o
  `reconcile_classified_telemetry(pipeline_run_id=run_id)`, que verifican lo
  almacenado sin reinsertar (ADR-0033).
- **Escritura sin confirmar** (`DatabaseOperationError` dentro de la
  transacción): lo habitual es que se haya revertido, pero no hay certeza. El
  adaptador conserva `run_id` y `operation`; una persona verifica el estado y
  decide un reenvío deliberado. `reconcile_*` no aplica a este caso.

Un `DependencyError` de persistencia sólo puede salir de la sonda previa. Si
`persist_raw_telemetry` termina con auditoría pendiente, la clasificada no se
escribe: el trabajo queda con la raw confirmada y la clasificada pendiente.

- Del lado driven, cada adaptador traduce su excepción con `raise … from exc`,
  sin copiar mensajes del driver: pueden traer parámetros o DSN.
- Del lado driving, un único traductor por protocolo: un `exception_handler` de
  FastAPI, un wrapper del consumidor y otro del CLI. Nunca un `try` por
  endpoint.
- El núcleo nunca importa `HTTPException` ni códigos de estado.

## 8. Comunicación entre módulos

| Necesidad | Mecanismo |
|---|---|
| Usar una capacidad de otro módulo | Su puerto driving público (`__init__.py`), inyectado por el configurador como si fuera un puerto driven del consumidor |
| Reaccionar a un hecho de otro módulo | Evento → outbox en la misma transacción → relay → consumidor idempotente |
| Hablar con otro servicio | Puerto driven propio + adaptador HTTP o de cola con ACL |

El consumidor declara su propio puerto (`ReviewQueueSource`) y un adaptador fino
lo implementa llamando al puerto driving del otro módulo. Si ese módulo se
extrae a otro servicio, cambia sólo el adaptador. Sin eventos en memoria
publicados antes del commit y sin tablas compartidas.

## 9. Tests

| Nivel | Qué prueba | Cómo |
|---|---|---|
| Aceptación | Casos de uso por el puerto driving | Configurador con perfil `memory`, reloj e IDs fijos; sin HTTP, base ni GPU |
| Contrato | Que cada adaptador cumpla su puerto | La misma suite contra el adaptador en memoria y el real (PostgreSQL 17 desechable) |
| Adaptador driving | Validación, auth, errores y protocolo | `httpx.AsyncClient` con `ASGITransport` sobre la app con perfil `memory` |
| End-to-end | Pocos flujos críticos | Perfil real; la visión con un clip corto sólo donde haya GPU |

Usá fakes con comportamiento real (el store en memoria rechaza duplicados igual
que PostgreSQL), no mocks por método: el test de contrato los mantiene honestos.
Ejemplos en
[references/testing-and-enforcement.md](references/testing-and-enforcement.md).

## 10. Enforcement

Contratos de import-linter en CI:
- el núcleo no importa adaptadores ni tecnología;
- los adaptadores driving y driven son independientes entre sí;
- nada de `vaaet_app` importa `vaaet_ml`.

Están listos para copiar en
[references/testing-and-enforcement.md](references/testing-and-enforcement.md) §3.
En la revisión de PR, mirá lo que el tooling no ve: reglas de negocio en
adaptadores, puertos con forma de la API del proveedor, casos de uso con `Depends`
y errores sin traducir.

## 11. Antipatrones

- Hexagonal en un CRUD con un actor y una base, o confundirla con «tres
  carpetas».
- Sólo puertos driven, sin contrato del caso de uso.
- Puertos con forma de la tecnología (`SqlRepository`, `VaaetCoreClient`).
- `Depends`, `Request` o `BackgroundTasks` dentro de casos de uso.
- Análisis de video dentro del request o en `BackgroundTasks`: el proceso web no
  es un worker.
- Instanciar adaptadores fuera del configurador; adaptadores que se llaman entre
  sí.
- DataFrames, `VideoAnalysisResult` o `HumanValidation` cruzando el puerto.
- `HTTPException` en el núcleo, o errores de infraestructura que suben sin
  traducir.
- Llamar a `vaaet-persistence` (síncrono) directamente desde un endpoint
  `async`.
- Deserializar un bundle sin `load_traffic_bundle()`, o llamarla desde el
  proceso web (importa TensorFlow).
- Reintentar automáticamente una escritura de `vaaet-persistence` que falló a
  mitad de camino (ADR-0028): se reconcilia.
- Tratar `PersistenceConflictError` como «ya procesado»: significa contenido
  distinto del almacenado.
- Guardar el video con un nombre aleatorio: `analyze_video` pierde `clip_id` y la
  hora de captura.
- Perfil `memory` activable en producción.
- Importar `vaaet_ml` desde el backend.
- Contraseñas, DSN o PII en comandos con `repr` o en logs.

## 12. Definition of Done

- **Decisión:** el módulo justifica hexagonal (§0.1), o se desaconsejó con su
  motivo.
- **Puertos:** driving por intención, con comandos y vistas propios; driven por
  necesidad, en lenguaje del núcleo; reloj e IDs como puertos.
- **Adaptadores:**
  - los driving son finos;
  - los driven tienen ACL y traducción de errores;
  - `vaaet-persistence` está envuelto en un threadpool;
  - el bundle se carga manifest-first.
- **Configurador:** uno por módulo más `create_app()` con `lifespan`; perfiles
  validados; producción sin adaptadores en memoria y con la licencia de YOLO
  verificada.
- **Errores:** tabla de §7 implementada con un traductor por protocolo.
- **Tests y CI:** aceptación con perfil `memory`, contrato por puerto driven,
  tests del adaptador HTTP e import-linter en CI.
- **VAAET:** si toca `vaaet-app/`, hay plan gobernado y ADR aprobados.

## 13. Referencias

Alistair Cockburn, *Hexagonal Architecture* (2005), y con Juan Manuel Garrido de
Paz, *Hexagonal Architecture Explained* (2024). Robert C. Martin, *Clean
Architecture*. Eric Evans, *Domain-Driven Design* (ACL). Mark Seemann,
*Dependency Injection Principles, Practices, and Patterns* (composition root).
Harry Percival y Bob Gregory, *Architecture Patterns with Python*. Documentación
de FastAPI (lifespan, dependencies, exception handlers) e import-linter.
