---
name: python-project-configuration
description: Configura y revisa proyectos Python reproducibles con supply chain endurecida, adaptado a VAAET. Distingue dos modos — librería (vaaet-core, vaaet-persistence y vaaet-ml, consumidas desde Colab, donde se respeta lo vigente y toda mejora se propone con plan) y aplicación (el futuro backend de vaaet-app o un proyecto nuevo). El camino por defecto, que un agente usa salvo que el repo o una decisión indiquen otra cosa, es pip + pip-tools: requirements.txt con hashes, pip install --require-hashes, --only-binary, --uploaded-prior-to, índices explícitos, pydantic-settings, pip-audit, Docker mínimo y apagado ordenado. uv (uv.lock, sync --locked, exclude-newer) queda como alternativa documentada, con los casos en que corresponde. Cubre versión de Python, dependency groups, extras, CI en GitHub Actions, Renovate o Dependabot con cooldown y trusted publishing. Usala siempre que se toque un pyproject.toml, requirements, uv.lock, pip, uv, pip-tools, la matriz de Python del CI, Dependabot o Renovate, un Dockerfile de Python o la configuración de entorno del backend, aunque no se diga «configuración». No la uses para migrar las librerías de VAAET a uv ni para agregarles lockfiles por iniciativa propia: eso es un cambio de dependencias que requiere plan y ADR.
---

# Configuración de proyectos Python (VAAET)

Baseline verificado el 2026-11-16. Las versiones envejecen rápido: revalidalas
con las fuentes de §12 antes de usarlas en un proyecto nuevo. Skills
relacionadas: `hexagonal-architecture-fastapi` (estructura del backend),
`js-project-configuration` (frontend), `validate` (quality gates) y
`governed-plan` (cambios que requieren plan).

**Principio rector:** un clon limpio más una instalación definida producen el
mismo entorno en la laptop, en Colab, en CI y en producción. Prioridades, en
orden: reproducibilidad, seguridad de la supply chain, correctitud,
simplicidad y velocidad.

## 0. Elegí el modo antes de proponer nada

| Modo | Dónde | Qué se hace |
|---|---|---|
| **Librería VAAET** | `vaaet-core/`, `vaaet-persistence/`, `vaaet-ml/` | Respetar lo vigente: es un contrato con Colab, con los notebooks y con el CI. Revisar contra §1 y §2, explicar los riesgos y **proponer** mejoras con plan gobernado. Nunca migrar de herramienta, agregar un lockfile ni cambiar dependencias directamente. |
| **Aplicación** | El futuro backend de `vaaet-app/` o un proyecto nuevo fuera del repo | El rigor completo de esta skill: lock con hashes, instalación congelada, cooldown, sólo wheels, entorno validado, imagen mínima. En `vaaet-app/`, primero plan gobernado y ADR (está reservado). |

Las librerías VAAET no son aplicaciones. Se instalan en el Python de Colab junto
con lo que Colab ya trae, y un lock con hashes de una plataforma no aplica ahí
([guía de Colab](../../../docs/operations/colab-guide.md)). Agregar un lockfile
o cambiar de herramienta es un cambio de dependencias, que `AGENTS.md` pone en
«Ask». La mitigación vigente del riesgo de dependencias está en la §7 de la
[arquitectura de software](../../../docs/architecture/software-architecture.md):
extras declarados, CI en 3.10–3.13 y `pip check`. El detalle de lo vigente y de lo que conviene proponer
está en [references/vaaet-library-mode.md](references/vaaet-library-mode.md).
Leelo antes de tocar cualquiera de los tres `pyproject.toml`.

### 0.1 Herramienta: qué usa un agente

**Por defecto, un agente (incluido un LLM como Claude) usa pip + pip-tools.**
pip es el instalador estándar de Python, está en todos los entornos (también en
Colab y en la imagen oficial) y es lo que ya usan las librerías de VAAET.
pip-tools agrega lo que pip solo todavía no da de forma estable: un
`requirements.txt` con hashes generado desde un `.in`. `pip lock`
(`pylock.toml`) sigue siendo experimental, y `pip freeze` no es un lockfile.

