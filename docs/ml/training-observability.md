# Observabilidad de entrenamiento y ciclo HITL

Estado: normativo y vigente.

El entrenamiento VAAET es un proceso manual y gobernado. Su ciclo es:

```text
revisión humana finalizada
  → catálogo HITL y holdout inmutables
  → input lock antes del cómputo costoso
  → entrenamiento/evaluación manual
  → informe inmutable por corrida
  → comparación compatible y decisión humana
```

No hay scheduler, reentrenamiento automático, promoción automática ni sustitución
automática de un bundle. La semilla sólo es un piloto de weak supervision; un
candidato que aspire a elegibilidad requiere evidencia humana conforme a los
ADRs 0017, 0018 y 0019.

## Configuración del notebook

En la única celda de configuración del notebook de entrenamiento se declaran:

```python
WRITE_TRAINING_REPORT = True
REFERENCE_TRAINING_RUN_ID = None
RUN_GROUPED_CROSS_VALIDATION = False
```

`WRITE_TRAINING_REPORT` persiste evidencia sólo tras validar evaluación, gates y
manifiesto. `REFERENCE_TRAINING_RUN_ID` recibe el UUID de una corrida anterior;
la comparación es descriptiva. `RUN_GROUPED_CROSS_VALIDATION` agrega evidencia
antes del entrenamiento final: nunca modifica los gates ni decide una promoción.

La configuración de fit centraliza semilla, épocas, batch y callbacks nuevos por
candidato o fold. Un `NaN`, entradas escaladas inválidas o una historia
incompleta detienen la corrida con un error de dominio en vez de producir un
informe aparentemente válido.

## Evidencia que se conserva

Cada corrida escribe de forma atómica bajo el root gobernado:

```text
training-runs/<pipeline-run-id>/
├── training-input-lock.json
├── training-observability-report.json
├── training-summary.md
└── diagnostics/
    ├── optimization-curves.png
    ├── test-quality.png
    └── supervision-governance.png
```

El JSON `vaaet-training-observability-report-v1` es la fuente canónica. El
Markdown y los gráficos son una lectura rápida para la decisión humana. Incluye
agregados de soporte, particiones, procedencia/pesos de supervisión, curva y
mejor época, métricas directas y de política, matrices de confusión, F1 macro,
calibración, seguridad de candidatos de incidente, lifecycle, bloqueos y
runtime redactado.

No se guardan filas, probabilidades por fila, videos, notas HITL, paths
absolutos, DSN, secretos ni binarios. El holdout nunca cuenta como evidencia que
reduce la memoria proxy: sólo el soporte humano de entrenamiento modifica ese
indicador por clase.

## Lectura de los diagnósticos

- **Curvas de optimización**: verificá que pérdida y validación sean finitas y
  que la mejor época no esconda una divergencia.
- **Calidad, confusión y confiabilidad**: revisá F1 macro, Normal–Congested,
  ECE, Brier y las matrices. Los umbrales ya existentes son los únicos gates.
- **Intervalos**: tablas, gráficos y gates reutilizan el mismo bootstrap de
  clips completos. Sin dos grupos independientes o sin soporte evaluable en el
  95 % de las réplicas, la métrica se muestra como insuficiente.
- **Supervisión y gobernanza**: observá el progreso humano hacia 300/300/100,
  el peso de memoria proxy decreciente, soporte descartado e integridad del
  holdout.

Los candidatos de incidente sólo expresan exposición y sensibilidad técnica. No
demuestran recall de `Accident`, que sigue siendo una decisión humana.

## Comparación segura y recuperación

Sólo se calculan deltas si ambos informes comparten el fingerprint del holdout,
el schema de features y las salidas estables. Una semilla, un holdout o un
contrato distinto se informa como **no comparable**; no debe forzarse una
conclusión.

En Colab, Drive conserva los objetos gobernados. Tras una interrupción, montá
Drive, recuperá el mismo `training-input-lock.json` y usá su UUID como referencia
para inspección; no reemplaces un informe existente ni continúes con datos
efímeros. Para una nueva corrida, generá un nuevo input lock y evaluála por
separado.

Las validaciones manuales en Colab —GPU, Drive, persistencia de los informes y
lectura de gráficos— continúan siendo requeridas antes de usar evidencia fuera
del entorno local.
