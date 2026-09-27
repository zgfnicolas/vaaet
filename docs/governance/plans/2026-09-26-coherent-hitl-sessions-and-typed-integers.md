# Plan gobernado — Sesiones HITL coherentes y tipos preservados

- Fecha: 2026-09-26
- Alcance: Persistence 0.3.3 y ML 4.9.3; Core permanece en 0.2.2
- Decisión: [ADR-0036](../../architecture/decisions/0036-coherent-hitl-sessions-and-typed-integers.md)
- Estado: implementado; aceptación operacional pendiente

## Fases

1. Reproducir reasociación por mutación del frame, pérdida de enteros opcionales,
   equivalencia incorrecta de notas y desincronización del formulario.
2. Sellar el contenido exportable y bloquear una sesión alterada antes de
   efectos sobre PostgreSQL o ZIP; conservar decisiones sin trasladarlas.
3. Unificar estado de envío y recuperación en la sesión y notificar al widget
   una confirmación externa sin repetir escrituras.
4. Preservar enteros y nulos en el codec tipado y comparar decisiones
   persistidas según sus tipos contractuales.
5. Ejecutar regresiones, calidad estática e integración PostgreSQL 17
   desechable; validar manualmente Colab y publicación coordinada en Drive.

## Criterio de cierre

Cada hallazgo debe contar con una regresión que pruebe el recorrido afectado.
Las pruebas sin PostgreSQL real no acreditan la integración de roles o
transacciones. No se alteran migraciones, snapshots, paquetes históricos,
remotos DVC ni servidores del usuario. Si faltan PostgreSQL, Colab o Drive,
el estado será «implementado; aceptación operacional pendiente».

## Matriz de hallazgos y evidencia

| Hallazgo | Regresión | Corrección | Evidencia local |
| --- | --- | --- | --- |
| Decisión asociable a otro clip tras mutar el frame | Mutaciones parametrizadas de clip, instante, continuidad, IDs, schema, modelo, estado y features; envío, recuperación y finalización bloqueados | Fotografía tipada de todas las columnas, contexto sellado e invalidación irreversible | Pruebas de `test_review_finalization.py` y `test_review_orchestration.py`; ningún ZIP creado |
| Entero opcional convertido a `float64` | Round-trip de nulos, `2**53 + 1`, límites BIGINT y paquete HITL sellado | Decodificación de enteros como `int`/`None` sin paso por flotante | Pruebas de codec y finalización; fingerprint tipado conservado |
| Nulo equiparado al texto `"None"` | Reintentos automático, explícito y reconciliación con notas distintas | Comparación contractual de texto, UUID, enteros, booleano y UTC | Nueve casos parametrizados y prueba PostgreSQL 17 añadida al job obligatorio; esta última pendiente de ejecución ambiental |
| Formulario desincronizado de la recuperación | Timeout, confirmación externa, avance único y pulsación posterior sin reenvío | Registro de decisión en la sesión y notificaciones locales al widget | `test_external_recovery_confirms_widget_once_without_resubmitting` y `test_confirmed_recovery_cannot_resubmit_same_decision` |

La prueba de recuperación → ZIP → ingestión existente continúa comprobando
identidad y etiqueta del clip original. Las suites sin PostgreSQL real no
sustituyen la integración con cuatro roles ni la comprobación manual en Colab
y Drive. La deuda histórica de advertencias Pyright se informa por separado.
