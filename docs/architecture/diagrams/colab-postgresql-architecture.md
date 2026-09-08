# Arquitectura Colab y PostgreSQL

```mermaid
flowchart LR
    U["Usuario"] --> N["Four Colab notebooks"]
    G["GitHub repository"] --> N
    N --> GPU["Managed GPU runtime"]
    Y["Ultralytics"] -->|"YOLO weights at runtime"| N
    N <-->|"Complete model bundle"| D["Google Drive"]
    N -->|"Explicit workflow profile"| S["vaaet-persistence"]
    S -->|"SQLAlchemy 2 + TLS"| P[("PostgreSQL 14+")]
    N -->|"Download"| U
```

Adquisición, entrenamiento e inferencia requieren una GPU gestionada; evaluación
es read-only. Las credenciales por perfil se leen directamente de Colab Secrets. `vaaet_raw`,
`vaaet_ml` y `vaaet_feedback` separan responsabilidades; la biblioteca
compartida centraliza las operaciones. Alembic y el administrador
nunca se ejecutan desde Colab. `/content` es efímero y la persistencia permanece
deshabilitada por defecto.
