# ADR-0036 — Sesiones HITL coherentes y enteros tipados preservados

- Estado: aceptada
- Fecha: 2026-09-26
- Complementa: ADR-0035

## Contexto

Una sesión preparada podía conservar sus decisiones mientras se modificaban
metadatos exportables del frame, incluida la identidad del clip. El formulario
no siempre reflejaba una recuperación externa confirmada. Además, el lector
`typed-csv-v1` convertía enteros opcionales a `float64` y la idempotencia de
PostgreSQL equiparaba un nulo con el texto literal `"None"`.

## Decisión

La sesión gestionada sella la procedencia y una fotografía tipada de todas las
columnas exportables. Comprueba vigencia e integridad antes de enviar,
recuperar, reconciliar o finalizar. El orden físico de las filas y un offset
distinto del mismo instante UTC no cambian su contenido contractual. Cualquier
contradicción invalida la sesión de forma irreversible: se prepara otra y las
decisiones originales no se trasladan automáticamente.

El registro de envíos de la sesión es la autoridad para el formulario. Una
recuperación confirmada notifica al widget y lo avanza una sola vez; un envío
posterior de ese mismo UUID devuelve el resultado confirmado sin otra escritura.
Los fallos de presentación no revierten el estado confirmado.

El lector `typed-csv-v1` materializa enteros con nulos como `int` y `None`, sin
pasar por `float64`. Los nuevos paquetes declaran lector mínimo ML 4.9.3;
no cambian el codec, fingerprint ni contratos contenedores. La comparación
idempotente de validaciones PostgreSQL usa tipos contractuales: nulo, texto,
UUID, booleano, entero e instante UTC no se comparan mediante `str()` general.

## Consecuencias

No cambian Alembic `0006`, permisos, historia ni artefactos existentes. Los
paquetes históricos ambiguos siguen siendo inspeccionables y sólo se admiten
para entrenamiento tras verificación y reexportación explícitas. PostgreSQL 17
con cuatro roles, Colab y Drive requieren validación operacional antes de
declarar el recorrido apto para producción.