Antes de elegir, aplicá esta regla en orden:

1. **Detectá lo que ya usa el repo** o el componente: `uv.lock` o `[tool.uv]`,
   `requirements*.txt` o `*.in`, `poetry.lock`, `pdm.lock`. Si hay una
   herramienta, seguí con esa. No migres por iniciativa propia: cambiar de
   herramienta es un cambio de dependencias («Ask»).
2. **Si no hay ninguna**, usá pip + pip-tools ([references/pip-tools.md](references/pip-tools.md)).
3. **Usá uv** ([references/uv.md](references/uv.md)) sólo si se cumple alguno de
   estos casos, y nombralo en la entrega:
   - el repo o el componente ya tiene `uv.lock` o `[tool.uv]`;
   - el ADR del componente eligió uv;
   - la persona lo pide explícitamente;
   - el proyecto tiene varios paquetes propios que conviene resolver con un
     solo lock (un workspace), o necesita un lock multiplataforma que
     pip-tools, que genera un lock por plataforma y versión de Python, no da;
   - la plataforma de despliegue ya provee uv y su caché.
4. **Nunca mezcles** herramientas ni lockfiles en el mismo componente. Dejá
   escrita la herramienta elegida y su motivo en la entrega.

### 0.2 Contexto a determinar

```text
MODO=        librería VAAET · aplicación
TIPO=        servicio/API · worker · CLI · librería publicada · notebook
CAMINO=      clásico: venv + pip + pip-tools (por defecto) · uv (alternativa, §0.1) · lo vigente (librería VAAET: pip + setuptools)
PYTHON=      el rango que permite el resto del sistema (ver §2)
DESPLIEGUE=  Colab · contenedor · plataforma gestionada · VM
ÍNDICE=      PyPI · proxy · índice interno para paquetes propios
```

### 0.3 Qué entregar

- **Aplicación**: archivos completos y comentados (`.python-version`,
  `pyproject.toml`, `requirements*.in/.txt` (o `uv.lock` con uv), `.gitignore`,
  `.env.example`, módulo de configuración, workflow de CI, `renovate.json` o
  `dependabot.yml`, `Dockerfile`, `.dockerignore`), con cada desviación del
  baseline justificada.
- **Librería VAAET**: hallazgos con archivo y línea, el riesgo de cada uno y
  las mejoras propuestas, ordenadas por impacto y costo, cada una con la
  decisión que necesita (plan, ADR o sólo revisión).
- **Revisión**: hallazgos con severidad, evidencia y corrección concreta.

## 1. Reglas duras

### En los dos modos

1. **Python con soporte.** Cada versión declarada está en bugfix o security, o
   tiene fecha de retiro planificada. Python 3.10 llegó a EOL en octubre de
   2026: en VAAET, proponé un plan para retirarlo (§2).
2. **Siempre en un entorno virtual** (o en el Python de Colab, que es el
   entorno del notebook). Nunca `sudo pip`, `pip install --user` ni
   `--break-system-packages` para el proyecto.
3. **Dependencias declaradas por responsabilidad**: runtime en `dependencies`,
   capacidades opcionales en extras, herramientas de dev en `[dev]` (lo
   vigente en VAAET), en `requirements-dev.in` (aplicación con pip-tools) o en
   `[dependency-groups]` (aplicación con uv). Nada del
   laboratorio (ML, DVC, Colab) en `vaaet-core` base (`AGENTS.md`).
4. **Ninguna dependencia nueva, techo nuevo ni cambio de herramienta sin
   pasar por «Ask»** (`AGENTS.md`). Explicá el motivo, el impacto en Colab y el
   costo de mantenerla.
5. **Secretos fuera de Git, logs, notebooks e imágenes.** Credenciales por
   variables de entorno o Colab Secrets (perfiles `VAAET_*`), nunca DSN
   literales ([reglas de negocio](../../../docs/product/business-rules.md),
   RN-24).

### Además, en modo aplicación

6. **Versión de Python fijada** en `.python-version` y declarada en
   `requires-python`, compatible con todas las librerías locales que consume.
