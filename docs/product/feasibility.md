<!-- context: VAAET/docs/product/feasibility.md — Evaluación vigente condicionada. -->

# Estudio de factibilidad de software — VAAET

## Estado documental

**Normativo como evaluación condicionada del laboratorio.** No aprueba una
operación comercial ni un despliegue web; esos alcances aún no existen.

| Campo | Detalle |
|---|---|
| Versión del laboratorio | 4.8.0 |
| Última revisión | 2026-08-27 |

## Factibilidad técnica

El laboratorio es viable para análisis batch de videos finitos: el core separa
percepción, telemetría, features, bundle e inferencia; persistencia separa
PostgreSQL; y ML conserva Colab, DVC y Drive. La calidad operacional sigue condicionada a
calibración local y ground truth: detección, velocidad y throughput no cuentan
con benchmarks públicos suficientes.

Colab aporta un entorno gestionado y efímero. GPU, tipo de acelerador, cuotas y
duración de sesión no están garantizados, por lo que los workflows de visión
fallan temprano sin GPU y las validaciones reales siguen siendo manuales.

## Factibilidad operativa y de datos

- Los videos y datos HITL requieren autorización y no se distribuyen por el
  carácter público del repositorio.
- PostgreSQL, Drive y DVC remoto son opcionales. PostgreSQL vive en la capa
  compartida, no en core, y ninguna de estas capacidades habilita serving.
- Los snapshots, holdouts e input locks hacen reproducible el laboratorio, pero
  no sustituyen autorización, backup ni revisión humana.

## Factibilidad legal y futura demo

VAAET se distribuye bajo AGPL-3.0-only. Una demo académica pública que ejecute
YOLO es viable sólo si completa el checklist de activos, publica el código
correspondiente y respeta retención y seguridad de datos. Una aplicación privada
o comercial que ejecute visión requiere licencia Ultralytics Enterprise fuera de
Git.

No se presupuestan costos de nube: AWS y cualquier proveedor pueden generar
cargos. Antes de una demo, el responsable debe revisar límites de facturación,
limpieza de recursos y el [runbook temporal](../operations/aws-temporary-demo-runbook.md).

## Veredicto

**Factible con gates.** El laboratorio puede evolucionar de forma controlada;
una API, Web App o despliegue temporal necesita alcance aprobado, contrato HTTP,
activos redistribuibles y evidencia específica del entorno.
