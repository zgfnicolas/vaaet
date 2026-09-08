# Plan gobernado — Integridad, continuidad y HITL uniforme

- Estado: implementado; validación de entornos externos pendiente
- Fecha: 2026-09-07
- ADR: [ADR-0027](../../architecture/decisions/0027-complete-bundle-identity-and-hitl-integrity.md)
- Alcance: `vaaet-core` 0.2.1 y `vaaet-ml` 4.6.1

## Objetivo

Cerrar las ambigüedades detectadas después de la adopción de los contratos v3:
identidad incompleta, reemplazo frágil del bundle, continuidad no idempotente,
resolución HITL desigual y evidencia estadística insuficientemente validada.
No cambian el modelo, las 19 features, los estados ni PostgreSQL.

## Cambios controlados

1. Incorporar `input_policy` y el algoritmo a la identidad exacta del bundle.
2. Restringir las identidades anteriores a evaluación histórica explícita.
3. Publicar y copiar bundles mediante staging, lock y recuperación por etapas.
4. Hacer idempotente la continuidad por clip, vista, continuidad fuente e
   instante UTC de inicio.
5. Consolidar features, predicciones y toda la cadena de validaciones antes de
   deduplicar el ground truth humano.
6. Validar tipos, UUIDs, schemas, valores finitos y conflictos antes de crear el
   dataset supervisado.
7. Diferenciar ausencia legítima de contexto de errores reales de inferencia.
8. Usar intervalos agrupados por clip en tablas, gates y Champion--Challenger.
9. Sincronizar contratos activos, contexto y documentación a Core 0.2.1 / ML
   4.6.1.

## Compatibilidad y despliegue

Los bundles, snapshots, predicciones y revisiones DVC históricos permanecen
intactos. Primero se inventariarían con herramientas read-only. Sólo un artefacto
seleccionado explícitamente puede reexportarse a un directorio nuevo, y queda
como piloto o candidato hasta volver a evaluarse. No se ejecutan commits, tags,
push, promociones ni cambios de datos operacionales desde esta entrega.

La secuencia recomendada es:

1. publicar código y documentación;
2. validar localmente las suites de core y ML;
3. comprobar PostgreSQL 17 en una instancia desechable;
4. validar Colab, Drive, YOLO e HITL en un runtime limpio;
5. inventariar artefactos antiguos;
6. regenerar o reexportar únicamente los seleccionados;
7. operar primero en shadow o piloto.

## Evidencia requerida

- Ruff, Pyright, pytest y `compileall` de ambos componentes.
- Integración PostgreSQL 17 sin modificar una base operacional.
- AST y auditoría de los cuatro notebooks.
- Enlaces Markdown y `git diff --check`.
- Validación manual en Colab y Drive para publicación, inferencia y revisión.
