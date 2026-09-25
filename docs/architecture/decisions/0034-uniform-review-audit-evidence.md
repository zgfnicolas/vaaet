# ADR-0034 — Evidencia uniforme de auditoría HITL

- Estado: aceptada
- Fecha: 2026-09-24
- Complementa: ADR-0033

## Contexto

La revisión PostgreSQL bloqueaba decisiones con auditoría pendiente en el
formulario y en la lectura directa. El exportador portable y los backups podían
eludir ese control. Además, los notebooks iniciaban corridas de escritura sin el
conteo y schema que exige su reconciliación.

## Decisión

Cada decisión supervisada declara su origen `portable` o `postgresql`. La
primera se confirma dentro de una sesión portable explícita. La segunda exige
corrida terminal, comprobante inmutable y coincidencia del contenido cuando la
fuente operacional está disponible. ZIPs nuevos incluyen la procedencia y el
fingerprint del comprobante por UUID de validación. Backups se verifican con las
tablas originales de corridas y comprobantes antes de adaptar sus IDs.

Los paquetes históricos sin evidencia suficiente permanecen intactos y son
inspeccionables; no entran al entrenamiento. Verificarlos y reexportarlos
requiere una acción explícita. Las corridas PostgreSQL de video comienzan
después de conocer las filas persistibles y conservan conteo, schema e identidad
de modelo exactos. El widget conserva UUID, fecha y contenido antes del envío.

La reconciliación humana traduce errores externos al contrato redactado de
persistencia. Alembic `0006`, las tablas y los permisos permanecen vigentes.

## Consecuencias

La evidencia en un ZIP protegido por checksums prueba integridad del snapshot,
no autenticidad criptográfica del productor. La aceptación operacional requiere
PostgreSQL 17 con roles reales y validación manual en Colab y Drive; las pruebas
con dobles de prueba no sustituyen esas comprobaciones.
