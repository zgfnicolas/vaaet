# ADR-0035 — Recuperación vinculada a la sesión y paquetes sin pérdida

- Estado: aceptada
- Fecha: 2026-09-26
- Complementa: ADR-0034

## Contexto

Una decisión PostgreSQL podía recuperarse por su ID numérico de predicción
sin comprobar que el clip abierto fuera el de su corrida original. Además, la
inferencia de tipos de CSV reinterpretaba textos como `007` y `NA`, y el estado
incierto de un envío no siempre llegaba al bloqueo de finalización. La lectura
de auditorías hacía una consulta cliente por corrida.

## Decisión

Una sesión HITL gestionada fija su origen, corrida de inferencia, revisión del
modelo, observaciones y valores contractuales de features. La recuperación
exige que esa sesión siga vigente, pertenezca a PostgreSQL y coincida con la
cola de la corrida original antes de reconciliar o incorporar la decisión.
Una decisión preparada se conserva por UUID y fecha y bloquea la finalización
mientras su resultado sea incierto o su auditoría siga pendiente. Tras reiniciar
el runtime, sólo se retoma reconstruyendo explícitamente la sesión original.

Los nuevos ZIP semilla y HITL declaran `typed-csv-v1`, tipos por columna,
posiciones de nulos y versión mínima de lector. El codec conserva literalmente
texto, distingue `None` de cadena vacía y lee `float64` sin inferencia textual.
El fingerprint HITL nuevo `sha256-contractual-frames-v3` codifica valores
tipados; los algoritmos anteriores permanecen para verificar históricos. Un
ZIP histórico con textos ambiguos conserva su integridad y puede inspeccionarse,
pero no se admite como supervisión sin verificación y reexportación explícitas.
El sellado valida un archivo temporal antes de publicar un destino inmutable.

La consulta de auditorías agrupa hasta 500 UUID por sentencia cliente mediante
la función PostgreSQL autorizada, dentro de la misma fotografía de lectura.
No cambian grants ni Alembic `0006`.

## Consecuencias

El bloqueo local de sesión no sustituye la autenticación ni la autorización
del futuro backend. El control de checksums acredita integridad, no autenticidad
del productor. La prueba operacional con PostgreSQL 17, Colab y Drive sigue
siendo obligatoria antes de declarar aptitud para producción.
