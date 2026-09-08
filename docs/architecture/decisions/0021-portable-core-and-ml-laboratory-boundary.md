# ADR-0021: Core portable y laboratorio ML separados

- Estado: aceptada
- Fecha: 2026-08-27
- Decisores: Facundo Nicolás González
- Actualiza: ADR-0020
- Actualizada por: ADR-0028

## Contexto

La percepción vehicular, la telemetría por minuto, las 19 features, la política
conservadora de estados y el bundle v2 serán reutilizados por los notebooks y
por workers de la futura API. Mantenerlos dentro del componente de laboratorio
forzaría a la aplicación a conocer DVC, Drive, PostgreSQL y configuración de
Colab.

## Decisión

La raíz sigue teniendo un único Git y DVC. ADR-0028 incorpora una tercera
distribución compartida para PostgreSQL:

```text
vaaet/
├─ vaaet-core/         # dominio e inferencia portable, import vaaet
├─ vaaet-persistence/  # PostgreSQL compartido, import vaaet_persistence
├─ vaaet-ml/           # laboratorio y notebooks, import vaaet_ml
├─ vaaet-app/   # reservado, sin código de API ni web todavía
├─ docs/
├─ .dvc/
└─ .github/
```

`vaaet-core` contiene contratos y errores de dominio, timestamps, telemetría,
ingeniería y etiquetado requeridos por serving, ciclo de vida/políticas del
bundle, validación manifest-first, carga de bundles y visión. Sus APIs públicas
son `vaaet.vision.analyze_video()`, `TrafficStatePrediction`,
`VideoAnalysisResult`, `vaaet.inference.load_traffic_bundle()` y
`TrafficStateEngine`. El motor clasifica minutos en memoria y nunca implementa
colas, workers, DVC, Drive ni persistencia.

`vaaet-persistence` conserva la única implementación de conexión, consultas,
escrituras, auditoría y migraciones PostgreSQL. `vaaet-ml` conserva datasets,
entrenamiento, evaluación, artefactos DVC, notebooks y adaptadores Colab. La
instalación completa sigue el orden core, persistencia y ML.

La futura API será el único adaptador entre la web y el core. Recibirá videos,
creará trabajos asíncronos consultables y almacenará referencias a resultados,
telemetría y video anotado. Sus workers invocarán el core de forma síncrona,
validarán el manifiesto vigente antes de deserializar y usarán
`vaaet-persistence` con credenciales propias. La Web App sólo consumirá HTTP versionado; no importará
Python ni conocerá rutas, DVC, Drive, PostgreSQL, modelos o datos HITL.

## Invariantes

- DVC continúa en la raíz y gobierna `vaaet-ml/artifacts/traffic-state/`.
- El core recibe sólo un directorio local de bundle; desconoce su procedencia.
- Se preservan bundle v2, 19 features, tres salidas aprendidas y cuatro estados
  públicos. `Accident` nunca se publica automáticamente.
- `stationary_confirmed` sigue siendo una señal conservadora por vehículo y
  minuto; no se agregan zonas, eventos de parking ni permanencia.
- No se implementan todavía API, framework, frontend, cola distribuida ni
  autenticación de usuarios web.

## Consecuencias

Las pruebas se separan por propiedad: visión, telemetría, contratos, bundle e
inferencia pertenecen al core; PostgreSQL pertenece a persistencia; y
entrenamiento, evaluación, datos y notebooks pertenecen a ML. CI instala y verifica los componentes por separado y
en conjunto. La validación manual de Colab GPU, Drive, DVC, YOLO y PostgreSQL
sigue siendo necesaria antes de promoción externa.
