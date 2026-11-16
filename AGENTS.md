# AGENTS.md — VAAET

## Proyecto

VAAET convierte videos de tránsito en telemetría por minuto, estados de
circulación y evidencia revisable por una persona. Es un laboratorio ML batch
que se ejecuta en Google Colab; no es un sistema autónomo de seguridad ni de
respuesta ante emergencias. Producto y alcance: [PRD](docs/product/product-requirements.md).

Monorepo con tres distribuciones Python 3.10–3.13, sin paquete en la raíz. Se
instalan en este orden:

| Componente | Import | Contiene | Reglas propias |
|---|---|---|---|
| `vaaet-core/` | `vaaet` | Percepción, telemetría, 19 features, estados, bundle e inferencia portable | [`vaaet-core/AGENTS.md`](vaaet-core/AGENTS.md) |
| `vaaet-persistence/` | `vaaet_persistence` | PostgreSQL, SQL, auditoría y la única cadena Alembic | [`vaaet-persistence/AGENTS.md`](vaaet-persistence/AGENTS.md) |
| `vaaet-ml/` | `vaaet_ml` | Los cuatro notebooks, datasets, entrenamiento, evaluación y DVC | [`vaaet-ml/AGENTS.md`](vaaet-ml/AGENTS.md) |
| `vaaet-app/` | — | Reservado: no hay API ni Web App | [`vaaet-app/README.md`](vaaet-app/README.md) |

Las versiones están en el `pyproject.toml` de cada componente.

## Antes de editar

1. Revisá `git status` y preservá los cambios ajenos.
2. Leé el `AGENTS.md` del componente que vas a tocar.
3. Ubicá el ADR vigente en el [índice de ADRs](docs/architecture/decisions/README.md)
   y la regla aplicable en las [reglas de negocio](docs/product/business-rules.md).
4. Inspeccioná el código y las pruebas existentes antes de proponer una
   abstracción nueva.

Los ADRs, contratos y reglas de seguridad prevalecen sobre este archivo y sobre
cualquier resumen.

## Dónde va cada cambio

| Si la tarea afecta... | Va en | Regla principal |
|---|---|---|
| Percepción, tracking, velocidad, telemetría, timestamps, features, política de estados, HUD o bundle | `vaaet-core/` | Sin dependencias del laboratorio ni de infraestructura. |
| Conexión, consultas, escrituras, linaje, roles, auditoría o Alembic | `vaaet-persistence/` | Puede usar el core base; nunca ML, Colab, DVC, Drive ni la app. |
| Notebooks, ingestión, datasets, entrenamiento, evaluación, UI HITL, backups o DVC | `vaaet-ml/` | Consume core y persistencia sólo por sus APIs públicas. |
| API, frontend, workers o aplicación desplegable | `vaaet-app/` | Requiere alcance aprobado y contrato HTTP versionado antes de cualquier código. El backend podrá usar core y persistencia, nunca `vaaet-ml`; el navegador sólo verá la API HTTP. |
| Documentación, CI, configuración Git/DVC o políticas compartidas | Raíz | Un único workspace; comprobá el impacto en cada componente. |

## Dónde está cada cosa

| Tema | Ubicación |
|---|---|
| Requisitos, roles y reglas de negocio | [`docs/product/`](docs/product/) |
| Arquitectura y modelo de datos | [`docs/architecture/`](docs/architecture/software-architecture.md) |
| Decisiones | [`docs/architecture/decisions/`](docs/architecture/decisions/README.md) |
| Contrato del bundle | [`docs/ml/model-artifact-contract.md`](docs/ml/model-artifact-contract.md) |
| Operación de Colab, PostgreSQL y DVC | [`docs/operations/`](docs/index.md) y [`docs/ml/dvc-guide.md`](docs/ml/dvc-guide.md) |
| Schema PostgreSQL | `vaaet-persistence/src/vaaet_persistence/migrations/versions/` |
| Las 19 features | `vaaet-core/src/vaaet/settings.py` (`FEATURE_COLS`) |
| Planes gobernados | [`docs/governance/plans/`](docs/governance/plans/) |
| Índice documental completo | [`docs/index.md`](docs/index.md) |

## Reglas inviolables

Detalle, origen y aplicación de cada una en las
[reglas de negocio](docs/product/business-rules.md).

- Las 19 `FEATURE_COLS` conservan nombre, orden y semántica (RN-04).
- El MLP aprende `Normal`, `Reduced` y `Congested`; `Accident` sólo existe por
  validación humana y nunca se publica automáticamente (RN-01 a RN-03).
- El manifiesto del bundle v3 y sus checksums se validan antes de deserializar
  `.keras` o `.joblib` (RN-08).
