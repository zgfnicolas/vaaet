# VAAET App

Este directorio reserva la futura aplicación VAAET. No contiene API, frontend,
framework, dependencias ni acceso directo a datos en esta etapa.

La futura API instalará `../vaaet-core` y `../vaaet-persistence`, validará el
bundle vigente mediante `vaaet.artifacts.validate_manifest()` antes de
deserializarlo y expondrá un contrato HTTP versionado. El backend usará una
identidad PostgreSQL propia; la Web App consumirá exclusivamente la API y no
accederá a PostgreSQL, DVC, Drive, artefactos binarios ni módulos Python.

Una API que ejecute `vaaet-core[vision]` sólo podrá desplegarse tras elegir una
vía de licencia: demo pública AGPL-3.0 con código reproducible y activos
aprobados, o aplicación privada/comercial con una licencia Ultralytics
Enterprise aplicable fuera de Git. Consultá el
[registro de licencias de terceros](../docs/governance/third-party-licenses.md).

La vía pública AGPL requiere el
[checklist de activos](../docs/governance/agpl-demo-release-checklist.md) y el
[runbook de demo AWS](../docs/operations/aws-temporary-demo-runbook.md) antes
de cualquier despliegue futuro.

La arquitectura está gobernada por
[ADR-0021](../docs/architecture/decisions/0021-portable-core-and-ml-laboratory-boundary.md).
La persistencia compartida está gobernada por
[ADR-0028](../docs/architecture/decisions/0028-shared-postgresql-persistence-layer.md).
