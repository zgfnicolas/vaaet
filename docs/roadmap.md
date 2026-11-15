# Roadmap

Muestra hacia dónde va VAAET por fases, sin fechas comprometidas. Cada fase
tiene un criterio de salida verificable. El detalle de cada cambio vive en su
[plan gobernado](governance/plans/) y en el [CHANGELOG](../CHANGELOG.md).

## Ahora — laboratorio 4.x

Objetivo: cerrar la evidencia pendiente y obtener el primer bundle elegible para
producción.

- **Validación manual pendiente.** Ejecutar en Colab, con GPU, Drive, DVC remoto
  y PostgreSQL 17 real con TLS, los ciclos implementados en código cuya
  aceptación operacional sigue abierta:
  - [continuidad temporal y revisiones del modelo](governance/plans/2026-09-05-temporal-continuity-and-model-revisions.md);
  - [persistencia compartida](governance/plans/2026-09-08-shared-postgresql-persistence-layer.md)
    y [fidelidad numérica](governance/plans/2026-09-09-postgresql-numeric-fidelity-hitl-integrity.md);
  - integridad HITL y recuperación: planes del
    [2026-09-07](governance/plans/2026-09-07-integrity-continuity-and-hitl-corrections.md),
    [2026-09-11](governance/plans/2026-09-11-operational-integrity-hitl-coherence.md),
    [2026-09-13](governance/plans/2026-09-13-hitl-integrity-and-operational-recovery.md),
    [2026-09-15](governance/plans/2026-09-15-complete-cycle-integrity.md),
    [2026-09-20](governance/plans/2026-09-20-verifiable-persistence-recovery.md),
    [2026-09-24](governance/plans/2026-09-24-uniform-review-audit-recovery.md)
    y los dos del [2026-09-26](governance/plans/2026-09-26-coherent-hitl-sessions-and-typed-integers.md)
    ([paquetes sin pérdida](governance/plans/2026-09-26-review-recovery-lossless-packages.md));
  - la evidencia de Colab del [monorepo](governance/plans/2026-08-25-monorepo-ml-app-boundary.md).
- **Soporte humano suficiente.** Llegar a 300 etiquetas `Normal`, 300 `Reduced`
  y 100 `Congested`, con al menos 100 minutos `Congested` de 20 episodios
  reales.
- **Holdout humano v2 congelado** con grupos independientes por estado estable.

Criterio de salida: un bundle con `production_eligible=true` que supera los
gates de la [model card](ml/model-card.md) sobre el holdout congelado, con
retrospective replay, shadow mode prospectivo y revisión de falsos positivos.

## Próximo — 5.0.0

- Eliminar las vistas de compatibilidad `public.*` mantenidas durante 4.x.
- Decidir si la FK `telemetry_features` → `traffic_predictions` pasa de
  `CASCADE` a `RESTRICT`; requiere plan gobernado y una revisión Alembic nueva
  (ver [políticas referenciales](architecture/data-model.md#políticas-referenciales)).

Criterio de salida: ningún consumidor depende de las vistas `public.*` y la
cadena Alembic de 5.0.0 pasa la integración con PostgreSQL 17.

## Más adelante

- **API y Web App en `vaaet-app/`.** Requiere alcance aprobado, contrato HTTP
  versionado, activos redistribuibles y el
  [checklist de demo AGPL](governance/agpl-demo-release-checklist.md) o una
  licencia Enterprise; continúa la fase 4 del
  [plan de demo pública](governance/plans/2026-08-27-agpl-public-demo.md).
- **Monitoreo de drift en producción**, una vez que exista un modelo en uso
  continuo.

Fuera del roadmap mientras no cambie el PRD: multi-cámara simultánea,
streaming, lectura de patentes, predicción de tráfico futuro y alertas push.
