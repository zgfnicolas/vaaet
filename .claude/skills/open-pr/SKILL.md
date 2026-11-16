---
name: open-pr
description: Prepara rama, commit, push y pull request de VAAET con Conventional Commits en español rioplatense y el template de PR. Sólo se ejecuta a pedido, porque publica en GitHub.
disable-model-invocation: true
argument-hint: "[descripción breve del cambio]"
---

# Abrir un pull request

Cambio: $ARGUMENTS

Seguí `.codex/skills/vaaet-git-workflow/SKILL.md` para las reglas de Git. Cada
paso que publica (commit, push, PR) necesita la confirmación explícita de la
persona; si no la diste en este pedido, detenete antes de ese paso.

1. **Estado**: `git status` y `git branch --show-current`. Si estás en `main`,
   creá `feature/<descripcion>` desde `main` actualizado. No incluyas cambios
   ajenos a la tarea.
2. **Validación**: usá la skill `validate` sobre lo cambiado. Si algo falla,
   detenete y reportalo.
3. **Revisión**: pedile al subagente `vaaet-reviewer` una revisión del diff y
   resolvé los hallazgos bloqueantes.
4. **Commit**: revisá `git diff --cached` en busca de secretos, binarios o
   archivos ajenos. Escribí el mensaje según `.git-commit-template.txt`:
   `tipo(scope): verbo en voseo formal + resultado`, cuerpo con qué y por qué,
   y la línea de coautoría del sistema.
5. **Push**: `git push -u origin <rama>`. Nunca `--force`.
6. **PR**: `gh pr create --base main` con el cuerpo de
   `.github/pull_request_template.md` completo, incluida la validación manual
   pendiente. Enlazá el plan gobernado si existe y agregá el PR al plan.
7. **CI**: el workflow sólo corre en PRs con base `main`. Si cambiás la base
   después, cerrá y reabrí el PR (`gh pr close` + `gh pr reopen`) para que
   corra. Ante una falla, usá el subagente `ci-investigator` y verificá si
   `main` ya fallaba en ese job antes de atribuírsela al PR.

Reportá la URL del PR, el commit y el estado de los checks. El merge lo decide
una persona.
