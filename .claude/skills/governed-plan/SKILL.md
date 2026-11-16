---
name: governed-plan
description: Crea un plan gobernado de VAAET en docs/governance/plans/ desde la plantilla única. Usala cuando un cambio toque arquitectura, contratos, seguridad, datos persistidos, dependencias, permisos o remotos, o cuando se pida un plan por fases con revisión humana.
argument-hint: "[nombre de la tarea]"
---

# Plan gobernado

Tarea: $ARGUMENTS

1. Confirmá que el cambio supera el umbral de riesgo de `AGENTS.md`
   («Trabajo con planes»). Si es un cambio acotado sin efecto en contratos,
   seguridad o datos, decilo y no crees un plan.
2. Copiá `docs/governance/plans/TEMPLATE.md` a
   `docs/governance/plans/AAAA-MM-DD-<slug>.md` con la fecha de hoy y un slug
   en inglés con guiones.
3. Completá cada marcador con rutas reales:
   - el ADR del [índice](../../../docs/architecture/decisions/README.md);
   - las reglas `RN-xx` de `docs/product/business-rules.md`;
   - los módulos afectados.

   Dividí el trabajo en fases chicas, cada una con un criterio de aceptación
   verificable. Marcá sólo la primera como `[Actual]`.
4. Registrá en el plan las decisiones que tomó la persona, con fecha. No
   incluyas secretos, rutas privadas ni datos personales.
5. Mostrá el plan y esperá la aprobación antes de ejecutar la primera fase.
6. Al cerrar cada fase:
   - marcá las tareas cumplidas;
   - registrá el ACK humano y el commit propuesto;
   - pasá la siguiente fase a `[Actual]`.

   Al terminar todo el plan, poné el estado global en `Completado` y enlazá el
   PR. El hook de inicio de sesión lista los planes que siguen «En progreso».
