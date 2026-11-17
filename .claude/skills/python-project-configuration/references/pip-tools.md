# Camino por defecto: venv + pip 26.1+ + pip-tools (modo aplicación)

Es el camino que usa un agente cuando el repo no tiene otra herramienta (regla
de §0.1 del `SKILL.md`). Ejemplo: el backend FastAPI de `vaaet-app`, que instala
`vaaet-core` y `vaaet-persistence` desde el mismo repo. No es el modo librería
de VAAET: las librerías no usan lock (ver [vaaet-library-mode.md](vaaet-library-mode.md)).
Verificado el 2026-11-16.

## Contenido

1. Por qué pip + pip-tools
2. Archivos
3. Librerías locales
4. Flujo de trabajo
5. Cooldown y excepciones
6. `pip.conf` e índices

## 1. Por qué pip + pip-tools

- pip está en cualquier entorno con Python, incluidos Colab y la imagen
  oficial, y es lo que ya usan las librerías de VAAET.
- pip-tools usa pip por debajo y agrega lo que pip solo todavía no da de forma
  estable: un `requirements.txt` con hashes generado desde un `.in`.
  `pip lock` (`pylock.toml`, PEP 751) sigue siendo experimental, y `pip freeze`
  no es un lockfile: mezcla directas y transitivas, no tiene hashes y refleja
  una sola máquina.
- El lock es por plataforma y por versión de Python. Generalo en la misma
  plataforma que producción (Linux x86_64 con la versión de `.python-version`),
  por ejemplo dentro de un contenedor. Si hace falta un lock multiplataforma,
  ese es uno de los casos para usar uv ([uv.md](uv.md)).

## 2. Archivos

```text
vaaet-app/
├── .python-version            versión de Python (ver §2 del SKILL.md)
├── pyproject.toml             metadatos y código del propio paquete (setuptools, como las librerías)
├── requirements-tools.in/.txt pip y pip-tools fijados, con hashes
├── requirements.in            dependencias directas de producción de terceros, con rangos
├── local-deps.in              dependencias de terceros de las librerías locales
├── requirements.txt           lock generado, con hashes, versionado
├── requirements-dev.in        -c requirements.txt + herramientas de dev y test
└── requirements-dev.txt       lock de dev, con hashes
```

```toml
# vaaet-app/pyproject.toml (ilustrativo; requiere plan y ADR aprobados)
[build-system]
requires = ["setuptools>=77.0"]
build-backend = "setuptools.build_meta"

[project]
name = "vaaet-app"
version = "0.1.0"
license = "AGPL-3.0-only"
requires-python = ">=3.13,<3.14"     # el techo lo impone vaaet-core (<3.14)
dependencies = [                      # metadatos del paquete; las versiones exactas las da el lock
  "vaaet-core==0.2.2",
  "vaaet-persistence==0.3.3",         # nunca vaaet-ml (ADR-0021)
  "fastapi>=0.120",
  "uvicorn>=0.38",
  "pydantic-settings>=2.11",
]

[tool.setuptools.packages.find]
where = ["src"]
```

```text
# requirements.in: sólo terceros, que llevan hash en el lock
fastapi>=0.120
uvicorn>=0.38
pydantic-settings>=2.11
-r local-deps.in
```

```text
# local-deps.in: copiá los requisitos de terceros de vaaet-core y vaaet-persistence
numpy>=1.26,<2.2
pandas>=2.2,<3
# ... el resto de las dependencias base de vaaet-persistence
```

```text
# requirements-dev.in
-c requirements.txt             # dev nunca cambia las versiones de producción
pytest>=8.4
httpx>=0.28
ruff>=0.14
pyright>=1.1.400,<2
pip-audit>=2.9
```

```text
# requirements-tools.in
pip>=26.1,<27
pip-tools>=7.5
```

## 3. Librerías locales

`vaaet-core`, `vaaet-persistence` y el propio `vaaet-app` **no** van en
`requirements.in`:

- No tienen hash, así que no pasan `--require-hashes`.
- No están en PyPI: pip-compile no las puede resolver por nombre.
- Según la versión, pip-compile escribe las rutas locales como `file:///`
  absolutas, lo que filtra la ruta de la máquina al lock.

