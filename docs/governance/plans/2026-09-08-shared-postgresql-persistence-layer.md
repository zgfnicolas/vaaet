# Plan gobernado — Persistencia PostgreSQL compartida

- Fecha: 2026-09-08
- Alcance: `vaaet-persistence` 0.1.0 y `vaaet-ml` 4.7.0
- Decisión: [ADR-0028](../../architecture/decisions/0028-shared-postgresql-persistence-layer.md)
- Estado: implementado; validación manual externa pendiente

## Objetivo

Extraer la persistencia PostgreSQL del laboratorio a una distribución reusable
por notebooks y una futura API, sin cambiar `vaaet-db-v3`, reescribir datos ni
incorporar código de aplicación.

## Fases

1. Crear el paquete independiente con configuración, conexiones, operaciones,
   auditoría y recursos Alembic.
2. Conservar en ML adaptadores Colab y fachadas 4.x sin SQL duplicado.
3. Mover las revisiones históricas byte a byte y delegar la configuración
   anterior con advertencia.
4. Actualizar bootstrap, notebooks, CI, documentación y contexto operativo.
5. Verificar un consumidor core + persistencia sin dependencias del laboratorio
   y ejecutar integración sobre PostgreSQL 17 desechable.

## Riesgos y mitigaciones

| Riesgo | Mitigación |
| --- | --- |
| Duplicar la cadena Alembic | Una sola carpeta canónica y checksums históricos en pruebas. |
| Romper imports 4.x | Fachadas delgadas con pruebas de paridad y deprecación. |
| Confundir identidad de biblioteca y workflow | Identidad de aplicación obligatoria aportada por el consumidor. |
| Cerrar recursos ajenos | Pruebas de propiedad de engine y liberación de conexiones. |
| Ampliar permisos al futuro backend | Identidad propia por proceso; nuevos grants sólo con la primera API. |
| Exponer secretos | URL estructurada, representaciones redactadas y Secrets sólo en el adaptador ML. |

## Despliegue y reversión

No se aplica una migración nueva. Una base situada en `0003` se reconoce sin
volver a ejecutar revisiones. La adopción despliega primero la biblioteca y
luego los consumidores. Si falla, se revierte el código; el esquema y las filas
permanecen compatibles con VAAET ML 4.6.1.

No se crean usuarios web, API, frontend, remotos DVC, commits ni cambios de
datos operacionales en esta entrega.

## Evidencia requerida

- Ruff, Pyright, pytest y `compileall` para core, persistencia y ML.
- Descubrimiento de una única cadena Alembic y checksums intactos.
- PostgreSQL 17: instalación limpia, base existente en `0003`, roles, rollback e
  idempotencia.
- Auditoría y AST de los cuatro notebooks, enlaces y `git diff --check`.
- Validación manual posterior en Colab para recolección, inferencia + HITL y
  entrenamiento read-only.
