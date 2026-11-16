---
paths:
  - "vaaet-ml/notebooks/**"
---

# Notebooks

- Los notebooks sólo orquestan módulos probados: sin lógica nueva, sin
  `sys.path` y con la instalación de core, persistencia y ML en ese orden.
- Al editarlos, corré desde `vaaet-ml/`: `ruff check notebooks --select F821`
  y `python ../.codex/skills/vaaet-notebook-orchestration/scripts/audit_notebooks.py notebooks`.
- Guía de dominio: `.codex/skills/vaaet-notebook-orchestration/SKILL.md`.
