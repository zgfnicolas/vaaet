<!-- context: VAAET/docs/product/business-model-canvas.md — Hipótesis de producto futura, no normativa. -->

# Business Model Canvas — VAAET

> **Archivado el 2026-11-15. No normativo.** Se conserva como referencia
> histórica y no describe el producto vigente; consultá el
> [PRD](../product/product-requirements.md).

## Estado documental

**Hipótesis de producto futura.** No describe servicios disponibles, precios,
plazos, acuerdos comerciales ni una Web App implementada. El estado técnico
vigente está en [ADR-0021](../architecture/decisions/0021-portable-core-and-ml-laboratory-boundary.md)
y la vía de serving con YOLO en [ADR-0022](../architecture/decisions/0022-agpl-public-demo-path.md).

| Campo | Detalle |
|---|---|
| Base actual | Laboratorio público AGPL-3.0-only |
| Última revisión | 2026-08-27 |

## Hipótesis a validar

| Área | Hipótesis |
|---|---|
| Usuarios | Investigadores, operadores viales y organizaciones con necesidad de análisis vehicular pueden beneficiarse de telemetría reproducible. |
| Propuesta de valor | La percepción, velocidad y estado por minuto pueden reducir tareas manuales cuando tengan calibración y evidencia local. |
| Canales | El repositorio público, notebooks y presentaciones académicas son los canales actuales; una API y Web App son opciones futuras. |
| Recursos | Core portable, laboratorio ML, documentación, datos con autorización y validación humana. |
| Actividades | Calibración, evaluación con ground truth, HITL, trazabilidad de bundles y revisión de licencia/datos. |
| Socios potenciales | Instituciones académicas, fuentes autorizadas de datos y futuros responsables de infraestructura. |

## Condiciones antes de una oferta o demo web

1. Aprobar un contrato HTTP versionado y el alcance de `vaaet-app/`.
2. Elegir la vía de serving: demo pública AGPL con checklist de activos completo,
   o Enterprise para aplicación privada/comercial.
3. Validar procedencia, redistribución y retención de videos, pesos y bundles.
4. Obtener métricas reproducibles de detección, velocidad, throughput y costos
   sobre el entorno realmente elegido.

Las estimaciones de precio, calendario comercial y cobertura operativa se
definirán sólo con evidencia y una revisión separada.
