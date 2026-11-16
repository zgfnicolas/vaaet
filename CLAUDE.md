@AGENTS.md

## Sólo para Claude Code

- Cada componente tiene su `CLAUDE.md`, que carga su `AGENTS.md` al trabajar
  ahí. Las reglas de `.claude/rules/` se cargan por ruta con lo no obvio de
  cada zona.
- Empezá en plan mode antes de tocar contratos, `vaaet-core/src/vaaet/`,
  `vaaet-persistence/` o migraciones, y esperá la aprobación.
- Si un plan gobernado está «En progreso», ejecutá sólo la fase marcada como
  actual y detenete al terminarla.
- Para validar, usá la skill `validate`; para revisar antes de un PR, el
  subagente `vaaet-reviewer`; para una falla de CI, `ci-investigator`.
- Los permisos y el hook `guard_paths.py` bloquean editar secretos, binarios
  ML, archivos DVC y revisiones Alembic publicadas con las herramientas de
  edición; los comandos de shell sólo los frenan los permisos. Si un bloqueo
  es legítimo, pedile a una persona que haga el cambio; no busques otra vía.
