# PRD — VAAET

**Normativo y vigente.** Define el producto de laboratorio actual: qué hace,
para quién y con qué límites. No autoriza una API, frontend ni despliegue web.
Ante una contradicción prevalecen los [ADRs](../architecture/decisions/), los
contratos y las [reglas de negocio](business-rules.md).

Responsable: Facundo Nicolás González

## 1. Visión

Que un video de tránsito se convierta en telemetría por minuto, un estado de
circulación conservador y evidencia que una persona pueda revisar, con datos y
modelos reproducibles.

## 2. Problema

Analizar un video de tránsito a mano exige mirar cada minuto, contar vehículos y
estimar velocidades sin un criterio uniforme ni registro reproducible. Un
clasificador automático, en cambio, puede publicar estados que nadie revisó y
transferirse a otra cámara sin validación. VAAET resuelve el análisis batch de
videos finitos del Puente General Manuel Belgrano y deja la confirmación de
incidentes en manos humanas.

## 3. Público objetivo

| Usuario | Necesidad | Acceso vigente |
|---|---|---|
| Operador o analista de video | Analizar un clip autorizado y revisar telemetría, estado y video anotado | Notebook de inferencia |
| Investigador de tránsito | Reproducibilidad, datasets trazables y evidencia de calidad | Los cuatro notebooks |
| Revisor | Confirmar o corregir estados, incluido `Accident` | Revisión HITL del notebook de inferencia |

Los permisos de cada uno están en [roles y permisos](roles.md). Un responsable
vial o institucional que consuma informes es una hipótesis futura sin acceso
directo; consultá el [archivo](../archive/README.md).

## 4. Propuesta de valor

- Telemetría por minuto completo, con métricas de calidad de la medición en
  lugar de valores inventados.
- Un MLP que aprende sólo estados estables y una política temporal que reduce
  oscilaciones y falsos positivos.
- Incidentes señalados para revisión, nunca publicados automáticamente.
- Bundles, datasets, holdouts e input locks reproducibles para un ciclo de
  mejora con Human-in-the-Loop (HITL).

## 5. Alcance

### Incluido

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
  sólo si el usuario la habilita.

### Fuera de alcance

Quedan fuera de alcance la API, el frontend, el serving web, multi-cámara
simultánea, detección automática de cambios de vista, ROI de parking, streaming,
lectura de patentes, predicción de tráfico futuro, alertas push y cualquier
cola o worker de aplicación. `vaaet-app/` sigue reservado.

## 6. Historias de usuario

| ID | Como... | Quiero... | Para... | Prioridad |
|---|---|---|---|---|
| HU-01 | operador o investigador | procesar un video | obtener telemetría por minuto y un video anotado | Alta |
| HU-02 | operador | clasificar cada minuto con un bundle validado | conocer el estado estable del tránsito | Alta |
| HU-03 | investigador | persistir resultados en PostgreSQL | conservar raw, features, predicciones y feedback | Media |
| HU-04 | investigador | entrenar el clasificador | obtener un bundle candidato trazable | Alta |
| HU-05 | revisor | validar o corregir predicciones | que el entrenamiento use decisiones humanas | Alta |
| HU-06 | investigador | comparar dos bundles | decidir una promoción con evidencia | Media |

### Criterios de aceptación

**HU-01 — Procesar video**

- Dado un MP4 y una GPU asignada, cuando se ejecuta adquisición o inferencia,
  entonces se obtiene telemetría v3 sólo de minutos completos y el tramo final
  parcial se descarta.
- Dado que Colab no asignó GPU, cuando se inicia un workflow de visión, entonces
  el preflight falla antes de la tarea costosa.
- Dado un nombre libre de video, cuando se procesa, entonces `record_time` usa
  la hora de procesamiento y se advierte menor trazabilidad.
- Dado un minuto sin detecciones, cuando se genera la telemetría, entonces se
  registran sólo valores observados y señales de calidad, sin promedios
  históricos.

**HU-02 — Clasificar tráfico**

- Dado un bundle cuyo manifiesto no valida, cuando se intenta cargarlo,
  entonces se rechaza antes de deserializar binarios.
- Dado un bundle válido, cuando se clasifica un minuto, entonces el estado
  automático es `Normal`, `Reduced` o `Congested` (0–2).
- Dada evidencia fuerte y persistente de incidente, cuando la política la
  detecta, entonces el estado se mantiene `Congested` y se marca
  `accident_rule_triggered` para revisión.
- Dado un bundle semilla `pilot`, cuando se usa en inferencia, entonces se
  exige autorizarlo explícitamente.

**HU-03 — Persistir resultados**

- Dado un perfil de mínimo privilegio configurado, cuando se habilita la
  persistencia, entonces las escrituras son idempotentes y se informa el
  resultado.
- Dada la falta de credenciales o un fallo de conexión, cuando termina el
  workflow, entonces informa que no hubo persistencia y conserva los outputs
  locales.
- Alembic, roles y credenciales administrativas nunca se ejecutan desde Colab.

**HU-04 — Entrenar clasificador**

- Dado un plan `SEED_BOOTSTRAP` o `HITL_RETRAINING` válido, cuando se entrena,
  entonces se obtiene un bundle v3 candidato con procedencia, checksums, gates
  y un training input lock.
- Dadas predicciones no validadas, cuando se arma el dataset, entonces nunca se
  usan como etiquetas.
- Dado un holdout humano congelado, cuando se entrena, entonces todos sus clips
  quedan excluidos de train.

**HU-05 — Revisar HITL**

