# Model card — VAAET Traffic State Classifier

## Identificación

| Campo | Valor |
|---|---|
| Proyecto | VAAET ML 4.6.1 |
| Modelo vigente | `mlp-v3.0` |
| Estado inicial | Pilot weak-supervision hasta cumplir gates humanos |
| Runtime | TensorFlow/Keras, Python 3.10–3.13, Google Colab |
| Artefacto | Bundle DVC contrato v3 |

## Uso previsto

El modelo ayuda a describir por minuto el flujo del Puente General Manuel Belgrano. No es un sistema autónomo de seguridad, no decide respuestas de emergencia y no debe transferirse a otra cámara o vía sin validación local.

## Arquitectura

```text
19 features v3
-> Dense(64) + BatchNorm + Dropout(0.3)
-> Dense(32) + BatchNorm + Dropout(0.2)
-> Dense(3, softmax)
-> confianza/margen + histéresis + transiciones adyacentes
-> detector conservador de posible incidente
-> confirmación humana opcional
```

Las salidas aprendidas son `Normal`, `Reduced` y `Congested`. El estado público `Accident` sólo puede provenir de una confirmación humana validada. Una sospecha automática permanece `Congested` y activa `accident_rule_triggered`.

## Features

Se conserva el orden contractual de 19 features: velocidad y volumen; conteos de cinco tipos; proporción de pesados; deltas, transición, varianza y persistencia por segmento continuo de cada clip; calidad de velocidad, near-zero y stationary sobre tracks únicos; hora y proxy nocturno. `record_time` se transporta en UTC, mientras `hour_of_day` y `weather_condition` se derivan en `America/Argentina/Buenos_Aires`. La semántica temporal corresponde a `traffic-features-v3`; `continuity_id` reinicia el contexto ante cambios de vista o huecos superiores a 90 segundos y no ingresa al MLP.

Los registros `traffic-telemetry-v1` no contienen evidencia moderna de calidad.
El modo semilla aplica `input_policy=legacy-v1-bootstrap`: neutraliza
`speed_measurement_quality`, `near_zero_motion_ratio` y
`stationary_confirmed_ratio` tanto en train como en serving. No se interpretan
como calidad perfecta ni se permite que los sintéticos revelen su procedencia.

## Datos y particiones

- Test: clips reales temporalmente posteriores y congelados.
- Validation: grupos reales completos del período restante.
- Train: grupos restantes; es la única partición que admite sintéticos.
- Scaler, class weights y cualquier balanceo se ajustan sólo con train.
- El bootstrap compara class weights, oversampling moderado y escenarios
  sintéticos de congestión sobre validation proxy; prioriza coste y falsos
  Congested, sin SMOTE 1:1.
- Escenarios sintéticos de Accident no son targets del MLP ni evidencia de eficacia real.

Las etiquetas de reglas son proxies. El bundle semilla es un piloto y sus
métricas sólo expresan fidelidad a esa weak supervision. En HITL, la memoria
proxy decrece hasta cero a 300 etiquetas humanas Normal, 300 Reduced y 100
Congested. Las métricas de producción sólo son válidas sobre un holdout real,
humano y agrupado conforme al [protocolo de anotación](human-annotation-protocol.md).

## Métricas y promoción

Los objetivos iniciales son F1-macro ≥0,88; precision/recall de Normal ≥0,93; precision Reduced ≥0,88 y recall ≥0,90; precision Congested ≥0,90 y recall ≥0,85; error Normal↔Congested ≤1%; ECE ≤0,05. Se publican por separado métricas `direct_*` del MLP y `final_*` posteriores a calibración e histéresis. La promoción usa límites conservadores del 95 % obtenidos por bootstrap de clips completos.

Sin al menos 100 minutos Congested validados de 20 episodios reales, esa clase es experimental. Sin accidentes reales no se publica recall de Accident. Para candidatos se reportan falsos por hora; el objetivo preliminar es menos de uno cada 100 horas y unas 300 horas negativas sin falsos para evidencia aproximada al 95%.

La promoción manual exige telemetría v3 suficiente, holdout humano v2, retrospective replay, shadow mode prospectivo y revisión de falsos positivos. El manifiesto conserva `production_eligible` y `promotion_blockers`.
El notebook no considera congelado un test sólo porque sus filas sean humanas.
Desde 4.4.0, `HUMAN_HOLDOUT_FROZEN=True` resuelve un snapshot contractual con
validation y test exactos, checksums y fingerprint. Todos sus clips se excluyen
de train y cada actualización produce una generación nueva. El manifiesto del
modelo registra ese fingerprint; candidatos evaluados con benchmarks diferentes
no son comparables automáticamente.

Desde 4.5.0, cada candidato registra además un
`vaaet-training-input-lock-v1`. El lock fija el snapshot semilla, revisión del
catálogo HITL, paquetes y fingerprints exactos, resolución de duplicados y
correcciones, y holdout utilizado. Repetir un entrenamiento con el mismo lock
reproduce la selección de datos, aunque los pesos dependan también de las semillas
y del runtime declarado.

Cada corrida válida puede conservar además un informe
`vaaet-training-observability-report-v1` con curvas, calidad/calibración y
progreso de supervisión agregado. Es evidencia para revisión humana; sus KPIs no
añaden gates ni promocionan candidatos. Los deltas sólo se muestran ante
holdouts, features y salidas compatibles. Consultá la
[guía de observabilidad](training-observability.md).

## Limitaciones

- Datos históricos de un único puente, período y configuración de cámara.
- Calidad de velocidad sin ground truth físico exhaustivo.
- `weather_condition` sigue siendo un proxy horario, no meteorología real.
- El MLP es tabular; la temporalidad se incorpora mediante features y política, no LSTM.
- El desempeño con incidentes reales es desconocido hasta adquirir ejemplos confirmados.

## Historial

| Versión | Cambio |
|---|---|
| `mlp-v1.0` | Baseline histórico de 14 features |
| `mlp-v1.1` | Baseline de 19 features y cuatro salidas |
| `mlp-v2.0` | Tres salidas estables, contrato v2 y política jerárquica humana para Accident |
| `mlp-v2.1` | Modos seed/HITL, política legacy paritaria y selección conservadora de balanceo |
| `mlp-v3.0` | Continuidad explícita, revisión exacta del bundle y evaluación agrupada por clip; desde Core 0.2.1 la identidad incluye `input_policy` |

Última revisión: 2026-09-07. Véanse [ADR-0014](../architecture/decisions/0014-hierarchical-traffic-state-and-incident-policy.md), [ADR-0015](../architecture/decisions/0015-postgresql-namespaces-security-and-hitl.md), [ADR-0017](../architecture/decisions/0017-seed-bootstrap-and-hitl-retraining.md), [ADR-0018](../architecture/decisions/0018-versioned-frozen-human-holdouts.md), [ADR-0019](../architecture/decisions/0019-immutable-seed-and-hitl-datasets.md), [ADR-0026](../architecture/decisions/0026-temporal-continuity-and-immutable-model-revisions.md) y [ADR-0027](../architecture/decisions/0027-complete-bundle-identity-and-hitl-integrity.md).
