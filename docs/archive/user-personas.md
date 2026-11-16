<!-- context: VAAET/docs/product/user-personas.md — Personas de referencia; no requisitos ni usuarios activos. -->

# Perfiles de usuario — VAAET

> **Archivado el 2026-11-15. No normativo.** Se conserva como referencia
> histórica y no describe el producto vigente; consultá el
> [PRD](../product/product-requirements.md) y los
> [roles y permisos](../product/roles.md).

## Estado documental

**Hipótesis de producto futura.** Los perfiles orientan investigación y diseño;
no describen una interfaz web existente, acuerdos con SISE ni métricas ya
validadas. El único acceso implementado hoy son los notebooks de laboratorio.

| Campo | Detalle |
|---|---|
| Última revisión | 2026-08-27 |
| Alcance actual | Adquisición, entrenamiento, inferencia y evaluación en notebooks |

## Operador o analista de video

Necesita analizar un clip autorizado y revisar telemetría, estado y video
anotado. En el laboratorio usa inferencia en Colab; una futura interfaz deberá
validarse separadamente y nunca podrá confirmar `Accident` automáticamente.

## Investigador de tránsito

Necesita reproducibilidad, exportaciones acotadas y evidencia de calidad. Usa
los workflows de adquisición, entrenamiento, inferencia y evaluación, con
datasets, holdouts y bundles trazables.

## Responsable vial o institucional

Es una persona hipotética que podría consumir informes preparados por un
operador o investigador. Sus necesidades de acceso, reportes, retención y
calibración deberán acordarse antes de crear una API o Web App.

## Agente de código

Lee `AGENTS.md`, `llms.txt`, el índice documental y los ADRs antes de proponer
cambios. Debe preservar los límites core--ML--app, los contratos de datos y la
política humana de `Accident`.

## Matriz orientativa

| Perfil | Acceso vigente | Futuro sujeto a aprobación |
|---|---|---|
| Operador o analista | Notebook de inferencia | API y Web App mediante HTTP |
| Investigador | Cuatro notebooks de laboratorio | Informes o integración adicional |
| Responsable institucional | Ninguno directo | Visualización y reportes acordados |
| Agente de código | Contexto y pruebas del repositorio | Cambios dentro de un alcance aprobado |
