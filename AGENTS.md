# AGENTS.md — Contexto operativo del monorepo VAAET

Este archivo es la entrada de trabajo para agentes de código. Explica dónde
realizar cada cambio, qué contratos no pueden alterarse silenciosamente y qué
evidencia se necesita antes de cerrar una tarea. No reemplaza la presentación
humana del [`README.md`](README.md), el resumen técnico de [`llms.txt`](llms.txt)
ni la documentación normativa de [`docs/`](docs/index.md).

## VAAET de un vistazo

| Aspecto | Estado vigente |
| --- | --- |
| Propósito | Convertir videos de tránsito en telemetría por minuto, estados de circulación y evidencia revisable por una persona. |
| Producto actual | Laboratorio ML y procesamiento batch; los workflows principales se ejecutan en Google Colab. |
| Runtime | Python 3.10–3.13. |
| Componentes activos | `vaaet-core/` portable, `vaaet-persistence/` compartido y `vaaet-ml/` como laboratorio. |
| Componente reservado | `vaaet-app/`; todavía no existe API ni Web App ejecutable. |
| Modelo de estados | El MLP aprende `Normal`, `Reduced` y `Congested`; `Accident` requiere confirmación humana. |
| Licencia | AGPL-3.0-only, con condiciones adicionales para serving que utilice Ultralytics YOLO. |
| Límite operativo | No es un sistema autónomo de seguridad ni de respuesta ante emergencias. |

La arquitectura vigente está definida por
[ADR-0021](docs/architecture/decisions/0021-portable-core-and-ml-laboratory-boundary.md).
Los ADRs, contratos y reglas de seguridad prevalecen sobre resúmenes y guías
introductorias.

## Mapa de contexto y orden de lectura

Antes de editar:

1. Leé este archivo y revisá el estado actual de Git sin descartar cambios
   ajenos.
2. Consultá [`llms.txt`](llms.txt) y el
   [índice documental](docs/index.md) para localizar el contrato o ADR vigente.
3. Leé las instrucciones del componente propietario:
   [`vaaet-core/AGENTS.md`](vaaet-core/AGENTS.md) o
   [`vaaet-ml/AGENTS.md`](vaaet-ml/AGENTS.md).
4. Inspeccioná las pruebas y el código existente antes de proponer una nueva
   abstracción.

| Fuente | Responsabilidad |
| --- | --- |
| [`README.md`](README.md) | Presentación y primer recorrido para personas. |
| `AGENTS.md` | Límites y reglas operativas compartidas para agentes. |
| [`llms.txt`](llms.txt) | Resumen portable y compacto para herramientas. |
| [`docs/index.md`](docs/index.md) | Navegación hacia arquitectura, contratos, operación, calidad y gobernanza. |
| [`vaaet-core/AGENTS.md`](vaaet-core/AGENTS.md) | Reglas de percepción, telemetría, features, bundle e inferencia portable. |
| [`vaaet-persistence/AGENTS.md`](vaaet-persistence/AGENTS.md) | Reglas de conexión, SQL, transacciones, seguridad y migraciones PostgreSQL. |
| [`vaaet-ml/AGENTS.md`](vaaet-ml/AGENTS.md) | Reglas de notebooks, entrenamiento, evaluación, datasets, adaptadores Colab y DVC. |

No crees raíces de contexto paralelas ni dupliques ADRs completos en archivos
introductorios. Si dos fuentes se contradicen, detené el cambio y señalá las
fuentes concretas antes de elegir una interpretación.

## Enrutamiento de cambios

| Si la tarea afecta... | Propietario | Regla principal |
| --- | --- | --- |
| Percepción, tracking, velocidad, telemetría, timestamps, 19 features, política de estados, HUD o bundle | `vaaet-core/` | Implementar con import `vaaet`; no incorporar dependencias del laboratorio. |
| Conexión, consultas, escrituras, linaje, roles, auditoría o Alembic PostgreSQL | `vaaet-persistence/` | Implementar con import `vaaet_persistence`; no depender del laboratorio ni de la futura aplicación. |
| Notebooks, ingestión, datasets, entrenamiento, evaluación, UI HITL, backups o registro DVC | `vaaet-ml/` | Implementar con import `vaaet_ml` y consumir core/persistencia mediante sus APIs públicas. |
| API, frontend, workers o aplicación desplegable | `vaaet-app/` | Está reservado: requiere alcance aprobado y contrato HTTP versionado antes de agregar código o dependencias. |
| Documentación, CI, configuración Git/DVC o políticas compartidas | Raíz | Mantener un único workspace y comprobar el impacto sobre los componentes. |