7. **Herramienta fijada**: pip y pip-tools fijados en un
   `requirements-tools.txt` con hashes (con uv: `[tool.uv] required-version` y
   la misma versión en CI y Docker).
8. **Un lockfile con hashes, versionado y nunca editado a mano**:
   `requirements.txt` generado con `pip-compile --generate-hashes` (con uv:
   `uv.lock`).
9. **Instalación congelada en CI y Docker**:
   `pip install --require-hashes --no-deps -r requirements.txt` (con uv:
   `uv sync --locked`).
10. **Sólo wheels para terceros.** Un sdist se compila a wheel en un
    pipeline controlado, nunca en la instalación.
    - pip: `--only-binary :all:` en la instalación con hashes. Las librerías
      locales por ruta (el backend de VAAET) no tienen wheel ni hash: se
      instalan en un paso aparte con `pip install --no-deps`.
    - uv: `no-build = true` también bloquea las librerías locales. Con
      librerías locales, instalá en dos pasos:
      `uv sync --locked --no-install-local --no-build` y después
      `uv sync --locked`.
11. **Cooldown donde se resuelve** (`--uploaded-prior-to=P7D`; con uv,
    `exclude-newer = "7 days"`) y uno igual o mayor en el bot de
    actualizaciones. Excepciones sólo para fixes de seguridad, documentadas.
12. **Paquetes internos desde un índice explícito por paquete.** Nunca
    `--extra-index-url` para resolverlos: abre la puerta a dependency
    confusion.
13. **`pip-audit` en CI** sobre las dependencias de producción, sin
    vulnerabilidades altas o críticas abiertas sin plan.
14. **Configuración validada al arrancar**, con los secretos como `SecretStr`.
15. **Artefacto sin dependencias de dev ni toolchain**, como usuario no root y
    con apagado ordenado.

## 2. Runtime

| Versión | Estado (noviembre de 2026) | Uso |
|---|---|---|
| 3.15 | Bugfix (salió el 9/10/2026) | CI de compatibilidad; producción cuando las dependencias nativas publiquen wheels |
| 3.14 | Bugfix | Default para una aplicación nueva **fuera** de VAAET |
| 3.13 | Security desde octubre de 2026 | Hoy, el techo de VAAET |
| 3.12 / 3.11 | Security | Soportados |
| 3.10 | **EOL (octubre de 2026)** | Planificar el retiro |

Implicancias en VAAET:

- Las tres librerías declaran `requires-python = ">=3.10,<3.14"`. Por eso el
  backend de `vaaet-app`, que las instala, **hoy no puede usar 3.14**. Su
  versión la fija el ADR del componente dentro del rango que admiten las
  librerías. Ampliar ese rango es un cambio de dependencias con su propio plan
  y su matriz de CI.
- Colab decide su versión de Python, y la
  [guía de Colab](../../../docs/operations/colab-guide.md) prohíbe cambiarla
  con apt o pip. Cualquier cambio de rango se valida contra el runtime de
  Colab vigente y su runtime de respaldo.
- Retirar 3.10 implica tocar:
  - `requires-python` y los `classifiers` de los tres `pyproject.toml`;
  - la matriz del CI;
  - el `target-version` de Ruff y el `pythonVersion` de `pyrightconfig.json`;
  - la línea de versiones soportadas de la guía de Colab.

  Va con plan gobernado. Los marcadores de TensorFlow distinguen 3.13 y no
  dependen de 3.10.

En modo aplicación, `.python-version` es la única fuente (uv, pyenv y
setup-python la leen). La versión de patch se fija en la imagen base por digest.
En una aplicación, `requires-python` acota a una línea; en una librería, lleva
sólo cota inferior, salvo que haya una incompatibilidad conocida (como en
VAAET).

## 3. Elegir camino (modo aplicación)

