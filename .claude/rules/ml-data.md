---
paths:
  - "vaaet-ml/src/vaaet_ml/data/**"
  - "vaaet-ml/src/vaaet_ml/training/**"
---

# Datos, HITL y entrenamiento

- Las reglas RN-13 a RN-19 gobiernan esta zona; leé
  `docs/product/business-rules.md` antes de cambiar la consolidación.
- Al combinar fuentes (PostgreSQL, paquetes, backups), los valores llegan con
  tipos distintos: un `uuid.UUID` se compara como su texto canónico y la
  identidad del modelo sale de la predicción validada, nunca de la feature.
- Un `NULL` en una columna nullable se conserva como `None`; no inventes
  valores.
- Los tests unitarios simulan catálogos de backup y conexiones; un cambio en
  lectura de backups o PostgreSQL necesita además la skill `pg-integration`.
