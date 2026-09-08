<!-- context: VAAET/docs/product/software-requirements.md — Requisitos de software vigentes. -->

# Especificación de Requisitos de Software (SRS) — VAAET

## Estado documental

**Normativo y vigente.** Complementa el [PRD](product-requirements.md); los
contratos y ADRs vigentes prevalecen ante cualquier resumen.

| Campo | Detalle |
|---|---|
| Versión del laboratorio | 4.7.0 |
| Última revisión | 2026-08-30 |
| Responsable técnico | Facundo Nicolás González |

## Arquitectura y restricciones

VAAET es un monorepo con tres distribuciones internas: `vaaet-core==0.2.1`
(import `vaaet`), `vaaet-persistence==0.1.0` (import `vaaet_persistence`) y
`vaaet-ml==4.7.0` (import `vaaet_ml`). El core procesa
videos finitos con Pipe-and-Filter síncrono y ordenado; persistencia centraliza
PostgreSQL; el laboratorio conserva entrenamiento, evaluación, Colab y DVC. La aplicación futura no
tiene código y sólo podrá usar una API HTTP versionada.

- Python 3.10–3.13.
- Google Colab Free/Pro aporta una GPU gestionada y no garantizada; colección,
  entrenamiento e inferencia fallan temprano si no está disponible.
- Evaluación Champion--Challenger es read-only y no exige GPU.
- Los videos son MP4; la procedencia recomendada sigue el patrón
  `bridge_YYYY-MM-DD_HH-MM-SS_to_HH-MM-SS.mp4`.
- PostgreSQL 14+ es opcional y se configura fuera de los notebooks mediante
  variables locales o Colab Secrets por perfil.

## Requisitos funcionales

| ID | Requisito | Prioridad |
|---|---|---|
| RF-001 | Obtener procedencia temporal del nombre canónico y advertir trazabilidad menor para nombres libres. | P0 |
| RF-002 | Seleccionar una variante YOLO 11 permitida según la duración del clip. | P0 |
| RF-003 | Detectar `car`, `truck`, `bus`, `motorcycle` y `bicycle` bajo los umbrales centrales del core. | P0 |
| RF-004 | Mantener tracking SORT con IDs por clip y poda de tracks. | P0 |
| RF-005 | Estimar velocidad con flujo óptico, compensación de cámara, perspectiva, plausibilidad y agregación robusta. | P0 |
| RF-006 | Confirmar estacionario con la política conservadora e histéresis vigente. | P1 |
| RF-007 | Generar telemetría v3 y las 19 features de `vaaet.settings.FEATURE_COLS`. | P0 |
| RF-008 | Clasificar sólo Normal/Reduced/Congested; `Accident` requiere validación humana. | P0 |
| RF-009 | Persistir opt-in mediante `vaaet-persistence`, con operaciones idempotentes y estado visible. | P1 |
| RF-010 | Generar video anotado con HUD, tracks, tipos y velocidad cuando corresponda. | P1 |
| RF-011 | Registrar datos sintéticos y entrenamiento HITL conforme a los contratos de procedencia y holdout. | P1 |
| RF-012 | Procesar segmentos offline de vistas declaradas con calibración local, reinicio de estado y descarte de minutos mixtos. | P1 |

La simultaneidad multi-cámara, la detección automática de vista, los ROI de
parking y el procesamiento de streaming no están implementados y quedan fuera de alcance.
Los cambios de cámara o zoom sólo se admiten offline mediante un plan explícito
y calibrado conforme a ADR-0025.

## Requisitos no funcionales

### Fiabilidad y rendimiento

- La sesión de visión preserva orden de frames, telemetría por minutos completos
  y descarte del tramo final parcial.
- Ante ausencia de detecciones se registran únicamente las observaciones del
  minuto; no se fabrican promedios históricos.
- Un error de decodificación no promete recuperación frame a frame: el runtime
  termina el procesamiento de manera segura y conserva sólo resultados ya
  materializados.
- Los fallos de PostgreSQL no invalidan el video ya procesado: la persistencia
  es una etapa separada y se informa al usuario.

### Seguridad y mantenibilidad

- Los secretos se leen desde Colab Secrets o variables de entorno locales; no se
  usa `getpass` ni se imprimen valores sensibles.
- El core no depende de PostgreSQL, DVC, Drive, notebooks ni `vaaet_ml`.
- Persistencia depende sólo del core base; ML consume ambos. Los tres se instalan desde sus `pyproject.toml`,
  sin `requirements.txt` ni lockfiles.
- Los cuatro notebooks sólo orquestan módulos testeados. La evaluación no crea
  `pipeline_run` ni persiste datos.

Consultá la [arquitectura](../architecture/software-architecture.md), el
[modelo de datos](../architecture/data-model.md) y los [ADRs](../architecture/decisions/).
