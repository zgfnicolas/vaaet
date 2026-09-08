---
name: vaaet-hybrid-qa
description: Diseñá y revisá pruebas VAAET basadas en riesgo para core, ML y una futura API, sin introducir infraestructura ni dependencias no aprobadas.
---

# QA híbrido y MLOps para VAAET

Diseñá evidencia de calidad proporcional al riesgo y al límite del componente. Esta skill guía pruebas para el core portable, el laboratorio ML y la futura aplicación; no crea una API, un framework ni una estrategia de CI nueva.

Antes de cambiar comportamiento, leé `AGENTS.md`, `llms.txt`, `docs/quality/test-plan.md` y el ADR aplicable. ADR-0021 delimita core y ML; ADR-0022 gobierna serving con YOLO; ADR-0024 gobierna PostgreSQL. Los contratos y ADRs prevalecen sobre esta skill.

## Ubicá cada prueba en su límite real

| Límite | Qué se prueba | Qué no debe cruzar |
| --- | --- | --- |
| `vaaet-core/` | Visión, telemetría, 19 features, estados, bundle v3 e inferencia portable | `vaaet_ml`, PostgreSQL, DVC, Drive y notebooks |
| `vaaet-ml/` | Datasets, entrenamiento, evaluación, notebooks, DVC y persistencia de laboratorio | Contratos públicos ni lógica portable duplicada |
| `vaaet-app/` futuro | Contrato HTTP, validación de requests y adaptadores de serving | Acceso web directo al core, DVC, Drive, PostgreSQL o bundles |

No pruebes una frontera mediante dependencias que la rompan. La Web App futura sólo consume una API HTTP versionada; sus workers usarán `vaaet-core`, nunca `vaaet-ml`, y validarán el manifiesto v2 antes de deserializar un bundle.

## Priorizá señal útil sobre cantidad de pruebas

- Cubrí transformaciones puras, reglas de dominio, validadores, excepciones y transiciones con arreglos, frames, DataFrames y artefactos pequeños, deterministas y representativos.
- Para esquemas, rutas, checksums, versiones de contrato e idempotencia, verificá el comportamiento observable y los rechazos esperados. Todo bundle se valida con `vaaet.artifacts.validate_manifest()` antes de cargar binarios.
- Usá fixtures, `tmp_path`, fakes, inyección de dependencias y `monkeypatch` para relojes, descarga, Drive, motores, sesiones y proveedores de modelo. Un mock debe aislar un borde, no reimplementar la lógica bajo prueba.
- Parametrizá variantes de entrada cuando expresen la misma regla. Usá `pytest.approx` y tolerancias justificadas para cálculos de punto flotante; no afirmes probabilidades crudas exactas ni resultados dependientes de hardware.
- No establezcas un porcentaje universal de cobertura, tiempo de ejecución o umbral de deriva. Medilos sobre un baseline representativo cuando un cambio de riesgo lo justifique.

## Preservá contratos de visión, datos y MLOps

Las pruebas de visión son ligeras, deterministas y temporales: preservan orden por clip, historial de tracks, reinicios por transición de `VideoViewPlan`, descarte de minutos mixtos y agregación de telemetría. No requieren GPU, pesos YOLO, videos privados, modelos pesados ni una sesión de Colab.

Aplicá propiedades o invariancias sólo si derivan de un contrato medible del algoritmo. No asumas que una rotación, compresión, cambio de cámara o hardware debe producir el mismo resultado sin evidencia y calibración.

Para datos, entrenamiento y evaluación, preservá las 19 `FEATURE_COLS` en orden, la separación por clip, el input lock, snapshots inmutables y el holdout humano congelado. El MLP aprende sólo `Normal`, `Reduced` y `Congested`; `Accident` exige validación humana. Las autopredicciones no reemplazan etiquetas humanas, los sintéticos no ingresan a validation/test y un piloto weak-proxy no se promueve automáticamente.

Tratándose de cambios de entrenamiento, evaluá calidad, cobertura, procedencia, fuga y compatibilidad de contratos usando los validadores existentes. La detección de deriva, pruebas generativas o de propiedades amplias se propone sólo cuando exista una pregunta operativa, datos separados y un método explícito; no se convierte en una métrica decorativa.

## Probá PostgreSQL sin debilitar la seguridad

