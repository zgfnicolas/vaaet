---
name: vaaet-python-ml-engineering
description: Build, review, refactor, or test professional Python for VAAET Data Science, computer vision, MLOps, and notebooks. Use for typed modular code, domain exceptions, logging, pytest, quality gates, notebook-to-module extraction, or maintainable model/data pipelines.
---

# Ingeniería Pythonica para VAAET

Construí Python profesional para VAAET 3.10–3.13: claro, tipado, comprobable y reproducible. Priorizá la corrección y el contrato de dominio por encima de acortar líneas o introducir abstracciones prematuras.

## 1. Decidí primero el límite y la forma del diseño

- Preservá el monorepo: la percepción portable, telemetría, contratos, validación del bundle e inferencia viven en `vaaet-core/src/vaaet/`; datasets, entrenamiento, evaluación, PostgreSQL y soporte de notebooks viven en `vaaet-ml/src/vaaet_ml/`. `vaaet-core` no depende de ML, DVC, Drive, PostgreSQL ni APIs de notebooks.
- Los notebooks sólo orquestan y visualizan. Importan `vaaet` para operaciones portables y `vaaet_ml` para laboratorio; no mutan `sys.path` ni duplican lógica reusable.
- Antes de cambiar un contrato, leé los ADRs aplicables. No cambies las 19 `FEATURE_COLS`, el MLP, umbrales, estados públicos, esquema PostgreSQL ni bundle v3 sin autorización y ADR.
- Aplicá KISS y YAGNI. Usá DRY cuando la duplicación represente un concepto estable, no para crear un framework de un único flujo.

Elegí funciones puras para transformaciones deterministas: reciben datos explícitos, devuelven resultados sin mutar entradas ni depender del entorno, y se prueban con facilidad. Usá objetos cuando exista estado legítimo o ciclo de vida: modelos cargados, sesiones, recursos externos, configuración validada o trackers. Representá valores de dominio estables con `@dataclass(frozen=True)` cuando corresponda.

Inyectá dependencias externas —engine de base, proveedor de modelos, reloj, raíz de archivos o cliente de descarga— en lugar de fijarlas como globales mutables. Preferí `Protocol` para dependencias sustituibles; incorporá un ABC sólo si hay comportamiento compartido o un ciclo de vida que realmente se deba imponer.

## 2. Tipá y validá en los bordes

- Anotá funciones públicas, atributos de clase, retornos y locales no obvios. Preferí `list[str]`, `dict[str, float]`, `Path`, `datetime`, `Literal`, `TypedDict`, `Protocol` y `Enum` cuando expresen el dominio.
- Validá en runtime forma, columnas, unidades, códigos de estado, checksums y versiones de contrato. El tipado estático no valida datos provenientes de video, CSV, PostgreSQL, Drive o un modelo.
- Mantené diccionarios de transporte o persistencia en el borde y convertílos pronto en objetos de dominio validados. Aislá `Any` en el adaptador mínimo de una librería sin tipos, validalo de inmediato y no lo propagues.
- Usá los validadores y dataclasses existentes. Pydantic, MyPy, nuevos stubs o cambios de alcance de Pyright son propuestas: requieren autorización, dependencias si aplican y una adopción incremental separada.

## 3. Escribí Pythonic con criterio

La concisión sirve cuando conserva la lectura del dominio; no es un objetivo en sí mismo.

- Usá guard clauses para rechazar temprano entradas inválidas o estados imposibles. Mantené las reglas de dominio que dependen de orden, prioridad o recuperación en bloques explícitos.
- Usá comprensiones de listas, diccionarios o conjuntos para transformaciones pequeñas, puras y legibles. Elegí un bucle con nombre ante efectos laterales, validación, manejo de errores, anidamiento no trivial o intermediarios significativos.
- Preferí generadores cuando el consumo sea incremental y evitar materializar la colección sea útil. No los uses si se necesita recorrer la misma secuencia varias veces o si ocultan el punto donde puede fallar el cálculo.
- Usá `with` para archivos, sesiones, recursos temporales y todo recurso con ciclo de vida. No dependas de cierres manuales que pueden omitirse ante un error.
- Usá `mapping.get(clave, predeterminado)` sólo si la ausencia es esperable y el predeterminado es válido. Accedé directamente y validá cuando una clave faltante indique un contrato malformado.
- Reservá el ternario para una asignación corta y evidente. Preferí `if` para efectos laterales, condiciones compuestas o varias ramas.
- Usá `match`/`case` para dispatch estructural estable en Python 3.10+, como variantes ya validadas. No escondas reglas de negocio ordenadas, umbrales o recuperación de errores en coincidencias amplias.
- Preferí `enumerate()` a contadores manuales, `zip()` a índices paralelos y desempaquetado cuando la forma sea explícita. Usá `zip(..., strict=True)` si longitudes iguales son un invariante; de otro modo definí y validá la semántica de truncamiento.
- Usá f-strings para texto local y presentación. Conservá logging parametrizado, por ejemplo `logger.info("stage=%s", stage)`, para no formatear mensajes descartados y respetar la convención del proyecto.

## 4. Hacé visible el comportamiento y protegé los recursos

