# Publicación de paquetes

Hoy VAAET no publica en PyPI: las librerías se instalan desde el checkout. Este
archivo aplica si un ADR decide publicar, o en un proyecto nuevo.

## Antes de publicar

- `pyproject.toml` completo: `name`, `version`, `license` (en VAAET,
  `AGPL-3.0-only`), `readme`, `classifiers` y `urls`.
- `requires-python` con cota inferior; techos sólo con una incompatibilidad
  conocida y documentada.
- `py.typed` si el paquete exporta tipos.
- La política de licencias de terceros revisada: no se redistribuyen pesos,
  videos ni datasets sin procedencia
  ([reglas de negocio](../../../../docs/product/business-rules.md), RN-24, y
  ADR-0022).

## Build y revisión

```bash
uv build                      # o python -m build
uvx twine check dist/*        # metadatos y README renderizable
```

Inspeccioná el wheel con `unzip -l dist/*.whl`. No debe incluir tests, datos ni
archivos `.env`. Si hay extensiones nativas, generá wheels por plataforma con
cibuildwheel.

## Publicación

- **Trusted publishing (OIDC)** desde CI, con
  `pypa/gh-action-pypi-publish` (genera attestations PEP 740) o
  `uv publish --trusted-publishing always`.
- Un `environment` de GitHub protegido para el job de publicación, con
  `permissions: { id-token: write }` sólo en ese job.
- Sin API tokens de larga vida ni publicaciones desde una laptop. 2FA para
  todos los maintainers.
- En un proyecto nuevo, el lockfile de desarrollo se versiona aunque los
  consumidores no lo usen. En las librerías VAAET rige el modo librería:
  publicar no habilita un lockfile sin su propia decisión.
