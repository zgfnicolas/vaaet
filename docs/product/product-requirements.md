<!-- context: VAAET/docs/product/product-requirements.md — Requisitos de producto vigentes. -->

# Documento de Requisitos del Producto (PRD) — VAAET

## Estado documental

**Normativo y vigente.** Define el producto de laboratorio actual; no autoriza
una API, frontend ni despliegue web. Para decisiones de arquitectura prevalecen
[ADR-0021](../architecture/decisions/0021-portable-core-and-ml-laboratory-boundary.md)
y [ADR-0022](../architecture/decisions/0022-agpl-public-demo-path.md), la
persistencia compartida sigue
[ADR-0028](../architecture/decisions/0028-shared-postgresql-persistence-layer.md), y para
cinemática multi-vista
[ADR-0025](../architecture/decisions/0025-calibrated-multi-view-video-segments.md).

| Campo | Detalle |
|---|---|
| Versión del laboratorio | 4.8.0 |
| Última revisión | 2026-08-30 |
| Responsable técnico | Facundo Nicolás González |

## Producto actual

VAAET analiza videos del Puente General Manuel Belgrano para producir
telemetría por minuto, video anotado y una clasificación conservadora del
tráfico. `vaaet-core` aporta percepción, telemetría, 19 features, política de
estados y bundle portable; `vaaet-persistence` aporta PostgreSQL compartido; y
`vaaet-ml` aporta notebooks, datasets, entrenamiento y evaluación.

El MLP predice `Normal`, `Reduced` y `Congested`. `Accident` es un estado
público exclusivamente humano; un candidato de incidente conserva `Congested`
hasta una revisión explícita.

## Alcance vigente

- Detección YOLO, tracking SORT, velocidad physics-first y estado estacionario
  conservador sobre videos finitos y ordenados.
- Plan opcional de segmentos multi-vista offline, con calibración local por
  referencias medidas, reinicio temporal y descarte de minutos mixtos.
- Telemetría v3 por minutos completos, video anotado y métricas de pipeline.
- Ingeniería de 19 features, MLP de tres salidas, política temporal y bundle v3
  validado antes de deserializar.
- Cuatro notebooks: adquisición, entrenamiento, inferencia y evaluación
  Champion--Challenger read-only.
- PostgreSQL e HITL opcionales, con perfiles de mínimo privilegio y persistencia
  visible sólo si el usuario la habilita.

Quedan fuera de alcance la API, el frontend, serving web, multi-cámara
simultánea, detección automática de cambios de vista, lectura de patentes,
predicción de tráfico futuro, alertas push y cualquier cola o worker de
aplicación. `vaaet-app/` sigue reservado.

## Historias de usuario vigentes

### US-001 — Procesar video

Como operador o investigador, quiero ejecutar adquisición o inferencia sobre un
video para obtener telemetría observada por minuto y un video anotado opcional.
La ejecución de visión requiere GPU: el preflight falla antes de una tarea
costosa si Colab no la asignó.

### US-002 — Clasificar tráfico

Como operador, quiero conocer el estado estable de cada minuto completo con un
bundle validado. El resultado automático es 0–2; `Accident` nunca se publica sin
validación humana.

### US-003 — Entrenar y evaluar

Como investigador, quiero entrenar con un plan tipado de semilla o HITL y
evaluar candidatos contra un holdout humano inmutable. Un bundle sólo es
elegible cuando satisface sus gates de procedencia, soporte, calibración y
calidad; los objetivos aún no son evidencia operacional publicada.

### US-004 — Persistir resultados de laboratorio

Como investigador, puedo habilitar PostgreSQL con un perfil limitado para
guardar datos raw, features, predicciones o feedback idempotentemente. Sin
credenciales o ante un fallo, el workflow informa que no hubo persistencia y
conserva los outputs locales disponibles.

## Objetivos y límites de calidad

Los objetivos de detección, velocidad y clasificación se miden sólo cuando haya
ground truth y holdout humano compatibles; no son resultados ya demostrados.

| Métrica | Objetivo / invariante |
|---|---|
| F1-macro del clasificador | ≥ 0.88 sobre holdout humano apto |
| F1 de detección | 0.97, objetivo pendiente de benchmark |
| MAE de velocidad | < 5 km/h, objetivo pendiente de ground truth |
| Estados `Accident` automáticos | 0 |

La guía de medición está en [KPIs](../quality/kpis.md) y las limitaciones en
[sesgos y limitaciones](../ml/bias-and-limitations.md).

## Restricciones técnicas

- Python 3.10–3.13; instalar primero `vaaet-core` (import `vaaet`) y después
  `vaaet-ml` (import `vaaet_ml`).
- Colección, entrenamiento e inferencia requieren GPU gestionada por Colab;
  evaluación es read-only y no la exige.
- Los notebooks son orquestadores. No modifican `sys.path`, no instalan DVC por
  separado ni manejan secretos en celdas.
- La demo web futura sólo podrá habilitarse por la vía pública AGPL con activos
  aprobados o por la vía Enterprise privada/comercial de ADR-0022.

La arquitectura, los contratos y los próximos pasos canónicos están en la
[documentación de VAAET](../index.md).
