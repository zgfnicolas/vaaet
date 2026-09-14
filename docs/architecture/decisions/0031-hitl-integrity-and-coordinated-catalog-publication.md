# ADR-0031 — Integridad HITL y publicación coordinada del catálogo

- Estado: aceptada
- Fecha: 2026-09-13
- Decisor: Facundo Nicolás González
- Complementa: ADR-0030

## Contexto

La recuperación local de paquetes HITL ya conservaba bytes inmutables, pero la
publicación del catálogo todavía admitía dos fallos: identidades repetidas podían
reasociarse antes de detectar una contradicción y dos sesiones concurrentes
podían reemplazar `catalog.json` desde la misma revisión leída. La notebook de
inferencia también podía conservar una clasificación anterior si se repetía sólo
su celda y el nuevo intento fallaba.

Los diagnósticos PostgreSQL y los manifiestos locales tenían bordes adicionales:
un error externo podía alcanzar el traceback público y un fallo secundario de
auditoría podía ocultar el resultado principal.

## Decisión

La consolidación valida primero cada UUID original y rechaza cualquier cambio de
clip, instante, continuidad, schema, corrida o contenido contractual. Recién
después resuelve aliases equivalentes, cadenas humanas y duplicados. El orden de
las fuentes no decide el resultado ni puede reasociar una validación.

La inferencia utiliza un `InferenceExecutionState` por intento. Al repetir la
clasificación se invalidan resultado, persistencia, revisión, dashboard y
callbacks anteriores. Un resultado vacío por falta de contexto es válido; un
fallo permanece bloqueado y no reutiliza filas previas.

Finalizar y publicar son operaciones distintas. `finalize_current_review()`
sella y valida un ZIP local `pending-sync`. Toda mutación de `catalog.json`
requiere un `HitlCatalogPublisher` activo, que mantiene exclusión local durante
lectura, validación, reemplazo y verificación. Sólo un runtime se designa como
publicador operacional.

El archivo de bloqueo vive en almacenamiento local y coordina procesos del mismo
host. No se presenta un archivo de Google Drive montado como bloqueo distribuido:
dos runtimes independientes no deben publicar simultáneamente. Cambiar el
publicador exige detener el anterior.

Los fallos de disponibilidad remota devuelven `pending-sync` sin reconstruir el
paquete. Una corrupción o contradicción de integridad se propaga como error y no
se reemplaza por un catálogo vacío. PostgreSQL expone sólo errores de dominio y
SQLSTATE validado; `test_connection()` devuelve `False` ante fallos de
infraestructura. Un fallo secundario al cerrar un manifiesto no sustituye la
excepción ni el resultado principal, pero bloquea pasos que requieran auditoría
completa.

## Invariantes

- No cambian Alembic `0005`, `vaaet-db-v3`, las 19 features ni los contratos ML.
- Los ZIP y catálogos históricos no se reescriben.
- `Accident` continúa siendo exclusivamente humano.
- PostgreSQL y la publicación remota continúan siendo opt-in.
- Ninguna excepción pública incluye mensajes, parámetros o secretos del driver.
- Un paquete se informa como `synced` sólo después de verificar archivo y entrada.

## Consecuencias

La notebook requiere dos pasos explícitos para una revisión portable: sellar el
ZIP y publicarlo desde el runtime coordinador. Esta separación evita perder el
paquete cuando Drive falla y hace visible el límite de concurrencia elegido.

La exclusión no ofrece coordinación distribuida. Si el proyecto necesita varios
publicadores remotos en el futuro deberá incorporar un servicio transaccional o
compare-and-swap verificable mediante otra decisión arquitectónica.

La integración real en PostgreSQL 17, Colab y Google Drive sigue siendo evidencia
ambiental obligatoria; las pruebas locales no la reemplazan.
