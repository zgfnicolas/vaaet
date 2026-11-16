# Reglas de negocio

Una regla de negocio se cumple siempre, sin importar el notebook, el componente
o la tecnología. Cada una tiene un ID estable que puede citarse en código,
pruebas, commits y revisiones. El origen indica el ADR que la decidió: cambiar
una regla exige un ADR nuevo y aprobación humana.

## Estados de tránsito

### RN-01 — El modelo aprende tres estados

El MLP aprende sólo `Normal`, `Reduced` y `Congested` (0–2). Los cuatro estados
públicos se conservan.

- Origen: [ADR-0014](../architecture/decisions/0014-hierarchical-traffic-state-and-incident-policy.md)
- Se aplica en: `vaaet/inference/policy.py`, manifiesto del bundle y
  `CHECK (traffic_state BETWEEN 0 AND 2)` en `vaaet_ml.traffic_predictions`

### RN-02 — `Accident` es exclusivamente humano

El estado 3 sólo existe en una validación humana que incluye una nota y
confirma que se revisó el contexto temporal. Ningún camino automático lo
publica.

- Origen: [ADR-0014](../architecture/decisions/0014-hierarchical-traffic-state-and-incident-policy.md),
  [ADR-0029](../architecture/decisions/0029-postgresql-numeric-fidelity-and-hitl-consistency.md)
- Se aplica en: constraint de `vaaet_feedback.human_validations` y política de
  inferencia del core

### RN-03 — Un posible incidente conserva `Congested`

Una evidencia fuerte y persistente de incidente mantiene el estado `Congested`
y activa `accident_rule_triggered` para revisión. Una medición incompleta o de
baja calidad nunca activa la alerta.

- Origen: [ADR-0014](../architecture/decisions/0014-hierarchical-traffic-state-and-incident-policy.md)
- Se aplica en: `vaaet/inference/policy.py`

## Telemetría, features y continuidad

### RN-04 — 19 features en orden contractual

Las 19 `FEATURE_COLS` conservan nombre, orden y semántica. Agregar, quitar o
reordenar una exige una decisión explícita con migración y compatibilidad.

- Origen: [ADR-0010](../architecture/decisions/0010-mlops-pipeline-19-features.md),
  [ADR-0026](../architecture/decisions/0026-temporal-continuity-and-immutable-model-revisions.md)
- Se aplica en: `vaaet/settings.py` (`FEATURE_COLS`)

### RN-05 — Sólo minutos completos y observados

La telemetría se emite por minutos completos; el tramo final parcial se
descarta. Un minuto sin detecciones conserva sólo valores observados y señales
de calidad, sin promedios históricos.

- Origen: [PRD](product-requirements.md), HU-01
- Se aplica en: sesión de visión de `vaaet-core`

### RN-06 — Ningún estado atraviesa un límite de continuidad

`continuity_id` se reinicia ante un clip nuevo, una transición de vista o un
hueco mayor a 90 segundos. Features, etiquetas, histéresis e incidentes no
atraviesan ese límite. Los timestamps duplicados, regresivos o inválidos se
rechazan.

- Origen: [ADR-0026](../architecture/decisions/0026-temporal-continuity-and-immutable-model-revisions.md),
  [ADR-0027](../architecture/decisions/0027-complete-bundle-identity-and-hitl-integrity.md)
- Se aplica en: `vaaet/continuity.py` (`normalize_continuity_frame()`)

### RN-07 — Las vistas no se mezclan

Un `VideoViewPlan` sólo admite segmentos offline declarados y calibrados. Cada
transición reinicia el estado temporal, descarta el minuto mixto y no
reidentifica vehículos entre vistas. No se inventan perfiles de calibración.

- Origen: [ADR-0025](../architecture/decisions/0025-calibrated-multi-view-video-segments.md)
- Se aplica en: `vaaet/vision/view_plan.py`

## Bundle y modelo

### RN-08 — Manifiesto antes que binarios

El manifiesto del bundle v3 y sus checksums se validan antes de deserializar
`.keras` o `.joblib`.

- Origen: [contrato del bundle](../ml/model-artifact-contract.md),
  [ADR-0021](../architecture/decisions/0021-portable-core-and-ml-laboratory-boundary.md)
- Se aplica en: `vaaet/artifacts.py` (`validate_manifest()`) y
  `vaaet/inference/bundle.py` (`load_traffic_bundle()`)

### RN-09 — Una revisión identifica un bundle exacto

