# El hexágono del backend de VAAET

Leé este archivo antes de diseñar un módulo concreto de `vaaet-app/`. Describe qué
puertos necesita el backend y qué API real de `vaaet-core` y `vaaet-persistence`
envuelve cada adaptador. Las firmas citadas existen hoy; si cambian, la fuente es
el código y no este archivo.

## Contenido

1. Límites que impone el repo
2. Módulos sugeridos
3. Puertos driven y su adaptador real
4. El flujo de un análisis
5. Tipos propios del núcleo
6. Decisiones que necesitan ADR

## 1. Límites que impone el repo

| Fuente | Regla para el backend |
|---|---|
| ADR-0021 | Usa `vaaet-core` y `vaaet-persistence`; **nunca** `vaaet_ml`. La web sólo ve una API HTTP versionada. |
| ADR-0022 | Ejecutar `vaaet-core[vision]` (Ultralytics YOLO) en serving exige una de dos vías: demo pública AGPL-3.0 con el checklist completo, o licencia Enterprise verificada fuera de Git. |
| ADR-0028 | El backend accede a PostgreSQL con **identidad propia**; no reutiliza las credenciales de los notebooks. |
| RN-02 | `Accident` sólo existe como validación humana con nota e `incident_context_reviewed`. |
| RN-08 | El bundle se valida manifest-first con `load_traffic_bundle()`. |
| RN-14, RN-17 | Las decisiones humanas son append-only y requieren auditoría verificable. |
| `AGENTS.md` | Visión es Pipe-and-Filter síncrono: no agregues colas o threads *dentro* del pipeline sin mediciones. Una cola *entre* la API y el worker es otra cosa y sí corresponde. |

## 2. Módulos sugeridos

| Módulo | Puertos driving | Por qué es hexagonal |
|---|---|---|
| `analysis` | `SubmitVideoAnalysis`, `RunAnalysisJob`, `GetAnalysis` | La web encola, el worker ejecuta y el CLI reprocesa: tres actores. La visión y PostgreSQL deben quedar fuera de los tests. |
| `review` | `ListReviewQueue`, `RecordReviewDecision` | HITL desde la web y, eventualmente, por importación; la persistencia es append-only con comprobantes. |
| `models` | `ListServableModels` | Catálogo de bundles autorizados. Si sólo lista, puede ser un servicio simple: aplicá §0.1. |

Un catálogo editable de cámaras o vistas, con un solo actor y una sola tabla, no
justifica hexagonal.

## 3. Puertos driven y su adaptador real

