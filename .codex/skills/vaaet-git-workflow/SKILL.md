---
name: vaaet-git-workflow
description: Gestioná y revisá cambios Git de VAAET con commits atómicos, trazables y en español argentino rioplatense formal. Usá esta skill para preparar ramas, staging, mensajes Conventional Commits, rebase local, pull requests, revisión de historial o controles previos a integrar cambios.
---

# VAAET Git Workflow

## Estado actual y límites de autoridad

Usá Git como historial técnico auditable, no como respaldo indiferenciado. Antes
de modificar el repositorio, leé `AGENTS.md`, el ADR aplicable,
`CONTRIBUTING.md` y el plan gobernado cuando corresponda. Para un cambio de
componente, leé también `vaaet-core/AGENTS.md` o `vaaet-ml/AGENTS.md`; ADR-0021
gobierna sus límites y ADR-0022 cualquier serving futuro con YOLO.

VAAET usa actualmente `main` como rama principal y `feature/*` para trabajo
aislado. La plantilla versionada `.git-commit-template.txt` es una guía local
opt-in, no una configuración aplicada automáticamente. GitHub carga
`.github/pull_request_template.md` en cada PR y ofrece plantillas de issues en
`.github/ISSUE_TEMPLATE/`; completá el template al abrir un PR. No hay una rama
`develop`, Git Flow completo, protección de ramas, firma de commits, commitlint
ni hooks configurados como política vigente. No los
presentes como capacidades existentes ni los agregues sin autorización explícita.

No crees ramas, hagas staging, commits, rebase, push, pull requests, merges,
tags ni cambios de configuración local o global sin la autorización que
corresponda. No reescribas historial compartido ni uses `--force` o
`--force-with-lease` salvo instrucción expresa y análisis de impacto.

## Escribí commits en español argentino rioplatense formal

Usá Conventional Commits con tipos técnicos en minúscula y un asunto en español
argentino rioplatense formal, en modo imperativo con voseo. Conservá los nombres
de código, APIs, contratos y scopes técnicos cuando sean necesarios.

```text
tipo(scope): verbo en voseo formal + resultado concreto
```

Usá sólo estos tipos: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`,
`test` y `chore`. Elegí un scope real de VAAET cuando aclare el alcance:
`core`, `ml`, `vision`, `features`, `inference`, `data`, `training`,
`evaluation`, `artifacts`, `notebooks`, `docs`, `ci` o `dvc`.

Preferí verbos como `incorporá`, `corregí`, `actualizá`, `documentá`,
`preservá`, `optimizá`, `validá`, `migrá` y `eliminá`. Evitá verbos de acción en
inglés, infinitivos impersonales, jerga informal, puntos finales y asuntos
vagos como `avances`, `wip` o `arreglos`.

Ejemplos válidos:

```text
feat(vision): incorporá telemetría ordenada por minuto
fix(data): corregí la deduplicación de registros por clip
docs(ml): documentá los bloqueos de promoción del bundle
test(training): validá la separación temporal entre clips
chore(ci): actualizá la matriz compatible con Python 3.13
```

Usá el cuerpo del commit sólo cuando explique una decisión, motivo, riesgo,
limitación, migración o impacto de operación que el título no alcanza a cubrir.
Escribilo también en español rioplatense formal. Referenciá un issue o ticket
cuando exista; no inventes identificadores ni expongas secretos, rutas privadas,
datos sensibles o excepciones sin redactar.

No reescribas commits históricos en inglés sólo para traducirlos. Aplicá esta
convención a nuevos commits y a mensajes aún locales que el responsable haya
autorizado limpiar antes de compartir.

## Ofrecé la plantilla local sólo cuando corresponda

La raíz contiene `.git-commit-template.txt`, una ayuda versionada para redactar
la convención vigente. Mantenela alineada con los tipos, scopes y español
rioplatense de esta skill; no la conviertas en una política de Git Flow, una
obligación de ticket ni una regla de Gitmoji.

Un desarrollador puede activarla para este clon con:

```text
git config --local commit.template .git-commit-template.txt
```

Ese comando modifica `.git/config`, no se propaga al clonar y requiere
autorización explícita antes de ejecutarse. No configures `--global` ni crees
scripts, hooks o configuración compartida para forzarla. `git commit` sin
`-m` abre la plantilla en el editor; un mensaje pasado con `-m` no la utiliza.

Las líneas que comienzan con `#` funcionan como guía y Git las ignora al crear
el mensaje. El pie `BREAKING CHANGE:` sólo corresponde a una incompatibilidad
real y no reemplaza el ADR, el plan ni la autorización que exija el cambio.

## Prepará cambios atómicos y verificables

Antes de sugerir un commit:

1. Inspeccioná rama, `git status`, diff y archivos staged; separá cambios ajenos
   o de responsabilidad distinta.
2. Confirmá que la unidad propuesta tiene un objetivo reversible y no mezcla
   refactorización, funcionalidad, migraciones o formateo sin justificación.
3. Ejecutá los gates aplicables de `AGENTS.md`, incluyendo `git diff --check`.
4. Revisá que no se incorporen secretos, binarios de modelo, DVC remoto,
   artefactos generados o archivos fuera del alcance autorizado.
5. Proponé un comando de commit en español y esperá autorización antes de
   ejecutarlo.

Un commit atómico debe poder revertirse sin dejar el contrato, los datos, los
notebooks o la documentación en un estado incoherente. No impongas un límite de
líneas artificial: separá por responsabilidad y riesgo, no por una métrica
cosmética.

## Usá ramas, rebase y GitHub con prudencia

Partí de `main` actualizado para una tarea nueva autorizada y usá un nombre
descriptivo bajo `feature/`, `fix/`, `docs/` o `chore/` sólo si aporta claridad.
No supongas que un cambio contenido necesita una rama nueva cuando el usuario
trabaja explícitamente sobre otra rama.

Antes de limpiar commits locales no publicados, revisá el rango exacto y
explicá el efecto de `rebase -i`. No hagas rebase de commits ya compartidos ni
resuelvas conflictos borrando cambios sin validación. Conservá una historia
legible mediante commits pequeños y mensajes semánticos, no mediante rebase
automático.

`gh` está disponible como opción para inspeccionar issues, checks o pull
requests una vez autenticado. Usalo sólo si el usuario autoriza la interacción
remota y no afirmes que una PR, protección de rama o firma criptográfica existe
sin verificarlo. Tratá firma SSH/GPG, branch protection, commitlint, hooks y
Git Flow completo como mejoras futuras que requieren decisión de gobernanza,
configuración y validación separadas.

## Informá el resultado en español

Al preparar una operación Git, reportá en español:

- Rama y alcance de los cambios revisados.
- Validaciones ejecutadas y las pendientes por ambiente o Colab.
- Riesgos, contratos y archivos excluidos del commit.
- Comando de commit sugerido en español rioplatense formal.
- Estado de autorización para cualquier operación que modifique historial local
  o remoto.

Rechazá commits monolíticos, mensajes genéricos o en inglés, mezcla de cambios
no relacionados, staging ciego, commits directos no autorizados a `main`,
secretos, artefactos binarios en Git, cambios de contrato sin ADR y rebase o
push forzado sobre historial compartido.
