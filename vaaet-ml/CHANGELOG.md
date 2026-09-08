# Historial de Cambios — VAAET

Todos los cambios relevantes del proyecto VAAET se documentan en este archivo, siguiendo los estándares de **Semantic Versioning (SemVer)** y la estructura de [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/).

## Identificación del Proyecto

| Campo | Detalles |
|---|---|
| **Nombre del Proyecto** | VAAET — Video Advanced Analysis of Traffic |
| **Responsable Técnico** | Facundo Nicolás González |
| **Responsable de Contexto** | Facundo Nicolás González |
| **Repositorio** | [github.com/zgfnicolas/vaaet](https://github.com/zgfnicolas/vaaet) |

---

## [Unreleased]

## [4.7.0] - 2026-09-08

### Añadido

- Distribución independiente `vaaet-persistence==0.1.0` para configuración,
  conexiones, operaciones, auditoría y migraciones PostgreSQL compartidas.
- Identidad de aplicación aportada por cada consumidor y prueba de integración
  sin instalar ML, Colab, TensorFlow, YOLO, DVC o Drive.
- ADR-0028 y guía operativa común para notebooks y futuros backends.

### Cambiado

- Los notebooks instalan core, persistencia y ML en ese orden y consumen la API
  PostgreSQL compartida; las fachadas `vaaet_ml.data` conservan compatibilidad
  durante VAAET 4.x.
- Alembic, las revisiones históricas byte a byte, roles y auditor administrativo
  tienen una sola ubicación canónica dentro de `vaaet-persistence`.

### Seguridad

- Cada consumidor selecciona un perfil explícito, aporta su identidad y conserva
  pools, TLS, redacción y mínimo privilegio sin reintentar escrituras.
- Se documentan bases separadas por entorno, privilegios por rol creador,
  backups diarios, 30 días de retención, restauración trimestral y RPO de 24 h.

## [4.6.1] - 2026-09-07

### Añadido

- `model_revision_algorithm=sha256-inference-contract-v2`, que incorpora la
  política de entrada a la identidad exacta del bundle.
- Propósito explícito de evaluación histórica para inspeccionar bundles con la
  identidad anterior sin habilitar inferencia operacional, HITL o promoción.
- Contrato puro en el core para comprobar que la evidencia de producción, los
  intervalos agrupados y la metadata de elegibilidad sean coherentes.

### Corregido

- Publicación recuperable del bundle ante fallos de movimiento, instalación,
  validación, restauración o limpieza, con exclusión de escritores concurrentes.
- Normalización de continuidad idempotente ante vistas y huecos temporales.
- Resolución HITL global y lineal entre PostgreSQL, backups y paquetes, con
  deduplicación previa, tipos estrictos y conservación de IDs de procedencia.
- Propagación de errores reales de inferencia; sólo el contexto temporal
  insuficiente conserva el resultado vacío esperado.
- Reportes e intervalos Champion--Challenger basados exclusivamente en clips
  completos, con evidencia insuficiente cuando faltan grupos independientes.

### Cambiado

- `vaaet-core` se publica como 0.2.1 y `vaaet-ml` como 4.6.1.
- Las identidades históricas se conservan sin reescritura y requieren una
  reexportación explícita a otro destino para adoptar el algoritmo corregido.

## [4.6.0] - 2026-09-05

### Añadido

- `continuity_id` contractual para reiniciar features, estados e incidentes
  ante cambios de vista o huecos superiores a 90 segundos.
- `model_revision` SHA-256 para distinguir bundles exactos y preservar
  predicciones y validaciones históricas.
- Notebook read-only de evaluación Champion–Challenger para bundles MLP v3,
  con validación del holdout humano congelado, métricas comparables e intervalos
  bootstrap reproducibles por clip.
- Perfil y comparación de deriva de covariables para cohortes
  `traffic-features-v3`, con controles de calidad, PSI y procedencia.
- Alembic `0003`, holdout humano v2, bundle v3, telemetría/features v3 y
  exportación atómica validada antes de reemplazar la copia DVC.

### Cambiado

- Las métricas distinguen salida `direct_*` del MLP y estado `final_*` después
  de calibración, umbrales e histéresis.
- Los gates de promoción utilizan límites conservadores del 95 % agrupados por
  clip y exposición negativa para las alertas de incidente.
- Las fuentes procesadas sólo aportan targets cuando demuestran validación
  humana explícita; una predicción no revisada no puede convertirse en etiqueta.
- El rol de inferencia conserva únicamente lectura e inserción sobre features y
  predicciones inmutables; ya no puede actualizarlas ni eliminarlas.
- La serialización del manifiesto rechaza JSON no estándar y representa métricas
  no disponibles como `null`, evitando bundles con `NaN` no portable.
- `vaaet-core` se publica como 0.2.0 y `vaaet-ml` como 4.6.0.

## [4.5.4] - 2026-09-02

### Corregido

- Bootstrap de Colab no destructivo: la primera resolución preserva paquetes
  compatibles del runtime y los refrescos de código usan `--no-deps`.
- Limpieza de módulos Pillow y Ultralytics cargados antes de instalar, seguida
  por un smoke test real de `ImageDraw` y `YOLO` antes de registrar el runtime.
- Selección de un único MP4 independiente de la descarga de resultados, con
  validación temprana y staging explícito bajo `/content`.
- Descargas condicionadas por configuración y protección contra persistencia
  de resultados obsoletos después de una ejecución fallida.

## [4.5.3] - 2026-08-22

### Corregido

- Compatibilidad oficial con Python 3.13 en metadata, dependencias condicionales
  de TensorFlow y matriz de CI, conservando Python 3.10–3.12.
- Preflight de runtime en los tres notebooks antes de instalar dependencias.
- Diagnóstico completo y accionable de stdout/stderr cuando `pip` no puede
  instalar VAAET en un runtime administrado de Colab.
- Runtime Colab 2026.07 con Python 3.12.13 documentado como fallback temporal.

## [4.5.2] - 2026-08-19

### Corregido

- Manejo explícito de clips con un único minuto completo: conservan video y
  telemetría sin intentar métricas, persistencia, HITL ni dashboard.
- Esquema contractual de clasificación también para resultados vacíos, evitando
  accesos inválidos a `traffic_state` cuando falta contexto temporal.
- Mensajes y documentación alineados con el mínimo de dos minutos consecutivos
  requerido por las features de diferencias.

## [4.5.1] - 2026-08-19

### Corregido

- Preservación exacta de valores `float64` al recargar CSV contractuales mediante
  el modo `round_trip` de Pandas, evitando falsos cambios de fingerprint.
- Validación del snapshot semilla temporal antes de publicarlo en el store
  inmutable.
- Recuperación idempotente de snapshots válidos que fueron escritos antes de
  crear `current.json`; los paquetes corruptos se conservan y se rechazan con
  un diagnóstico explícito.

## [4.5.0] - 2026-08-10

### Añadido

- Store inmutable `vaaet-seed-bootstrap-v1` con generaciones, fingerprint y
  pointer atómico `current.json`.
- Catálogo `vaaet-dataset-catalog-v1` y un paquete portable por sesión HITL,
  tanto con PostgreSQL como sin él.
- Resolución global de correcciones append-only mediante UUID y exclusión
  contractual de predicciones no revisadas.
- `vaaet-training-input-lock-v1` por entrenamiento y descriptor dentro de
  `model-manifest.json`.
- ADR-0019 para gobernar datasets portables inmutables y locks de entrada.

### Cambiado

- Entrenamiento consume el snapshot semilla vigente y todos los paquetes HITL
  activos del catálogo, en lugar de rutas ZIP mutables.
- Inferencia acumula las decisiones de revisión y ofrece una finalización
  explícita, idempotente y sincronizable con Google Drive.

### Seguridad y calidad

- Escrituras atómicas de pointers y catálogo, validación de rutas relativas,
  checksums SHA-256 y cuarentena catalogable.
- Ciclos, ramas, referencias inválidas y conflictos de etiquetas o features
  detienen la ingestión antes de entrenar.

## [4.4.0] - 2026-08-10

### Añadido

- Contrato portable `vaaet-human-holdout-v1` para congelar validation y test
  humanos con checksums, fingerprint y soporte por clase.
- Almacenamiento versionado en Google Drive mediante `current.json`, creación
  inicial, reutilización exacta y actualizaciones explícitas e idempotentes.
- Descriptor del benchmark en el manifiesto del modelo y comparación restringida
  a candidatos evaluados con el mismo fingerprint.
- ADR-0018 para gobernar el benchmark humano congelado.

### Seguridad y calidad

- Los clips reservados se excluyen completamente de train y nunca se sustituyen
  por una partición efímera cuando Drive falla.
- Accident, weak labels y datos sintéticos quedan fuera del holdout humano.
- Las correcciones contradictorias exigen una nueva generación auditable.

## [4.3.0] - 2026-08-09

### Añadido

- Modos explícitos `SEED_BOOTSTRAP` y `HITL_RETRAINING` sobre un pipeline común.
- Paquete semilla procesado reutilizable y memoria proxy decreciente por clase.
- Comparación reproducible de class weights, oversampling moderado y sintéticos
  de congestión, seleccionada sólo con validation.
- Lifecycle del bundle con modo, supervisión, política de entrada y etapa
  `pilot`, `candidate` o `production`.
- ADR-0017 para gobernar weak-supervision bootstrap y continuous training HITL.

### Cambiado

- El modelo vigente es `mlp-v2.1`; conserva 19 features y tres salidas estables.
- La política legacy neutraliza de forma idéntica en entrenamiento e inferencia
  las evidencias de calidad desconocidas.
- Inferencia identifica y autoriza de forma explícita bundles piloto.

### Seguridad y calidad

- Accident sigue siendo imposible como salida automática y queda reservado a
  validación humana.
- Las predicciones sin revisar nunca ingresan como targets y los sintéticos
  permanecen exclusivamente en train.

## [4.2.2] - 2026-08-09

### Corregido

- `record_time` se normaliza como UTC timezone-aware en adquisición, ingestión,
  sintéticos, auditoría, ingeniería, CSV, contratos y persistencia.
- Los timestamps legacy sin zona se interpretan como hora de Buenos Aires; las
  features `hour_of_day` y `weather_condition` conservan esa semántica local.
- La combinación observada de 2.068 filas reales UTC y 200 sintéticas deja de
  producir timestamps mixtos y completa auditoría e ingeniería de features.

### Pruebas

- Se cubren equivalencia local/UTC, deduplicación por instante, cruce entre
  entrenamiento e inferencia y la regresión completa de 2.268 registros.

## [4.2.1] - 2026-08-09

### Corregido

- La extracción de backups custom usa entradas exactas `TABLE DATA` del catálogo
  de `pg_restore`, preservando compatibilidad con `public.traffic_data` y
  `vaaet_raw.traffic_data` sin pasar nombres calificados a `--table`.
- Una restauración con retorno no exitoso, tabla ausente, tabla raw vacía o SQL
  sin el bloque `COPY` solicitado se detiene con un diagnóstico específico.
- La procedencia de entrenamiento informa tabla legacy/moderna, versión del
  lector y filas importadas.

### Pruebas

- CI genera backups custom legacy y modernos con PostgreSQL 17 y verifica su
  ingestión real de extremo a extremo.

## [4.2.0] - 2026-08-06

### Añadido

- Schema `vaaet_ops` y registro redactado de ejecuciones collection, inference,
  training y review, con fallback JSON cuando PostgreSQL no está disponible.
- Migración incremental `20260806_0002`, comentarios de catálogo, auditor
  read-only y ADR-0016.

### Cambiado

- Los contratos Python usan nombres semánticos para columnas base, calidad,
  metadata y esquema raw canónico; las versiones permanecen en los datos.
- Consultas y vistas activas usan proyecciones explícitas, los UUID de ejecución
  tienen integridad referencial y los roles escriben operaciones mediante
  funciones autorizadas.
- Se eliminaron índices redundantes y se reforzaron etiquetas de estados,
  totales vehiculares y cadenas HITL append-only.

### Seguridad

- La base exclusiva revoca creación pública y aplica default privileges cerrados.
- La continuidad exige cifrado en reposo, 30 días de retención, RPO de 24 horas
  y restauraciones trimestrales verificadas.

## [4.1.0] - 2026-08-04

### Añadido

- Contrato PostgreSQL `vaaet-db-v2` con schemas `vaaet_raw`, `vaaet_ml` y
  `vaaet_feedback`, migración Alembic y cuatro roles de mínimo privilegio.
- Configuración tipada por perfil, TLS, health check redactado y soporte directo
  para Colab Secrets, entorno local y `.env` explícito.
- Ingestión declarativa que combina PostgreSQL, backups, CSV raw y paquetes
  `vaaet-training-dataset-v1.zip` con checksums y procedencia.
- Cola HITL posterior a inferencia, validaciones append-only y exportación offline.
- Integración PostgreSQL 17 en CI para migración, constraints, vistas y grants.

### Cambiado

- Features y predicciones se persisten en tablas separadas; una reinferencia no
  modifica ni elimina feedback humano.
- El entrenamiento sólo acepta etiquetas humanas efectivas 0–2; Accident se
  reserva para evaluar el detector y las predicciones sin revisar quedan excluidas.
- Los notebooks ya no contienen DDL ni lógica propia de credenciales.

### Corregido

- Los clips sin una ventana completa de 60 segundos conservan el video anotado
  y finalizan sin crear telemetría parcial, CSV vacío, escrituras PostgreSQL ni
  sesiones HITL inválidas.

### Deprecado

- Variables `DB_*` y vistas `public.*`, disponibles sólo durante VAAET 4.x.

## [4.0.0] - 2026-08-01

### Cambiado

- Adoptado source layout `src/vaaet/` y distribución Python `vaaet-ml`.
- Formalizados tres workflows: adquisición bajo demanda, entrenamiento e inferencia.
- Extraído el análisis de video anotado a `vaaet.vision.analysis` y reemplazado
  el notebook monolítico por `collect_traffic_telemetry.ipynb`.
- Añadidas deduplicación CSV, persistencia idempotente en `traffic_data`, Secrets
  de Colab, procedencia temporal y ADR-0013.
- Definido bundle portable de cuatro archivos, validado y versionado como unidad con DVC.
- Establecido el límite multi-repo ML/Web mediante ADR-0012.
- Sincronizada CI para Python 3.10–3.12, todos los extras, `pip check`, Ruff,
  pytest, tres notebooks, enlaces, DVC y control de binarios ML.
- Sustituido el clasificador plano de cuatro salidas por `mlp-v2.0`: tres
  estados estables, calibración por validation, histéresis y candidato de incidente.
- Prohibido `Accident` automático; el código 3 requiere override humano validado.
- Migrada telemetría a schema v2 nullable, con contadores por track único y
  semántica temporal reiniciada por clip y hueco.
- Sustituidos SMOTE 1:1 y `validation_split` por test temporal, validation por
  grupos, class weights limitados y gates explícitos de promoción.
- Publicados contrato de bundle v2, ADR-0014, protocolo de anotación humana y
  auditoría obligatoria del dataset.

### Incompatible

- Eliminados imports `src.*`, hacks de `sys.path` y rutas activas heredadas.
- Las rutas y referencias previas sólo se conservan como registro histórico.

## [3.1.0] - 2026-07-23

**Hito:** Estandarización de Documentación 2026

### 🚀 Añadido

- **Documentación:** 20+ documentos nuevos siguiendo plantillas estandarizadas:
  - `docs/SRS.md` — Especificación de Requisitos (IEEE 830)
  - `docs/SAD.md` — Arquitectura de Software (reemplaza DDS.md)
  - `docs/DATA_MODEL.md` — Modelo de Datos y Diccionario
  - `docs/TEST_PLAN.md` — Plan de Pruebas
  - `docs/MODEL_CARD.md` — Model Card estilo HuggingFace
  - `docs/USER_PERSONAS.md` — Perfiles de Usuario
  - `docs/USE_CASES.md` — Casos de Uso del Negocio
  - `docs/RISK_MATRIX.md` — Matriz de Riesgos
  - `docs/DEPLOYMENT.md` — Manual de Despliegue
  - `docs/FEASIBILITY.md` — Estudio de Factibilidad
  - `docs/SECURITY_POLICY.md` — Política de Seguridad y Privacidad
  - `docs/BUSINESS_CANVAS.md` — Business Model Canvas
  - `docs/NDA.md` — Acuerdo de Confidencialidad
  - `docs/SOW.md` — Declaración de Trabajo
  - `docs/PROJECT_PLAN.md` — Plan de Gestión del Proyecto
  - `docs/INDEX.md` — Índice maestro de documentación
- **Infraestructura:**
  - `pyproject.toml` — Configuración de paquete Python (compatible Colab)
  - `.env.example` — Template de variables de entorno
  - `.github/workflows/ci.yml` — Pipeline CI con GitHub Actions
  - `SECURITY.md` — Política de seguridad en raíz
  - `SUPPORT.md` — Canales de soporte
  - `AGENTS.md` — Contexto de ejecución para agentes de IA
  - `llms.txt` — Resumen optimizado para RAG/LLMs
- **ADR:** ADR-010 — Pipeline MLOps con 19 features y señales de calidad
- **Directorios:** `models/perception/`, `artifacts/traffic-state/`, `data/raw/`, `data/processed/`, `data/sample/`

### 🛠️ Cambiado

- **Directorio:** `Docs/` renombrado a `docs/` (convención universal)
- **Idioma:** Toda la documentación migrada a español argentino formal
- **README.md:** Reescrito completamente en español con nueva estructura
- **CONTRIBUTING.md:** Reescrito en español con guías actualizadas
- **CHANGELOG.md:** Migrado a español con secciones de Context Health
- **PRD.md:** Reescrito con historias de usuario en formato Gherkin
- **DDS.md → SAD.md:** Renombrado y reescrito como Documento de Arquitectura de Software
- **USER_GUIDE.md:** Reescrito en español
- **DATA_LINEAGE.md:** Reescrito en español con actualización a 19 features
- **BIAS_AND_LIMITATIONS.md:** Reescrito en español
- **KPIs/KPIs.md:** Reescrito en español

### 🤖 Gestión de Contexto (Context Health)

- Creado `AGENTS.md` con sistema de gobernanza Always/Ask/Never
- Creado `llms.txt` optimizado para consumo por RAG
- Actualización de cross-references entre 30+ documentos
- Eliminación de deuda de contexto: todas las referencias apuntan a archivos existentes
- 10 ADRs documentados y clasificados (activos vs supersedidos)

---

## [3.0.0] - 2025-07-14

**Hito:** Arquitectura modular de tres módulos + Clasificador MLP

### 🚀 Añadido

- Arquitectura de tres módulos con código compartido en `src/` (ADR-009)
- `src/config.py` — Fuente única de verdad para constantes, rutas, umbrales
- `src/db.py` — Factory de engine SQLAlchemy con credenciales por variables de entorno
- `src/features.py` — Feature engineering compartido (9 → 19 columnas)
- `src/labeling.py` — Reglas de auto-etiquetado compartidas (4 estados del tráfico)
- `src/classification.py` — Inferencia compartida + gate conservador de accidentes
- `src/contracts.py` — Contratos de datos tipados con validación
- `src/synthetic.py` — Generador de datos sintéticos para clases raras
- `src/persistence.py` — Persistencia en BD con upsert idempotente
- `src/perception/` — Pipeline de percepción: detector, tracker, velocidad, flujo óptico
- Módulo 2 de producción: `notebooks/inference/analyze_traffic_video.ipynb`
- Scaffold experimental de feedback loop HITL
- Suite de tests: 19 archivos, ~2.556 líneas
- ADR-009: Arquitectura modular de tres etapas

### 🛠️ Cambiado

- Módulo 0 (bootstrap) archivado en `archive/bootstrap-v1/`
- Módulo 1 movido a `notebooks/training/train_traffic_state_classifier.ipynb`
- ADR-001 a ADR-007 supersedidos por ADR-009
- ADR-008: Input(13,) corregido a Input(14,) (14 features canónicas, luego 19)
- Estructura del proyecto reorganizada según principios SOLID, YAGNI, KISS

### 🗑️ Eliminado

- `vaaet.ipynb` (duplicado del notebook bootstrap)
- Estructura de directorios obsoleta: `notebooks/phase_1_perception/`, `notebooks/phase_2_intelligence/`
- `src/utils/` (directorio placeholder)

---

## [2.0.0] - 2025-03-07

**Hito:** Clasificador de estados del tráfico con TensorFlow/Keras

### 🚀 Añadido

- Módulo 1: Clasificador de estados del tráfico con MLP de TensorFlow/Keras
- 4 estados del tráfico: Normal, Reducido, Congestionado, Accidente
- Feature engineering: 9 campos crudos → 14 features de ingeniería
- Auto-etiquetado con reglas de ingeniería de tráfico
- Balanceo de clases con SMOTE (imbalanced-learn)
- 2 tablas nuevas: `telemetry_raw` (14 features + FK), `traffic_classifications` (predicción + HITL)
- Diagrama del pipeline de inteligencia (Mermaid)
- Diagrama ERD extendido con 3 tablas y cadena de FK
- ADR-008: TensorFlow/Keras para clasificación de tráfico

### 🛠️ Cambiado

- Proyecto reestructurado: notebooks/, models/, data/, src/, docs/
- requirements.txt expandido con 7 dependencias nuevas

---

## [1.0.0] - 2025-03-06

**Hito:** Pipeline completo de análisis vehicular — Percepción

### 🚀 Añadido

- Pipeline completo de análisis vehicular para el Puente Gral. Manuel Belgrano
- Detección y clasificación con YOLO 11 (5 variantes: n/s/m/l/x)
- Selección automática de modelo por duración del video
- Tracking persistente con SORT liviano
- Cálculo de velocidad híbrido: 70% física + 30% MLP suavizador
- Compensación de movimiento de cámara vía Flujo Óptico (Lucas-Kanade)
- Corrección de perspectiva adaptativa por coordenada Y
- Detección ultraconservadora de vehículos estacionarios (conjunción AND de 6 criterios)
- Soporte multi-cámara: detección automática de layouts (1, 2, 4 vistas)
- Persistencia opcional en PostgreSQL (AWS RDS) por minuto
- Video de salida con anotaciones, overlays, y HUD informativo
- Generador de video sintético para demos de portfolio
- Interfaz universal de upload (Colab + local)
- Optimización para Google Colab Free/Pro (frame skipping, memory cleanup)

---

## Convención de Commits

- `feat(...)`: Nueva funcionalidad
- `fix(...)`: Corrección de errores
- `docs(...)`: Cambios en documentación
- `refactor(...)`: Mejora de código sin cambios funcionales
- `test(...)`: Adición o modificación de tests

## Versionado

| Tipo de Cambio | Incremento |
|---|---|
| **Mayor (Major)** | Cambios que rompen compatibilidad o arquitectura profunda |
| **Menor (Minor)** | Nuevas funcionalidades sin romper compatibilidad |
| **Parche (Patch)** | Correcciones menores y mantenimiento |

---

Responsable del documento: Facundo Nicolás González
Fecha de revisión: 2026-07-23
