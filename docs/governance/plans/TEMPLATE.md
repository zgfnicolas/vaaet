# Plan de ejecución: <nombre de la tarea o feature>

- Fecha de inicio: YYYY-MM-DD
- Estado global: Propuesto / En progreso / Completado / Bloqueado
- Ticket, issue o PR vinculado: <identificador público o N/A>

## 1. Contexto y restricciones

Antes de editar código, leer:

- Arquitectura y ADRs: `<rutas reales en docs/architecture/>`
- Contrato o reglas de negocio: `<rutas reales en docs/ml/, product/ o data>`
- Módulos afectados: `<rutas de código, notebooks o migraciones>`
- Invariantes y riesgos: `<contratos, permisos, datos, rollback o recuperación>`

**Directiva de integridad:** mantener KISS; no implementar lógica fuera de la
fase actual. Ejecutar una fase, mostrar evidencia y detenerse para solicitar el
ACK humano antes de iniciar la siguiente.

## 2. Versionado y trazabilidad

- Convención vigente: Conventional Commits en español argentino rioplatense
  formal, por ejemplo `feat(vision): incorporá persistencia ordenada de
  telemetría`.
- Ticket o issue: prefijarlo o referenciarlo sólo cuando exista una política de
  proyecto que lo requiera.
- Gitmoji: no usarlo como requisito hasta que una decisión del repositorio lo
  adopte explícitamente.
- Commit o PR: proponerlo al cerrar una fase; crear el commit únicamente con
  autorización explícita del responsable.

## 3. Fases de ejecución HITL

**Instrucción para IA:** ejecutar sólo la fase marcada como `Actual`. Al
concluir, reportar los archivos modificados, las validaciones, los riesgos
restantes y el comando de commit sugerido; esperar el ACK humano.

### [Completada] Fase 1: <nombre>

- [x] <resultado verificable>
- Review humano (ACK): Aprobado por <rol o identificador>
- Evidencia y commit/PR: <referencia pública>

### [Actual] Fase 2: <nombre>

- [ ] <tarea acotada>
- [ ] <test, migración o validación requerida>
- Review humano (ACK): Pendiente
- Commit propuesto: `git commit -m "<type>(<scope>): <verbo en voseo formal + resultado>"`

### [Pendiente] Fase 3: <nombre>

- [ ] <tarea posterior>
- Review humano (ACK): Pendiente

## 4. Criterios de aceptación

- [ ] Las validaciones requeridas por la fase y `AGENTS.md` pasan.
- [ ] Los contratos, invariantes, permisos y secretos permanecen protegidos.
- [ ] La documentación canónica afectada se actualizó, si corresponde.
- [ ] El commit o PR propuesto sigue la convención vigente y tiene revisión
      humana cuando el cambio es gobernado.

## 5. Post-mortem y ajuste sistémico

- Desviación o bloqueo: <hecho verificable o N/A>
- Causa y alcance: <resumen>
- Ajuste reutilizable: <cambio propuesto a una regla, skill, ADR o proceso>
- Decisión humana: <ACK, NACK, pendiente o N/A>