No existe un paquete Python instalable en la raíz. En desarrollo, CI y Colab se
instala `vaaet-core`, luego `vaaet-persistence` y finalmente `vaaet-ml`.

## Convención de código y documentación interna

Mantené identificadores, nombres de archivos y código en inglés. Redactá los
comentarios y docstrings propios en español rioplatense formal: usá forma
declarativa para contratos (por ejemplo, «Valida…» o «Representa…») y voseo
formal para instrucciones operativas («Ejecutá…», «Editá…»). Documentá sólo
contratos, efectos laterales, invariantes, decisiones y algoritmos no evidentes;
no narres una línea obvia ni repitas el nombre de un símbolo.

## Límites de componentes

### `vaaet-core/`

Contiene la lógica portable de percepción, telemetría, clasificación y carga
segura del bundle. No puede depender de `vaaet_ml`, PostgreSQL, Alembic, DVC,
Google Drive ni APIs de notebooks. Recibe archivos y contratos locales ya
resueltos por el consumidor; no decide de dónde provienen.

### `vaaet-ml/`

Contiene el laboratorio: notebooks, fuentes de datos, entrenamiento,
evaluación, adaptadores Colab y artefactos ML. Puede consumir core y
persistencia, pero nunca debe convertirse en dependencia de serving. El notebook de
evaluación es read-only y no promociona modelos ni persiste resultados
operacionales.

### `vaaet-persistence/`

Contiene el acceso compartido a PostgreSQL, contratos de configuración,
consultas y escrituras concretas, auditoría y la única cadena Alembic. Puede
depender del core base, pero no de ML, Colab, DVC, Drive o la aplicación.

### `vaaet-app/`

Permanece reservado. Una futura Web App sólo podrá consumir una API HTTP
versionada; el navegador no accederá directamente a módulos Python,
PostgreSQL, DVC, Google Drive ni rutas de artefactos. El backend podrá consumir
`vaaet-core` y `vaaet-persistence`, nunca `vaaet-ml`, y validará el manifiesto
antes de deserializar un bundle.

## Invariantes no negociables

- Las 19 `FEATURE_COLS` conservan nombre, orden y semántica contractual salvo
  una decisión explícita con migración y compatibilidad definidas.
- El MLP tiene tres salidas aprendidas: `Normal`, `Reduced` y `Congested`. Los
  cuatro estados públicos se conservan, pero `Accident` nunca se publica de
  forma automática.
- El manifiesto del bundle v3 y sus checksums se validan antes de deserializar
  `.keras` o `.joblib`. Consultá el
  [contrato del bundle](docs/ml/model-artifact-contract.md).
- Git identifica versiones; DVC almacena el bundle atómico. Existe una sola raíz
  Git/DVC y un único remoto lógico `vaaet-registry`, configurado por entorno en
  `.dvc/config.local`. [ADR-0023](docs/architecture/decisions/0023-provider-neutral-dvc-registry.md)
  gobierna esta operación.
- PostgreSQL pertenece a la capa compartida `vaaet-persistence`. Alembic es la única
  autoridad DDL y los perfiles aplican TLS y mínimo privilegio. No ejecutes
  migraciones administrativas desde notebooks. Consultá
  [ADR-0024](docs/architecture/decisions/0024-provider-neutral-postgresql-and-schema-as-code.md).
- La extracción compartida y la frontera con el futuro backend están gobernadas
  por [ADR-0028](docs/architecture/decisions/0028-shared-postgresql-persistence-layer.md).
- Videos, datasets privados, validaciones sensibles, credenciales, DSN,
  certificados, calibraciones reales y binarios ML no se versionan con Git ni
  se exponen en logs o ejemplos.
- `VideoViewPlan` es opcional y sólo admite segmentos offline declarados y
  calibrados. Cada transición reinicia el estado temporal y descarta el minuto
  mixto; no se inventan perfiles ni se reidentifican vehículos entre vistas.
  Consultá
  [ADR-0025](docs/architecture/decisions/0025-calibrated-multi-view-video-segments.md).
- `continuity_id` separa tramos físicos continuos y `model_revision` identifica
  un bundle exacto. Ningún estado, incidente o revisión puede atravesar esos
  límites o sobrescribir historia. Consultá
  [ADR-0026](docs/architecture/decisions/0026-temporal-continuity-and-immutable-model-revisions.md).
