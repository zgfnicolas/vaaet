# ADR-0030 — Idempotencia operacional y coherencia HITL portable

- Estado: aceptada
- Fecha: 2026-09-11
- Decisor: Facundo Nicolás González
- Complementa: ADR-0029

## Contexto

La implementación de ADR-0029 expuso bordes que todavía podían perder
coherencia: una feature válida del core era rechazada, el trigger de revisión
solicitaba un permiso de bloqueo no concedido, un reintento podía fabricar otra
corrida y distintas representaciones del mismo instante producían UUID
portables diferentes. Además, la creación de un paquete HITL dependía del
montaje de Drive y los notebooks no distinguían el procesamiento de cada
intento de persistencia.

## Decisión

Alembic `0005` mantiene `vaaet-db-v3` y reemplaza únicamente la función de
validación append-only. La serialización continúa con un advisory lock
transaccional por predicción, sin `FOR KEY SHARE`, `UPDATE`, `DELETE` ni
privilegios administrativos para el reviewer. La función permanece
`SECURITY INVOKER` y fija su `search_path`.

Las escrituras validan el DataFrame completo antes de adquirir recursos. Los
lotes usan una sentencia `INSERT` multi-`VALUES` parametrizada, `RETURNING` y
una relectura agrupada por claves. La observabilidad registra sentencias reales,
filas, lotes y duración. Los reintentos exitosos informan filas procesadas sin
reescribir el conteo terminal con la cantidad insertada por primera vez.

Una decisión humana conserva UUID, fecha y corrida originales. Antes de crear
una corrida automática se consulta esa identidad; contenido igual reutiliza el
registro y contenido o corrida contradictorios producen un conflicto. La
cadena efectiva debe ser un único grafo lineal completamente alcanzable desde
su raíz.

La identidad portable normaliza el instante a UTC y deriva UUID desde corrida,
clave natural, continuidad, schema y revisión exacta. Los paquetes históricos
no se modifican: sus aliases sólo se resuelven en memoria cuando la equivalencia
contractual es demostrable. No se inventan revisiones, UUID, revisores ni
fechas para completar fuentes antiguas.

Un backup legado que sólo marca una predicción como revisada, pero no contiene
la tabla autoritativa `human_validations` con identidades y cadena completas,
permanece inspeccionable y no se transforma en ground truth.

Los notebooks publican una clasificación sólo después de validar contrato y
paridad HUD/batch. Cada intento de persistencia posee un manifiesto local
separado y correlacionado con `pipeline_run_id`. La finalización HITL sella
primero el ZIP local y sincroniza después; un fallo remoto conserva exactamente
los mismos bytes como `pending-sync`.

Los paquetes nuevos declaran `sha256-contractual-frames-v2`: el fingerprint
sella también `reviewed_at`, porque la fecha pertenece a la decisión humana.
Los paquetes anteriores sin discriminador se verifican con el algoritmo legado
que omitía esa columna; nunca se reescriben para aparentar la identidad nueva.

## Invariantes

- Las 19 features, sus cálculos, el MLP, los umbrales y los estados no cambian.
- `low_speed_persistence` es un conteo temporal entero entre 0 y 2.
- `Accident` requiere una decisión humana con nota y contexto temporal.
- PostgreSQL continúa opt-in y Alembic es la única autoridad DDL.
- Las revisiones `0001`--`0004` permanecen byte a byte intactas.
- Los errores públicos no incluyen mensajes externos, parámetros ni secretos.

## Consecuencias

Los consumidores que escriben requieren la revisión `0005`. Los paquetes sin
trazabilidad suficiente permanecen disponibles para inspección, pero no pueden
convertirse en ground truth. La validación real exige PostgreSQL 17 con roles
separados y una ejecución Colab/Drive; los mocks no sustituyen esa evidencia.
