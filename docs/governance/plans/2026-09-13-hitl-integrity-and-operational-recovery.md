# Plan gobernado — Integridad HITL y recuperación operacional

- Fecha: 2026-09-13
- Alcance: `vaaet-persistence` 0.2.2 y `vaaet-ml` 4.8.2
- Decisión: [ADR-0031](../../architecture/decisions/0031-hitl-integrity-and-coordinated-catalog-publication.md)
- Estado: implementado en código; validación externa pendiente

## Objetivo

Cerrar seis fallos reproducibles de asociación HITL, estado obsoleto de
inferencia, concurrencia del catálogo, redacción PostgreSQL, recuperación Drive
y preservación del error principal sin alterar schemas ni contratos ML.

## Fases

1. Reproducir UUID contradictorios antes de canonicalizar aliases.
2. Incorporar estado tipado e invalidación de acciones derivadas por intento.
3. Separar sellado local y publicación mediante un publicador único explícito.
4. Cubrir disponibilidad e integridad remota como resultados diferentes.
5. Centralizar SQLSTATE seguro y diagnóstico PostgreSQL sin causas externas.
6. Preservar excepción o resultado principal ante fallos secundarios de auditoría.
7. Actualizar notebook, documentación, contexto, metadata y regresiones.
8. Validar localmente y completar las comprobaciones ambientales declaradas.

## Riesgos y controles

| Riesgo | Control |
| --- | --- |
| Etiqueta asociada a otro clip | Conflicto de UUID original antes de aliases y resultado independiente del orden. |
| Reutilización de un resultado anterior | Estado por intento y callbacks ligados a su UUID. |
| Pérdida de una entrada del catálogo | Exclusión local durante toda la publicación y un publicador operacional. |
| Falsa garantía distribuida | Límite explícito: el bloqueo no coordina runtimes Colab distintos. |
| Pérdida del ZIP por Drive | Sellado local previo y reintento sobre los mismos bytes. |
| Error externo o auditoría ocultando la causa | Excepción de dominio redactada y fallo secundario sólo como advertencia. |

## Despliegue y recuperación

El orden es regresiones, implementación, validación local, PostgreSQL desechable,
Colab/Drive y adopción. Antes de cerrar un runtime deben conservarse o descargarse
los ZIP `pending-sync`. Para cambiar el publicador se detiene el anterior y recién
después se inicia el nuevo.

Esta entrega no aplica migraciones, no modifica catálogos privados y no ejecuta
operaciones DVC o Git remotas. Ante un conflicto de integridad se conserva el ZIP
local y se detiene la publicación para reconciliación explícita.

## Evidencia requerida

- Suites completas de core, persistencia, ML y repositorio.
- Publicaciones secuenciales y contención concurrente en un mismo host.
- PostgreSQL 17 con cuatro identidades de mínimo privilegio.
- Flujo completo de revisión, exportación e ingestión combinada.
- Colab limpio, repetición de celdas y recuperación de Drive.
- Ruff, Pyright, `compileall`, notebooks, enlaces y `git diff --check`.
