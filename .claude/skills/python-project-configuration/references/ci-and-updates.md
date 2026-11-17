# CI y actualizaciones

## Contenido

1. Reglas comunes de GitHub Actions
2. Job uv para el backend de `vaaet-app`
3. Variante clásica (pip-tools)
4. Auditoría de vulnerabilidades
5. Renovate y Dependabot
6. Cooldown del bot

Agregar o cambiar un job de `.github/workflows/ci.yml` es un cambio de CI de la
raíz: lleva su plan y se revisa como cualquier otro cambio.

## 1. Reglas comunes de GitHub Actions

- `permissions: { contents: read }` a nivel de workflow. Sólo un job que lo
  necesite pide más, y lo declara él mismo.
- Acciones fijadas por SHA, con el tag en un comentario (`# v5`). Un bot las
  actualiza.
- `actions/checkout` con `persist-credentials: false`.
- `concurrency` con `cancel-in-progress` en PRs.
- Cachear la caché de descargas (uv o `~/.cache/pip`), nunca `.venv`.
- Ningún secreto en `run:` con `echo` ni en logs. Las credenciales del índice,
  por `secrets.*` y variables de entorno.

## 2. Job uv para el backend de `vaaet-app`

```yaml
# Fragmento para .github/workflows/ci.yml (ilustrativo; requiere plan y ADR)
  app-backend:
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    defaults: { run: { working-directory: vaaet-app } }
    steps:
      - uses: actions/checkout@<sha>          # v4
        with: { persist-credentials: false }
      - uses: astral-sh/setup-uv@<sha>        # vX
        with: { version: "0.13.<patch>", enable-cache: true }   # la misma que [tool.uv] required-version
      - run: uv python install                # .python-version
      - run: uv lock --check
      - run: uv sync --locked --no-install-local --no-build      # terceros sólo como wheels
      - run: uv sync --locked                                    # librerías locales y proyecto
      - run: uv run --frozen ruff check .     # --frozen: el lock ya se verificó arriba
      - run: uv run --frozen ruff format --check .
      - run: uv run --frozen pyright
      - run: uv run --frozen lint-imports     # contratos de la skill hexagonal
      - run: uv run --frozen pytest
      - name: Auditoría de dependencias de producción
        run: |
          uv export --locked --no-dev --no-emit-project \
            --no-emit-package vaaet-core --no-emit-package vaaet-persistence \
            --format requirements.txt -o .audit-requirements.txt
          uv run --frozen pip-audit -r .audit-requirements.txt --require-hashes --disable-pip --strict
```

- El filtro de rutas del workflow suma `vaaet-app/**`, `vaaet-core/**` y
  `vaaet-persistence/**`: un cambio en una librería también tiene que probar
  el backend que la consume.
- `--no-emit-project` deja afuera el propio proyecto, pero las librerías
  locales se siguen exportando sin hash y `--require-hashes` las rechazaría:
  por eso `--no-emit-package`. Sus dependencias de terceros sí quedan en el
  export y se auditan.
- Matriz opcional con la siguiente versión de Python como job no bloqueante.

## 3. Variante clásica (pip-tools)

```yaml
      - uses: actions/setup-python@<sha>      # v5
        with:
          python-version-file: .python-version
          cache: pip
          cache-dependency-path: requirements*.txt
      - run: python -m venv .venv && echo "$PWD/.venv/bin" >> "$GITHUB_PATH"
      - run: python -m pip install --require-hashes --no-deps --only-binary :all: -r requirements-tools.txt
      - run: pip-compile --generate-hashes --strip-extras -o requirements.txt requirements.in && git diff --exit-code requirements.txt
      - run: python -m pip install --require-hashes --no-deps --only-binary :all: -r requirements.txt -r requirements-dev.txt
      - run: python -m pip check
      - run: ruff check . && ruff format --check . && pytest
      - run: pip-audit -r requirements.txt --require-hashes --disable-pip --strict
```

`git diff --exit-code` después de `pip-compile` detecta un lock que no
corresponde a los `.in`.

## 4. Auditoría de vulnerabilidades

- `pip-audit --disable-pip` sólo funciona con requirements con hashes o con
  `--no-deps`. `--strict` falla si no pudo recolectar una dependencia: es lo
  que se quiere en CI.
- Para las librerías de VAAET, que no tienen lock, la propuesta 3 de
  [vaaet-library-mode.md](vaaet-library-mode.md) (con plan) es un job no
  bloqueante que instale el componente con sus extras y corra `pip-audit` sobre
  el entorno. Volvelo bloqueante cuando exista la política de excepciones
  (las CVEs de TensorFlow sin fix son un caso típico).
- `pip-audit` detecta advisories conocidos, no malware nuevo.

## 5. Renovate y Dependabot

```json
{
  "extends": ["config:recommended"],
  "minimumReleaseAge": "7 days",
  "internalChecksFilter": "strict",
  "lockFileMaintenance": { "enabled": true, "schedule": ["before 6am on monday"] },
  "packageRules": [
    { "matchManagers": ["pep621", "pip-compile"], "matchUpdateTypes": ["patch", "minor"], "groupName": "python non-major" },
    { "matchUpdateTypes": ["major"], "automerge": false, "labels": ["major-upgrade"] }
  ],
  "vulnerabilityAlerts": { "minimumReleaseAge": null }
}
```

- `internalChecksFilter: "strict"` (el default) hace que Renovate no cree la
  rama hasta que se cumple el cooldown.
- Usá Renovate ≥ 44.61.3: las versiones anteriores tenían un bypass de
  `minimumReleaseAge` al pedir un rebase del PR.

```yaml
# .github/dependabot.yml (alternativa)
version: 2
updates:
  - package-ecosystem: uv            # "pip" para pip-tools o para las librerías VAAET
    directory: /vaaet-app
    schedule: { interval: weekly }
    cooldown: { default-days: 7 }
    groups:
      non-major: { update-types: [minor, patch] }
  - package-ecosystem: github-actions
    directory: /
    schedule: { interval: weekly }
    cooldown: { default-days: 7 }
```

- `cooldown.default-days` va de 1 a 90. `semver-major-days` y similares sólo
  aplican en ecosistemas con SemVer: verificá el soporte del ecosistema antes
  de usarlos.
- Un grupo con comodines puede saltear el cooldown: si un paquete del grupo
  califica, se dispara el grupo entero. Preferí grupos por tipo de update.
- Para las librerías de VAAET, empezá sólo con `github-actions` (propuesta 2
  de [vaaet-library-mode.md](vaaet-library-mode.md)). Las dependencias Python
  necesitan su ADR.

## 6. Cooldown del bot

El cooldown del bot es igual o mayor que el de la herramienta (`exclude-newer`
o `--uploaded-prior-to`). Si es menor, abre PRs que el lock rechaza. Las
excepciones de seguridad se resuelven con `vulnerabilityAlerts` en Renovate, o
con un PR manual con `exclude-newer-package`, nunca bajando el cooldown global.
