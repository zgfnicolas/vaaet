# Camino alternativo: uv (modo aplicación)

**No es el camino por defecto.** Un agente usa pip + pip-tools
([pip-tools.md](pip-tools.md)) salvo que se cumpla alguno de estos casos, que
tiene que nombrar en la entrega:

- el repo o el componente ya tiene `uv.lock` o `[tool.uv]` (seguir con lo que
  hay);
- el ADR del componente eligió uv;
- la persona lo pide explícitamente;
- hay varios paquetes propios que conviene resolver con un solo lock (un
  workspace), o hace falta un lock multiplataforma (pip-tools genera uno por
  plataforma y versión de Python);
- la plataforma de despliegue ya provee uv y su caché.

Qué aporta uv en esos casos: un lock multiplataforma con hashes, el cooldown
registrado en el lock (`exclude-newer`), índices explícitos por paquete y una
resolución mucho más rápida. El costo es una herramienta más que instalar y
fijar en cada entorno.

Ejemplo: el backend FastAPI de `vaaet-app`, que instala `vaaet-core` y
`vaaet-persistence` desde el mismo repo. Versiones verificadas el 2026-11-16
(uv 0.13.7).

## Contenido

1. `pyproject.toml`
2. Comandos
3. Cooldown y excepciones
4. Índices privados
5. Librerías locales y workspaces

## 1. `pyproject.toml`

```toml
# vaaet-app/pyproject.toml (ilustrativo; requiere plan y ADR aprobados)
[project]
name = "vaaet-app"
version = "0.1.0"
license = "AGPL-3.0-only"
requires-python = ">=3.13,<3.14"     # el techo lo impone vaaet-core (<3.14)
dependencies = [
  "vaaet-core==0.2.2",               # pin exacto, como el resto del monorepo
  "vaaet-persistence==0.3.3",        # nunca vaaet-ml (ADR-0021)
  "fastapi>=0.120",
  "uvicorn[standard]>=0.38",
  "pydantic-settings>=2.11",
  "anyio>=4.6",
  "typer>=0.20",
]

[project.optional-dependencies]
worker = ["vaaet-core[vision,inference]==0.2.2"]    # sólo la imagen del worker

[dependency-groups]                  # PEP 735: no se publican ni van a producción
test = ["pytest>=8.4", "httpx>=0.28", "asgi-lifespan>=2.1"]
dev = [
  { include-group = "test" },
  "ruff>=0.14",
  "pyright>=1.1.400,<2",
  "import-linter>=2.5",
  "pip-audit>=2.9",
]

[tool.uv]
required-version = ">=0.13,<0.14"   # la minor fijada en CI y Docker; exclude-newer relativo exige >= 0.9.17
exclude-newer = "7 days"             # cooldown: lo publicado hace < 7 días no se resuelve
default-groups = ["dev"]             # uv sync local instala dev; producción usa --no-dev
# Sin no-build = true global: bloquearía vaaet-core y vaaet-persistence, que no tienen wheel.
# Los terceros se instalan sólo como wheels con el sync en dos pasos (§2).

[tool.uv.sources]
vaaet-core = { path = "../vaaet-core" }
vaaet-persistence = { path = "../vaaet-persistence" }

[build-system]
requires = ["uv_build>=0.13,<0.14"]     # la misma minor que uv; o setuptools, como las librerías (lo decide el ADR)
build-backend = "uv_build"
```

- **Aplicación**: cotas inferiores en `pyproject.toml`; la exactitud la da
  `uv.lock`. **Librería**: rangos amplios y techos sólo con una
  incompatibilidad conocida.
- El cooldown va en `pyproject.toml`, no sólo en la CLI, para que aplique a
  cada `uv lock` y `uv sync`.
- Un `uv.toml` junto al `pyproject.toml` hace que uv ignore `[tool.uv]`: usá
  uno u otro.
- **`no-build = true` global también bloquea las librerías locales por ruta**,
  porque no tienen wheel: `uv sync` falla con «marked as `--no-build` but has
  no binary distribution» (verificado con uv 0.13.7). Usalo sólo en proyectos
  sin dependencias locales. Con librerías locales, aplicá `--no-build` en el
  paso de terceros (§2).
