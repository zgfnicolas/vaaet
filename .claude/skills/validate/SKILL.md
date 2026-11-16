---
name: validate
description: Corre los quality gates de VAAET sobre los componentes que cambiaron (Ruff, Pyright, pytest, compileall, notebooks y tests de repositorio). Usala antes de dar una tarea por terminada, antes de un commit o cuando se pida validar, testear o verificar cambios.
allowed-tools: Bash(git status *) Bash(git diff *) Bash(ruff check *) Bash(pytest *) Bash(python -m pytest *) Bash(pyright *) Bash(python -m compileall *)
---

# Validar cambios

1. Listá lo cambiado: `git diff --name-only main...HEAD` más `git status --short`.
   Agrupá por componente: `vaaet-core/`, `vaaet-persistence/`, `vaaet-ml/` y
   raíz (`docs/`, `.claude/`, `.github/`, `*.md`).
2. Por cada componente afectado, corré desde su carpeta los comandos de su
   `AGENTS.md`:

   | Componente | Comandos |
   |---|---|
   | `vaaet-core/` | `ruff check src tests`, `pyright --project ../pyrightconfig.json`, `pytest tests -m "not postgres"`, `python -m compileall -q src tests` |
   | `vaaet-persistence/` | `ruff check src tests`, `pyright src`, `pytest -m "not postgres"`, `python -m compileall -q src` |
   | `vaaet-ml/` | `ruff check src tests scripts migrations`, `pyright --project ../pyrightconfig.json`, `pytest tests -m "not postgres"`, `python -m compileall -q src tests scripts migrations`, `ruff check notebooks --select F821`, `python scripts/audit-notebooks.py notebooks` |
   | Raíz o documentación | `pytest tests/repository` desde `vaaet-ml/` y `git diff --check` |

   Si cambió `vaaet-core/` o `vaaet-persistence/`, corré también los tests de
   los componentes que lo consumen.
3. Si el cambio toca SQL, migraciones, backups o lectura desde PostgreSQL, los
   tests unitarios no alcanzan: avisá que hace falta `/pg-integration` o el job
   `postgres-integration` del CI.
4. Reportá por componente qué pasó, qué falló con su primer error y qué no se
   pudo correr y por qué. No presentes como aprobado algo que no corrió.

## Notas del entorno

- Python 3.10–3.13. Si el intérprete del sistema está fuera de rango, usá un
  venv (`py -3.11 -m venv` en Windows) con core, persistencia y ML en ese orden.
- En Windows sin rutas largas, pasá `--basetemp` con una ruta corta. Las fallas
  `FileNotFoundError`/`WinError 3` en directorios temporales son del entorno:
  comprobá si fallan igual sin tu cambio antes de atribuírselas.
- Para separar una falla propia de una previa, corré el mismo test en un
  worktree de `main` fuera del repositorio
  (`git worktree add <ruta-temporal> main`, y después `git worktree remove`).
  No uses `git stash` sobre trabajo ajeno ni sobre archivos intent-to-add.
- `ruff format --check` no es un gate del CI; no reformatees archivos ajenos.
