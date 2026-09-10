# Plan gobernado — Fidelidad PostgreSQL y coherencia HITL

- Fecha: 2026-09-09
- Alcance: `vaaet-persistence` 0.2.0 y `vaaet-ml` 4.8.0
- Decisión: [ADR-0029](../../architecture/decisions/0029-postgresql-numeric-fidelity-and-hitl-consistency.md)
- Estado: implementado en código; validación externa pendiente

## Objetivo

Cerrar las diferencias entre cálculos `float64`, persistencia, linaje de
corridas, paquetes HITL y resolución humana, sin alterar el modelo ni reparar
datos históricos mediante inferencias.

## Fases

1. Añadir regresiones para tipos estrictos, idempotencia, identidad y recursos.
2. Incorporar Alembic `0004`, preservando los hashes de `0001`--`0003`.
3. Unificar adaptadores operacionales/portables y lecturas consistentes.
4. Actualizar notebooks, auditor, permisos, documentación y metadata.
5. Probar instalación limpia y actualización desde `0003` en PostgreSQL 17.
6. Ensayar backup/restauración y recién después aplicar una ventana
   administrativa en cada entorno.

## Riesgos y controles

| Riesgo | Control |
| --- | --- |
| Reescritura y bloqueo al cambiar tipos | Restauración aislada, medición y ventana administrativa. |
| Falso reintento idempotente | Comparación canónica exacta y rollback del lote completo. |
| Ground truth ambiguo | Vista de conflictos y exclusión de cadenas no lineales. |
| Fuga de secretos por excepciones | Excepciones de dominio sin mensaje ni parámetros externos. |
| Lecturas partidas | Una conexión `REPEATABLE READ`, read-only, para los componentes HITL. |
| Fuga de certificados o pools | Ownership explícito, limpieza idempotente y timeouts finitos. |

## Despliegue y recuperación

El orden obligatorio es regresiones, integración descartable, inventario
read-only, backup y restauración de prueba, migración administrativa,
consumidores y validación Colab/Drive. No se ejecutan migraciones desde
notebooks ni durante esta implementación.

No hay downgrade automático. Ante una falla se conserva el backup, se detienen
los consumidores nuevos y se aplica una corrección hacia adelante o una
restauración controlada.

## Evidencia requerida

- Suites core, persistencia, ML y repositorio.
- PostgreSQL 17 desde cero y desde `0003`, con usuarios LOGIN de mínimo
  privilegio y rollback de lotes.
- Ruff, Pyright, `compileall`, auditoría/AST de notebooks, enlaces y
  `git diff --check`.
- Validación manual en Colab/Drive, documentada como pendiente si el entorno no
  está disponible.
