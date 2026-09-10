# Plan de pruebas — VAAET

## Contexto

VAAET es un monorepo con `vaaet-core==0.2.1` (import `vaaet`) y
`vaaet-persistence==0.2.0` (import `vaaet_persistence`) y
`vaaet-ml==4.8.0` (import `vaaet_ml`). [ADR-0021](../architecture/decisions/0021-portable-core-and-ml-laboratory-boundary.md)
define los límites; las reglas para agentes están en
[AGENTS.md](../../AGENTS.md) y [llms.txt](../../llms.txt). Este plan cubre
validación automática y evidencia manual; no reemplaza contratos de datos,
bundles o licencias.

La estrategia es proporcional al riesgo: una prueba de caracterización o
regresión cubre cada rama nueva de un módulo materialmente modificado. La
cobertura se puede consultar con `pytest-cov`, pero no bloquea CI con un
porcentaje global. Los tests no descargan pesos, no requieren GPU, Drive, DVC
remoto, videos privados ni credenciales personales.

## Objetivos

- Preservar los contratos del core: visión, telemetría, 19 features, estados,
  bundle v3 e inferencia manifest-first.
- Verificar el modo opcional de vistas calibradas: plan continuo, referencias
  geométricas válidas, reinicio por transición y descarte de minutos mixtos,
  sin alterar el modo legado de una vista.
- Mantener aisladas las capas: PostgreSQL bajo `vaaet_persistence`; datos,
  entrenamiento, evaluación, Colab, DVC y utilidades bajo `vaaet_ml`.
- Comprobar que los cuatro notebooks sean orquestadores delgados y sintácticamente
  válidos.
- Detectar regresiones de estructura, documentación, licencias y límites de
  componentes antes de integrar cambios.

## Estrategia

| Nivel | Propiedad | Ubicación principal |
| --- | --- | --- |
| Unitario y contractual | Core portable, paquetes del pipeline, bundle e inferencia | `vaaet-core/tests/` |
| Unitario y de integración local | Datos, entrenamiento, evaluación y runtime del laboratorio | `vaaet-ml/tests/` |
| PostgreSQL | Migraciones, roles, grants y contratos reales | `vaaet-persistence/tests/integration/` y compatibilidad ML con PostgreSQL 17 en CI |
| Repositorio | Imports separados, contexto de agentes, notebooks, enlaces, licencias y layout | `vaaet-ml/tests/repository/` |
| Notebook | Flujo lineal, configuración y nombres entre celdas | auditor, `ast.parse()` y Ruff `F821` |
| Sintaxis | Código Python de paquetes, scripts y migraciones | `compileall` |

Los notebooks activos son adquisición, entrenamiento, inferencia y evaluación
Champion--Challenger. Sólo los tres primeros son workflows operacionales;
evaluación es read-only y no crea `pipeline_run` ni persiste datos.

## Matriz de cambio y suites

| Cambio | Suites obligatorias | Invariante principal |
| --- | --- | --- |
| `vaaet-core` | Ruff, Pyright, pytest core y compileall | 19 features, bundle v3 manifest-first y `Accident` sólo humano |
| Visión o `VideoViewPlan` | Suite core con fakes de detector, reloj y writer | orden, reinicio por transición y descarte de minutos mixtos |
| `vaaet-ml/src` | Ruff, Pyright, pytest ML sin `postgres` y compileall | locks, snapshots, HITL, holdouts, gates humanos y diagnósticos redactados |
| PostgreSQL/Alembic/roles | Suite de persistencia e integración `postgres` | migraciones, grants, mínimo privilegio e idempotencia en PostgreSQL 17 desechable |
| DVC o `vaaet-registry` | Suite pertinente y job DVC | configuración neutral, manifiesto antes de DVC y ausencia de red en CI |
| Notebook | Auditor, AST, Ruff `F821`, paridad y suite ML | Run All lineal, configuración única y sin outputs ni nombres ocultos |
| CI, contexto o docs | Tests de repositorio, enlaces y diff check | límites core--ML--app y comandos vigentes |

Los unitarios usan fixtures, `tmp_path`, `monkeypatch` y adaptadores falsos
para filesystem, reloj, modelos, Drive, DVC, SQLAlchemy y widgets. Un mock
aisla el borde externo; no reimplementa la lógica bajo prueba.

## Ejecución local

Desde la raíz, instalar el core antes del laboratorio y elegir los extras del
workflow. No existe un paquete instalable raíz.

```bash
python -m pip install -e "./vaaet-core[vision,inference,dev]"
python -m pip install -e "./vaaet-persistence[admin,dev]"
python -m pip install -e "./vaaet-ml[training,visualization,database,dev]"
python -m pip check
```

Luego, desde cada componente:

```bash
# vaaet-core/
ruff check src tests
pytest tests -v --tb=short
python -m compileall -q src tests

# vaaet-persistence/
ruff check src tests
pytest tests -v --tb=short -m "not postgres"
python -m compileall -q src tests

# vaaet-ml/
ruff check src tests scripts migrations
pytest tests -v --tb=short -m "not postgres"
python -m compileall -q src tests scripts migrations
ruff check notebooks --select F821
python ../.codex/skills/vaaet-notebook-orchestration/scripts/audit_notebooks.py notebooks
```

También se deben compilar con `ast.parse()` las celdas de los cuatro notebooks,
resolver enlaces Markdown y ejecutar `git diff --check`.

Para cambios del registro, instalar además `dvc`, `dvc-gdrive` y `dvc-s3` desde
los extras de ML. `dvc doctor`, `dvc status` y las pruebas de `vaaet-registry`
no autentican ni transfieren artefactos.

## CI y evidencia manual

GitHub Actions ejecuta la matriz Python 3.10--3.13 de core, persistencia y ML, tipado,
instalaciones mínimas aisladas, integración del workspace, PostgreSQL, enlaces,
calidad de repositorio y DVC. La calidad de repositorio revisa
`git diff --check` en el rango completo de cada evento. Los cambios en
`.codex/skills/` activan CI porque el auditor de notebooks se ejecuta desde ese
directorio. DVC se invoca desde la raíz con
`vaaet-ml[dvc,dvc-gdrive,dvc-s3,dev]`, sin autenticarse ni transferir datos.

Un fallo determinista de contrato, lint, tipo o test se corrige; no se reintenta
para ocultarlo ni se convierte en `skip` o `xfail` sin una decisión explícita.
Un fallo PostgreSQL se reproduce únicamente contra la base efímera gobernada.
Las verificaciones externas pendientes no se declaran exitosas mediante mocks.

La evidencia local no sustituye las comprobaciones manuales en Colab: GPU,
Google Drive, DVC remoto, descarga/ejecución YOLO y PostgreSQL con Secrets.
Antes de usar cinemática calibrada fuera del laboratorio, medir referencias
conocidas en cada perfil y registrar el error de un clip con transición
planificada; sólo una comparación posterior con radar o GPS puede cuantificar
un MAE de velocidad.
Una futura demo web debe completar además los requisitos de
[ADR-0022](../architecture/decisions/0022-agpl-public-demo-path.md) y el
[checklist AGPL](../governance/agpl-demo-release-checklist.md).
