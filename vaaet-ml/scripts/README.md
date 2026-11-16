# Utilidades manuales

Este directorio contiene herramientas auxiliares; no forma parte del runtime de
los notebooks.

- `notebook_bootstrap.py`: resuelve extras sin reinstalar dependencias
  compatibles, refresca ambos paquetes desde el checkout y valida el borde
  visual real antes del preflight de cada notebook.
- `convert-postgres-backup.py`: convierte un backup PostgreSQL a CSV para Colab.
- `export-training-dataset.py`: crea y verifica `vaaet-training-dataset-v1.zip` desde exports CSV administrativos.
- `evaluate-telemetry-exports.py`: compara resultados exportados de telemetría.
- `audit-notebooks.py`: audita sin modificarlos la estructura y la higiene de
  los notebooks. Es un gate del CI: `python scripts/audit-notebooks.py notebooks`.
- `audit-postgres-database.py`: audita en modo read-only migración, permisos,
  comentarios, constraints, índices, tamaños, integridad y planes PostgreSQL.
- `vaaet-registry`: comando instalable del paquete que configura el remoto local,
  valida bundles y opera el registro DVC. Su guía está en
  [`docs/ml/dvc-guide.md`](../../docs/ml/dvc-guide.md).

Requieren instalación editable del proyecto. No se admiten scripts temporales,
parches ni modificaciones de `sys.path`.

Las migraciones y roles viven en `migrations/`; no son utilidades de notebook.