| Puerto (núcleo) | Adaptador real | API que envuelve | Notas de traducción |
|---|---|---|---|
| `BundleCatalog.resolve(revision) -> BundleHandle` (web y worker) | `VaaetBundleCatalog` | `vaaet.artifacts.validate_manifest(bundle_dir)` y `vaaet.inference.bundle.authorize_bundle(manifest, *, allow_pilot, allow_experimental, persist_to_database)`. Sólo leen el manifiesto y los checksums; no importan TensorFlow | `ArtifactValidationError` o `ArtifactNotFoundError` → `UnusableBundleError`. `authorize_bundle` lanza `RuntimeError`/`ValueError` genéricos (no está en `vaaet.inference.__all__`): capturalos sólo alrededor de esa llamada. En serving, `persist_to_database=True`. Importar `vaaet.inference.bundle` ejecuta `vaaet/inference/__init__.py`, que arrastra pandas (no TensorFlow): el proceso web necesita pandas instalado. Si `validate_manifest` verifica checksums de los binarios, envolvé `resolve` en `anyio.to_thread.run_sync`. El `BundleHandle` del núcleo expone revisión y etapa. |
| `BundleLoader.load(handle)` (sólo worker) | `LoadedBundleRegistry` | `vaaet.inference.load_traffic_bundle(directory, *, allow_pilot, allow_experimental, persist_to_database, purpose=BundleLoadPurpose.INFERENCE)` → `LoadedTrafficBundle`. Repite la validación del manifiesto y deserializa con TensorFlow | Mismas traducciones. Cacheá el bundle cargado por revisión dentro del proceso worker; el `LoadedTrafficBundle` no cruza el puerto. |
| `TrafficAnalyzer.analyze(video, bundle) -> AnalysisOutcome` | `VaaetCoreTrafficAnalyzer` | `vaaet.vision.analysis.analyze_video(video_path, output_path=None, *, prediction_provider=..., view_plan=None)` → `VideoAnalysisResult` (`telemetry`, `classifications`, `complete_minutes`, `metrics`); `vaaet.inference.TrafficStateEngine(bundle).predict_latest` como `prediction_provider` y `.classify(telemetry)` para el resultado por minuto | Síncrono y pesado (GPU): sólo lo invoca el worker. `clip_id` sale de `source.stem` y la hora de captura de `extract_recording_start(nombre)`; si el nombre no la codifica, usa la hora de proceso y lo loguea. Sin `output_path`, escribe `<stem>_vaaet_annotated.mp4` junto al original: pasá una ruta que controle `VideoStorage` y guardá la referencia en el `AnalysisOutcome` (ADR-0021). Nunca en Git ni en logs (RN-24). `VideoOpenError` → `DependencyError`; `VideoValidationError` → `InvalidInputError`. Convierte el DataFrame en `MinuteState` del núcleo. |
| `AnalysisStore.save_outcome(job_id, outcome)` | `PersistenceAnalysisStore` | `vaaet_persistence.persist_raw_telemetry(df, *, engine, application_name, application_version)` → `int`, y después `persist_classified_telemetry(df, *, engine, model_version, model_revision, application_name, application_version)` → `PersistResult`. La clasificada exige las 19 `FEATURE_COLS`, `continuity_id`, `feature_schema_version` y `telemetry_schema_version` | **Síncrono**: envolvé cada llamada en `anyio.to_thread.run_sync`. `PersistenceConflictError` (contenido distinto del almacenado) → `ConflictError`. `DatabaseOperationError` → `WriteOutcomeUnknownError` con `run_id` y `operation`: lo verifica una persona, nunca se reintenta (ADR-0028). `PipelineAuditIncompleteError` → `AuditPendingError` con `run_id`: se cierra con `reconcile_*_telemetry(pipeline_run_id=run_id)` (ADR-0033). `PersistenceValidationError`, `DatabaseSchemaVersionError`, `DatabaseNotConfiguredError` y los `ValueError` de contrato → `ConfigurationError`. Para no perder fidelidad (RN-04, RN-23), el `AnalysisOutcome` lleva la carga por minuto como un payload opaco con sus tipos, que sólo los adaptadores del worker interpretan; un test verifica el ida y vuelta contra `FEATURE_COLS`. |
| `ReviewLedger.record(decision)` | `PersistenceReviewLedger` | `vaaet_persistence.persist_human_validation_record(HumanValidation(prediction_id, validated_state, reviewer_id, notes, incident_context_reviewed, ...), *, engine, application_name, application_version)` → `PersistedHumanValidation` | `HumanValidation` valida RN-02 en `__post_init__`, pero el núcleo valida antes con su propia regla, así el error se expresa en el lenguaje del núcleo. Usá `review_source` propio del backend, no `"colab"`. |
| `ReviewQueueSource.pending(...)` | `PersistenceReviewQueue` | `vaaet_persistence.load_review_queue(*, engine, pipeline_run_id=None, mode="priority")` → `pd.DataFrame` | Convertí cada fila a `ReviewItem`; el DataFrame no cruza el puerto. |
| `VideoStorage.put / open_local` | `S3VideoStorage`, `LocalVideoStorage`, `InMemoryVideoStorage` | SDK del proveedor (ADR) | Los videos no se versionan ni se loguean (RN-24). `open_local` entrega una ruta temporal al worker, porque `analyze_video` recibe un `Path`. `put` valida y conserva un nombre con el patrón contractual del core (o lo asigna el sistema): de ese nombre salen `clip_id` y la hora de captura, y dos subidas de `video.mp4` no deben compartir `clip_id`. |
| `AnalysisJobQueue.enqueue / ack / retry / reject` | Tecnología del ADR, `InMemoryJobQueue` | — | El mensaje lleva IDs, nunca el video. |
| `Clock`, `IdGenerator` | `utc_now`, `new_job_id` (`uuid4` o UUIDv7 de una biblioteca) / fijos en tests | — | `record_time` y los instantes del núcleo son siempre UTC aware. |

