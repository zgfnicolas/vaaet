# Camino clásico: venv + pip 26.1+ + pip-tools (modo aplicación)

Para cuando la plataforma o la política sólo permiten pip, o en repos donde
pip-tools ya funciona bien. No es el modo librería de VAAET: las librerías no
usan lock (ver [vaaet-library-mode.md](vaaet-library-mode.md)).

## Archivos

```text
requirements-tools.in / .txt   pip y pip-tools fijados, con hashes
requirements.in                dependencias directas de producción, con rangos
requirements.txt               lock generado, con hashes, versionado
requirements-dev.in            -c requirements.txt + herramientas de dev y test
requirements-dev.txt           lock de dev, con hashes
```

```text
# requirements.in: sólo terceros, que llevan hash en el lock
fastapi>=0.120
uvicorn[standard]>=0.38
pydantic-settings>=2.11
-r local-deps.in                # dependencias de terceros de las librerías locales, copiadas de sus pyproject
```

```text
# requirements-dev.in
-c requirements.txt             # dev nunca cambia las versiones de producción
pytest>=8.4
ruff>=0.14
pip-audit>=2.9
```

Las librerías locales (`../vaaet-core`, `../vaaet-persistence`) **no** van en
`requirements.in`. No tienen hash, y según la versión, pip-compile las escribe
como rutas `file:///` absolutas, lo que filtra la ruta de la máquina al lock.
Se instalan en un paso aparte, con `--no-deps`, después de las dependencias
con hash:

```bash
python -m pip install --require-hashes --no-deps --only-binary :all: -r requirements.txt
python -m pip install --no-deps ../vaaet-core ../vaaet-persistence
python -m pip check                      # verifica que el lock cubra lo que piden las locales
```

`local-deps.in` repite los requisitos de terceros de las librerías locales
(`numpy>=1.26,<2.2`, `pandas>=2.2,<3`, etcétera), para que entren al lock con
hash. Un archivo de constraints (`-c`) no alcanza: acota versiones, pero no
agrega paquetes. Si una librería cambia sus dependencias y `local-deps.in` no
se actualiza, `pip check` lo detecta.

## Flujo

```bash
python3.13 -m venv .venv && . .venv/bin/activate
python -m pip install --require-hashes --no-deps -r requirements-tools.txt

export PIP_UPLOADED_PRIOR_TO=P7D            # cooldown al resolver (pip >= 26.1)
pip-compile --generate-hashes --strip-extras -o requirements.txt requirements.in
pip-compile --generate-hashes --strip-extras -o requirements-dev.txt requirements-dev.in
pip-compile --upgrade-package httpx --generate-hashes -o requirements.txt requirements.in

pip-sync requirements.txt requirements-dev.txt             # local: el entorno queda igual al lock
python -m pip install --require-hashes --no-deps --only-binary :all: -r requirements.txt   # CI y producción
python -m pip check
```

- pip-compile resuelve con pip por debajo. Verificá que tu versión de
  pip-tools propague `PIP_UPLOADED_PRIOR_TO` al resolver; si no lo hace, el
  cooldown no existe y lo tiene que cubrir el bot (§6 de
  [ci-and-updates.md](ci-and-updates.md)).
- `--uploaded-prior-to` acepta el formato relativo `PnD` desde pip 26.1. Sus
  notas de versión advierten que la opción puede cambiar en versiones
  futuras: revisá el changelog al actualizar pip.
- `pip freeze` no es un lockfile: mezcla directas y transitivas, no tiene
  hashes y refleja una sola máquina.
- `--require-hashes` obliga a que todo el árbol tenga hash: es la defensa
  contra tarballs alterados y dependencias no declaradas.
- `pip lock` y `pip install -r pylock.toml` (PEP 751) siguen siendo
  experimentales: usalos como formato de intercambio, no como lock primario.
- Para wheels propios, `--build-constraint build-constraints.txt`.

## `pip.conf` del proyecto (o variables `PIP_*` en CI)

```ini
[global]
require-virtualenv = true
disable-pip-version-check = true
index-url = https://pypi.example.internal/simple   # proxy único que también espeja PyPI
only-binary = :all:
```

Nunca `extra-index-url` para paquetes internos.
