# ADR-0033 — Recuperación verificable y auditoría HITL completa

- Estado: aceptada
- Fecha: 2026-09-20
- Decisor: Facundo Nicolás González
- Complementa: ADR-0032

## Contexto

Una escritura PostgreSQL podía terminar correctamente y perder sólo el cierre
de su corrida. La reconciliación previa volvía a comparar filas, pero carecía
de un comprobante transaccional que demostrara qué conjunto exacto había sido
confirmado por esa corrida. Eso permitía que evidencia compatible de otra
corrida pareciera suficiente y dejaba ambiguo si una decisión humana ya
persistida podía avanzar hacia exportación o entrenamiento.

También quedaban dos bordes de interoperabilidad: las validaciones de fuentes
históricas se comparaban antes de terminar de resolver aliases demostrables de
features y predicciones, y la fachada pública de exportación offline mantenía
un formato independiente que podía reemplazar fechas e identidades.

## Decisión

Alembic `0006` incorpora `vaaet_ops.persistence_receipts`. Cada operación de
datos registra en la misma transacción un comprobante inmutable con algoritmo,
fingerprint tipado, soporte procesado e insertado, schemas, revisión del modelo,
fecha y propietario. Los datos y su comprobante se confirman o revierten
juntos. Repetir la misma corrida y contenido recupera el comprobante original;
un contenido distinto produce conflicto.

La reconciliación crea un intento separado enlazado mediante
`reconciles_run_id`. Antes de cerrar la corrida original, verifica propietario,
workflow, metadata, comprobante, soporte y contenido almacenado dentro de una
sola transacción. Nunca reinserta datos. Una corrida histórica sin comprobante
permanece bloqueada para recuperación automática.

Una validación humana sólo se considera confirmada cuando su corrida está
terminal y conserva el comprobante correspondiente. Una decisión guardada con
auditoría pendiente mantiene UUID y fecha, no avanza el formulario, no se
exporta y no se convierte en target. El reintento reconcilia esa misma decisión.

La consolidación HITL resuelve aliases por niveles: features, referencias de
predicciones, predicciones y recién después validaciones. Los aliases existen
sólo en memoria y preservan todas las identidades de procedencia. El exportador
offline 4.x delega en el normalizador y sellador canónicos; exige contexto
operacional explícito, conserva las decisiones originales y nunca publica el
catálogo.

## Invariantes

- Alembic `0001` a `0005` permanece byte a byte intacto.
- No se fabrican comprobantes para corridas históricas.
- Los comprobantes excluyen metadata generada por PostgreSQL y procedencia
  complementaria; incluyen identidades y contenido contractual tipado.
- Una auditoría pendiente bloquea exportación HITL y entrenamiento supervisado.
- Reconciliar no reinserta, no reabre estados terminales ni modifica decisiones.
- No cambian features, MLP, estados, bundle, identidades portables ni datasets.
- PostgreSQL continúa siendo opcional y el catálogo HITL conserva un único
  publicador coordinado.

## Consecuencias

Los consumidores que escriben datos requieren Alembic `0006`. Una escritura
puede devolver un resultado confirmado con auditoría incompleta; el consumidor
debe conservar su identidad y reconciliarla explícitamente antes de ejecutar
pasos dependientes.

La tabla de comprobantes añade una escritura por operación pública, no por
fila. La integración real con PostgreSQL 17 y los cuatro roles sigue siendo la
evidencia necesaria para acreditar permisos, atomicidad y comportamiento bajo
concurrencia. Colab y Drive requieren además validación manual en su entorno.
