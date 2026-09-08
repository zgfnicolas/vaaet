# ADR-0027 — Identidad completa, publicación recuperable e integridad HITL

- Estado: aceptada
- Fecha: 2026-09-07
- Decisores: Facundo Nicolás González
- Actualiza: ADR-0017, ADR-0019, ADR-0023 y ADR-0026
- Complementa: ADR-0018, ADR-0021 y ADR-0024

## Contexto

La primera identidad `model_revision` del bundle v3 no incorporaba
`input_policy`. Dos bundles con los mismos binarios y política de decisión, pero
con transformaciones de entrada diferentes, podían compartir revisión. Además,
el reemplazo del directorio del bundle no distinguía todas las etapas de fallo,
y las distintas fuentes HITL no resolvían las cadenas de corrección mediante
una única implementación.

La continuidad temporal también debía ser idempotente: volver a normalizar un
dataset ya segmentado no puede generar identificadores nuevos. Finalmente, una
declaración repetida de `production_eligible=true` no constituye por sí misma
evidencia suficiente para servir un modelo.

## Decisión

Se mantiene el contenedor bundle v3 y se publica el discriminador
`model_revision_algorithm=sha256-inference-contract-v2`. La revisión incluye
los hashes de los tres binarios, la política de decisión, el schema de
features, el training input lock y `input_policy`.

Los bundles v3 creados con el algoritmo anterior no se reescriben. Sólo pueden
cargarse con un propósito tipado de evaluación histórica, sin persistencia,
HITL ni promoción. Una reexportación requiere un destino nuevo y un motivo;
conserva los binarios, crea otra revisión y elimina toda elegibilidad heredada.

La publicación valida el candidato antes del reemplazo, usa exclusión de
escritor y registra si movió el original o instaló el candidato. Sólo elimina
archivos creados por la propia operación. Si no puede restaurar, conserva el
respaldo y comunica su ruta. Una falla posterior al publicar que sólo afecte la
limpieza se informa como advertencia y no revierte el bundle válido.

`normalize_continuity_frame()` es la única autoridad de segmentación y debe
cumplir idempotencia. Las fuentes HITL se consolidan antes de resolver UUIDs y
`supersedes_validation_id`; se rechazan ciclos, ramas, referencias cruzadas,
tipos ambiguos y conflictos de contenido. Reinferencias equivalentes se
deduplican conservando todos sus identificadores de procedencia.

El core valida la evidencia estructural de producción: supervisión, política
de entrada, holdout, cobertura, soporte, ausencia de Accident automático,
intervalos agrupados y exposición de falsas alertas. Las métricas de promoción
deben provenir de bootstrap por clips completos y ser coherentes con sus
estimaciones puntuales. La evaluación histórica puede inspeccionar metadata
contradictoria, pero no convertirla en autorización operacional.

## Consecuencias

- Cambiar la política de entrada cambia necesariamente `model_revision`.
- DVC puede listar historia antigua, pero recuperarla para evaluación exige una
  intención explícita.
- Una interrupción abrupta puede dejar un respaldo para recuperación manual;
  nunca se elige o elimina automáticamente por antigüedad.
- PostgreSQL no requiere una migración adicional: las consultas read-only
  recuperan la historia de validaciones ya modelada por Alembic `0003`.
- Las 19 features, las tres salidas del MLP, los umbrales y los cuatro estados
  públicos no cambian.
