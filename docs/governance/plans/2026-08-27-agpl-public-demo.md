# Plan de ejecución: vía AGPL-3.0 para demo pública temporal

- Fecha de inicio: 2026-08-27
- Estado global: Preparación AGPL completada; fase 4 espera alcance de aplicación
- Ticket, issue o PR vinculado: [#4](https://github.com/zgfnicolas/vaaet/pull/4)

## 1. Contexto y restricciones

Antes de editar, leer ADR-0021, ADR-0022, `AGENTS.md`, el registro de licencias
de terceros y las guías oficiales de [Ultralytics](https://docs.ultralytics.com/help/contributing/).
El responsable confirmó que puede relicenciar las contribuciones del historial.

La vía elegida es AGPL-3.0 para un monorepo público y una demo académica
temporal. No se crea API, frontend, framework, infraestructura AWS, DVC remoto,
datos, pesos ni bundles nuevos. Los videos SISE, datos HITL, credenciales y
activos sin permiso de redistribución permanecen fuera de Git.

**Directiva de integridad:** ejecutar una fase, registrar evidencia y esperar
el ACK humano antes de iniciar la siguiente.

## 2. Versionado y trazabilidad

- Convención: Conventional Commits en español argentino rioplatense formal.
- Versiones de `vaaet-core` y `vaaet-ml`: sin cambio hasta una release
  coordinada; el cambio de licencia se registra en `Unreleased`.
- Commit o PR: sólo con autorización explícita del responsable.

## 3. Inventario de referencias a sustituir

| Fuente activa | Estado actual | Acción de fase 2 |
| --- | --- | --- |
| `LICENSE` y los dos `pyproject.toml` | MIT | Adoptar `AGPL-3.0-only`. |
| `AGENTS.md`, `vaaet-app/README.md`, `vaaet-core/README.md` | Enterprise obligatorio | Declarar las dos vías y el checklist AGPL. |
| `docs/governance/third-party-licenses.md` | Gate Enterprise exclusivo | Registrar AGPL pública y Enterprise privada/comercial. |
| `docs/product/feasibility.md` | MIT y compatibilidad automática | Corregir la evaluación legal y de activos. |
| `docs/operations/deployment.md` y documentación de despliegue | Sin runbook AGPL/AWS | Añadir preparación, límites y limpieza de demo. |

Los planes y ADRs históricos no se reescriben salvo para añadir una referencia
de actualización cuando resulte necesaria para evitar una contradicción activa.

## 4. Fases de ejecución HITL

### [Completada] Fase 1: decisión e inventario

- [x] Registrar ADR-0022 como propuesta de la vía AGPL-3.0.
- [x] Crear este plan gobernado e inventariar fuentes activas MIT/Enterprise.
- [x] Confirmar autorización del responsable para relicenciar contribuciones.
- [x] Verificar enlaces de los documentos nuevos y `git diff --check`.
- Review humano (ACK): Aprobado por solicitud de 2026-08-27.
- Commit propuesto: `docs(architecture): proponé la vía AGPL para la demo pública`

### [Completada] Fase 2: relicencia y consistencia documental

- [x] Sustituir la licencia raíz y los metadatos de paquetes por AGPL-3.0-only.
- [x] Actualizar documentación operativa y avisos SPDX de fuentes propias.
- [x] Reemplazar el gate Enterprise exclusivo por las dos vías autorizadas.
- [x] Añadir pruebas de consistencia de licencia, metadatos y documentación.
- Evidencia: Ruff, compileall, JSON de cuatro notebooks, enlaces Markdown y
      `git diff --check` correctos; 67 pruebas de licencia, estructura,
      notebooks y aislamiento core aprobadas.
- Review humano (ACK): Aprobado por solicitud de 2026-08-27.

### [Completada] Fase 3: checklist de activos y runbook AWS

- [x] Incorporar checklist por demo para código, dependencias, modelos, bundles,
      datos, secretos, retención, borrado y limpieza de recursos.
- [x] Documentar que la vía AGPL no implica costo de Ultralytics, pero no
      garantiza costo cero de AWS.
- [x] Validar enlaces, pruebas de repositorio y gates de calidad aplicables.
- Evidencia: Ruff y compileall correctos; 68 pruebas de licencia, estructura,
      notebooks y aislamiento core aprobadas; enlaces Markdown y
      `git diff --check` correctos.
- Review humano (ACK): Aprobado por solicitud de 2026-08-27.

### [Pendiente] Fase 4: implementación y demo futura

- [ ] Aprobar un contrato HTTP versionado antes de crear API o frontend.
- [ ] Ejecutar el checklist AGPL con el commit/tag público y activos aprobados.
- [ ] Validar manifest-first, enlace de fuente, AWS temporal y limpieza manual.
- Prerrequisito: alcance aprobado de API/web, contrato HTTP versionado, activos
      con procedencia/redistribución verificada y acceso AWS del responsable.
- Review humano (ACK): Pendiente de la futura implementación.

## 5. Criterios de aceptación

- [ ] La documentación activa no presenta Enterprise como única vía para una
      demo pública AGPL.
- [ ] La raíz y las distribuciones declaran la licencia AGPL-3.0-only de forma
      coherente, sin cambiar contratos ni versiones.
- [ ] Cada demo futura tiene código fuente público reproducible y un inventario
      de activos redistribuibles; no expone secretos, videos ni datos privados.
- [ ] La arquitectura de ADR-0021 y los gates actuales de calidad se preservan.

## 6. Post-mortem y ajuste sistémico

- Desviación o bloqueo: la política Enterprise exclusiva no contemplaba la
  alternativa AGPL oficial para una demostración académica pública.
- Causa y alcance: el hardening anterior priorizó un serving privado/comercial
  antes de definir el alcance de la demo.
- Ajuste reutilizable: separar siempre el gate de licencia del modelo de
  visibilidad y registrar las vías permitidas antes de crear infraestructura.
- Decisión humana: fases 1 a 3 aprobadas; fase 4 queda pendiente de una futura
  implementación de aplicación.
