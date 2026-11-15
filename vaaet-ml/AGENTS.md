# AGENTS.md — VAAET ML

Leé primero el [`AGENTS.md`](../AGENTS.md) raíz. Este componente es el
laboratorio: distribución `vaaet-ml`, import `vaaet_ml`. Consume `vaaet-core`
(import `vaaet`) y `vaaet-persistence` (import `vaaet_persistence`) por sus APIs
públicas y nunca se usa para serving. Trabajá con criterio de ML Engineer:
conservá la compatibilidad con Colab Free y los contratos vigentes.

## Estructura

Los cuatro notebooks: tres workflows operacionales y una auditoría read-only.

```text
notebooks/data-collection/collect_traffic_telemetry.ipynb   adquisición opcional de telemetría y video anotado
notebooks/training/train_traffic_state_classifier.ipynb     19 features y entrenamiento batch
notebooks/inference/analyze_traffic_video.ipynb             inferencia, estado y revisión HITL
notebooks/evaluation/evaluate_models_and_eda.ipynb          Champion--Challenger read-only
src/vaaet_ml/                                               laboratorio instalable
tests/                                                      pruebas unitarias, contractuales y de repositorio
```

| Ruta | Responsabilidad |
|---|---|
| `src/vaaet_ml/settings.py` | Rutas y configuración del laboratorio. DVC nunca se configura acá. |
| `src/vaaet_ml/data/` | Datasets, backups, catálogo HITL, input locks, adaptadores Colab y fachadas PostgreSQL. |
| `src/vaaet_ml/features/` | Ingeniería, etiquetado y generación sintética para entrenamiento. |
| `src/vaaet_ml/training/` | Modos `SEED_BOOTSTRAP` y `HITL_RETRAINING`, holdout y balanceo. |
| `src/vaaet_ml/evaluation/` | Comparación, drift y reporting. |
| `src/vaaet_ml/view_plan.py` | Carga el JSON privado de `VIEW_PLAN_PATH` y entrega al core un contrato validado. |

La lógica operativa reutilizable vive en `../vaaet-core/src/vaaet/` y el acceso
PostgreSQL en `../vaaet-persistence/src/vaaet_persistence/`; no la traslades a
`src/vaaet_ml/` ni a los notebooks.

## Reglas

- Los notebooks sólo orquestan: instalan core, persistencia y ML en ese orden,
  importan `vaaet.*`, `vaaet_persistence.*` y `vaaet_ml.*` según responsabilidad
  y nunca modifican `sys.path`.
- Adquisición, entrenamiento e inferencia crean un `pipeline_run`; evaluación no
  crea corridas ni persiste datos, y no promociona modelos.
- `VIEW_PLAN_PATH = None` conserva la vista única. Los planes reales, perfiles y
  referencias geométricas no se versionan.
- Seed, paquetes HITL, input locks y holdouts son inmutables; sólo el runtime
  designado con un `HitlCatalogPublisher` activo modifica el catálogo.
- Los perfiles de workflow leen `VAAET_DB_*` y `VAAET_<PROFILE>_DB_*` desde
  Colab Secrets o el entorno. La identidad administrativa nunca se usa en Colab.
- DVC se administra desde la raíz con el remoto `vaaet-registry`: instalá `dvc`
  y sólo el plugin necesario (`dvc-gdrive` o `dvc-s3`).
- Las revisiones Alembic son historial ejecutable y no se reescriben.

Las reglas de datos y HITL, con su ADR de origen, están en las
[reglas de negocio](../docs/product/business-rules.md) (RN-13 a RN-19). Los
ADRs vigentes por tema están en el
[índice de ADRs](../docs/architecture/decisions/README.md).

## Límites

| Nivel | Acciones |
|---|---|
| Always | Leer los ADRs aplicables; ejecutar Ruff, tests, compilación y enlaces; mantener los notebooks como orquestadores. |
| Ask | Cambiar las 19 `FEATURE_COLS`, el esquema PostgreSQL, dependencias, umbrales, el MLP, remotos DVC o iniciar una refactorización mayor. |
| Never | Commitear secretos; eliminar tests; versionar `.pt`, `.keras` o `.joblib` con Git; hardcodear conexiones; romper Colab Free. |

## Comentarios y docstrings

Identificadores y código en inglés. Comentarios y docstrings propios en español
rioplatense formal: forma declarativa en contratos y voseo formal sólo en
instrucciones operativas. Explicá contratos, efectos laterales, invariantes y
decisiones no evidentes, sin narrar operaciones triviales.

## Validación

Desde `vaaet-ml/`, con core, persistencia y este componente instalados:

```bash
ruff check src tests scripts migrations
pyright --project ../pyrightconfig.json
pytest tests/ -v --tb=short -m "not postgres"
python -m compileall -q src tests scripts migrations
ruff check notebooks --select F821
python ../.codex/skills/vaaet-notebook-orchestration/scripts/audit_notebooks.py notebooks
git diff --check
```

El CI compila además cada celda de los notebooks con `ast.parse()` y verifica
los enlaces Markdown. GPU, Drive, PostgreSQL real, descarga de YOLO y DVC remoto
se validan manualmente en Colab.
