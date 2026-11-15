# Registro de decisiones de arquitectura (ADR)

Cada ADR registra una decisión, su contexto, las opciones y sus consecuencias.
Este índice es el único lugar donde se listan; otros documentos enlazan el ADR
puntual que aplica.

## Reglas

- Un ADR aceptado no se edita. Si la decisión cambia, se escribe uno nuevo y el
  anterior pasa a *Reemplazada por ADR-NNNN*.
- Estados: Propuesta, Aceptada, Rechazada, Obsoleta, Reemplazada.
- Un ADR por decisión, numerado con cuatro dígitos que nunca se renumeran.
- Para escribir uno, copiá la [plantilla](0000-template.md) y agregalo a este
  índice en el mismo cambio.

## Índice

| ADR | Decisión | Tema | Estado |
|---|---|---|---|
| [0001](0001-monolithic-notebook.md) | Notebook monolítico sobre módulos Python | Arquitectura | Reemplazada por 0009 |
| [0002](0002-adaptive-yolo11-model-selection.md) | YOLO 11 con selección adaptativa por duración | Visión | Reemplazada por 0009 |
| [0003](0003-sort-over-deepsort.md) | SORT sobre DeepSORT y ByteTrack | Visión | Reemplazada por 0009 |
| [0004](0004-mlp-speed-smoother.md) | MLP como suavizador de velocidad | Visión | Reemplazada por 0009 |
| [0005](0005-postgresql-aws-rds.md) | PostgreSQL en AWS RDS sobre SQLite | Persistencia | Reemplazada por 0015 |
| [0006](0006-conservative-stationary-detection.md) | Detección de estacionarios ultra-conservadora | Visión | Reemplazada por 0009 |
| [0007](0007-google-colab-runtime.md) | Google Colab como entorno principal | Runtime | Reemplazada por 0009 |
| [0008](0008-keras-traffic-state-classifier.md) | TensorFlow/Keras para el clasificador de estado | Modelo | Aceptada |
| [0009](0009-modular-three-stage-architecture.md) | Arquitectura modular de tres etapas | Arquitectura | Aceptada |
| [0010](0010-mlops-pipeline-19-features.md) | Pipeline MLOps con 19 features y señales de calidad | Features | Aceptada |
| [0011](0011-dvc-model-registry.md) | DVC como registro de modelos | MLOps | Aceptada; remoto reemplazado por 0023 |
| [0012](0012-ml-web-boundary-and-artifact-contract.md) | Límite ML/Web y contrato portable de artefactos | Frontera | Aceptada |
| [0013](0013-on-demand-data-collection-workflow.md) | Workflow de adquisición bajo demanda | Workflows | Aceptada |
| [0014](0014-hierarchical-traffic-state-and-incident-policy.md) | Clasificación jerárquica del flujo e incidentes | Estados | Aceptada |
| [0015](0015-postgresql-namespaces-security-and-hitl.md) | PostgreSQL modular, mínimo privilegio e ingestión HITL | Persistencia | Aceptada |
| [0016](0016-postgresql-hardening-and-pipeline-runs.md) | Hardening PostgreSQL y registro de ejecuciones | Persistencia | Aceptada |
| [0017](0017-seed-bootstrap-and-hitl-retraining.md) | Inicio semilla y reentrenamiento HITL | Entrenamiento | Aceptada |
| [0018](0018-versioned-frozen-human-holdouts.md) | Holdout humano congelado y versionado | Evaluación | Aceptada |
| [0019](0019-immutable-seed-and-hitl-datasets.md) | Datasets semilla y HITL inmutables | Datasets | Aceptada |
| [0020](0020-single-git-monorepo-and-application-boundary.md) | Monorepo Git único y límite de aplicación | Frontera | Aceptada; actualizada por 0021 |
| [0021](0021-portable-core-and-ml-laboratory-boundary.md) | Core portable y laboratorio ML separados | Frontera | Aceptada |
| [0022](0022-agpl-public-demo-path.md) | Vía AGPL-3.0 para una demo web pública | Licencias | Aceptada |
| [0023](0023-provider-neutral-dvc-registry.md) | Registro DVC portable por configuración local | MLOps | Aceptada |
| [0024](0024-provider-neutral-postgresql-and-schema-as-code.md) | PostgreSQL portable y migraciones como código | Persistencia | Aceptada |
| [0025](0025-calibrated-multi-view-video-segments.md) | Segmentos multi-vista con calibración explícita | Visión | Aceptada |
| [0026](0026-temporal-continuity-and-immutable-model-revisions.md) | Continuidad temporal y revisiones inmutables del modelo | Modelo | Aceptada |
| [0027](0027-complete-bundle-identity-and-hitl-integrity.md) | Identidad completa del bundle e integridad HITL | Modelo | Aceptada |
| [0028](0028-shared-postgresql-persistence-layer.md) | Persistencia PostgreSQL compartida | Persistencia | Aceptada |
| [0029](0029-postgresql-numeric-fidelity-and-hitl-consistency.md) | Fidelidad numérica e integridad HITL en PostgreSQL | Persistencia | Aceptada |
| [0030](0030-operational-idempotency-and-portable-hitl-coherence.md) | Idempotencia operacional y coherencia HITL portable | HITL | Aceptada |
| [0031](0031-hitl-integrity-and-coordinated-catalog-publication.md) | Integridad HITL y publicación coordinada del catálogo | HITL | Aceptada |
| [0032](0032-complete-cycle-integrity.md) | Integridad determinista del ciclo completo | HITL | Aceptada |
| [0033](0033-verifiable-persistence-recovery-and-hitl-audit.md) | Recuperación verificable y auditoría HITL completa | HITL | Aceptada |
| [0034](0034-uniform-review-audit-evidence.md) | Evidencia uniforme de auditoría HITL | HITL | Aceptada |
| [0035](0035-review-recovery-and-lossless-packages.md) | Recuperación vinculada a la sesión y paquetes sin pérdida | HITL | Aceptada |
| [0036](0036-coherent-hitl-sessions-and-typed-integers.md) | Sesiones HITL coherentes y enteros tipados | HITL | Aceptada |

## Vigentes por tema

| Tema | ADRs que gobiernan el estado actual |
|---|---|
| Frontera entre componentes | [0021](0021-portable-core-and-ml-laboratory-boundary.md), [0028](0028-shared-postgresql-persistence-layer.md) |
| Estados y modelo | [0014](0014-hierarchical-traffic-state-and-incident-policy.md), [0026](0026-temporal-continuity-and-immutable-model-revisions.md), [0027](0027-complete-bundle-identity-and-hitl-integrity.md) |
| Visión multi-vista | [0025](0025-calibrated-multi-view-video-segments.md) |
| Datasets, entrenamiento y holdouts | [0017](0017-seed-bootstrap-and-hitl-retraining.md), [0018](0018-versioned-frozen-human-holdouts.md), [0019](0019-immutable-seed-and-hitl-datasets.md) |
| PostgreSQL | [0024](0024-provider-neutral-postgresql-and-schema-as-code.md), [0028](0028-shared-postgresql-persistence-layer.md), [0029](0029-postgresql-numeric-fidelity-and-hitl-consistency.md), [0033](0033-verifiable-persistence-recovery-and-hitl-audit.md) |
| Integridad HITL | [0030](0030-operational-idempotency-and-portable-hitl-coherence.md) a [0036](0036-coherent-hitl-sessions-and-typed-integers.md) |
| Registro DVC | [0023](0023-provider-neutral-dvc-registry.md) |
| Serving con YOLO | [0022](0022-agpl-public-demo-path.md) |