El engine de SQLAlchemy lo crea el configurador a partir de `DatabaseSettings` y
lo comparte entre los adaptadores de persistencia. Usá
`vaaet_persistence.database_engine(settings)`: es un context manager que sondea
la conexión al entrar y llama a `dispose_engine` al salir, así que el `lifespan`
sólo lo abre con un `ExitStack`. Si usás `get_engine`, el cierre con
`dispose_engine` queda a tu cargo. Las operaciones de `vaaet_persistence` nunca
disponen un engine recibido.

## 4. El flujo de un análisis

```text
POST /api/v1/analyses  (multipart)
  router HTTP ─► VideoStorage.put (adaptador)          # el archivo no entra al núcleo
             ─► SubmitVideoAnalysis(cmd con StoredVideoRef y model_revision)
                  ├─ BundleCatalog.resolve(revision)   # sólo manifiesto, sin TensorFlow: rechaza un bundle no servible antes de encolar
                  ├─ AnalysisStore.create_job(...)
                  └─ AnalysisJobQueue.enqueue(job_id)
  ◄─ 202 Accepted + Location: /api/v1/analyses/{job_id}

worker (proceso aparte, con GPU)
  consumidor ─► RunAnalysisJob(job_id)
                  ├─ VideoStorage.open_local(ref)
                  ├─ BundleLoader.load(handle)                # load_traffic_bundle, cacheado por revisión
                  ├─ TrafficAnalyzer.analyze(video, bundle)   # síncrono, Pipe-and-Filter
                  ├─ AnalysisStore.save_outcome(job_id, outcome)
                  └─ estado del trabajo: succeeded | failed | needs_reconciliation | needs_verification
             ─► ack | retry | reject según el error del núcleo

GET /api/v1/analyses/{job_id}  ─► GetAnalysis ─► AnalysisView
```

- El proceso web nunca importa `vaaet.vision`: si el adaptador de visión no está
  instalado ni configurado, el web arranca igual. El worker sí lo necesita.
- `RunAnalysisJob` es idempotente: repetir un `job_id` ya resuelto devuelve el
  resultado guardado sin volver a escribir, acorde a la idempotencia de
  `vaaet-persistence`.

## 5. Tipos propios del núcleo

El núcleo no importa nada de `vaaet`. `vaaet.settings` sólo usa la biblioteca
estándar, pero `vaaet.contracts` arrastra pandas, y depender del paquete ata el
núcleo a la versión del core. El núcleo define sus tipos y un test de contrato
verifica la paridad.

```python
# domain/traffic.py
from enum import IntEnum

class TrafficState(IntEnum):
    NORMAL = 0
    REDUCED = 1
    CONGESTED = 2
    ACCIDENT = 3          # sólo por decisión humana (RN-02)

AUTOMATIC_STATES = frozenset({TrafficState.NORMAL, TrafficState.REDUCED, TrafficState.CONGESTED})
```

```python
# testing/contracts/test_state_parity.py — corre donde vaaet-core esté instalado
from vaaet.settings import STATE_LABELS

def test_traffic_states_match_vaaet_core() -> None:
    assert {state.value: state.name.title() for state in TrafficState} == dict(STATE_LABELS)
```

Lo mismo vale para `ModelRevision` (SHA-256 de 64 caracteres) y para
`AnalysisOutcome`, que reemplaza al `VideoAnalysisResult` del lado del núcleo.

## 6. Decisiones que necesitan ADR

Esta skill no las fija; el diseño debe nombrarlas como pendientes:

- FastAPI, el estilo hexagonal y las dependencias nuevas del backend: ADR-0021
  todavía no habilita API ni framework, y las dependencias están en «Ask»;

- tecnología de la cola de trabajos y semántica de reintentos;
- almacenamiento de videos y su retención;
- identidad y perfil PostgreSQL del servicio (ADR-0028), que hoy no existe en
  `DatabaseProfile`;
- vía de licencia de YOLO para el worker (ADR-0022);
- autenticación de la web y de los revisores, y origen del `reviewer_id`
  seudónimo;
- versión de Python y empaquetado de `vaaet-app` dentro del monorepo.