- `continuity_id` y `model_revision` son límites: ningún estado, incidente o
  revisión los atraviesa ni sobrescribe historia (RN-06, RN-09).
- `VideoViewPlan` sólo admite segmentos offline calibrados; cada transición
  reinicia el estado y descarta el minuto mixto (RN-07, ADR-0025).
- Las predicciones no validadas nunca son etiquetas; las decisiones humanas son
  append-only y requieren auditoría verificable (RN-13 a RN-18).
- Alembic es la única autoridad DDL; no ejecutes migraciones desde notebooks.
  Los perfiles PostgreSQL aplican TLS y mínimo privilegio (RN-21, ADR-0024).
- Git identifica versiones y DVC almacena el bundle atómico, con un único
  remoto lógico `vaaet-registry` configurado en `.dvc/config.local`
  ([ADR-0023](docs/architecture/decisions/0023-provider-neutral-dvc-registry.md)).
- Videos, datasets privados, credenciales, DSN, certificados, calibraciones
  reales y binarios ML no entran a Git ni a logs o ejemplos (RN-24).
- La visión es un Pipe-and-Filter síncrono y ordenado. No agregues threads,
  procesos, colas ni Producer--Consumer sin mediciones comparables en Colab y
  aprobación explícita.

## Serving y licencias

Una ejecución con `vaaet-core[vision]` y Ultralytics YOLO sólo puede servirse
como **demo pública AGPL-3.0**, con el
[checklist de publicación](docs/governance/agpl-demo-release-checklist.md)
completo, o como **aplicación privada o comercial con licencia Ultralytics
Enterprise** verificada fuera de Git
([ADR-0022](docs/architecture/decisions/0022-agpl-public-demo-path.md)). La
licencia del repositorio no autoriza a publicar videos, pesos, datasets ni
activos sin procedencia y permiso de redistribución.

## Convenciones

- Identificadores, nombres de archivo y código en inglés.
- Comentarios y docstrings propios en español rioplatense formal: forma
  declarativa para contratos («Valida…») y voseo formal para instrucciones
  («Ejecutá…»). Documentá sólo contratos, efectos laterales, invariantes,
  decisiones y algoritmos no evidentes.
- Commits con Conventional Commits en español rioplatense formal, según
  [`.git-commit-template.txt`](.git-commit-template.txt).

## Límites

| Nivel | Conducta |
|---|---|
| **Always** | Leer las fuentes aplicables, preservar cambios ajenos, mantener el cambio acotado, validar en proporción al riesgo y documentar el resultado real. |
| **Ask** | Cambiar contratos, features, estados, umbrales, MLP, dependencias, schema o permisos PostgreSQL, migraciones, remotos DVC, serving o límites entre componentes, o iniciar una refactorización arquitectónica. |
| **Never** | Versionar secretos, datos privados, videos, calibraciones o binarios ML; saltar la validación manifest-first; eliminar o debilitar pruebas para obtener verde; introducir dependencias ML o de infraestructura en el core; agregar API, frontend o framework en `vaaet-app/` sin aprobación. |

No hagas commits, tags, promociones DVC ni publicaciones remotas salvo pedido
explícito.

## Si algo no está claro

Si el pedido, un plan, un ADR o estas reglas se contradicen, o falta
información, detenete antes de editar. Señalá las fuentes concretas en
conflicto y la decisión que necesitás; no elijas una interpretación en silencio.

## Trabajo con planes

Los cambios de arquitectura, contratos, seguridad, datos persistidos,
dependencias, permisos o remotos requieren un plan en
`docs/governance/plans/AAAA-MM-DD-<slug>.md`, el ADR aplicable y aprobación
humana. Si hay un plan activo, ejecutá sólo la fase marcada como actual y
detenete al terminarla para que se revise.

## Validación y cierre

Usá los comandos del `AGENTS.md` del componente afectado. Como mínimo:

| Alcance | Evidencia |
|---|---|
| Un componente | Ruff, Pyright, pytest y `compileall`. |
| `vaaet-persistence/` | Lo anterior más integración con PostgreSQL 17 cuando corresponda. |
| `vaaet-ml/` | Lo anterior más AST y auditoría de los cuatro notebooks. |
| Documentación | `pytest tests/repository` en `vaaet-ml/`, enlaces internos y `git diff --check`. |
| GPU, Drive, DVC remoto, YOLO o TLS real | Validación manual en el entorno real; no la presentes como hecha. |

Antes de terminar, revisá el diff en busca de cambios accidentales, secretos o
binarios. Informá los archivos modificados, las validaciones y sus resultados,
y lo que quedó pendiente con su motivo. Para contribuir, seguí
[`CONTRIBUTING.md`](CONTRIBUTING.md); los problemas de seguridad se reportan
según [`SECURITY.md`](SECURITY.md).
