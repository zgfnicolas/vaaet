# Plan gobernado — Recuperación verificable e integridad HITL

- Fecha: 2026-09-20
- Alcance: Persistence 0.3.0 y ML 4.9.0; Core permanece en 0.2.2
- Decisión: [ADR-0033](../../architecture/decisions/0033-verifiable-persistence-recovery-and-hitl-audit.md)
- Estado: implementado en código; validación externa pendiente

## Objetivo

Cerrar cuatro fallos reproducibles: decisiones humanas con auditoría incompleta
que podían avanzar, reconciliación insuficientemente ligada a la corrida,
aliases históricos comparados antes de demostrar equivalencia y un exportador
offline incompatible con el contrato vigente.

## Fases

1. Incorporar regresiones deterministas para los cuatro hallazgos.
2. Registrar comprobantes inmutables dentro de cada transacción de datos.
3. Reconciliar contra corrida, comprobante, soporte y filas exactas.
4. Bloquear decisiones humanas pendientes en UI, exportación y entrenamiento.
5. Resolver aliases por niveles conservando identidad y procedencia originales.
6. Delegar la fachada de exportación en el sellador portable canónico.
7. Aplicar Alembic `0006` en PostgreSQL 17 desechable y probar mínimo privilegio.
8. Sincronizar notebooks, CI, documentación y evidencia de calidad.

## Riesgos y controles

| Riesgo | Control |
| --- | --- |
| Cerrar una corrida con datos de otra | Fingerprint tipado, propietario, metadata y lectura exacta en una transacción. |
| Repetir una escritura durante recuperación | Reconciliación sin `INSERT` de datos y UUID determinista del intento. |
| Exportar una decisión pendiente | Lista separada de pendientes y rechazo del sellador. |
| Convertir pendientes en targets | Consulta read-only que detiene la fuente antes de cargar feedback. |
| Rechazar aliases históricos válidos | Resolución feature → prediction → validation antes de comparar referencias. |
| Alterar artefactos históricos | Compatibilidad sólo en memoria; ZIP, IDs y fingerprints permanecen intactos. |

## Despliegue y recuperación

El orden de adopción es regresiones, código, migración desechable, documentación,
backup, migración administrativa autorizada y validación Colab/Drive. Si la
adopción falla, se revierte el consumidor; no se degrada la base ni se fabrican
comprobantes históricos. Las corridas antiguas incompletas sin recibo requieren
investigación explícita.

La implementación no toca bases, artefactos privados, DVC ni remotos del
usuario. Tampoco crea commits, tags o promociones.

## Evidencia requerida

- Suites de core, persistencia, ML y repositorio.
- PostgreSQL 17 desde cero y desde `0005`, con cuatro usuarios de mínimo
  privilegio y flujo completo.
- Atomicidad, conflicto, idempotencia y reconciliación sin reinserciones.
- Exportación compatible e ingestión combinada con aliases históricos.
- Colab con decisión pendiente, reinicio, recuperación y publicación Drive.
- Ruff, Pyright, `compileall`, notebooks, enlaces y `git diff --check`.