- Dada una predicción, cuando el revisor la valida, entonces se agrega una
  validación append-only y la predicción histórica no cambia.
- Dado que el revisor elige `Accident`, cuando confirma, entonces debe incluir
  una nota y confirmar que revisó el contexto temporal.
- Dada una validación con auditoría pendiente, cuando se finaliza la revisión,
  entonces no se exporta ni se usa como target hasta recuperarla.

**HU-06 — Evaluar candidatos**

- Dados dos bundles y un holdout compatible, cuando se ejecuta la evaluación,
  entonces se validan ambos manifiestos y se publican métricas emparejadas.
- Ejecutar la evaluación no crea `pipeline_run`, no escribe en DVC ni
  PostgreSQL y no promociona modelos.

## 7. Requisitos funcionales

| ID | Requisito | HU | Prioridad |
|---|---|---|---|
| RF-001 | Obtener la procedencia temporal del nombre canónico `bridge_YYYY-MM-DD_HH-MM-SS_to_HH-MM-SS.mp4` y advertir menor trazabilidad para nombres libres. | HU-01 | P0 |
| RF-002 | Seleccionar una variante YOLO 11 permitida según la duración del clip. | HU-01 | P0 |
| RF-003 | Detectar `car`, `truck`, `bus`, `motorcycle` y `bicycle` bajo los umbrales centrales del core. | HU-01 | P0 |
| RF-004 | Mantener tracking SORT con IDs por clip y poda de tracks. | HU-01 | P0 |
| RF-005 | Estimar velocidad con flujo óptico, compensación de cámara, perspectiva, plausibilidad y agregación robusta. | HU-01 | P0 |
| RF-006 | Confirmar estacionario con la política conservadora e histéresis vigente. | HU-01 | P1 |
| RF-007 | Generar telemetría v3 y las 19 features de `vaaet.settings.FEATURE_COLS`. | HU-01, HU-04 | P0 |
| RF-008 | Clasificar sólo `Normal`, `Reduced` y `Congested`; `Accident` requiere validación humana. | HU-02, HU-05 | P0 |
| RF-009 | Persistir opt-in mediante `vaaet-persistence`, con operaciones idempotentes y estado visible. | HU-03 | P1 |
| RF-010 | Generar video anotado con HUD, tracks, tipos y velocidad cuando corresponda. | HU-01 | P1 |
| RF-011 | Registrar datos sintéticos y entrenamiento HITL conforme a los contratos de procedencia y holdout. | HU-04, HU-05 | P1 |
| RF-012 | Procesar segmentos offline de vistas declaradas con calibración local, reinicio de estado y descarte de minutos mixtos. | HU-01 | P1 |

## 8. Requisitos no funcionales

| ID | Categoría | Requisito |
|---|---|---|
| RNF-01 | Fiabilidad | La sesión de visión preserva el orden de frames y procesa con Pipe-and-Filter síncrono. |
| RNF-02 | Fiabilidad | Un error de decodificación termina el clip de forma segura y conserva sólo resultados ya materializados. |
| RNF-03 | Fiabilidad | Un fallo de PostgreSQL no invalida el video ya procesado; la persistencia es una etapa separada. |
| RNF-04 | Seguridad | Los secretos se leen desde Colab Secrets o variables de entorno; no se usa `getpass` ni se imprimen valores sensibles. |
| RNF-05 | Seguridad | PostgreSQL usa TLS `verify-full` por defecto y un perfil de mínimo privilegio por workflow. |
| RNF-06 | Mantenibilidad | El core no depende de PostgreSQL, DVC, Drive, notebooks ni `vaaet_ml`; persistencia depende sólo del core base. |
| RNF-07 | Mantenibilidad | Los notebooks sólo orquestan módulos probados y no modifican `sys.path`. |
| RNF-08 | Portabilidad | Python 3.10–3.13; se instala `vaaet-core`, luego `vaaet-persistence` y por último `vaaet-ml`, desde sus `pyproject.toml`. |
| RNF-09 | Entorno | Adquisición, entrenamiento e inferencia requieren GPU gestionada por Colab; evaluación es read-only y no la exige. |

## 9. Métricas de éxito

Los objetivos se miden sólo con ground truth y holdout humano compatibles;
todavía no son resultados demostrados.

| Métrica | Objetivo |
|---|---|
| F1-macro del clasificador | ≥ 0,88 sobre holdout humano apto |
| F1 de detección | 0,97, pendiente de benchmark |
| MAE de velocidad | < 5 km/h, pendiente de ground truth |
| Estados `Accident` automáticos | 0 |

Los gates por clase están en la [model card](../ml/model-card.md), la medición en
[KPIs](../quality/kpis.md) y las limitaciones en
[sesgos y limitaciones](../ml/bias-and-limitations.md).

## 10. Supuestos, riesgos y preguntas abiertas

- Los datos provienen de un único puente, período y configuración de cámara; el
  modelo no se transfiere a otra vía sin validación local.
- Colab no garantiza GPU, tipo de acelerador, cuotas ni duración de sesión; las
  validaciones reales siguen siendo manuales.
- Videos y datos HITL requieren autorización y no se distribuyen por el carácter
  público del repositorio.
- Una demo web con YOLO sólo puede seguir la vía pública AGPL con activos
  aprobados o la vía Enterprise privada de
  [ADR-0022](../architecture/decisions/0022-agpl-public-demo-path.md).
- Pregunta abierta: qué alcance, contrato HTTP y activos redistribuibles
  habilitarán `vaaet-app/`.