- Dejá que datos adquiera, valide y persista; visión procese frames; features produzca las variables canónicas; inferencia clasifique; y entrenamiento/evaluación gestione ciclo de vida y calidad.
- Una función debe tener una responsabilidad entendible. Ramificación profunda, múltiples efectos y rutas de error confusas son señales para revisar el diseño. Complejidad alta o archivos extensos son señales de revisión, no límites mecánicos que obliguen a fragmentar módulos correctos.
- Usá `vaaet.logging` en código reusable: `INFO` para ciclo de vida, `WARNING` para degradación recuperable, `ERROR` para fallos y `DEBUG` para diagnósticos acotados. No registres secretos, DSNs, certificados, credenciales, rutas privadas ni excepciones sin redactar. JSON logging es una mejora futura, no una dependencia ni configuración implícita.
- Elevá la excepción más específica de `vaaet.exceptions` o `vaaet_ml.exceptions`, o agregá un subtipo documentado si cambia la recuperación posible. Encadená excepciones esperables con contexto seguro y detené pipelines corruptos antes de persistir o publicar artefactos.
- Delegá SQL parametrizado a la capa existente: nunca interpolés valores o identificadores no controlados en sentencias SQL. Recibí `Path` o valores de ruta en un borde validado, resolvelos contra una raíz permitida y rechazá escapes de esa raíz. No expongas esos valores en logs.

## 5. Concurrencia sólo con evidencia

No deduzcas una implementación por el tipo de tarea. Medí CPU, I/O, memoria, tamaño de lotes, FPS y orden lógico primero: extensiones nativas pueden liberar el GIL, una operación de I/O puede no justificar `asyncio`, y CPU alta no implica automáticamente `ProcessPoolExecutor`.

`vaaet.vision.analyze_video()` conserva su flujo ordenado y síncrono: SORT, flujo óptico, suavizado, estado estacionario y telemetría por minuto no se paralelizan ni externalizan. No agregues hilos, procesos, colas o workers para el pipeline de visión sin profiling, alcance aprobado y la guía `vaaet-resilient-async-architecture`. Cualquier API o worker futuro en `vaaet-app/` exige contrato HTTP versionado y respeta los límites de serving vigentes.

## Probá contratos, no infraestructura pesada

Al cambiar comportamiento, actualizá pruebas junto al código:

- Probá transformaciones puras, validaciones, excepciones y transiciones con arrays, frames y DataFrames pequeños y deterministas.
- Usá fixtures, fakes, inyección o mocks para PostgreSQL, Drive, descargas, relojes y modelos. Las pruebas unitarias no requieren pesos YOLO, GPU, credenciales ni una base en vivo.
- Agregá pruebas de contrato o integración para esquemas, manifiestos, idempotencia, checksums y paridad de notebooks cuando cambien esos bordes. Afirmá comportamiento observable e invariantes, no detalles internos.
- Mantené semillas explícitas. Un objetivo de 90% de cobertura en módulos core nuevos o modificados materialmente no es una afirmación sobre la cobertura actual; baselining, plugins de cobertura o CI requieren autorización.

## Gates y definición de terminado

Ejecutá los controles del componente que cambió:

1. En `vaaet-core/`: `ruff check src tests`, `pyright --project ../pyrightconfig.json`, `pytest tests -v --tb=short` y `python -m compileall -q src tests`.
2. En `vaaet-ml/`: `ruff check src tests scripts`, `pyright --project ../pyrightconfig.json`, `pytest tests -v --tb=short` y `python -m compileall -q src tests scripts`.
3. Parseá las celdas de código de los cuatro notebooks en `vaaet-ml/notebooks/` si cambian notebooks o el flujo que importan.
4. Verificá enlaces Markdown y ejecutá `git diff --check` desde la raíz.

Pyright es el gate estático vigente. No agregues MyPy, Pydantic, stubs, hooks, dependencias, configuración de tipado, plugins de cobertura ni gates de CI sin autorización explícita y un baseline incremental. Para notebooks nuevos, mantené la orquestación ejecutable mínima —preferentemente menos de 50 líneas por celda operativa— y llamá módulos probados; extraé lógica existente de forma incremental.

## Rechazá estos antipatrones

- Funciones monolíticas de notebooks que duplican `vaaet-core/src/vaaet/` o `vaaet-ml/src/vaaet_ml/`.
- `except Exception: pass`, continuar luego de corrupción de datos o usar `print` como único contrato entre módulos.
- `Any` generalizado, datos de borde sin validar, secretos hardcodeados o rutas dependientes del entorno.
- SQL interpolado, rutas sin validación de frontera, binarios `.pt`, `.keras` o `.joblib` en Git, y abstracciones distribuidas sin necesidad medida.
- Clases sin estado que sólo ocultan funciones, o una regla de concisión que vuelva opaco al dominio.

## Resultado de una revisión

Al revisar o cambiar código, informá el límite de responsabilidad, contrato tipado de entrada y salida, validación y excepción, impacto en logging o linaje, pruebas ejecutadas o necesarias, evidencia de rendimiento si aplica y riesgo pendiente. Preferí un parche pequeño y enfocado antes que una reescritura arquitectónica.