- Si un paquete de terceros no publica wheel, compilalo en un job dedicado y
  publicalo en el índice interno. No habilites builds de sdists en la
  instalación.
- El extra `worker` existe para que la imagen web no instale Ultralytics ni
  TensorFlow (ver la skill hexagonal). Distribuir la imagen del worker exige
  una vía de licencia de ADR-0022.

## 2. Comandos

```bash
uv python install                      # lee .python-version
uv sync                                # entorno local (incluye default-groups)
uv add httpx                           # agrega y re-lockea, respetando el cooldown
uv add --group test respx
uv lock --upgrade-package httpx        # actualización puntual y revisable
uv run --env-file .env -- uvicorn vaaet_app.bootstrap.app:create_app --factory --reload
uv lock --check                        # CI: falla si uv.lock no corresponde a pyproject.toml
uv sync --locked --no-dev --no-install-local --no-build   # paso 1: sólo wheels de terceros
uv sync --locked --no-dev                                 # paso 2: construye sólo las librerías locales y el proyecto
uv sync --locked --no-dev --extra worker
uv export --locked --no-dev --no-emit-project --no-emit-package vaaet-core --no-emit-package vaaet-persistence \
  --format requirements.txt -o .audit-requirements.txt      # las locales no tienen hash
```

- `--locked` (falla si el lock está desactualizado) en CI. `--frozen` (no
  verifica) sólo en un paso posterior a la verificación.
- `uv export --format pylock.toml` produce un PEP 751 portable, para
  herramientas que lo necesiten.

## 3. Cooldown y excepciones

- `exclude-newer = "7 days"` requiere uv ≥ 0.9.17. Las versiones anteriores
  fallan al leerlo como fecha.
- El lock guarda el plazo, no una fecha: `exclude-newer-span = "P7D"` en
  `[options]`, junto a un `exclude-newer` neutro que sólo existe por
  compatibilidad (verificado con uv 0.13.7). Por eso el cooldown no se vuelve
  viejo ni invalida el lock con el paso de los días. Si una versión vieja de uv
  hace fallar `uv sync --locked` en el deploy, actualizá uv antes de debilitar
  el cooldown.
- **Excepción de seguridad** dentro del plazo: en un PR con el CVE y la fecha
  de retiro de la excepción,

  ```toml
  [tool.uv]
  exclude-newer-package = { starlette = false }   # CVE-2026-XXXX; retirar el 2026-12-01 (@owner)
  ```

  No uses `--exclude-newer` por CLI: no queda registrado.

## 4. Índices privados

```toml
[[tool.uv.index]]
name = "internal"
url = "https://pypi.example.internal/simple"
explicit = true                    # sólo lo usan los paquetes asignados en [tool.uv.sources]

[tool.uv.sources]
acme-contracts = { index = "internal" }
```

- Las credenciales van por variables (`UV_INDEX_INTERNAL_USERNAME` y
  `UV_INDEX_INTERNAL_PASSWORD`), nunca en el archivo. En Docker, por
  `--mount=type=secret`.
- La estrategia por defecto de uv (`first-index`) evita que un paquete con el
  mismo nombre en PyPI le gane a uno interno. No la cambies a
  `unsafe-best-match`.
- Reservá también en PyPI los nombres de paquetes internos.

## 5. Librerías locales y workspaces

- En VAAET, el backend consume las librerías por `path`. **No** conviertas el
  monorepo en un workspace de uv: las librerías se instalan con pip en Colab y
  en su CI. Un workspace es una decisión de arquitectura del repo, con su ADR.
- Si una aplicación nueva tiene varios paquetes propios, un workspace con un
  solo lock en la raíz es lo adecuado:

  ```toml
  [tool.uv.workspace]
  members = ["apps/*", "packages/*"]
  ```

  Para trabajar por miembro: `uv sync --package <nombre>` y
  `uv run --package <nombre> pytest`.
