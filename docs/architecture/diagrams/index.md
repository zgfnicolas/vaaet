# Diagramas de arquitectura

- [Pipeline completo](pipeline-flow.md)
- [Entrenamiento e inteligencia](intelligence-pipeline.md)
- [Selección adaptativa de YOLO](model-selection.md)
- [Cálculo de velocidad](speed-calculation.md)
- [Arquitectura Colab y PostgreSQL](colab-postgresql-architecture.md)
- [Modelo relacional `vaaet-db-v3`](../data-model.md)

El diagrama multi-cámara simultánea fue retirado porque describe una capacidad
no implementada. El soporte actual es un plan offline y secuencial de vistas
calibradas; consultá el [diagrama de velocidad](speed-calculation.md) y
[ADR-0025](../decisions/0025-calibrated-multi-view-video-segments.md).
