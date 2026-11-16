# ADR-0037 — Corrección del literal `:legacy-` en la migración `0003`

- Estado: Aceptada
- Fecha: 2026-11-15
- Decisores: responsable técnico
- Reemplaza a: N/A; actualiza el invariante de bytes de ADR-0029, ADR-0030 y ADR-0033 sólo para `0003`

## Contexto

La revisión Alembic `20260905_0003` asigna `continuity_id` a las filas
históricas con el literal SQL `':legacy-'`. `op.execute()` envuelve el string
en `sqlalchemy.text()`, que interpreta `:legacy` como un parámetro. Sin valor
para ese parámetro, cualquier SQLAlchemy 2.x falla con *A value is required for
bind parameter 'legacy'*. En modo offline (`alembic upgrade --sql`) no falla:
escribe `'NULL-'` y produciría `continuity_id` incorrectos.

En consecuencia, ninguna base pudo pasar de `0002` con Alembic online, y el job
`postgres-integration` falla desde que entró `0003` el 2026-09-06. Por eso
`0004` a `0006` tampoco se probaron contra PostgreSQL 17 en CI. El responsable
técnico confirmó que ninguna base real pasó de `0002`.

ADR-0029, ADR-0030 y ADR-0033 fijan que las revisiones históricas permanecen
byte a byte intactas, y RN-21 prohíbe modificar revisiones publicadas.

## Opciones consideradas

1. Escapar el literal en `0003` como `'\:legacy-'`.
2. Fijar SQLAlchemy por debajo de 2.1. Se descartó porque 2.0 falla igual.
3. Dejar `0003` intacta y agregar una revisión correctiva. Es imposible, porque
   Alembic ejecuta `0003` antes que cualquier revisión nueva.

## Decisión

Se corrige `0003` escapando sólo ese literal; PostgreSQL recibe `':legacy-'`
exactamente como pretendía la revisión original. No cambian el schema, los
datos esperados, la identidad de la revisión ni las revisiones `0001`, `0002`,
`0004`, `0005` y `0006`.

El hash congelado de `0003` se actualiza y un test nuevo compila el SQL de cada
revisión sin base de datos. Ese test rechaza parámetros sin valor y la
conversión offline a `'NULL-'`.

## Motivos

- Es la única corrección posible: la revisión defectuosa bloquea toda la cadena.
- Es segura: ninguna base aplicó `0003` con Alembic online, porque esa
  ejecución siempre falla.
- El resultado coincide con la intención documentada en ADR-0026.

## Consecuencias

- (+) La cadena Alembic completa vuelve a ejecutarse y `postgres-integration`
  valida otra vez `0004` a `0006`.
- (+) El test de SQL de migraciones detecta este error en cualquier revisión
  futura sin requerir PostgreSQL.
- (−) Se rompe una vez el invariante de bytes de una revisión publicada. La
  excepción queda limitada a `0003` y a este ADR; la regla general de RN-21
  sigue vigente.
- Una base migrada alguna vez con SQL offline generado antes de esta corrección
  tendría `continuity_id` con prefijo `NULL-` y necesitaría una corrección
  gobernada. No se conoce ninguna.
