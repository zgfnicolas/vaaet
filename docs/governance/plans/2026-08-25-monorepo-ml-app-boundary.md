# Plan de ejecución: monorepo ML y frontera de aplicación

- Fecha de inicio: 2026-08-25
- Estado global: Validación local completada; evidencia manual de Colab pendiente
- Ticket, issue o PR vinculado: [#1](https://github.com/zgfnicolas/vaaet/pull/1)

## 1. Contexto y restricciones

Antes de editar código, leer ADR-0012 a ADR-0019, ADR-0020, el contrato del
bundle v2, `AGENTS.md` y las guías operacionales de Colab. La migración conserva
las 19 features, los estados, el MLP, PostgreSQL, DVC, Drive y los artefactos
inmutables. No incorpora API, frontend, framework ni dependencias.

**Directiva de integridad:** cada fase requiere evidencia y ACK humano antes de
iniciar la siguiente. Los cambios estructurales se realizan con `git mv` y no
se mezclan con cambios de comportamiento ML.

## 2. Versionado y trazabilidad

- Convención: Conventional Commits en español argentino rioplatense formal.
- Versión del paquete: sin cambio; el traslado se registra en `Unreleased`.
- Commit o PR: sólo con autorización explícita del responsable.

## 3. Fases de ejecución HITL

### [Completada] Fase 1: gobierno y frontera reservada

- [x] Registrar ADR-0020 y sus invariantes.
- [x] Reservar `vaaet-app/` sin código de aplicación.
- [x] Verificar enlaces Markdown y `git diff --check`.
- Review humano (ACK): solicitud de implementación de 2026-08-25.
- Commit propuesto: `docs(architecture): incorporá decisión de monorepo VAAET`

### [Completada] Fase 2: traslado mecánico de ML

- [x] Reubicar con `git mv` el paquete, notebooks, tests, migraciones, scripts,
      datos, artefactos y configuración ML bajo `vaaet-ml/`.
- [x] Adaptar empaquetado, CI, DVC, Alembic, documentación y pruebas de rutas.
- [x] Verificar wheel local, compileall, enlaces y auditoría estructural.
- Review humano (ACK): autorizado por solicitud de 2026-08-25.

### [Completada] Fase 3: orquestación y operaciones Colab

- [x] Extraer bootstrap, diagnóstico y configuraciones tipadas al core y al laboratorio.
- [x] Reducir las celdas de notebooks y comprobar `Run All` seguro.
- Evidencia: auditor de cuatro notebooks sin errores ni celdas largas; compileall y
      enlaces Markdown correctos. Ruff y pytest siguen pendientes del entorno `.venv`
      con el extra `dev`.
- Review humano (ACK): autorizado por solicitud de 2026-08-25.

### [Parcial] Fase 4: validación integral

- [x] Ejecutar gates locales y registrar limitaciones del runtime.
  - Python 3.12.13 en `.venv`; `pip check`, Ruff, compileall, AST, auditor de
    notebooks, enlaces Markdown y `git diff --check`: correctos.
  - Pytest: **461 aprobados, 11 omitidos, 1 advertencia** (`seed` legacy v1
    deprecado); las omisiones corresponden a integración PostgreSQL y TensorFlow
    opcional en este host Windows sin GPU.
  - Wheel no editable `vaaet-ml==4.5.3`: construido e importado desde una
    venv limpia; conserva `vaaet` y la versión 4.5.3.
  - Se detectó y corrigió una regresión de notebook: la carga de bundle vuelve
    a validar el manifiesto antes de deserializar mediante
    `vaaet.inference.bundle.load_traffic_bundle()`.
- [ ] Completar validación manual en Colab para GPU, Drive, DVC, YOLO y PostgreSQL.

| Comprobación manual | Evidencia requerida |
| --- | --- |
| GPU/preflight | Colección, entrenamiento e inferencia fallan temprano sin GPU y muestran framework, `nvidia-smi`, RAM, disco y commit; evaluación sigue read-only sin GPU. |
| Drive | Bundle, seed, HITL, holdout e input lock usan sus raíces canónicas, checksum y `pending-sync` sin fallback efímero. |
| DVC remoto | Desde la raíz: `dvc status`, `dvc pull` y un `dvc push` controlado preservan `vaaet-ml/artifacts/traffic-state/`. |
| YOLO | Descarga autorizada y análisis de un clip corto generan video anotado y telemetría sin desbordar RAM. |
| PostgreSQL | Secrets por perfil, TLS, Alembic/grants y persistencia opt-in; entrenamiento permanece read-only. |

- Limitación local: el CLI DVC no está instalado en la venv de validación y no
  existen credenciales, GPU, Drive ni PostgreSQL en este host; esas pruebas no
  se simulan ni se dan por aprobadas.
- Review humano (ACK): autorizado por solicitud de 2026-08-26; cierre final
  pendiente de la evidencia manual anterior.

## 4. Criterios de aceptación

- [x] Un único Git, DVC y superficie CI permanecen en la raíz.
- [x] `vaaet-ml` instala y conserva sus contratos y pruebas.
- [x] La futura aplicación queda aislada por API y validación de manifiesto.
- [x] No se versionan binarios ML; el escaneo sólo encontró placeholders en
      `.env.example` y un fixture de pruebas, no secretos operativos.

## 5. Post-mortem y ajuste sistémico

- Desviación o bloqueo: N/A.
- Causa y alcance: N/A.
- Ajuste reutilizable: ADR-0020 establece la frontera única para futuras fases.
- Decisión humana: fases 1 a 4 autorizadas; el cierre requiere evidencia
  manual de Colab y sus integraciones externas.
