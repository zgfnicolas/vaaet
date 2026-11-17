# Modo librería: lo vigente en VAAET y qué proponer

Leé este archivo antes de revisar o proponer cambios en `vaaet-core`,
`vaaet-persistence` o `vaaet-ml`. Describe lo que hay y por qué, y lista las
mejoras que conviene **proponer**. Ninguna se aplica sin plan gobernado: todas
tocan dependencias, CI o versiones, que `AGENTS.md` pone en «Ask». Si el código
cambió, prevalece el código.

## Contenido

1. Lo vigente y su motivo
2. Qué no tocar en una revisión
3. Mejoras para proponer, por prioridad
4. Cómo presentar una propuesta

## 1. Lo vigente y su motivo

| Tema | Hoy | Por qué |
|---|---|---|
| Distribuciones | Tres paquetes setuptools con layout `src/`, AGPL-3.0, versión propia en cada `pyproject.toml` | ADR-0021 y ADR-0028: componentes separados que se instalan en orden core → persistencia → ML |
| Python | `requires-python = ">=3.10,<3.14"`; matriz de CI 3.10–3.13; Ruff `target-version = "py310"`; Pyright con `pythonVersion` 3.10 | Colab decide su versión; la [guía de Colab](../../../../docs/operations/colab-guide.md) documenta el runtime actual y uno de respaldo |
| Rangos | Terceros con cota inferior y techo (`numpy>=1.26,<2.2`, `pandas>=2.2,<3`); TensorFlow con marcadores por versión de Python | Los techos protegen la compatibilidad con el NumPy y el TensorFlow de Colab, que no se pueden reemplazar libremente |
| Internas | Pins exactos (`vaaet-core==0.2.2` en persistencia y ML) | Una versión de core coherente por instalación; el CI verifica las versiones |
| Herramientas de dev | Extra `[dev]` (pytest, pytest-cov, Ruff, Pyright, pandas-stubs) | `pip install -e ".[dev]"` funciona con cualquier pip del entorno |
| Lockfiles | Ninguno | Un lock de una plataforma no aplica al Python de Colab, que ya trae paquetes, y agregarlo es un cambio de dependencias («Ask» en `AGENTS.md`). La mitigación vigente está en la §7 de la [arquitectura de software](../../../../docs/architecture/software-architecture.md); la [matriz de riesgos archivada](../../../../docs/archive/risk-matrix.md) (R-008) ya advertía no introducir lockfiles sin una decisión aprobada |
| Instalación en Colab | La celda de setup clona o actualiza el repo; `vaaet-ml/scripts/notebook_bootstrap.py` instala desde el checkout sin `--editable`, en orden, y reinstala con `--no-deps` si la huella de dependencias no cambió | Los notebooks no ejecutan `!pip` manual |
| Instalación local | Venv e instalación editable en orden, según `CONTRIBUTING.md` | |
| CI | Un job por componente con la matriz 3.10–3.13, más `pip check`, `package-smoke` (instalación no editable en venvs separados), `workspace-integration`, `typing`, `postgres-integration` y `dvc-check` | Garantiza que cada distribución se instala sola, y que las tres juntas siguen siendo consistentes |
| Acciones | Por tag (`actions/checkout@v4`, `actions/setup-python@v5`), sin bloque `permissions` ni caché de pip | Configuración original; ver §3 |
| Secretos | Perfiles `VAAET_DB_*` y `VAAET_<PROFILE>_DB_*` desde el entorno o Colab Secrets; `vaaet-ml/.env.example` como plantilla | RN-24 y ADR-0024 |

## 2. Qué no tocar en una revisión

- Los techos de versión: tienen motivo. Si uno parece viejo, proponé
  ampliarlo con la evidencia de Colab y del CI; no lo quites.
- El orden de instalación ni los pins internos exactos.
- `notebook_bootstrap.py` ni las celdas de setup de los notebooks.
- El extra `[dev]`, mientras no esté aprobado el cambio a dependency groups.
- La matriz de Python del CI, que es la garantía de compatibilidad.

## 3. Mejoras para proponer, por prioridad

| # | Propuesta | Beneficio | Costo y riesgo | Decisión |
|---|---|---|---|---|
| 1 | `permissions: { contents: read }` en `ci.yml` y `persist-credentials: false` en `checkout` | El token del workflow deja de tener escritura | Bajo. Verificar que ningún job necesite escribir | Cambio de CI con plan corto |
| 2 | Fijar las acciones por SHA, con el tag en un comentario, y sumar Dependabot para `github-actions` | Una acción comprometida no entra sin revisión | Bajo; PRs semanales del bot | Ídem |
| 3 | Un job de `pip-audit` sobre las dependencias de runtime, primero no bloqueante | Visibilidad de advisories conocidos | Bajo; puede marcar CVEs de TensorFlow sin fix | Ídem; definir la política de excepciones |
| 4 | Plan de retiro de Python 3.10 (EOL en octubre de 2026) | Menos matriz y deps al día: el ecosistema ya retira 3.10 (por ejemplo, las wheels de PyTorch) | Medio. Toca `requires-python`, los classifiers, la matriz, Ruff, Pyright y la guía de Colab | Plan gobernado; validar en Colab |
| 5 | Archivo de constraints sólo para CI (`pip install -c ci-constraints.txt`) | Un CI reproducible sin imponer un lock a Colab | Medio. Hay que mantenerlo y actualizarlo con un bot | ADR (cambia la mitigación de §7 de la arquitectura) |
| 6 | `[dependency-groups]` (PEP 735) en lugar del extra `[dev]` | Las herramientas de dev dejan de ser «instalables» por consumidores | Medio. Requiere pip ≥ 25.1 en todos los entornos y cambiar `CONTRIBUTING.md` y el CI | Plan gobernado |
| 7 | Caché de pip en `setup-python` (`cache: pip` con `cache-dependency-path` a los `pyproject.toml`) | CI más rápido | Bajo | Cambio de CI |
| 8 | Renovate o Dependabot para dependencias Python, con cooldown de 7 días y sin automerge | Ver las actualizaciones a tiempo | Medio. Cada PR tiene que pasar Colab y la matriz | ADR; ver [ci-and-updates.md](ci-and-updates.md) |

Migrar las librerías a uv o agregarles un lockfile **no** está en la lista: no
resuelve un problema actual y rompe el modelo de instalación de Colab. Si
alguien lo pide, explicá el porqué y ofrecé la propuesta 5 como alternativa.

## 4. Cómo presentar una propuesta

Para cada mejora:

1. Hallazgo, con archivo y línea (por ejemplo, `.github/workflows/ci.yml` sin
   bloque `permissions`).
2. Riesgo concreto que reduce.
3. Cambio propuesto, como diff o fragmento.
4. Impacto en Colab, en local, en CI y en las otras dos librerías.
5. Validación necesaria: la matriz del CI, `package-smoke` y, si cambia una
   dependencia, una corrida en Colab con el runtime vigente.
6. Decisión que necesita: plan gobernado (skill `governed-plan`), ADR o sólo
   revisión.

Agrupá las de bajo riesgo (1, 2 y 7) en un solo plan de «endurecimiento de CI»
y dejá las demás como planes aparte.