- En unitarios, sustituí engines, sesiones y errores externos mediante fakes o mocks acotados.
- Para migraciones, roles, grants, constraints, vistas y flujos idempotentes, usá la integración marcada `postgres` contra PostgreSQL 17 desechable de CI. Nunca apuntes a producción, una base compartida, credenciales personales o un entorno de Colab.
- Mantené Alembic y la identidad administrativa fuera de notebooks. Verificá perfiles de mínimo privilegio, TLS, `pipeline_run`, transacciones por lote, claves naturales y feedback HITL append-only cuando cambie la persistencia.
- No uses tests para ejecutar DDL ad-hoc, modificar remotos DVC, registrar secretos ni vaciar bases de datos fuera del entorno de integración gobernado.

`Testcontainers` es una alternativa futura, no un requisito: requiere Docker disponible, dependencia aprobada, estrategia de CI y una decisión explícita que mejore la cobertura respecto de la instancia PostgreSQL ya desechable.

## Mantené los notebooks verificables y acotados

Los cuatro notebooks siguen siendo orquestadores delgados. Conservá la auditoría estructural, el parseo AST de sus celdas y la evidencia manual de reinicio más `Run All` cuando haya inputs de Colab disponibles. No automatices como gate general entrenamientos, GPU, Drive, DVC remoto, descargas YOLO ni persistencia operativa.

Al cambiar un notebook o un flujo que importa, usá `$vaaet-notebook-orchestration`: mantené configuración explícita, semillas y procedencia; extraé lógica reusable al componente dueño; y evitá outputs masivos, binarios, trazas sensibles o estado oculto.

`nbmake`, Papermill y treon son propuestas futuras. Sólo consideralos para notebooks seleccionados, offline y no mutantes, con dependencia, presupuesto de CI, revisión de privacidad y autorización explícita.

## Prepará FastAPI sin adelantar la aplicación

No agregues FastAPI, endpoints, frontend, dependencias ni scaffolding en `vaaet-app/` hasta contar con alcance aprobado, contrato HTTP versionado y la vía de serving autorizada por ADR-0022. Una vez aprobados, el contrato debe definir entradas, salidas, errores y compatibilidad antes de implementar pruebas.

Para esa API futura:

- Usá pruebas de contrato y `TestClient` para requests válidos, validación de bordes, códigos de error y respuestas sin secretos; reemplazá dependencias externas por fakes controlados.
- Probá que el adaptador valide el manifiesto antes de deserializar y que no revele rutas, binarios, DVC, Drive, PostgreSQL ni detalles internos al cliente web.
- Añadí pruebas asíncronas sólo si el código realmente define límites asíncronos. No introduzcas `pytest-asyncio` por anticipación ni confundas concurrencia de request con paralelizar el pipeline de visión síncrono.

FastAPI, HTTPX, `pytest-asyncio`, Pydantic, Pandera, Hypothesis, Evidently y Deepchecks no son dependencias vigentes para esta skill. Cualquiera de ellas requiere autorización explícita, evaluación de seguridad y privacidad, impacto de CI, baseline de mantenimiento y ADR si altera arquitectura o contratos.

## Gates y entrega de evidencia

Ejecutá sólo los gates del componente afectado, conforme a sus `AGENTS.md` y al plan de pruebas: Ruff, Pyright, pytest y compilación por componente; auditor y AST de notebooks si aplica; enlaces Markdown y `git diff --check` desde la raíz. Las verificaciones manuales de Colab, GPU, Drive, DVC remoto, YOLO y PostgreSQL con Secrets no se sustituyen por mocks locales.

Al cerrar una prueba o revisión, informá el contrato cubierto, entradas representativas, bordes sustituidos, invariantes comprobados, tolerancias usadas, comandos ejecutados, evidencia manual pendiente y riesgo residual. Usá `$vaaet-python-ml-engineering`, `$vaaet-vision-kinematics`, `$vaaet-mlp-hitl-observability` y `$vaaet-postgres-mlops` cuando el cambio pertenezca a esos dominios.

## Rechazá estos antipatrones

- Pruebas unitarias que descargan pesos, requieren GPU, dependen de Drive o contactan servicios reales.
- Mocks completos del algoritmo, pruebas que inspeccionan internals sin contrato o aserciones exactas sobre resultados no deterministas.
- Ejecución automática de notebooks operacionales, entrenamiento o persistencia como una rutina de CI sin diseño y autorización.
- Bases de datos no desechables, credenciales en fixtures, migraciones desde notebooks, DDL ad-hoc o limpieza destructiva fuera del entorno gobernado.
- Introducir dependencias de QA, un umbral de cobertura o una métrica de deriva como política sin baseline, aprobación ni evidencia.
- Implementar o probar una API inexistente, exponer URL públicas o permitir que web acceda a artefactos, datos o infraestructura de ML.
