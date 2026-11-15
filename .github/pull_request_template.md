## Qué cambia

Descripción breve y motivo.

Plan gobernado o issue: N/A

## Tipo de cambio

- [ ] Nueva funcionalidad (`feat`)
- [ ] Corrección (`fix`)
- [ ] Refactor sin cambio de comportamiento (`refactor`)
- [ ] Documentación (`docs`)
- [ ] Pruebas, CI o mantenimiento (`test`, `chore`)

## Componentes afectados

- [ ] `vaaet-core`
- [ ] `vaaet-persistence`
- [ ] `vaaet-ml`
- [ ] Raíz (documentación, CI o configuración)

## Checklist

- [ ] Ruff, Pyright, pytest y `compileall` pasan en los componentes afectados.
- [ ] Agregué pruebas para la lógica nueva.
- [ ] No cambian las 19 features, los estados, el MLP, el bundle ni el schema; si cambian, hay plan, ADR y aprobación.
- [ ] Actualicé la sección «Unreleased» del `CHANGELOG.md` si cambia un comportamiento observable.
- [ ] Actualicé `docs/` si cambia una regla, un rol, un contrato o la arquitectura.
- [ ] No hay secretos, `.env`, videos, datos privados, calibraciones reales ni binarios ML.

## Validación manual pendiente

GPU, Drive, DVC remoto, YOLO o PostgreSQL real que quedan por validar en Colab, o N/A.

## Cómo probarlo

Pasos para verificar el cambio.
