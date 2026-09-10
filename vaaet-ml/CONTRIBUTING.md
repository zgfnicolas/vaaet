# Guía de contribución — VAAET ML 4.8.0

Antes de modificar el proyecto, leé el [contexto raíz](../AGENTS.md), el
[resumen portable](../llms.txt), [AGENTS.md](AGENTS.md) y el ADR aplicable en
[`../docs/architecture/decisions/`](../docs/architecture/decisions/). ADR-0021
y ADR-0028 definen core, persistencia, ML y app; ADR-0022 gobierna serving con
YOLO.

## Reglas fundamentales

- La lógica portable vive en `../vaaet-core/src/vaaet/`; los notebooks sólo orquestan.
- Los imports de laboratorio usan `vaaet_ml.*`; el dominio usa `vaaet.*` y las
  operaciones PostgreSQL compartidas usan `vaaet_persistence.*`.
- `../vaaet-core/src/vaaet/settings.py` define contratos y umbrales; este
  componente define rutas y adaptadores de laboratorio; persistencia define DB.
- Los notebooks instalan core, persistencia y ML en ese orden.
- Las 19 features, cuatro estados, esquema PostgreSQL y arquitectura MLP son
  contratos; cualquier cambio requiere aprobación y un ADR nuevo.
- Los pesos YOLO y binarios `.keras`/`.joblib` no se versionan con Git. El bundle
  completo se registra como unidad mediante DVC.
- Código, APIs, identificadores y nombres se escriben en inglés. Los comentarios
  y docstrings propios usan español rioplatense formal y sólo explican contratos,
  efectos laterales, invariantes, decisiones o algoritmos no evidentes.

## Entorno y calidad

Python soportado: 3.10–3.13.

```bash
python -m pip install -e "../vaaet-core[vision,inference,dev]"
python -m pip install -e "../vaaet-persistence[admin,dev]"
python -m pip install -e ".[training,visualization,database,dev]"
ruff check src tests scripts
pytest tests/ -v --tb=short
python -m compileall -q src tests scripts
git diff --check
```

También deben compilar todas las celdas de los notebooks y resolver los enlaces
Markdown activos. La ejecución end-to-end con GPU, Drive, PostgreSQL y DVC
remoto se valida manualmente en Google Colab.

## Cambios por área

- Entrenamiento: `notebooks/training/train_traffic_state_classifier.ipynb` y
  [ADR-0008](../docs/architecture/decisions/0008-keras-traffic-state-classifier.md).
- Inferencia: `notebooks/inference/analyze_traffic_video.ipynb` y
  [ADR-0009](../docs/architecture/decisions/0009-modular-three-stage-architecture.md).
- Bundle y límite core/API: [ADR-0021](../docs/architecture/decisions/0021-portable-core-and-ml-laboratory-boundary.md).
- DVC: [guía DVC](../docs/ml/dvc-guide.md).
- Evaluación: `notebooks/evaluation/evaluate_models_and_eda.ipynb` es el cuarto
  notebook activo y sólo audita bundles y cohortes declaradas.

Actualizá [CHANGELOG.md](CHANGELOG.md) y la documentación cuando cambie un
comportamiento observable. Nunca incluyas secretos ni datos sensibles.
