# Flujo de cálculo de velocidad physics-first

`vaaet-core/src/vaaet/vision/pipeline.py` coordina el análisis ordenado; la
estimación vive en `vaaet-core/src/vaaet/vision/speed.py`. El resultado depende
del historial de cada track y no ofrece un fallback de velocidad inventada.

```mermaid
flowchart TD
    A[Historial temporal del track] --> B[Flujo óptico global]
    B --> C[Compensar movimiento de cámara]
    C --> D[Desplazamientos por frame]
    D --> E[Filtrar ruido y anomalías]
    E --> F{¿Plan de vista calibrado?}
    F -->|No| G[Corrección de perspectiva por zona Y]
    F -->|Sí| H[Contacto inferior y escala por profundidad]
    G --> I[Convertir píxeles a metros]
    H --> I
    I --> J[Velocidad física km/h]
    J --> K{¿Plausible y confiable?}
    K -->|No| L[Excluir de la síntesis]
    K -->|Sí| M[Suavizado por track]
    A --> N[Analizar movimiento]
    N --> O[Confirmación estacionaria con histéresis]
    M --> P[Acumulador por minuto]
    O --> P
    L --> P
    P --> Q[Síntesis robusta y señales de calidad]
    Q --> R[Fila de telemetría apta para clasificación]
```

La fusión MLP de velocidad es un path dormido y no integra el runtime activo.
Con un `VideoViewPlan`, un cambio de vista reinicia estado temporal y cualquier
minuto mixto se descarta antes de esta síntesis. La escala por profundidad no es
una homografía ni habilita afirmaciones de precisión física sin ground truth.
