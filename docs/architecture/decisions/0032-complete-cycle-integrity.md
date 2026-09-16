# ADR-0032 — Integridad determinista del ciclo completo

- Estado: aceptada
- Fecha: 2026-09-15
- Decisor: Facundo Nicolás González
- Complementa: ADR-0030 y ADR-0031

## Contexto

La consolidación HITL, la lectura PostgreSQL y el cierre auditable ya tenían
identidad e idempotencia explícitas, pero quedaban seis bordes reproducibles.
El orden físico de UUID podía alterar la validación temporal, un identificador
de predicción ambiguo podía asociar una revisión a otro minuto y dos fuentes
históricas equivalentes podían rechazarse antes de resolver sus aliases.

Además, una escritura confirmada podía informarse como fallida si fallaba sólo
el cierre de su corrida, la lectura moderna podía caer silenciosamente a una
consulta legacy y una salida defectuosa del modelo podía transformarse en una
clasificación aparentemente válida.

## Decisión

La consolidación separa relaciones de secuencias: valida identidades y
contenido, resuelve aliases por niveles —features, predicciones y validaciones—,
deduplica y recién entonces ordena establemente por clip e instante UTC antes de
normalizar continuidad. El orden de fuentes o filas no decide el resultado.

Una `prediction_id` de una sesión de revisión identifica exactamente una
observación contractual. Repeticiones idénticas se consolidan; cualquier cambio
de minuto, clip, continuidad, schema, corrida, revisión o contenido se rechaza
antes de exportar un ZIP o modificar el catálogo. Los aliases históricos se
aplican sólo en memoria y conservan IDs y procedencia originales.

PostgreSQL exige `TelemetryReadMode.CURRENT` o `TelemetryReadMode.LEGACY`.
Cada modo ejecuta una única consulta y ninguna excepción activa el otro. Legacy
es una selección deliberada para telemetría raw, advierte sus campos desconocidos
y no se admite como feedback humano.

`PipelineRunOutcome` distingue el trabajo confirmado de su auditoría. Un fallo
de cierre no niega una escritura ya realizada ni provoca una reinserción. La
reconciliación vuelve a leer identidad, claves y contenido, completa únicamente
la auditoría pendiente y registra un intento separado. Los pasos que requieren
trazabilidad completa permanecen bloqueados mientras `audit_complete` sea falso.

El core ofrece una única validación de probabilidades para inferencia,
calibración, entrenamiento y evaluación. Toda matriz debe tener forma `(N, 3)`,
valores finitos dentro de `[0, 1]` y suma uno por fila con tolerancia absoluta
`1e-6`. Las salidas inválidas se rechazan; no se recortan ni renormalizan.

## Invariantes

- Alembic permanece en `0005` y las revisiones históricas no cambian.
- No cambian las 19 features, el MLP, los estados, los umbrales ni los formatos.
- `Accident` continúa siendo exclusivamente humano.
- Los aliases no reescriben ZIP, catálogos, holdouts ni fingerprints históricos.
- Una reconciliación nunca reinserta telemetría, predicciones o validaciones.
- Un modo legacy explícito no simula lineage ni calidad moderna.

## Consecuencias

Los consumidores deben declarar la lectura legacy y tratar un resultado con
auditoría incompleta como una operación confirmada todavía no habilitada para
pasos dependientes. La recuperación requiere conservar corrida, revisión y
contenido originales.

La validación estricta puede descubrir artefactos históricos ambiguos que antes
parecían utilizables. Permanecen inspeccionables, pero deben reconciliarse o
excluirse explícitamente. Las pruebas locales no sustituyen la integración con
PostgreSQL 17, los cuatro roles, Colab y Google Drive.
