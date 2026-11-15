# Plan gobernado — Continuidad temporal y revisiones inmutables

- Estado: implementado; validación de proveedor pendiente
- PR: [#21](https://github.com/zgfnicolas/vaaet/pull/21)
- Fecha: 2026-09-05
- ADR: [ADR-0026](../../architecture/decisions/0026-temporal-continuity-and-immutable-model-revisions.md)
- Alcance: `vaaet-core` 0.2.0 y `vaaet-ml` 4.6.0

## Objetivo

Eliminar transporte de estado entre secuencias discontinuas, preservar la
historia exacta de inferencias y basar la promoción en evidencia agrupada por
clip. No cambian las 19 features, las tres salidas del MLP ni la regla que
reserva `Accident` para confirmación humana.

## Cambios controlados

1. Introducir `continuity_id` en telemetría y features, con corte por vista o
   hueco superior a 90 segundos.
2. Calcular `model_revision` sobre el bundle completo y el input lock.
3. Migrar PostgreSQL mediante Alembic `0003`, conservando referencias HITL.
4. Separar métricas directas y finales, con intervalos por bootstrap de clips.
5. Publicar holdout humano v2 y exigir compatibilidad exacta para comparar.
6. Exportar bundles mediante staging, validación y reemplazo atómico.

## Secuencia de despliegue

1. Crear y verificar un backup administrativo de la base vigente.
2. Conservar bundles, semillas y holdouts v2 como artefactos históricos.
3. Aplicar `alembic upgrade head` con el rol administrador en una ventana de
   mantenimiento.
4. Ejecutar el auditor PostgreSQL y comprobar revisión, constraints, grants y
   filas legacy migradas.
5. Regenerar la semilla v3 desde el backup raw original.
6. Ejecutar inferencia v3 en shadow o piloto y producir nuevos paquetes HITL.
7. Crear una generación de holdout v2 con grupos humanos suficientes.
8. Entrenar un candidato y compararlo sólo contra el mismo fingerprint.
9. Promover manualmente con Git/DVC únicamente si todos los gates pasan.

## Rollback y seguridad

La migración no intenta reconstruir revisiones que ya hubieran sido
sobrescritas antes de v3. Genera identificadores legacy deterministas y conserva
sus FKs. Si la migración falla, no se continuará con inferencia v3; se restaurará
el backup en una base aislada y se investigará antes de reintentar. Los
notebooks no ejecutan DDL, no promocionan DVC ni reciben credenciales
administrativas.

## Evidencia requerida

- Ruff, Pyright, pytest y `compileall` de core y ML.
- PostgreSQL 17 desde cero y actualización real desde Alembic `0002`.
- Auditoría y AST de notebooks, enlaces y `git diff --check`.
- Prueba manual en Colab del HUD progresivo, inferencia batch y persistencia.
- Prueba manual del proveedor para TLS, backup, restauración y grants.
