# Plan de ejecución: alineación de la documentación

- Fecha de inicio: 2026-11-15
- Estado global: Completado
- Ticket, issue o PR vinculado: N/A

## 1. Contexto y restricciones

La documentación aplica parcialmente el principio «un tema, un lugar». Cada
ADR nuevo se narra en cinco archivos de contexto, conviven tres documentos de
requisitos, los roles se repiten en tres guías, 27 documentos de `docs/` no
tienen enlaces entrantes y la versión del laboratorio está escrita a mano en
unos quince documentos. El objetivo es que cada tema tenga un único documento
responsable y que el contexto para agentes apunte a esos documentos en lugar
de copiarlos.

Antes de editar, leer:

- Arquitectura y ADRs: `docs/architecture/software-architecture.md`,
  `docs/architecture/data-model.md` y `docs/architecture/decisions/`.
- Contrato o reglas de negocio: `docs/product/product-requirements.md` y
  `docs/ml/model-artifact-contract.md`.
- Módulos afectados: documentación, contexto para agentes,
  `.github/` y `vaaet-ml/tests/repository/test_repository_structure.py`.
- Invariantes y riesgos: no se cambian contratos, features, estados, schema,
  dependencias ni código de producción. El cuerpo de los ADRs aceptados no se
  reescribe. Los tests de repositorio se reapuntan al nuevo contrato
  documental sin eliminar verificaciones.

Decisiones humanas tomadas el 2026-11-15:

1. Eliminar `llms.txt` y `vaaet-ml/llms.txt`; `AGENTS.md` es la única fuente
   de contexto para agentes.
2. Unificar PRD, SRS y casos de uso en un único PRD.
3. Archivar los documentos comerciales e hipotéticos en `docs/archive/`;
   `project-plan.md` se reemplaza por `docs/roadmap.md`.

No requiere un ADR nuevo: no cambia arquitectura, contratos de datos ni
límites entre componentes. Los ADRs permanecen en
`docs/architecture/decisions/`.

**Directiva de integridad:** mantener KISS; no implementar lógica fuera de la
fase actual. Ejecutar una fase, mostrar evidencia y detenerse para solicitar el
ACK humano antes de iniciar la siguiente.

## 2. Versionado y trazabilidad

- Convención vigente: Conventional Commits en español rioplatense formal con
  scope `docs`, por ejemplo
  `docs(product): unificá los requisitos en un único PRD`.
- Commit o PR: proponerlo al cerrar cada fase; crear el commit únicamente con
  autorización explícita del responsable.

## 3. Fases de ejecución HITL

### [Completada] Fase 1: negocio

- [x] Reescribir el PRD con visión, problema, público, alcance, historias con
      criterios de aceptación, requisitos no funcionales, métricas y supuestos.
- [x] Absorber RF-001…RF-012, los RNF del SRS y CU-001…CU-006; eliminar
      `software-requirements.md` y `use-cases.md`.
- [x] Crear `docs/product/roles.md` y reemplazar las tablas repetidas por
      enlaces.
- [x] Crear `docs/product/business-rules.md` con reglas `RN-xx`, origen y
      aplicación.
- [x] Archivar canvas, personas, factibilidad, SOW y NDA en `docs/archive/`.
- [x] Reapuntar los tests de repositorio afectados.
- Review humano (ACK): Aprobado por el responsable técnico (2026-11-15)
- Commit propuesto: `git commit -m "docs(product): unificá requisitos, roles y reglas de negocio"`

### [Completada] Fase 2: técnico

- [x] Índice único y plantilla de ADRs; normalizar sólo la línea de estado.
- [x] Reordenar la arquitectura como arc42 reducida con contexto C4, conceptos
      transversales y riesgos vigentes; archivar la matriz de riesgos.
- [x] Completar el modelo de datos con políticas referenciales y datos
      sensibles; retirar los ERD duplicados.
- [x] Agregar un test que exige listar cada ADR en el índice.
- Hallazgo: `traffic_predictions` referencia `telemetry_features` con
  `ON DELETE CASCADE`. Se documentó como deuda técnica; cambiarlo requiere una
  revisión Alembic y queda fuera de este plan.
- Review humano (ACK): Aprobado por el responsable técnico (2026-11-15)
- Commit propuesto: `git commit -m "docs(architecture): ordená ADRs, arquitectura y modelo de datos"`

### [Completada] Fase 3: agentes

