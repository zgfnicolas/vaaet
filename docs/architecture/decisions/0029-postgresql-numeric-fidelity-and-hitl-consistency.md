# ADR-0029 — Fidelidad numérica e integridad HITL en PostgreSQL

- Estado: aceptada
- Fecha: 2026-09-09
- Decisor: Facundo Nicolás González
- Actualiza: ADR-0024 y ADR-0028

## Contexto

La extracción de `vaaet-persistence` dejó una única implementación compartida,
pero reveló diferencias entre el contrato tabular y su representación
operacional: `NUMERIC(p,s)` redondeaba cálculos `float64`, algunas corridas no
registraban la misma identidad antes de insertar y las validaciones podían
resolverse por fecha en lugar de por la cadena append-only.

Esas diferencias afectan idempotencia, trazabilidad y la futura reutilización
desde un backend. Los históricos no pueden recuperar precisión ya perdida ni
deben convertirse silenciosamente en ground truth moderno.

## Decisión

Alembic `0004` conserva `vaaet-db-v3` y cambia las medidas continuas, features y
probabilidades a `DOUBLE PRECISION`. Los conteos y estados permanecen enteros.
Cada tabla numérica declara `numeric_representation`: `legacy-rounded` para las
filas anteriores y `float64` para escrituras nuevas. No se reconstruyen
decimales históricos. Los schemas de telemetría y features dejan de tener un
valor predeterminado en PostgreSQL: cada escritura nueva debe declararlos y ser
validada antes de abrir la transacción.

Las corridas registran `application_name` y se crean antes de las filas que las
referencian. Inicio y cierre son idempotentes únicamente cuando identidad y
contenido coinciden; una colisión diferente es un conflicto inmutable.

La validación humana efectiva es el único nodo terminal de una cadena válida.
Las inserciones se serializan por predicción, impiden raíces paralelas,
sucesores múltiples y sustituciones cruzadas. Los conflictos históricos se
conservan en una vista de diagnóstico y quedan fuera de la vista supervisada.

Las lecturas HITL relacionadas usan una transacción read-only `REPEATABLE READ`.
Las escrituras validan todas las filas antes de comenzar y se envían en lotes
acotados dentro de una sola transacción. Los UUID portables se derivan de las
claves operacionales verificadas; los IDs numéricos originales se conservan
como procedencia.

Cada escritura registra observaciones seguras de filas, lotes, consultas de
datos, duración y throughput, sin payloads ni credenciales. Esas mediciones
sirven para ajustar el pool o el tamaño de lote con evidencia; no constituyen
una promesa de latencia para un proveedor todavía no medido.

## Invariantes

- Las 19 features, el MLP, los umbrales, los estados y los contratos ML no
  cambian.
- `Accident` sólo existe mediante una validación humana con contexto confirmado
  mediante un booleano real y una nota.
- PostgreSQL sigue siendo opt-in y Alembic sigue siendo la única autoridad DDL.
- `0001`--`0003` permanecen byte a byte intactas.
- TLS remoto usa `verify-full` por defecto; `require` es una excepción advertida,
  `verify-ca` no verifica hostname y `disable` se limita a localhost.
- Los mensajes externos y parámetros SQL no se propagan a errores públicos.

## Consecuencias

La migración puede reescribir tablas y requiere ensayo sobre una restauración,
backup y ventana administrativa. No existe downgrade que vuelva a redondear
datos nuevos; la recuperación es hacia adelante o mediante restauración.

Los paquetes históricos siguen siendo inspeccionables, pero cualquier conflicto
o representación incompatible exige reconciliación explícita antes de entrenar.
La API futura podrá consumir la misma semántica sin depender del laboratorio.