| | Clásico: venv + pip 26.1+ + pip-tools (**por defecto**) | uv (alternativa, ver §0.1) |
|---|---|---|
| Declaración | `requirements.in` y `requirements-dev.in`; `pyproject.toml` para el propio paquete | `pyproject.toml` (`[project]`, `[dependency-groups]`) |
| Lock | `requirements.txt` con `--generate-hashes`, uno por plataforma y versión de Python | `uv.lock` multiplataforma con hashes |
| Instalación congelada | `pip install --require-hashes --no-deps -r requirements.txt` | `uv sync --locked` |
| Sólo wheels | `--only-binary :all:`; las librerías locales en un paso aparte | Sync en dos pasos si hay librerías locales |
| Cooldown | `--uploaded-prior-to=P7D` (pip ≥ 26.1; la opción todavía puede cambiar) | `exclude-newer = "7 days"` (uv ≥ 0.9.17) |
| Índices | Un solo `index-url` (proxy) | `[[tool.uv.index]]` con `explicit = true` + `[tool.uv.sources]` |
| Librerías locales | `pip install --no-deps ../vaaet-core` después del lock | `[tool.uv.sources]` con `path` |
| Disponibilidad | En todo entorno con Python, incluido Colab | Hay que instalarlo y fijar su versión |

Criterio: pip + pip-tools por defecto, porque es lo que ya existe en cualquier
entorno y lo que usan las librerías de VAAET. uv sólo en los casos de §0.1. No
mezcles herramientas ni lockfiles, ni uses `uv pip install` dentro de un
proyecto gestionado con `uv sync`.

En VAAET, la herramienta del backend la confirma el ADR de `vaaet-app`. Las
librerías siguen con pip y setuptools mientras no haya otra decisión.

Detalle y ejemplos: [references/pip-tools.md](references/pip-tools.md)
(por defecto) y [references/uv.md](references/uv.md) (alternativa).

## 4. Árbol de dependencias

| Dónde | Contiene | Error típico |
|---|---|---|
| `[project] dependencies` | Lo que se importa en runtime | Poner `pydantic` en dev porque «sólo valida» |
| `[project.optional-dependencies]` | Capacidades opcionales para consumidores (`vaaet-core[vision]`) | Meter herramientas de dev en un extra de producción |
| `[dev]` (lo vigente en VAAET) o `[dependency-groups]` (PEP 735) | Test, lint, tipos y auditoría | Instalar pytest en la imagen de producción |
| `[build-system] requires` | Backend de build (`setuptools`, `uv_build`) | Dejarlo sin cota en wheels propios críticos |

Antes de agregar una dependencia, respondé:

- ¿Lo resuelve la biblioteca estándar (`tomllib`, `zoneinfo`, `pathlib`,
  `dataclasses`, `asyncio.TaskGroup`, `secrets`)?
- ¿Publica wheels para las plataformas y versiones de Python de la matriz,
  incluida la de Colab?
- ¿Cuántas transitivas suma (`uv tree --package x` o `pipdeptree`)?
- ¿Tiene mantenimiento, trusted publishing y attestations en PyPI?
- ¿Instala archivos `.pth` o entry points que se ejecutan solos?
- ¿Es compatible con AGPL-3.0? (Ver la
  [política de licencias](../../../docs/governance/third-party-licenses.md).)
- ¿Cuánto suma a la imagen o al tiempo de import? ¿Qué pasa si se abandona?

Los overrides (`constraints.txt` en el camino clásico, `override-dependencies`
en uv) sólo sirven para parchear una transitiva vulnerable. Cada uno lleva
CVE, fecha, dueño y condición de salida en un comentario, y se revisan
mensualmente.

## 5. Supply chain por capas

| Capa | Aplicación (clásico / uv) | Librería VAAET hoy | Evita |
|---|---|---|---|
| Resolución | `--uploaded-prior-to` / `exclude-newer` | Rangos con techos | Versiones maliciosas recién publicadas |
| Fuentes | Un solo proxy / índice explícito por paquete | Sólo PyPI y rutas locales | Dependency confusion |
| Build | `--only-binary :all:` / `--no-build` sobre terceros | Wheels de PyPI (TensorFlow y OpenCV ya son wheels) | Código arbitrario de sdists |
| Lock | `pip-compile` + `git diff --exit-code` y `--require-hashes` / `uv lock --check` + `--locked` | Sin lock (Colab; cambio en «Ask») | Árboles alterados, deriva |
| Integridad | Hashes en el lock; attestations (PEP 740) | `pip check` en CI | Artefactos alterados |
| Vulnerabilidades | `pip-audit` sobre el export sin dev | No hay (propuesta) | Advisories conocidos (no malware nuevo) |
| CI | Acciones por SHA, `permissions` mínimos | Acciones por tag, sin `permissions` (propuesta) | Acciones comprometidas, tokens con exceso de alcance |

