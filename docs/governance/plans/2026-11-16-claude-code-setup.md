# Plan de ejecución: configuración del repositorio para Claude Code

- Fecha de inicio: 2026-11-16
- Estado global: Completado
- Ticket, issue o PR vinculado: [#33](https://github.com/zgfnicolas/vaaet/pull/33)

## 1. Contexto y restricciones

El repositorio sólo tenía `CLAUDE.md` con `@AGENTS.md`. Claude Code no carga los
`AGENTS.md` de componente (lee `CLAUDE.md` por directorio), no ve las skills de
`.codex/` y no tenía permisos, hooks ni subagentes: las reglas críticas eran
sólo instrucciones. Este plan agrega las garantías (permisos y hooks) y el
contexto propio de Claude Code sin duplicar `AGENTS.md` ni las skills de Codex.

- Fuentes: [`AGENTS.md`](../../../AGENTS.md), RN-21 y RN-24 de las
  [reglas de negocio](../../product/business-rules.md) y
  [ADR-0037](../../architecture/decisions/0037-migration-0003-bind-literal-correction.md).
- Módulos afectados: `.claude/`, `CLAUDE.md` raíz y de componente,
  `.gitignore`, filtro de rutas del CI, documentación de agentes y tests de
  repositorio.
- Invariantes: no cambian código de producción, contratos, dependencias ni
  jobs de CI. No se agrega `.mcp.json`: `gh` cubre GitHub y un MCP de
  PostgreSQL expondría credenciales.

Decisiones humanas del 2026-11-16: alcance completo; skills `validate`,
`pg-integration`, `open-pr` y `governed-plan`; crear `CLAUDE.local.md`.

**Directiva de integridad:** ejecutar una fase, mostrar evidencia y esperar el
ACK humano antes de la siguiente.

## 2. Versionado y trazabilidad

- Commit propuesto por fase con scope `config` o `docs`.
- Commit, push y PR sólo con autorización explícita.

## 3. Fases de ejecución HITL

### [Completada] Fase 1: garantías y carga de contexto

- [x] Entradas de Claude Code en `.gitignore`.
- [x] `.claude/settings.json` con `allow`, `ask` y `deny`.
- [x] `CLAUDE.md` raíz con la sección propia de Claude Code y `CLAUDE.md` por
      componente.
- [x] Tests de configuración.
- Review humano (ACK): Aprobado por el responsable técnico (2026-11-16)
- Commit propuesto: `git commit -m "chore(config): configurá permisos y contexto de Claude Code"`

### [Completada] Fase 2: hooks

- [x] `guard_paths.py` (`PreToolUse`) y `session_context.py` (`SessionStart`),
      con salida UTF-8 para Windows.
- [x] Tests que ejecutan los hooks con JSON de ejemplo.
- [x] Cerrar el plan de la migración `0003`, que seguía «En progreso» aunque el
      PR #32 ya estaba integrado.
- Review humano (ACK): Aprobado por el responsable técnico (2026-11-16)
- Commit propuesto: `git commit -m "chore(config): agregá hooks de protección y contexto"`

### [Completada] Fase 3: reglas, skills y subagentes

- [x] Cinco reglas con `paths` que apuntan a las skills de `.codex/`.
- [x] Skills `validate`, `pg-integration`, `open-pr` y `governed-plan`;
      plantilla única de planes en `docs/governance/plans/TEMPLATE.md`.
- [x] Subagentes de sólo lectura `vaaet-reviewer` y `ci-investigator`.
- [x] Scripts de `pg-integration` probados de punta a punta: sólo fallan las
      dos aserciones que exigen `pg_restore` 17.
- Desviación: el primer `run` falló en un test de zonas horarias porque
  `initdb` tomó la zona del sistema; el servidor arranca ahora en UTC, como el
  CI.
- Review humano (ACK): Aprobado por el responsable técnico (2026-11-16)
- Commit propuesto: `git commit -m "chore(config): agregá reglas, skills y subagentes de Claude Code"`

### [Completada] Fase 4: documentación, CI y entorno local

- [x] `docs/index.md`, `CONTRIBUTING.md`, skill de context engineering,
      filtro de rutas del CI y `CHANGELOG.md`.
- [x] `CLAUDE.local.md` no versionado, con las notas del entorno local.
- [x] Revisión del subagente `vaaet-reviewer` y corrección de sus hallazgos
      (ver abajo).
- Review humano (ACK): Aprobado por el responsable técnico (2026-11-16)
- Commit propuesto: `git commit -m "docs(config): documentá la configuración de Claude Code"`

## 4. Criterios de aceptación

- [x] `pytest tests/repository` en `vaaet-ml/`, Ruff y `git diff --check` pasan.
- [ ] `/permissions`, `/hooks`, `/agents` y el menú `/` muestran la
      configuración sin reglas inválidas.
- [x] Editar una revisión Alembic publicada, un secreto o un binario ML queda
      bloqueado por permisos o hooks (probado ejecutando el hook).

### Checklist de la guía de configuración

| Ítem | Resultado |
|---|---|
| `AGENTS.md` con comandos, reglas, límites y contradicciones | Sí, 147 líneas |
| `CLAUDE.md` importa `@AGENTS.md` y suma menos de 200 líneas | Sí, 163 en total |
| `deny` para `.env`, secretos y comandos peligrosos | Sí; `.env.example` sigue legible |
| `.gitignore` con los tres archivos personales y temporales | Sí |
| Ningún secreto real en el proyecto | Sí, sólo `vaaet-ml/.env.example` |
| Reglas con `paths` | Las cinco |
| `.mcp.json` | No se agrega: `gh` cubre GitHub |
| Skills con efectos usan `disable-model-invocation` | `pg-integration` y `open-pr` |
| Subagentes revisores de sólo lectura y sin worktree | Los dos |
| Hooks registrados, ejecutables y con `exit 2` | Sí; se invocan con `python3` |
| `/permissions`, `/hooks`, `/agents` sin errores | Pendiente: verificación manual al reiniciar |

### Revisión de `vaaet-reviewer` (2026-11-16)

Sin violaciones de RN-xx, imports cruzados, binarios ni secretos reales. Se
corrigieron:

- **Bloqueante:** `guard_paths.py` bloqueaba una revisión Alembic nueva en
  cuanto existía en disco. Ahora sólo considera publicada la que existe en
  `origin/main` o `main`, con un test sobre un repo Git temporal.
- **Bloqueante:** los scripts de `pg-integration` podían borrar bases de otra
  instancia en el mismo puerto. Ahora verifican `SHOW data_directory` antes de
  arrancar o borrar.
- `deny` ampliado a variantes de `push --force`, `git clean`, `rm -fr` y
  `alembic downgrade`. `cat` restringido a `.env` y `.env.local`, para que
  `.env.example` siga legible. `git branch` acotado a lectura. `ask` para
  editar `.claude/settings.json` y `.claude/hooks/`.
- `guard_paths.py` bloquea ante un error inesperado y compara la ruta privada
  sin distinguir mayúsculas.
- La auditoría de `run_ci_steps.sh` verifica la revisión `head` y no corta el
  script si falla.
- `validate` incluye Pyright para `vaaet-ml` y reemplaza `git stash` por un
  worktree de `main`.
- `CLAUDE.md` aclara que el hook cubre las herramientas de edición, no el
  shell.

Limitaciones aceptadas:

- Los subagentes son de sólo lectura por su prompt, no por una restricción:
  tienen `Bash` para consultar Git y GitHub.
- Las reglas `deny` de Bash son la mejor protección por patrón, no una
  garantía ante cualquier variante de un comando.

## 5. Post-mortem y ajuste sistémico

- Desviación o bloqueo: el primer `run` de `pg-integration` falló por la zona
  horaria del servidor, y la revisión encontró dos bloqueantes. Todo quedó
  corregido antes del commit.
- Causa y alcance: scripts y hooks nuevos, sin efecto en producción.
- Ajuste reutilizable: pasar cada configuración nueva por `vaaet-reviewer`
  antes del commit.
- Decisión humana: ACK del plan completo y pedido de commit y PR (2026-11-16)
