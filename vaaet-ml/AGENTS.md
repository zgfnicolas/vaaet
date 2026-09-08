# AGENTS.md — Contexto de ejecución para agentes de IA

## Identificación

| Campo | Detalle |
|---|---|
| Proyecto | VAAET ML — Video Advanced Analysis of Traffic |
| Versión | 4.7.0 |
| Runtime objetivo | Python 3.10–3.13; Google Colab |
| Responsable | Facundo Nicolás González |
| Última revisión | 2026-08-27 |

## Mandato

Actuá como Senior ML Engineer con foco en visión artificial, MLOps y pipelines de datos. Antes de editar, leé `../AGENTS.md`, `../llms.txt`, este archivo y las decisiones aplicables en `../docs/architecture/decisions/`. Conservá la compatibilidad con Colab Free y los contratos vigentes.

VAAET tiene tres workflows operacionales y un cuarto notebook activo de
evaluación:

```text
notebooks/data-collection/  adquisición opcional de telemetría y video anotado
notebooks/training/         preparación de 19 features y entrenamiento batch
notebooks/inference/        inferencia de video, estado y feedback
notebooks/evaluation/       auditoría Champion--Challenger read-only
src/vaaet_ml/               laboratorio instalable: datos, entrenamiento y evaluación
tests/                      pruebas unitarias, contractuales y de repositorio
```

Adquisición, entrenamiento e inferencia son workflows operacionales. Evaluación
no crea `pipeline_run` ni persiste datos.

La lógica operativa reutilizable vive en `../vaaet-core/src/vaaet/` y el acceso
PostgreSQL en `../vaaet-persistence/src/vaaet_persistence/`; este componente
consume ambas bibliotecas. La Web App futura sólo consumirá una API cuyo backend
usará core/persistencia y validará el bundle v3. El MLP aprende tres estados estables;
Accident es un estado público exclusivamente humano conforme a ADR-0014.
ADR-0021 gobierna esta frontera junto con los ADRs de datos, HITL y holdouts.

## Gobernanza

| Nivel | Acciones |
|---|---|
| Always | Leer ADRs aplicables; ejecutar Ruff, tests, compilación y enlaces; mantener notebooks como orquestadores. |
| Ask | Cambiar las 19 `FEATURE_COLS`, esquema PostgreSQL, dependencias, umbrales, MLP, remotes DVC o una nueva refactorización mayor. |
| Never | Commitear secretos; eliminar tests; versionar `.pt`, `.keras` o `.joblib` directamente con Git; hardcodear conexiones; romper Colab Free. |

## Capas y reglas

- `../vaaet-core/src/vaaet/`: contratos, umbrales algorítmicos, percepción,
  features, política de estados e inferencia portable.
- `settings.py`: rutas y configuración exclusiva del laboratorio. DVC se
  configura desde la raíz mediante `vaaet-registry` y nunca desde settings.
- `data/`: datasets, backups, adaptadores Colab y fachadas PostgreSQL 4.x.
- `../vaaet-persistence/`: configuración, conexiones, SQL, escrituras,
  auditoría, roles y única cadena Alembic.
- `features/`: ingeniería, etiquetado y generación sintética de entrenamiento.
- `evaluation/`: comparación, drift y reporting de laboratorio.

Los notebooks instalan `vaaet-core`, `vaaet-persistence` y luego `vaaet-ml`:
importan `vaaet.*` para operaciones, `vaaet_persistence.*` para PostgreSQL y
`vaaet_ml.*` para laboratorio. Nunca modifican
`sys.path`. El core no puede importar este paquete ni PostgreSQL, DVC o Drive.

## Comentarios y docstrings

Mantené identificadores y código en inglés. Redactá comentarios y docstrings
propios en español rioplatense formal; explicá contratos, efectos laterales,
invariantes y decisiones no evidentes, sin narrar operaciones triviales. Usá
forma declarativa en contratos y voseo formal sólo en instrucciones operativas.
Las revisiones Alembic son historial ejecutable y no se reescriben para adaptar
su estilo documental.

## Validación

1. Instalar `../vaaet-core`, `../vaaet-persistence` y luego este componente local.
2. `ruff check src tests scripts`
3. `pyright --project ../pyrightconfig.json`
4. `pytest tests/ -v --tb=short`
5. `python -m compileall -q src tests scripts`
6. Compilar las celdas de los cuatro notebooks con `ast.parse()`.
7. Comprobar enlaces Markdown.
8. Ejecutar `git diff --check`.

GPU, Drive, PostgreSQL, descarga de YOLO y DVC remoto se validan manualmente en Colab.

No agregar, quitar ni reordenar las 19 `FEATURE_COLS`; no cambiar los cuatro estados públicos ni el esquema PostgreSQL sin autorización y un ADR. ADR-0021 gobierna el core/laboratorio; ADR-0013 el workflow de adquisición, ADR-0014 la arquitectura jerárquica, ADR-0015 los namespaces/HITL, ADR-0016 el hardening y linaje operacional, ADR-0017 los modos semilla/HITL, ADR-0018 el benchmark humano versionado, ADR-0019 los datasets inmutables, ADR-0024 la configuración PostgreSQL portable y ADR-0028 la capa compartida.
