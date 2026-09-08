# Contrato del bundle de modelo

El límite entre el laboratorio y cualquier consumidor de serving es un
directorio local portable, versionado como unidad con DVC en
`vaaet-ml/artifacts/traffic-state/`. El core no conoce DVC, Drive ni su
procedencia; el consumidor le entrega un directorio local ya aprobado.

## Contenido obligatorio

| Archivo | Función |
|---|---|
| `traffic_classifier.keras` | MLP de tres estados estables |
| `feature_scaler.joblib` | `StandardScaler` ajustado con el training set |
| `label_mapping.joblib` | Mapping de los cuatro códigos canónicos |
| `model-manifest.json` | Compatibilidad, integridad y procedencia |

El contrato v3 distingue `model_output_mapping` —Normal, Reduced y Congested—
de los cuatro estados públicos. También contiene la política jerárquica,
temperatura de calibración, umbrales por clase, margen, histéresis, prohibición de Accident automático,
confirmación humana obligatoria, elegibilidad, bloqueos de promoción y
checksums SHA-256. `model_revision` identifica los hashes exactos del modelo,
scaler y mapping junto con la política de decisión, el schema de features, el
training input lock y `input_policy`. `model_version` continúa siendo una
etiqueta semántica reutilizable. Las exportaciones nuevas declaran
`model_revision_algorithm=sha256-inference-contract-v2`.

`training_lifecycle` vuelve explícitos cuatro datos de serving:

- `training_mode`: `seed-bootstrap` o `hitl-retraining`.
- `supervision`: `weak-proxy` o `human-validated`.
- `input_policy`: `legacy-v1-bootstrap` o `canonical-v3`; `canonical-v2` se
  admite únicamente para bundles históricos.
- `deployment_stage`: `pilot`, `candidate` o `production`.

Desde VAAET 4.4.0, un modelo que declara `data_provenance.human_holdout=true`
debe incluir también `human_holdout`: contrato `vaaet-human-holdout-v2`, UUID del
snapshot, generación, fingerprint SHA-256 y filas de validation/test. Un modelo
sin benchmark congelado utiliza `null`. El descriptor no incorpora el dataset;
sólo permite auditar con qué fotografía humana se midió el candidato y rechazar
comparaciones automáticas entre fingerprints distintos.
El contrato v2 de holdout incorpora `continuity_id` y `model_revision`. Los
holdouts v1 sólo comparan bundles v2 históricos.

Desde VAAET 4.5.0, `training_input_lock` puede incorporar el descriptor
`vaaet-training-input-lock-v1`: UUID del lock y fingerprint SHA-256 de la selección
exacta de semilla, catálogo HITL y holdout. El JSON completo permanece en
`MyDrive/vaaet-ml/training-runs/<run-id>/`; el bundle conserva sólo su descriptor
y continúa teniendo cuatro archivos.

Un bundle semilla siempre es `pilot` y `production_eligible=false`. La política
legacy neutraliza las tres evidencias de calidad desconocidas tanto durante el
entrenamiento como durante la inferencia, evitando una divergencia train/serve.

Todo consumidor debe ejecutar `vaaet.artifacts.validate_manifest()` después de
obtener el bundle y antes de cargar Keras o joblib. En la futura API, el worker
es responsable de esa validación y de storage; la Web App sólo recibe referencias
por HTTP. Un campo ausente, JSON inválido, versión no soportada, schema/mapping
incompatible, archivo faltante o checksum alterado rechaza el bundle con un
error de dominio explícito.

`production_eligible=false` no invalida la integridad del bundle. Inferencia
permite un `pilot` sólo mediante `ALLOW_PILOT_BUNDLE=True`, lo identifica en el
output y conserva sus decisiones conservadoras. Los candidatos HITL no aprobados
requieren la autorización experimental separada; ningún flag cambia la metadata
ni promociona el artefacto.

Los bundles v3 sin `model_revision_algorithm` usan la identidad histórica que
no incluía `input_policy`. El loader operacional los rechaza aunque se activen
flags de piloto o candidato. Sólo el propósito tipado `historical-evaluation`
permite inspeccionarlos sin persistencia, HITL ni promoción. Una reexportación
usa `reexport_historical_bundle(...)`, exige un destino nuevo y un motivo, crea
otra revisión y fuerza `production_eligible=false`; el artefacto debe volver a
evaluarse antes de cualquier uso operacional.

Para declarar `production`, el core no acepta únicamente los booleanos de
elegibilidad. También valida holdout compatible, cobertura v3, soporte humano,
cero Accident automáticos, exposición de incidentes y métricas directas/finales
con intervalos del 95 % por bootstrap de clips completos. Las estimaciones
puntuales deben coincidir con esos intervalos.

## Versionado con DVC

Después del primer entrenamiento se elimina `.gitkeep`, se configura el remoto
local una única vez y se registra el directorio completo. `stage` valida el
manifiesto antes de invocar DVC:

```bash
vaaet-registry stage
git add vaaet-ml/artifacts/traffic-state.dvc .gitignore
git commit -m "feat(models): registrá bundle mlp-vX.Y"
git tag model/mlp-vX.Y
vaaet-registry push
```

La [guía del registro DVC](dvc-guide.md) describe la configuración local
agnóstica de proveedor, recuperación por commit o tag y migración manual. La
infraestructura de publicación y descarga queda fuera de alcance. La futura
API y Web App pertenecerán al mismo monorepo, con los límites de
[ADR-0021](../architecture/decisions/0021-portable-core-and-ml-laboratory-boundary.md);
ADR-0012 conserva el antecedente histórico del contrato.
La semántica jerárquica está gobernada por [ADR-0014](../architecture/decisions/0014-hierarchical-traffic-state-and-incident-policy.md).
El ciclo semilla/HITL está gobernado por [ADR-0017](../architecture/decisions/0017-seed-bootstrap-and-hitl-retraining.md).
El benchmark humano congelado está gobernado por [ADR-0018](../architecture/decisions/0018-versioned-frozen-human-holdouts.md).
La gestión inmutable de datasets está gobernada por [ADR-0019](../architecture/decisions/0019-immutable-seed-and-hitl-datasets.md).
La continuidad y la identidad exacta del bundle están gobernadas por
[ADR-0026](../architecture/decisions/0026-temporal-continuity-and-immutable-model-revisions.md).
La identidad corregida, la compatibilidad histórica y la publicación
recuperable están gobernadas por
[ADR-0027](../architecture/decisions/0027-complete-bundle-identity-and-hitl-integrity.md).