`model_revision` identifica un bundle exacto, incluido su `input_policy`.
Ninguna predicción histórica se sobrescribe: una reinferencia con otro bundle
crea filas nuevas.

- Origen: [ADR-0026](../architecture/decisions/0026-temporal-continuity-and-immutable-model-revisions.md),
  [ADR-0027](../architecture/decisions/0027-complete-bundle-identity-and-hitl-integrity.md)
- Se aplica en: manifiesto del bundle y clave
  `(telemetry_feature_id, model_revision)` en PostgreSQL

### RN-10 — El modelo semilla es un piloto

Un bundle entrenado sólo con weak supervision tiene `deployment_stage=pilot` y
`production_eligible=false`. Usarlo en inferencia exige autorización explícita.

- Origen: [ADR-0017](../architecture/decisions/0017-seed-bootstrap-and-hitl-retraining.md)
- Se aplica en: `vaaet/lifecycle.py` y `vaaet/artifact_validation.py`

### RN-11 — La promoción es una decisión humana

Ninguna evaluación promociona un modelo. Dos candidatos sólo se comparan para
promoción si usan el mismo fingerprint de holdout humano, y los gates se aplican
sobre límites conservadores del 95 % por bootstrap de clips completos.

- Origen: [ADR-0018](../architecture/decisions/0018-versioned-frozen-human-holdouts.md),
  [ADR-0026](../architecture/decisions/0026-temporal-continuity-and-immutable-model-revisions.md)
- Se aplica en: notebook de evaluación (read-only) y
  [model card](../ml/model-card.md)

### RN-12 — Probabilidades válidas o rechazo

Toda matriz de probabilidades tiene forma `(N, 3)`, valores finitos en `[0, 1]`
y suma uno por fila con tolerancia `1e-6`. Una salida inválida se rechaza; no se
recorta ni se renormaliza.

- Origen: [ADR-0032](../architecture/decisions/0032-complete-cycle-integrity.md)
- Se aplica en: `vaaet/calibration.py`

## HITL y datasets

### RN-13 — Una predicción no es una etiqueta

Las predicciones sin validación humana nunca se usan como targets de
entrenamiento.

- Origen: [ADR-0017](../architecture/decisions/0017-seed-bootstrap-and-hitl-retraining.md)
- Se aplica en: entrenamiento `HITL_RETRAINING` de `vaaet-ml`

### RN-14 — Validaciones append-only con una única etiqueta efectiva

Una corrección es una validación nueva que sustituye a la anterior; nada se
edita ni se borra. La etiqueta efectiva es el único nodo terminal de una cadena
lineal válida. Las cadenas ambiguas se conservan para diagnóstico y quedan fuera
del uso supervisado.

- Origen: [ADR-0029](../architecture/decisions/0029-postgresql-numeric-fidelity-and-hitl-consistency.md),
  [ADR-0030](../architecture/decisions/0030-operational-idempotency-and-portable-hitl-coherence.md)
- Se aplica en: vistas `effective_human_labels` y `human_validation_conflicts`

### RN-15 — Datasets inmutables

La semilla, los paquetes HITL, los input locks y los holdouts humanos no se
sobrescriben. Datos distintos generan una versión nueva con
`CREATE_NEW_VERSION` y un motivo.

- Origen: [ADR-0018](../architecture/decisions/0018-versioned-frozen-human-holdouts.md),
  [ADR-0019](../architecture/decisions/0019-immutable-seed-and-hitl-datasets.md)
- Se aplica en: `vaaet_ml/data/` y `vaaet_ml/data/training_input_lock.py`

### RN-16 — El holdout no entra a train

Todos los clips de un holdout humano congelado se excluyen del entrenamiento.

- Origen: [ADR-0018](../architecture/decisions/0018-versioned-frozen-human-holdouts.md)
- Se aplica en: particiones de entrenamiento de `vaaet-ml`

### RN-17 — Sin auditoría verificable no hay supervisión

Una validación con auditoría pendiente conserva su UUID y fecha, pero no se
exporta ni se usa como target hasta recuperarla contra su comprobante. Toda
decisión supervisada declara su origen `portable` o `postgresql`.

- Origen: [ADR-0033](../architecture/decisions/0033-verifiable-persistence-recovery-and-hitl-audit.md),
  [ADR-0034](../architecture/decisions/0034-uniform-review-audit-evidence.md)
