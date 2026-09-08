# Directorios de datos

- `raw/`: backups y exportaciones originales; nunca versionar datos sensibles.
- `processed/`: datasets generados para entrenamiento.
- `sample/`: ejemplos pequeños, anónimos y no sensibles.

`traffic_data`/CSV v3 añade continuidad, contadores de tracks únicos, calidad de velocidad,
flujo óptico y `telemetry_schema_version`. Las filas históricas v1/v2 conservan
esos campos como `NULL`; no equivalen a calidad perfecta. La plantilla de
ground truth está en `sample/traffic-state-annotation-template.csv` y su uso se
describe en [el protocolo humano](../../docs/ml/human-annotation-protocol.md).

Los datos operativos permanecen ignorados por Git. DVC se reserva para el bundle
de modelo aprobado, no para videos ni backups de bases de datos.

El inicio semilla produce snapshots `vaaet-seed-bootstrap-v1-0001-<fingerprint>.zip`
bajo `MyDrive/vaaet-ml/data/seed-bootstrap/snapshots/`; `current.json` selecciona
la generación activa sin sobrescribir anteriores. Cada sesión finalizada de
revisión produce su propio `vaaet-training-dataset-v1.zip` bajo
`MyDrive/vaaet-ml/data/hitl-reviews/YYYY/MM/DD/` y una entrada en `catalog.json`.
Estos artefactos no se versionan con Git. El directorio local `processed/` sólo
contiene salidas efímeras y paquetes pendientes de sincronización.