- La identidad vigente incluye `input_policy`; las identidades anteriores son
  sólo históricas. La publicación recuperable y la resolución HITL uniforme
  están gobernadas por
  [ADR-0027](docs/architecture/decisions/0027-complete-bundle-identity-and-hitl-integrity.md).
- La visión mantiene un pipeline Pipe-and-Filter síncrono y ordenado. No
  introduzcas threads, procesos, colas o Producer--Consumer sin mediciones
  comparables en Colab y aprobación explícita.

## Serving y licencias

Una ejecución que incorpore `vaaet-core[vision]` y Ultralytics YOLO sólo puede
seguir una de estas vías:

1. **demo pública AGPL-3.0**, con código y activos aprobados y el
   [checklist de publicación](docs/governance/agpl-demo-release-checklist.md)
   completo;
2. **aplicación privada o comercial con licencia Ultralytics Enterprise**
   vigente, verificada fuera de Git.

[ADR-0022](docs/architecture/decisions/0022-agpl-public-demo-path.md) gobierna
esta frontera. No interpretes la licencia del repositorio como autorización
para publicar videos, pesos, datasets o activos sin procedencia y permiso de
redistribución.

## Gobernanza: Always / Ask / Never

| Nivel | Conducta esperada |
| --- | --- |
| **Always** | Leer las fuentes aplicables; inspeccionar código, pruebas y estado Git; preservar cambios ajenos; mantener el cambio acotado; validar en proporción al riesgo; documentar el resultado real. |
| **Ask** | Cambiar contratos, 19 features, estados, umbrales, MLP, dependencias, schema o permisos PostgreSQL, migraciones, remotos DVC, serving, límites core--persistencia--ML--app o iniciar una refactorización arquitectónica. |
| **Never** | Versionar secretos, datos privados, videos, calibraciones o binarios ML; saltar la validación manifest-first; eliminar o debilitar pruebas para obtener un resultado verde; introducir dependencias ML/infraestructura en el core; agregar silenciosamente API, frontend o framework en `vaaet-app/`. |

Los cambios arquitectónicos, de contratos, seguridad, datos persistidos,
dependencias, permisos o remotos requieren un plan gobernado en
`docs/governance/plans/`, el ADR aplicable y aprobación humana antes de ejecutar
la fase de riesgo. No hagas commits, tags, promociones DVC ni publicaciones
remotas salvo solicitud explícita.

## Calidad y validación

Usá los comandos completos definidos por el componente propietario y ejecutá
sólo los extras necesarios.

| Alcance | Evidencia mínima |
| --- | --- |
| `vaaet-core/` | Ruff, Pyright, pytest y `compileall` según [`vaaet-core/AGENTS.md`](vaaet-core/AGENTS.md). |
| `vaaet-persistence/` | Ruff, Pyright, pytest, `compileall` e integración PostgreSQL 17 según [`vaaet-persistence/AGENTS.md`](vaaet-persistence/AGENTS.md). |
| `vaaet-ml/` | Ruff, Pyright, pytest, `compileall`, AST y auditoría de notebooks según [`vaaet-ml/AGENTS.md`](vaaet-ml/AGENTS.md). |
| Documentación o contexto | Enlaces Markdown internos, coherencia con ADRs y contratos, y `git diff --check`. |
| PostgreSQL | Pruebas unitarias más integración PostgreSQL 17 cuando corresponda; la validación real de TLS y proveedor es manual. |
| DVC, Drive, GPU o YOLO | Pruebas sin red cuando existan y validación manual explícita en el entorno real. |
| Cambio transversal | Validaciones de todos los componentes afectados y controles de integración del workspace. |

No presentes una comprobación manual pendiente como si hubiera pasado. Si una
prueba no puede ejecutarse, indicá el motivo, el riesgo que queda abierto y el
comando o entorno necesario para completarla.

## Cierre y handoff

Antes de finalizar una tarea:

1. Confirmá que el resultado solicitado existe y respeta los límites del
   componente.
2. Revisá el diff para detectar cambios accidentales, secretos, binarios o
   archivos ajenos al alcance.
3. Informá archivos modificados y decisiones relevantes sin copiar logs
   extensos.
4. Enumerá las validaciones ejecutadas y sus resultados.
5. Señalá comprobaciones manuales pendientes, limitaciones y riesgos restantes.
6. Proponé un commit Conventional Commits sólo cuando ayude al handoff; no lo
   crees sin autorización explícita.

Para contribuir, seguí [`CONTRIBUTING.md`](CONTRIBUTING.md). Los problemas de
seguridad se reportan mediante [`SECURITY.md`](SECURITY.md), nunca mediante
issues públicos con información sensible.