`pip-audit` encuentra advisories conocidos, no malware nuevo. El cooldown y las
fuentes explícitas son las defensas contra lo recién publicado.

## 6. Configuración y entorno

- El backend valida su configuración al arrancar con `pydantic-settings`: los
  secretos como `SecretStr`, con prefijo `VAAET_APP_`, y la identidad
  PostgreSQL propia del servicio (ADR-0028). Parte del `AppSettings` de la
  skill hexagonal, con dos diferencias: `environment` es obligatoria y
  `vision_license` es un `Literal` con las dos vías de ADR-0022.
- Las librerías leen sus perfiles `VAAET_DB_*` y `VAAET_<PROFILE>_DB_*` desde
  el entorno o Colab Secrets, como ya hacen. No cambies ese contrato sin plan.
- `.env.example` versionado, con valores ficticios y un comentario por
  variable. `.env` nunca entra a Git ni a la imagen. Producción recibe las
  variables de la plataforma o del secret manager.
- Logueá un resumen (entorno, puerto, nivel de log), nunca `os.environ` ni
  `settings.model_dump()` sin excluir los secretos.

Código y tests en [references/config-and-runtime.md](references/config-and-runtime.md).

## 7. CI y actualizaciones

- **Aplicación**: un workflow propio (`app-backend.yml`, no un job dentro de
  `ci.yml`), con filtro de rutas (`vaaet-app/**` y las librerías que consume),
  que corre:
  1. lock verificado;
  2. instalación congelada;
  3. Ruff, Pyright o mypy, y pytest;
  4. `pip-audit`;
  5. build de la imagen.

  Acciones fijadas por SHA, `permissions: { contents: read }` y
  `persist-credentials: false`. Se cachea la caché de descargas, nunca `.venv`.
- **Librería VAAET**: el CI vigente instala cada componente por separado, en
  la matriz 3.10–3.13, con `pip check`, y además prueba la instalación no
  editable (`package-smoke`). Esas garantías se conservan. Las mejoras de §5
  se proponen como un cambio de CI con plan.
- **Bots**: Renovate o Dependabot con un cooldown igual o mayor que el de la
  herramienta, para no abrir PRs que el lock va a rechazar. Automerge sólo con
  CI verde y nunca en majors. En Dependabot, los grupos con comodines pueden
  saltear el cooldown de cada paquete: agrupá con cuidado.

Workflows y configuraciones listos: [references/ci-and-updates.md](references/ci-and-updates.md).

## 8. Producción

- Imagen `-slim` (glibc) fijada por digest. Alpine obliga a compilar wheels
  nativos como OpenCV o psycopg.
- Dependencias en una capa cacheable, proyecto instalado no editable, venv
  copiado a la etapa final. Usuario no root, `CMD` en forma exec y sin uv ni
  pip en la imagen final.
- El contexto de build del backend de VAAET es la raíz del repo, porque
  instala `vaaet-core` y `vaaet-persistence` por ruta. El `.dockerignore`
  excluye `.git`, `.env*`, `.venv`, datos, videos y binarios ML.
- La imagen con `vaaet-core[vision]` (Ultralytics) sólo se distribuye por una
  vía de licencia de ADR-0022.
- Apagado ordenado: `uvicorn --timeout-graceful-shutdown`, recursos liberados
  en el `lifespan` y un timeout menor que el grace period del orquestador.

Dockerfile y ciclo de vida en [references/config-and-runtime.md](references/config-and-runtime.md).

## 9. Publicación

Hoy VAAET no publica en PyPI. Si un ADR lo decide:
- trusted publishing (OIDC) desde CI, con attestations y sin tokens de larga
  vida;
- metadatos completos y revisión del wheel;
- AGPL-3.0 declarada.

