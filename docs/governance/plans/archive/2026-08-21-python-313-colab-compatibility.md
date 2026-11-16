# Plan de ejecución: compatibilidad de Google Colab con Python 3.13

- Fecha de inicio: 2026-08-21
- Fecha de cierre: 2026-08-22
- Estado global: Completado
- Ticket, issue o PR vinculado: [#1](https://github.com/zgfnicolas/vaaet/pull/1)

## 1. Contexto y restricciones

La sesión administrada de Colab observada usa Python 3.13, mientras VAAET ML
4.5.2 declara `requires-python = ">=3.10,<3.13"`. `pip` rechaza el paquete antes
de instalar sus extras y el notebook sólo expone un `CalledProcessError`.

Fuentes revisadas:

- [ADR-0013](../../../architecture/decisions/0013-on-demand-data-collection-workflow.md)
  a [ADR-0019](../../../architecture/decisions/0019-immutable-seed-and-hitl-datasets.md).
- `vaaet-ml/pyproject.toml`, los tres notebooks activos y `.github/workflows/ci.yml`.
- [Guía de Colab](../../../operations/colab-guide.md) y contexto raíz del repositorio.

Invariantes: no cambiar las 19 features, MLP, estados públicos, umbrales,
PostgreSQL, bundle v2 ni remotes DVC. Mantener instalación normal en Colab,
editable localmente y una única celda de setup por notebook.

## 2. Versionado y trazabilidad

- Release: VAAET ML 4.5.3.
- Commit propuesto: `fix(notebooks): support Python 3.13 in Colab`.
- No requiere ADR: amplía compatibilidad del runtime sin alterar contratos.

## 3. Fase de ejecución HITL

### [Completada] Fase única: compatibilidad y diagnóstico de instalación

- [x] Ampliar metadata, dependencias condicionales y CI a Python 3.13.
- [x] Hacer fail-fast y observable la instalación en los tres notebooks.
- [x] Sincronizar documentación y contexto activo.
- [x] Ejecutar los gates exigidos por `AGENTS.md`.
- Review humano (ACK): plan aprobado por Facundo Nicolás González el 2026-08-21.

## 4. Criterios de aceptación

- [x] Python 3.10–3.13 está declarado y cubierto por la matriz de CI.
- [x] TensorFlow 2.20 es el mínimo efectivo en Python 3.13.
- [x] Una instalación fallida muestra el diagnóstico de `pip` y una recuperación.
- [x] Los notebooks conservan una sola instalación y compilan.
- [x] Ruff, pytest, compileall, enlaces y `git diff --check` pasan.

## 5. Recuperación

Si Python 3.13 no resuelve todos los extras, se revierte el patch y se utiliza
temporalmente el runtime Colab 2026.07 con Python 3.12.13. No se instala ni se
reemplaza Python dentro del notebook.

## 6. Evidencia y cierre

- Ruff: sin errores en `src`, `tests` y `scripts`.
- Pytest local: 426 pruebas aprobadas y 9 pruebas de integración PostgreSQL
  omitidas por no disponer del servicio externo.
- Los tres notebooks compilan, pasan el auditor de orquestación y conservan una
  única instalación capturada.
- Las pruebas simulan Python 3.13, una versión futura no soportada y un fallo de
  `pip` con preservación de `stdout` y `stderr`.
- La ejecución real con Python 3.13, GPU y extras completos queda cubierta por
  la matriz de CI y el checklist manual de Colab.

Post-mortem: la causa fue exclusivamente la restricción `<3.13` de metadata; no
fue necesario modificar contratos ML, datos, PostgreSQL ni el bundle.
