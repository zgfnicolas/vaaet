---
paths:
  - "docs/**"
  - "**/AGENTS.md"
  - "**/CLAUDE.md"
  - "README.md"
  - "CONTRIBUTING.md"
---

# Documentación y contexto para agentes

- Un tema, un lugar: enlazá el documento responsable en lugar de copiarlo. Los
  ADRs se listan sólo en `docs/architecture/decisions/README.md`.
- No escribas versiones ni fechas de revisión en documentos vigentes; la
  versión vive en cada `pyproject.toml`.
- `AGENTS.md` raíz debe quedar en menos de 150 líneas y, sumado a `CLAUDE.md`,
  en menos de 200.
- Validá con `pytest tests/repository` desde `vaaet-ml/`.
