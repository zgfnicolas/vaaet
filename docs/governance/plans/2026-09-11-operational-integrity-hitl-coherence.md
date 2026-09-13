# Plan gobernado — Integridad operacional y coherencia HITL

- Fecha: 2026-09-11
- Alcance: `vaaet-persistence` 0.2.1 y `vaaet-ml` 4.8.1
- Decisión: [ADR-0030](../../architecture/decisions/0030-operational-idempotency-and-portable-hitl-coherence.md)
- Estado: implementado en código; validación externa pendiente

## Objetivo

Cerrar los doce hallazgos de integridad, idempotencia, recursos, identidad
portable y recuperación HITL sin alterar contratos ML ni reescribir historia.

## Fases

1. Reproducir cada defecto con pruebas de dominio y bordes tabulares.
2. Incorporar Alembic `0005` sin modificar las revisiones anteriores.
3. Corregir validación, lotes, recursos y linaje idempotente.
4. Unificar la identidad portable y validar el grafo humano completo.
5. Separar estado de procesamiento, persistencia y sincronización en notebooks.
6. Sellar fechas de revisión nuevas y conservar la verificación del algoritmo
   histórico sin reescribir paquetes existentes.
7. Actualizar metadata, documentación, contexto y controles CI.
8. Validar desde cero y desde `0004` en PostgreSQL 17 desechable.
9. Probar manualmente Colab, revisión y recuperación `pending-sync`.

## Riesgos y controles

| Riesgo | Control |
| --- | --- |
| Bloqueo o permisos excesivos en revisión | Advisory lock, reviewer real y pruebas negativas de privilegios. |
| Alias histórico ambiguo | Equivalencia tipada completa o rechazo sin modificar el ZIP. |
| Pérdida de una decisión por reintento | UUID y corrida originales devueltos desde PostgreSQL. |
| Clasificación parcial reutilizada | Publicación posterior a contrato y paridad; estado previo invalidado. |
| Pérdida del paquete al fallar Drive | ZIP local validado primero y sincronización reintentable por bytes. |
| Métricas de consultas ficticias | Contadores incrementados al ejecutar cada sentencia real. |

## Despliegue y recuperación

El orden obligatorio es regresiones, implementación, integración desechable,
documentación, backup/restauración de prueba, migración administrativa,
consumidores y validación Colab. Esta entrega no aplica migraciones ni modifica
artefactos privados.

`0005` es una corrección hacia adelante. Si una adopción falla, se detienen los
consumidores nuevos y se restaura el backup ensayado o se publica otra revisión;
no se reescriben validaciones, paquetes ni revisiones históricas.

## Evidencia requerida

- Suites completas de core, persistencia, ML y repositorio.
- PostgreSQL 17 desde cero y desde `0004`, con cuatro LOGIN independientes.
- Revisión, corrección, exportación, ingestión combinada e idempotencia.
- Ruff, Pyright, `compileall`, AST/auditoría de notebooks, enlaces y diff check.
- Validación manual en Colab y Drive, informada como pendiente si no se ejecuta.
