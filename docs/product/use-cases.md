<!-- context: VAAET/docs/product/use-cases.md — Casos de uso vigentes de laboratorio. -->

# Casos de Uso del Negocio — VAAET

## Estado documental

**Normativo y vigente para el laboratorio.** La futura Web App no es un actor
implementado; su frontera está definida por ADR-0021.

| Campo | Detalle |
|---|---|
| Versión del laboratorio | 4.7.0 |
| Última revisión | 2026-08-27 |

## CU-001 — Procesar video

| Campo | Detalle |
|---|---|
| Actor | Operador o investigador |
| Precondición | Video MP4 y GPU disponible para el workflow de visión |
| Resultado | Telemetría v3 de minutos completos y video anotado opcional |

El notebook de adquisición o inferencia procesa en orden detección, tracking,
velocidad, telemetría y render. Con nombre libre conserva la hora de ejecución
como procedencia con advertencia. Sin detecciones, el minuto conserva sólo
valores observados y señales de calidad; no usa promedios históricos. Si la
captura no puede continuar, el clip finaliza de forma segura y no se inventan
filas posteriores.

## CU-002 — Clasificar estado de tráfico

| Campo | Detalle |
|---|---|
| Actor | Operador o investigador |
| Precondición | Telemetría v3 y bundle v3 validado manifest-first |
| Resultado | Estado estable por minuto completo, confianza y evidencia |

La cadena construye las 19 features, escala con el bundle y predice tres
estados. La política temporal puede abrir un candidato de incidente, pero el
estado automático permanece `Congested`; `Accident` requiere revisión humana.

## CU-003 — Persistir resultados de laboratorio

| Campo | Detalle |
|---|---|
| Actor | Investigador que habilita el adaptador PostgreSQL |
| Precondición | Perfil de mínimo privilegio en Colab Secrets o variables locales |
| Resultado | Escrituras idempotentes de raw, features, predicciones o feedback autorizados |

Sin credenciales o ante una conexión fallida, el notebook informa que no hubo
persistencia y mantiene los outputs locales disponibles. Alembic, roles y
credenciales administrativas nunca se ejecutan desde Colab.

## CU-004 — Entrenar clasificador

| Campo | Detalle |
|---|---|
| Actor | Investigador |
| Precondición | Plan `SEED_BOOTSTRAP` o `HITL_RETRAINING` válido y GPU disponible |
| Resultado | Bundle v3 candidato con procedencia, checksums y gates |

El entrenamiento audita telemetría v3 y fuentes legacy declaradas, usa las 19 features, conserva la
proveniencia de datos reales/sintéticos y separa los tres estados aprendidos de
la política humana de `Accident`.

## CU-005 — Revisar HITL

| Campo | Detalle |
|---|---|
| Actor | Revisor autorizado |
| Precondición | Predicción persistida y perfil `reviewer` configurado |
| Resultado | Validación append-only en `vaaet_feedback.human_validations` |

La revisión no modifica predicciones históricas. El entrenamiento consume sólo
la última validación humana efectiva y los conflictos detienen la promoción.

## CU-006 — Evaluar candidatos

| Campo | Detalle |
|---|---|
| Actor | Investigador |
| Precondición | Dos bundles y holdout humano compatible |
| Resultado | Comparación Champion--Challenger y EDA de drift read-only |

El cuarto notebook valida ambos manifiestos y no crea `pipeline_run`, no cambia
DVC ni PostgreSQL y no promociona modelos.

Para operaciones, configuración y recuperación consultá la [guía de usuario](../operations/user-guide.md).
