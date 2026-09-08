# Pipeline de entrenamiento e inferencia jerárquica

```mermaid
flowchart TD
    A[(vaaet_raw.traffic_data v1/v2)] --> B[Auditoría contractual]
    B --> C[19 features v2 por clip y segmento continuo]
    C --> D[Etiquetas proxy o humanas<br/>Normal / Reduced / Congested]
    D --> E[Holdout humano congelado por grupos]
    D --> F[Validation por grupos]
    D --> G[Train por grupos<br/>sintéticos opcionales con peso reducido]
    G --> H[StandardScaler fit sólo en train]
    H --> I[MLP 19 -> 64 -> 32 -> 3]
    F --> J[Selección por coste, F1 y calibración]
    I --> J
    J --> K[Política temporal<br/>umbrales + margen + histéresis]
    K --> L[Detector de posible incidente]
    L -->|sin evidencia| M[Estado estable 0-2]
    L -->|fuerte y persistente| N[Congested + accident_rule_triggered]
    N -->|confirmación humana validada| O[Accident público]
    M --> P[Bundle v3]
    O --> Q[(feedback humano)]
    Q --> D
    E --> R[Evaluación final real y humana]
    P --> R
```

El MLP nunca emite `Accident`. Validation/test no contienen sintéticos y una ventana parcial no se clasifica. El bundle sólo es promovible cuando su manifiesto no contiene bloqueos.

## Bundle

| Archivo | Propósito |
|---|---|
| `traffic_classifier.keras` | MLP de tres salidas |
| `feature_scaler.joblib` | Scaler ajustado con train |
| `label_mapping.joblib` | Cuatro estados públicos |
| `model-manifest.json` | Contrato v2, política, métricas, procedencia y checksums |