Detalle en [references/publishing.md](references/publishing.md).

## 10. Antipatrones

- `pip install` fuera de un entorno virtual, o `sudo pip`, `--user` o
  `--break-system-packages`.
- Introducir uv (o cualquier otra herramienta) por iniciativa propia en un
  repo que ya usa pip, o al revés: la regla de §0.1 manda seguir con lo que
  hay.
- `pip freeze` como lockfile: no tiene hashes y refleja una sola máquina.
- `uv sync` sin `--locked` en CI, o `--frozen` sin haber verificado antes el
  lock.
- Dos herramientas o dos lockfiles; `uv.toml` y `[tool.uv]` a la vez.
- `exclude-newer = "7 days"` con uv < 0.9.17, o cooldown sólo por CLI.
- `no-build = true` global con librerías locales por ruta: uv se niega a
  instalarlas («marked as --no-build but has no binary distribution»).
- Desactivar `no-build` u `only-binary` «para que funcione»: el sdist se
  compila en un pipeline controlado.
- `--extra-index-url` para paquetes internos, o credenciales del índice en
  `pyproject.toml`, `pip.conf` o la imagen.
- Dependencias `git+https` sin commit fijo.
- Overrides sin motivo ni fecha; techos de versión por inercia en una librería
  nueva. Los techos de VAAET tienen motivo, así que no los quites en una
  revisión.
- Herramientas de test en la imagen de producción; imágenes `latest` o sin
  digest.
- `.env` dentro de la imagen; secretos como `str`; loguear `os.environ` o la
  configuración completa.
- `CMD` en forma shell; servidor sin graceful timeout; `except Exception: pass`
  globales.
- En VAAET:
  - migrar las librerías a uv o agregarles un lockfile sin plan;
  - `!pip install` manual en un notebook;
  - instalar `vaaet-ml` en el backend;
  - subir `requires-python` sin validar Colab.

## 11. Definition of Done

**Modo aplicación**
- `.python-version` soportada y compatible con las librerías locales;
  `requires-python` coherente; herramienta elegida con la regla de §0.1,
  nombrada en la entrega y fijada en el repo, CI y Docker.
- Lock con hashes versionado y verificado en CI; instalación congelada; sólo
  wheels; cooldown en la configuración y en el bot; índices explícitos.
- `pip-audit` sin altas ni críticas abiertas; overrides documentados.
- Configuración validada al arrancar, con tests; `SecretStr`; nada sensible
  en logs, Git ni imágenes.
- Imagen sin dev, no root, fijada por digest; apagado ordenado.
- En `vaaet-app/`: plan gobernado y ADR aprobados antes del primer archivo.

**Modo librería VAAET**
- Lo vigente se respeta y queda verificado: matriz, `pip check`,
  `package-smoke` e instalación de Colab.
- Cada hallazgo tiene riesgo, evidencia y propuesta. Lo que cambia
  dependencias, CI o versiones lleva plan.

## 12. Referencias

| Archivo | Cuándo leerlo |
|---|---|
| [references/vaaet-library-mode.md](references/vaaet-library-mode.md) | Antes de revisar o proponer cambios en las tres librerías |
| [references/pip-tools.md](references/pip-tools.md) | **Camino por defecto**: configurar una aplicación con pip + pip-tools, incluido el backend de `vaaet-app` |
| [references/uv.md](references/uv.md) | Camino alternativo, sólo en los casos de §0.1 |
| [references/ci-and-updates.md](references/ci-and-updates.md) | Al escribir o revisar workflows, Renovate o Dependabot |
| [references/config-and-runtime.md](references/config-and-runtime.md) | Configuración validada, Docker y apagado ordenado |
| [references/publishing.md](references/publishing.md) | Si se decide publicar un paquete |

Fuentes:
- Python: devguide (estado de versiones) y PEP 668, 735, 740 y 751.
- pip: notas de 25.1 y 26.1; pip-tools.
- uv: Settings, Resolution, Indexes, Docker y GitHub Actions.
- pip-audit, Renovate (`minimumReleaseAge`), Dependabot (`cooldown`) y PyPI
  Trusted Publishers.