- [x] Reducir `AGENTS.md` a menos de 150 líneas y enlazar reglas e índice de
      ADRs.
- [x] Eliminar ambos `llms.txt` y sus referencias; crear `CLAUDE.md` y
      `.github/copilot-instructions.md` como punteros.
- [x] Quitar narraciones de ADRs y versiones de los `AGENTS.md` de componente;
      reorganizar `docs/index.md`.
- [x] Reapuntar los tests de contexto y exigir que ningún `AGENTS.md` cite
      `llms.txt` ni versiones fijas.
- Review humano (ACK): Aprobado por el responsable técnico (2026-11-15)
- Commit propuesto: `git commit -m "docs(agents): unificá el contexto para agentes en AGENTS.md"`

### [Completada] Fase 4: gestión

- [x] Mover el CHANGELOG a la raíz y unificar `CONTRIBUTING.md`.
- [x] Agregar template de PR y plantillas de issues.
- [x] Crear `docs/roadmap.md`, archivar `project-plan.md` y enlazar el PR de
      cada plan; archivar el único plan en estado *Completado*.
- [x] Quitar la versión obsoleta de `vaaet-ml/.env.example`.
- Desviación: el CHANGELOG no se suma al barrido de rutas obsoletas porque, como
  historia, cita rutas retiradas; un test nuevo verifica su ubicación.
- Review humano (ACK): Aprobado por el responsable técnico (2026-11-15)
- Commit propuesto: `git commit -m "docs: centralizá changelog, contribución, plantillas y roadmap"`

### [Completada] Fase 5: operación, limpieza y README

- [x] Redistribuir `deployment.md`: entornos, indicadores de salud, rollback y
      checklist en la guía de Colab; DRP en la guía PostgreSQL.
- [x] Quitar versiones de títulos, fechas de revisión y encabezados de contexto
      de los documentos vigentes; un test impide que vuelvan.
- [x] Reducir el README a lo esencial y pasar el checklist de la guía.
- [x] Completar `vaaet-ml/.env.example` con los tres timeouts que el código lee.
- Excepción: la mención «lector mínimo ML 4.9.3» de la guía de Colab se conserva
  porque es un valor contractual de los paquetes HITL, no un sello de versión.
- Review humano (ACK): Aprobado por el responsable técnico (2026-11-15)
- Commit propuesto: `git commit -m "docs: simplificá README y guías operativas"`

## 4. Criterios de aceptación

- [x] `pytest tests/repository` de `vaaet-ml`, Ruff y `git diff --check` pasan
      al cerrar cada fase.
- [x] Ningún enlace interno roto; todo documento vigente tiene un enlace
      entrante.
- [x] Los contratos, invariantes, permisos y secretos permanecen protegidos.
- [x] Cada tema tiene un único documento responsable.

### Checklist de la guía de documentación

| Eje | Resultado |
|---|---|
| Información del repo | README de dos oraciones, LICENSE y `.env.example` completo. Pendiente manual: probar el inicio rápido en una máquina limpia. |
| Negocio | PRD con alcance y fuera de alcance; cada historia con criterios; matriz de roles; cada regla con ID y origen. |
| Técnico | C4 de contexto y contenedores; ADRs de stack indexados; la única cascada del schema está documentada como deuda. El modelo de datos describe contratos y relaciones, no un diccionario columna por columna. |
| Gestión | CONTRIBUTING, template de PR y plantillas de issues, CHANGELOG con «Unreleased» y roadmap con la fase actual. |
| Agentes | `AGENTS.md` de 147 líneas, punteros de una línea, regla ante contradicciones, sin secretos y planes enlazados a su PR. |

## 5. Post-mortem y ajuste sistémico

- Desviación o bloqueo: un `sed` con rango `1,/-->/` borró un diagrama Mermaid
  porque buscó el cierre desde la línea 2; se restauró desde Git. Los scripts
  de Python escribieron CRLF en Windows; se normalizaron a LF.
- Causa y alcance: herramientas de edición masiva; ningún archivo quedó dañado.
- Ajuste reutilizable: en Windows, escribir con `newline="\n"` o bytes y revisar
  `git diff --stat` después de cada edición masiva.
- Decisión humana: ACK del plan completo (2026-11-15)
- Hallazgo fuera de alcance: la FK `telemetry_features` → `traffic_predictions`
  usa `ON DELETE CASCADE`; queda en el roadmap 5.0.0 para decisión.
