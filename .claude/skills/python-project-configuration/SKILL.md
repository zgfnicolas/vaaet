---
name: python-project-configuration
description: Configura y revisa proyectos Python reproducibles con supply chain endurecida, adaptado a VAAET. Distingue dos modos — librería (vaaet-core, vaaet-persistence y vaaet-ml, consumidas desde Colab, donde se respeta lo vigente y toda mejora se propone con plan) y aplicación (el futuro backend de vaaet-app o un proyecto nuevo, con uv.lock o pip-tools con hashes, sync --locked, exclude-newer o --uploaded-prior-to, sólo wheels, índices explícitos, pydantic-settings, pip-audit, Docker mínimo y apagado ordenado). Cubre versión de Python, dependency groups, extras, CI en GitHub Actions, Renovate o Dependabot con cooldown y trusted publishing. Usala siempre que se toque un pyproject.toml, requirements, uv.lock, pip, uv, pip-tools, la matriz de Python del CI, Dependabot o Renovate, un Dockerfile de Python o la configuración de entorno del backend, aunque no se diga «configuración». No la uses para migrar las librerías de VAAET a uv ni para agregarles lockfiles por iniciativa propia: eso es un cambio de dependencias que requiere plan y ADR.
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

### 0.1 Contexto a determinar

```text
MODO=        librería VAAET · aplicación
TIPO=        servicio/API · worker · CLI · librería publicada · notebook
CAMINO=      uv · clásico (venv + pip + pip-tools) · lo vigente (librería VAAET: pip + setuptools)
PYTHON=      el rango que permite el resto del sistema (ver §2)
DESPLIEGUE=  Colab · contenedor · plataforma gestionada · VM
ÍNDICE=      PyPI · proxy · índice interno para paquetes propios
```

### 0.2 Qué entregar

- **Aplicación**: archivos completos y comentados (`.python-version`,
  `pyproject.toml`, `uv.lock` o `requirements*.in/.txt`, `.gitignore`,
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
   vigente en VAAET) o en `[dependency-groups]` (aplicación). Nada del
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
7. **Herramienta fijada**: `[tool.uv] required-version` y la versión de uv
   fijada en CI y Docker, o pip y pip-tools fijados en un
   `requirements-tools.txt` con hashes.
8. **Un lockfile con hashes, versionado y nunca editado a mano**: `uv.lock` o
   `requirements.txt` generado con `pip-compile --generate-hashes`.
9. **Instalación congelada en CI y Docker**: `uv sync --locked`, o
   `pip install --require-hashes --no-deps -r requirements.txt`.
10. **Sólo wheels para terceros.** Un sdist se compila a wheel en un
    pipeline controlado, nunca en la instalación.
    - Sin librerías locales: `no-build = true` o `--only-binary :all:`.
    - Con librerías locales por ruta, como el backend de VAAET: `no-build`
      también bloquea esas librerías, porque no tienen wheel. Instalá en dos
      pasos: `uv sync --locked --no-install-local --no-build` (sólo wheels de
      terceros) y después `uv sync --locked` (construye sólo lo local).
11. **Cooldown donde se resuelve** (`exclude-newer = "7 days"` o
    `--uploaded-prior-to=P7D`) y uno igual o mayor en el bot de
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

| | uv (recomendado) | Clásico (venv + pip 26.1+ + pip-tools) |
|---|---|---|
| Declaración | `pyproject.toml` (`[project]`, `[dependency-groups]`) | `requirements.in` y `requirements-dev.in` |
| Lock | `uv.lock` multiplataforma con hashes | `requirements.txt` por plataforma, con `--generate-hashes` |
| Instalación congelada | `uv sync --locked` | `pip install --require-hashes --no-deps -r requirements.txt` |
| Sólo wheels | `no-build = true`, o el sync en dos pasos si hay librerías locales | `--only-binary :all:` y las locales en un paso aparte |
| Cooldown | `exclude-newer = "7 days"` (uv ≥ 0.9.17) | `--uploaded-prior-to=P7D` (pip ≥ 26.1; la opción todavía puede cambiar) |
| Índices | `[[tool.uv.index]]` con `explicit = true` + `[tool.uv.sources]` | Un solo `index-url` (proxy) |
| Librerías locales | `[tool.uv.sources]` con `path` | Rutas locales en el `.in` |

Criterio: uv por defecto. El camino clásico, cuando la plataforma sólo permite
pip o en repos donde pip-tools ya funciona. No mezcles herramientas ni
lockfiles, ni uses `uv pip install` dentro de un proyecto gestionado con
`uv sync`.

En VAAET, la herramienta del backend la decide el ADR de `vaaet-app`. Las
librerías siguen con pip y setuptools mientras no haya otra decisión.

Detalle y ejemplos: [references/uv.md](references/uv.md) y
[references/pip-tools.md](references/pip-tools.md).

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

Los overrides (`override-dependencies` en uv, `constraints.txt` en el camino
clásico) sólo sirven para parchear una transitiva vulnerable. Cada uno lleva
CVE, fecha, dueño y condición de salida en un comentario, y se revisan
mensualmente.

## 5. Supply chain por capas

| Capa | Aplicación (uv / clásico) | Librería VAAET hoy | Evita |
|---|---|---|---|
| Resolución | `exclude-newer` / `--uploaded-prior-to` | Rangos con techos | Versiones maliciosas recién publicadas |
| Fuentes | Índice explícito por paquete / un solo proxy | Sólo PyPI y rutas locales | Dependency confusion |
| Build | `--no-build` sobre terceros / `--only-binary :all:` | Wheels de PyPI (TensorFlow y OpenCV ya son wheels) | Código arbitrario de sdists |
| Lock | `uv lock --check` + `--locked` / `--require-hashes` | Sin lock (Colab; cambio en «Ask») | Árboles alterados, deriva |
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

- **Aplicación**: un job propio con filtro de rutas (`vaaet-app/**` y las
  librerías que consume) que corre:
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
  `requires-python` coherente; herramienta fijada en el repo, CI y Docker.
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
| [references/uv.md](references/uv.md) | Al configurar un proyecto con uv, incluido el backend de `vaaet-app` |
| [references/pip-tools.md](references/pip-tools.md) | Si el camino es pip + pip-tools |
| [references/ci-and-updates.md](references/ci-and-updates.md) | Al escribir o revisar workflows, Renovate o Dependabot |
| [references/config-and-runtime.md](references/config-and-runtime.md) | Configuración validada, Docker y apagado ordenado |
| [references/publishing.md](references/publishing.md) | Si se decide publicar un paquete |

Fuentes:
- Python: devguide (estado de versiones) y PEP 668, 735, 740 y 751.
- uv: Settings, Resolution, Indexes, Docker y GitHub Actions.
- pip: notas de 25.1 y 26.1; pip-tools.
- pip-audit, Renovate (`minimumReleaseAge`), Dependabot (`cooldown`) y PyPI
  Trusted Publishers.