Se instalan en un paso aparte, con `--no-deps`, después de las dependencias con
hash:

```bash
python -m pip install --require-hashes --no-deps --only-binary :all: -r requirements.txt
python -m pip install --no-deps ../vaaet-core ../vaaet-persistence .
python -m pip check          # falla si local-deps.in quedó desactualizado respecto de las librerías
```

`local-deps.in` existe para que las dependencias de terceros de las librerías
entren al lock con hash. Un archivo de constraints (`-c`) no alcanza: acota
versiones, pero no agrega paquetes.

## 4. Flujo de trabajo

```bash
# Una vez, en un venv nuevo
python3.13 -m venv .venv && . .venv/bin/activate
python -m pip install --require-hashes --no-deps -r requirements-tools.txt

# Generar o regenerar los locks (con el cooldown, §5)
export PIP_UPLOADED_PRIOR_TO=P7D
pip-compile --generate-hashes --strip-extras --allow-unsafe -o requirements.txt requirements.in
pip-compile --generate-hashes --strip-extras --allow-unsafe -o requirements-dev.txt requirements-dev.in
pip-compile --upgrade-package httpx --generate-hashes --strip-extras --allow-unsafe -o requirements.txt requirements.in

# Desarrollo local: el entorno queda igual al lock y después se suman las locales editables
pip-sync requirements.txt requirements-dev.txt
python -m pip install --no-deps -e ../vaaet-core -e ../vaaet-persistence -e .

# CI y producción
python -m pip install --require-hashes --no-deps --only-binary :all: -r requirements.txt
python -m pip install --no-deps ../vaaet-core ../vaaet-persistence .
python -m pip check
```

- `pip-sync` desinstala todo lo que no figura en el lock, incluidas las
  librerías locales. Por eso se vuelven a instalar después de cada `pip-sync`.
- `--allow-unsafe` incluye `pip` y `setuptools` en el lock cuando alguna
  dependencia los pide, para que `--require-hashes` no falle por ellos.
- `--require-hashes` obliga a que todo el árbol tenga hash: es la defensa
  contra tarballs alterados y contra dependencias no declaradas.
- `--only-binary :all:` impide compilar sdists de terceros en la instalación.
  Si un paquete no publica wheel, compilalo en un job dedicado con
  `--build-constraint build-constraints.txt` y publicalo en el índice interno.
- El CI regenera los locks y falla si difieren (`git diff --exit-code`): así
  detecta un `.in` modificado sin su lock. Ver [ci-and-updates.md](ci-and-updates.md).

## 5. Cooldown y excepciones

- `--uploaded-prior-to=P7D` (o `PIP_UPLOADED_PRIOR_TO=P7D`) acepta el formato
  relativo `PnD` desde pip 26.1. Sus notas de versión advierten que la opción
  puede cambiar: revisá el changelog al actualizar pip.
- pip-compile resuelve con pip por debajo. Verificá que tu versión de
  pip-tools propague `PIP_UPLOADED_PRIOR_TO` al resolver. Si no lo hace, el
  cooldown no existe y lo tiene que cubrir el bot (§6 de
  [ci-and-updates.md](ci-and-updates.md)).
- **Excepción de seguridad** dentro del plazo: regenerá el lock sin la variable
  sólo para ese paquete (`pip-compile --upgrade-package starlette==X.Y.Z`), en
  un PR con el CVE, y dejá un comentario en `requirements.in` con la fecha de
  retiro de la excepción.

## 6. `pip.conf` e índices

```ini
# pip.conf del proyecto (o variables PIP_* en CI)
[global]
require-virtualenv = true
disable-pip-version-check = true
index-url = https://pypi.example.internal/simple   # un solo proxy que también espeja PyPI
only-binary = :all:
```

- Nunca `extra-index-url` para paquetes internos: pip elige la versión más
  alta entre los índices, y un paquete público con el mismo nombre le gana al
  interno (dependency confusion).
- Las credenciales del índice van por variables (`PIP_INDEX_URL` desde un
  secreto de CI) o por keyring, nunca en `pip.conf` ni en la imagen.
- Reservá también en PyPI los nombres de paquetes internos.
