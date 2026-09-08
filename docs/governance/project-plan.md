# Plan de gestión del proyecto — VAAET

- Estado: activo
- Última revisión: 2026-08-27
- Responsable técnico: Facundo Nicolás González

## Alcance vigente

VAAET analiza tránsito vehicular del Puente General Manuel Belgrano mediante
percepción, telemetría por minuto y clasificación de estado. El monorepo mantiene
un único Git y DVC, con cuatro componentes delimitados:

| Componente | Estado | Responsabilidad |
| --- | --- | --- |
| `vaaet-core` | Activo | Percepción, telemetría, 19 features, política de estados, bundle e inferencia portable (`vaaet`) |
| `vaaet-persistence` | Activo | Acceso, operaciones, auditoría y migraciones PostgreSQL compartidas (`vaaet_persistence`) |
| `vaaet-ml` | Activo | Colab, datasets, entrenamiento, evaluación, adaptadores DB, DVC y laboratorio (`vaaet_ml`) |
| `vaaet-app` | Reservado | Futura API y Web App, sin código, framework ni dependencias aún |

[ADR-0021](../architecture/decisions/0021-portable-core-and-ml-laboratory-boundary.md)
y [ADR-0028](../architecture/decisions/0028-shared-postgresql-persistence-layer.md)
definen esos límites. La web futura sólo consumirá HTTP; sus workers usarán
core + persistencia con identidad propia y validarán el manifiesto vigente.

## Invariantes de gestión

- Se preservan las 19 features contractuales, tres salidas aprendidas, cuatro estados
  públicos y la política humana exclusiva de `Accident`.
- El laboratorio mantiene separación entre `SEED_BOOTSTRAP`, `HITL_RETRAINING`,
  snapshots, input locks y holdouts humanos inmutables.
- DVC gobierna `vaaet-ml/artifacts/traffic-state/`; Git identifica sus
  versiones por commit o tag y no almacena pesos, bundles, videos, datos
  privados ni secretos. ADR-0023 define el remoto local `vaaet-registry`.
- Toda futura demo con YOLO seguirá [ADR-0022](../architecture/decisions/0022-agpl-public-demo-path.md):
  vía pública AGPL con activos aprobados, o licencia Enterprise privada fuera
  de Git.

## Calidad y trazabilidad

Los cambios siguen Conventional Commits en español argentino rioplatense formal.
Las fuentes de contexto portables son [AGENTS.md](../../AGENTS.md),
[llms.txt](../../llms.txt) y [docs/index.md](../index.md); los ADRs y contratos
prevalecen sobre resúmenes y README.

CI valida core, persistencia y ML por separado, integración del workspace, PostgreSQL,
enlaces y DVC. Los gates locales incluyen Ruff, pytest, compileall, AST de los
cuatro notebooks y `git diff --check`. GPU, Drive, DVC remoto, YOLO y PostgreSQL
con Secrets mantienen validación manual en Colab antes de promoción externa.

## Próximos pasos

1. Completar la evidencia manual pendiente de Colab para los workflows ML.
2. Mantener el bundle y los datasets trazables conforme a los ADRs de datos y
   HITL.
3. Antes de crear código en `vaaet-app/`, aprobar un alcance y contrato HTTP
   versionado, activos redistribuibles y el checklist de demo aplicable.

Los planes fechados en [`docs/governance/plans/`](plans/) conservan la
trazabilidad de fases pasadas y pendientes; no se sustituyen por este resumen.
