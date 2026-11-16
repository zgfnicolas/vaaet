<!-- context: VAAET/docs/governance/statement-of-work.md — Plantilla hipotética, no contractual. -->

# Declaración de Trabajo (SOW) — VAAET

> **Archivado el 2026-11-15. No normativo.** Se conserva como referencia
> histórica y no describe el producto vigente; consultá el
> [PRD](../product/product-requirements.md).

## Estado documental

**Plantilla para uso futuro; no es una oferta ni un contrato.** No establece
SLA, costo, plazo, rendimiento, cliente ni aceptación vigente. Cualquier uso
externo requiere revisión humana, legal y técnica independiente.

| Campo | Detalle |
|---|---|
| Base técnica actual | Monorepo con core portable y laboratorio ML |
| Última revisión | 2026-08-27 |

## Alcance de referencia

Un futuro acuerdo podrá seleccionar, de manera expresa y verificable:

- análisis offline de videos autorizados mediante percepción, telemetría y
  clasificación conservadora;
- calibración por ubicación y evaluación con ground truth aportado legalmente;
- almacenamiento opcional operado con perfiles de mínimo privilegio;
- entrega de documentación, evidencia de pruebas y activos aprobados.

Quedan fuera de esta plantilla: instalación de cámaras, análisis de patentes,
operación 24/7, decisiones automáticas sobre incidentes, aplicación móvil,
serving web no aprobado y cualquier dato sin autorización.

## Condiciones mínimas por definir en cada acuerdo

| Tema | Decisión requerida |
|---|---|
| Entregables | Componentes, formatos, criterios de aceptación y evidencia medible |
| Datos | Propiedad, autorización, retención, acceso y redistribución |
| Infraestructura | Responsable, presupuesto, observabilidad, backup y borrado |
| Seguridad | Roles, secretos, reporte privado de vulnerabilidades y respuesta |
| Licencia | Ruta AGPL pública o licencia Enterprise para serving privado/comercial |
| Operación | Soporte, SLA, responsables, calendario y plan de reversión |

La arquitectura vigente no incluye API, frontend, AWS ni infraestructura de
aplicación. Antes de incorporarlos deben aprobarse el contrato HTTP y los gates
de [ADR-0021](../architecture/decisions/0021-portable-core-and-ml-laboratory-boundary.md)
y [ADR-0022](../architecture/decisions/0022-agpl-public-demo-path.md).
