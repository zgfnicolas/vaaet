# Documentación de VAAET

VAAET es un monorepo con `vaaet-core` (`vaaet`, 0.2.1),
`vaaet-persistence` (`vaaet_persistence`, 0.2.0), `vaaet-ml` (`vaaet_ml`,
4.8.0) y `vaaet-app` reservado. La topología está definida por
[ADR-0021](architecture/decisions/0021-portable-core-and-ml-laboratory-boundary.md)
y [ADR-0028](architecture/decisions/0028-shared-postgresql-persistence-layer.md),
con integridad operacional actualizada por
[ADR-0029](architecture/decisions/0029-postgresql-numeric-fidelity-and-hitl-consistency.md).

## Estado y precedencia documental

- **Normativo y vigente**: contratos, arquitectura, operaciones, requisitos,
  calidad y seguridad describen el estado implementado.
- **Hipótesis futura**: Canvas, SOW y personas conservan ideas de producto sin
  prometer API, Web App, costos, plazos ni servicios disponibles.
- **Histórico**: changelog y planes fechados registran su momento; los ADRs
  conservan sus decisiones originales. ADR-0021 a ADR-0029
  prevalecen para la topología, serving con YOLO, registro DVC, operación
  PostgreSQL y segmentos de video calibrados actuales.

## Inicio para agentes de código

Antes de editar, leer las [instrucciones de raíz](../AGENTS.md), el
[resumen portable](../llms.txt), las reglas específicas de
[`vaaet-core`](../vaaet-core/AGENTS.md) o
[`vaaet-ml`](../vaaet-ml/AGENTS.md), y el ADR aplicable. Para una futura demo
web con YOLO, leer además [ADR-0022](architecture/decisions/0022-agpl-public-demo-path.md)
y el [checklist AGPL](governance/agpl-demo-release-checklist.md).

## Puntos de entrada

- [Arquitectura de software](architecture/software-architecture.md)
- [ADR-0020: monorepo ML y frontera de aplicación](architecture/decisions/0020-single-git-monorepo-and-application-boundary.md)
- [ADR-0021: core portable y laboratorio ML](architecture/decisions/0021-portable-core-and-ml-laboratory-boundary.md)
- [ADR-0022: vía AGPL-3.0 para demo web pública](architecture/decisions/0022-agpl-public-demo-path.md)
- [ADR-0023: registro DVC portable por configuración local](architecture/decisions/0023-provider-neutral-dvc-registry.md)
- [ADR-0024: PostgreSQL portable y migraciones como código](architecture/decisions/0024-provider-neutral-postgresql-and-schema-as-code.md)
- [ADR-0025: segmentos multi-vista con calibración explícita](architecture/decisions/0025-calibrated-multi-view-video-segments.md)
- [ADR-0026: continuidad temporal y revisiones inmutables](architecture/decisions/0026-temporal-continuity-and-immutable-model-revisions.md)
- [ADR-0027: identidad completa, publicación recuperable e HITL uniforme](architecture/decisions/0027-complete-bundle-identity-and-hitl-integrity.md)
- [ADR-0028: persistencia PostgreSQL compartida](architecture/decisions/0028-shared-postgresql-persistence-layer.md)
- [ADR-0029: fidelidad numérica e integridad HITL](architecture/decisions/0029-postgresql-numeric-fidelity-and-hitl-consistency.md)
- [Contrato del bundle](ml/model-artifact-contract.md)
- [Guía del registro DVC](ml/dvc-guide.md)
- [ADR de inicio semilla y HITL](architecture/decisions/0017-seed-bootstrap-and-hitl-retraining.md)
- [ADR de holdout humano congelado](architecture/decisions/0018-versioned-frozen-human-holdouts.md)
- [ADR de datasets semilla/HITL inmutables](architecture/decisions/0019-immutable-seed-and-hitl-datasets.md)
- [Model card y gates de promoción](ml/model-card.md)
- [Observabilidad de entrenamiento y ciclo HITL](ml/training-observability.md)
- [Protocolo de anotación humana](ml/human-annotation-protocol.md)
- [Guía de usuario](operations/user-guide.md)
- [Guía de Google Colab](operations/colab-guide.md)
- [Guía de calibración multi-vista](operations/multi-view-calibration-guide.md)
- [Notebook de evaluación Champion--Challenger](../vaaet-ml/notebooks/evaluation/evaluate_models_and_eda.ipynb)
- [Operación PostgreSQL](operations/postgresql-guide.md)
- [Requisitos de producto](product/product-requirements.md)
- [Plan de pruebas](quality/test-plan.md)
- [Planes de ejecución gobernados](governance/plans/)
- [Plan de demo pública AGPL](governance/plans/2026-08-27-agpl-public-demo.md)
- [Registro de licencias de terceros](governance/third-party-licenses.md)
- [Checklist de demo pública AGPL](governance/agpl-demo-release-checklist.md)
- [Runbook de demo temporal AWS](operations/aws-temporary-demo-runbook.md)
- [Modelo PostgreSQL](architecture/data-model.md)
- [ADR-0015: PostgreSQL seguro e HITL](architecture/decisions/0015-postgresql-namespaces-security-and-hitl.md)
- [ADR-0016: hardening PostgreSQL y ejecuciones](architecture/decisions/0016-postgresql-hardening-and-pipeline-runs.md)

## Mapa documental

- `architecture/`: diseño, datos, linaje, diagramas y decisiones.
- `ml/`: model card, contrato, DVC, sesgos y limitaciones.
- `product/`: requisitos, usuarios, casos de uso y factibilidad.
- `operations/`: despliegue y operación.
- `quality/`: pruebas, KPIs y riesgos.
- `governance/`: planificación, seguridad y registros legales.

Los cuatro notebooks son adquisición, entrenamiento, inferencia y evaluación.
Los tres primeros son workflows operacionales; evaluación es un auditor
read-only posterior al entrenamiento y no crea un `pipeline_run` ni persiste
datos. Los ADRs y contratos prevalecen sobre resúmenes, README y guías
operacionales.
