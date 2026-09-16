# Configuración de workflows en notebooks

Las cuatro notebooks usan presets tipados. El preset es una receta completa:
define entradas, requisitos, escrituras y próximos pasos antes de comenzar. Los
valores predeterminados permiten `Run All` sin escribir en PostgreSQL, publicar
catálogos ni copiar artefactos a Drive.

## Regla de uso

1. Elegí un preset soportado en la única celda editable de configuración.
2. Ejecutá el resumen y revisá entradas, Secrets y escrituras esperadas.
3. Usá `CUSTOM` sólo junto con un objeto de configuración tipado creado mediante
   `dataclasses.replace()` sobre un preset conocido.
4. No actives una escritura por la mera presencia de credenciales.

## Recolección

| Preset | Resultado |
| --- | --- |
| `CollectionPreset.LOCAL` | Video anotado y CSV raw en el runtime. |
| `CollectionPreset.POSTGRES` | Lo anterior más persistencia explícita con el perfil `collection`. |
| `CollectionPreset.TRACKING_DIAGNOSTIC` | Recolección local con HUD técnico. |

Seleccionar o subir un MP4 no equivale a descargar resultados. La descarga al
equipo y la persistencia PostgreSQL son decisiones independientes.

## Inferencia

| Preset | Resultado |
| --- | --- |
| `InferencePreset.PILOT_OFFLINE` | Inferencia piloto local, sin escrituras. |
| `InferencePreset.PILOT_HITL` | Inferencia piloto y revisión portable. |
| `InferencePreset.PERSISTED_INFERENCE` | Predicciones en PostgreSQL, sin revisión. |
| `InferencePreset.PERSISTED_HITL` | Persistencia y revisión humana explícitas. |
| `InferencePreset.EXPERIMENTAL_OFFLINE` | Evaluación local de candidato, sin escritura operacional. |

Repetir la clasificación crea otro intento e invalida acciones derivadas del
anterior. Un clip sin contexto temporal produce un resultado vacío válido; un
fallo del modelo bloquea persistencia, revisión y dashboard. `Accident` nunca es
una salida automática.

## Entrenamiento

| Preset | Fuente principal |
| --- | --- |
| `TrainingPreset.SEED_UPLOAD` | Backup o CSV raw subido. |
| `TrainingPreset.SEED_POSTGRES` | Telemetría raw PostgreSQL read-only. |
| `TrainingPreset.HITL_CATALOG` | Catálogo HITL inmutable de Drive. |
| `TrainingPreset.HITL_CATALOG_POSTGRES` | Catálogo más feedback PostgreSQL. |
| `TrainingPreset.HITL_FROZEN_HOLDOUT` | Reentrenamiento con benchmark humano fijo. |

La lectura PostgreSQL moderna es `postgres_telemetry_read_mode="current"`.
`"legacy"` debe elegirse deliberadamente y sólo se admite para crear una semilla
desde telemetría raw histórica; ningún error cambia de modo automáticamente.

El entrenamiento puede generar un bundle aunque el cierre auditable falle, pero
en ese caso no lo copia a Drive ni lo habilita para pasos que requieren lineage
completo. La reconciliación verifica la corrida y no repite el entrenamiento.

## Evaluación

| Preset | Operación read-only |
| --- | --- |
| `EvaluationPreset.CHECK_ONLY` | Verifica configuración sin cargar evidencia. |
| `EvaluationPreset.COMPARE_MODELS` | Compara Champion y Challenger sobre el mismo holdout. |
| `EvaluationPreset.FILE_DRIFT` | Analiza deriva entre cohortes de archivos. |
| `EvaluationPreset.POSTGRES_DRIFT` | Lee una cohorte PostgreSQL con límites UTC explícitos. |

La evaluación no promociona, no modifica DVC y no escribe datos operacionales.

## PostgreSQL, Drive y recuperación

Los cuatro perfiles PostgreSQL pueden apuntar al mismo servidor, pero usan
credenciales y permisos independientes. Consultá la [guía PostgreSQL](postgresql-guide.md)
y la [guía Colab](colab-guide.md#secrets-y-postgresql).

Finalizar una revisión crea primero un ZIP local `pending-sync`. Publicarlo en
Drive requiere el publicador coordinado del catálogo. Un fallo remoto conserva
los mismos bytes para reintentar; no reconstruye la sesión ni inventa otra
identidad.
