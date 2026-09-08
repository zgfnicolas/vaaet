# AGENTS.md — VAAET Core

Leé primero el [`AGENTS.md`](../AGENTS.md) raíz, el
[`llms.txt`](../llms.txt) y [ADR-0021](../docs/architecture/decisions/0021-portable-core-and-ml-laboratory-boundary.md).

## Alcance

`vaaet-core` es la distribución portable `vaaet-core==0.2.1`, con import
`vaaet`. Contiene percepción, telemetría, 19 features, política de estados y
bundle/inferencia manifest-first. No puede importar `vaaet_ml`, PostgreSQL,
DVC, Google Drive ni APIs de notebook; tampoco administra colas, workers,
persistencia ni rutas remotas.

## Contratos

- APIs públicas: `vaaet.vision.analyze_video()`, `TrafficStatePrediction`,
  `VideoAnalysisResult`, `vaaet.inference.load_traffic_bundle()` y
  `TrafficStateEngine`.
- El bundle v3 se valida antes de deserializar; conserva 19 features, tres
  salidas aprendidas y cuatro estados públicos. `Accident` nunca es automático.
- Visión procesa clips finitos con Pipe-and-Filter síncrono, ordenado y una
  única sesión mutable por video. No agregar `Queue`, threads, procesos ni
  Producer--Consumer sin medición comparable en Colab y aprobación explícita.
- `VideoViewPlan` es opt-in para segmentos offline ya calibrados. No leer planes
  desde rutas remotas, inferir perfiles, transferir IDs entre vistas ni emitir
  telemetría de un minuto que cruza una transición.
- `continuity_id` reinicia features, estados e incidentes por cambio de vista o
  hueco superior a 90 segundos. `model_revision` identifica el bundle exacto;
  `model_version` sigue siendo una etiqueta semántica.

## Comentarios y docstrings

Usá identificadores y código en inglés, y comentarios y docstrings propios en
español rioplatense formal. Documentá APIs públicas, invariantes del pipeline y
algoritmos no evidentes; evitá explicar helpers triviales o repetir el código.
Los contratos se redactan en forma declarativa y las instrucciones, con voseo
formal.

## Calidad

Desde `vaaet-core/`, instalar los extras estrictamente necesarios y ejecutar:

```bash
python -m pip install -e ".[vision,inference,dev]"
ruff check src tests
pyright --project ../pyrightconfig.json
pytest tests -v --tb=short
python -m compileall -q src tests
git diff --check
```

Los cambios de contratos, features, estados, bundle o límites de componentes
requieren aprobación y el ADR aplicable. No incorporar secretos, pesos, videos
ni artefactos binarios al repositorio.
