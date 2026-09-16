# Plan gobernado — Integridad del ciclo completo

- Fecha: 2026-09-15
- Alcance: Core 0.2.2, Persistence 0.2.3 y ML 4.8.3
- Decisión: [ADR-0032](../../architecture/decisions/0032-complete-cycle-integrity.md)
- Estado: implementado en código; validación externa pendiente

## Objetivo

Cerrar seis fallos reproducibles de orden temporal, asociación de revisiones,
compatibilidad histórica, auditoría de escrituras, lectura legacy y validación
de probabilidades, sin cambiar schemas persistidos ni contratos ML.

## Fases

1. Reproducir cada hallazgo mediante fixtures deterministas.
2. Consolidar HITL en orden contractual y cronológico, independiente del input.
3. Rechazar predicciones ambiguas antes de generar artefactos portables.
4. Resolver aliases por niveles conservando identidades y procedencia originales.
5. Separar trabajo confirmado de auditoría y reconciliar sin reinserciones.
6. Exigir un modo PostgreSQL explícito, sin fallback por excepción.
7. Reutilizar la validación matemática del core en todos los consumidores.
8. Sincronizar metadata, notebooks, documentación y evidencia de calidad.

## Riesgos y controles

| Riesgo | Control |
| --- | --- |
| Continuidad validada sobre orden de UUID | Orden estable por clip e instante UTC después de consolidar. |
| Etiqueta vinculada a otro minuto | Relación uno-a-uno por `prediction_id` y rechazo de contradicciones. |
| Rechazo de fuentes históricas equivalentes | Aliases verificados por nivel y sólo en memoria. |
| Repetición de una escritura confirmada | Resultado tipado y reconciliación read-only del contenido. |
| Permisos ocultos por fallback legacy | Un único query por `TelemetryReadMode`. |
| Clasificación plausible desde probabilidades inválidas | Validador compartido, sin corrección silenciosa. |

## Despliegue y recuperación

El orden es regresiones, implementación, integración PostgreSQL desechable,
documentación y validación Colab/Drive. No hay migración nueva: Alembic `0005`
continúa siendo la revisión requerida. La recuperación de una auditoría
incompleta conserva la corrida original y crea evidencia separada, sin repetir
la operación de datos.

Esta entrega no modifica artefactos privados, catálogos, holdouts, DVC ni bases
del usuario. No crea commits, tags, pushes ni promociones automáticas.

## Evidencia requerida

- Suites completas de core, persistencia, ML y repositorio.
- PostgreSQL 17 con cuatro usuarios de mínimo privilegio y flujo extremo a extremo.
- Permutación de fuentes, aliases equivalentes y contradicciones intencionales.
- Fallo de auditoría posterior a una escritura real y reconciliación idempotente.
- Colab limpio con clip real, repetición de celdas y revisión portable.
- Ruff, Pyright, `compileall`, notebooks, enlaces y `git diff --check`.