- Se aplica en: `vaaet_ml/data/review_audit.py`

### RN-18 — Una sesión de revisión alterada se invalida

La sesión de revisión sella su procedencia y las columnas exportables. Cualquier
alteración la invalida de forma irreversible y sus decisiones no se trasladan
a otra sesión. La recuperación sólo procede contra la sesión original vigente.

- Origen: [ADR-0035](../architecture/decisions/0035-review-recovery-and-lossless-packages.md),
  [ADR-0036](../architecture/decisions/0036-coherent-hitl-sessions-and-typed-integers.md)
- Se aplica en: sesión de revisión HITL de `vaaet-ml`

### RN-19 — Un único publicador del catálogo

Sólo el runtime designado con un `HitlCatalogPublisher` activo modifica el
catálogo HITL. El bloqueo es local al host: dos runtimes de Colab no publican a
la vez.

- Origen: [ADR-0031](../architecture/decisions/0031-hitl-integrity-and-coordinated-catalog-publication.md)
- Se aplica en: `vaaet_ml/data/hitl_catalog.py`

## Persistencia

### RN-20 — PostgreSQL es opcional y no rompe el workflow

La persistencia se habilita explícitamente. Si falta la credencial o falla la
conexión, el workflow lo informa y conserva sus outputs locales.

- Origen: [ADR-0024](../architecture/decisions/0024-provider-neutral-postgresql-and-schema-as-code.md)
- Se aplica en: `vaaet-persistence` y notebooks de `vaaet-ml`

### RN-21 — Alembic es la única autoridad DDL

El schema sólo cambia mediante una revisión Alembic nueva. Las revisiones
publicadas no se modifican y ninguna migración se ejecuta desde un notebook. La
única excepción es la corrección de `0003` registrada en ADR-0037.

- Origen: [ADR-0024](../architecture/decisions/0024-provider-neutral-postgresql-and-schema-as-code.md),
  [ADR-0028](../architecture/decisions/0028-shared-postgresql-persistence-layer.md),
  [ADR-0037](../architecture/decisions/0037-migration-0003-bind-literal-correction.md)
- Se aplica en: `vaaet-persistence/src/vaaet_persistence/migrations/`

### RN-22 — Escritura y comprobante en la misma transacción

Cada escritura de datos registra su comprobante en la misma transacción. Una
reconciliación verifica el contenido almacenado y nunca reinserta filas.

- Origen: [ADR-0032](../architecture/decisions/0032-complete-cycle-integrity.md),
  [ADR-0033](../architecture/decisions/0033-verifiable-persistence-recovery-and-hitl-audit.md)
- Se aplica en: `vaaet_persistence/receipts.py`

### RN-23 — Fidelidad `float64` sin reconstruir historia

Las medidas continuas, features y probabilidades se guardan como
`DOUBLE PRECISION`; los conteos y estados, como enteros. Las filas históricas
redondeadas se marcan `legacy-rounded` y no se reconstruyen.

- Origen: [ADR-0029](../architecture/decisions/0029-postgresql-numeric-fidelity-and-hitl-consistency.md)
- Se aplica en: columna `numeric_representation` de cada tabla numérica

## Datos privados y licencias

### RN-24 — Lo privado no entra a Git

Videos, datasets privados, validaciones sensibles, credenciales, DSN,
certificados, calibraciones reales y binarios ML no se versionan con Git ni se
exponen en logs o ejemplos. El bundle se versiona con DVC.

- Origen: [ADR-0023](../architecture/decisions/0023-provider-neutral-dvc-registry.md),
  [política de seguridad](../governance/security-policy.md)
- Se aplica en: `.gitignore` y CI (rechazo de binarios ML)

### RN-25 — Sólo agregados, sin identidades

VAAET persiste agregados por minuto y revisiones seudónimas. No extrae patentes,
identidades ni frames individuales.

- Origen: [política de seguridad](../governance/security-policy.md)
- Se aplica en: contrato de telemetría y `VAAET_REVIEWER_ID`

### RN-26 — Serving con YOLO por una vía explícita

Una ejecución con `vaaet-core[vision]` sólo se sirve como demo pública AGPL con
el checklist completo o como aplicación privada con licencia Ultralytics
Enterprise verificada fuera de Git.

- Origen: [ADR-0022](../architecture/decisions/0022-agpl-public-demo-path.md)
- Se aplica en: [checklist de demo AGPL](../governance/agpl-demo-release-checklist.md)
