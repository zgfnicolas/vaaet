# Plan de ejecución: corrección del literal de la migración `0003`

- Fecha de inicio: 2026-11-15
- Estado global: En progreso
- Ticket, issue o PR vinculado: N/A

## 1. Contexto y restricciones

`postgres-integration` falla en CI desde el 2026-09-06 con *A value is required
for bind parameter 'legacy'*. La causa es el literal `':legacy-'` de la
revisión `20260905_0003`: `text()` lo interpreta como parámetro con cualquier
SQLAlchemy 2.x. Se verificó con 2.0.54 y 2.1.8, así que fijar la versión no
corrige el problema. La decisión está en
[ADR-0037](../../architecture/decisions/0037-migration-0003-bind-literal-correction.md).

- Módulos afectados: `vaaet-persistence/src/vaaet_persistence/migrations/versions/20260905_0003_temporal_continuity_model_revision.py`
  y las pruebas unitarias de `vaaet-persistence`.
- Invariantes: no cambian el schema, los datos esperados, la identidad de la
  revisión ni ninguna otra revisión. El responsable técnico confirmó que
  ninguna base real pasó de `0002`, así que no hay datos que reparar.

**Directiva de integridad:** ejecutar la fase, mostrar evidencia y esperar el
ACK humano antes de integrar.

## 2. Versionado y trazabilidad

- Commit propuesto: `fix(persistence): escapá el literal legacy de la migración 0003`.

## 3. Fases de ejecución HITL

### [Actual] Fase 1: corrección y regresión

- [x] Reproducir el error sin base de datos y confirmar que no depende de la
      versión de SQLAlchemy.
- [x] Escapar `':legacy-'` como `'\:legacy-'` en `0003` y actualizar su hash.
- [x] Agregar un test que compila el SQL de cada revisión, rechaza parámetros
      sin valor y la conversión offline a `'NULL-'`.
- [x] Registrar ADR-0037 y actualizar RN-21, la guía y el modelo de datos.
- [x] La cadena `0001`→`0006` se aplica en CI sobre PostgreSQL 17 desde la base
      legacy.
- [x] Corregir la segunda falla que apareció detrás de `0003`: el test de
      integración no se podía importar porque `vaaet.inference` cargaba `cv2`
      con sólo el extra `inference`. `TrafficStatePrediction` pasa a
      `vaaet.contracts`, con reexport desde `vaaet.vision`, y un test del core
      lo protege.
- [ ] `postgres-integration` en verde sobre PostgreSQL 17 en CI.
- Review humano (ACK): Aprobado el enfoque por el responsable técnico (2026-11-15); integración pendiente
- Commit propuesto: `git commit -m "fix(persistence): escapá el literal legacy de la migración 0003"`

## 4. Criterios de aceptación

- [ ] La cadena Alembic completa se aplica en CI desde una base legacy y desde
      una base vacía.
- [x] `test_migration_sql.py` falla contra la `0003` original y pasa con la
      corrección.
- [x] Las revisiones `0001`, `0002`, `0004`, `0005` y `0006` no cambian.

## 5. Post-mortem y ajuste sistémico

- Desviación o bloqueo: el primer diagnóstico atribuyó la falla a SQLAlchemy
  2.1; una prueba con 2.0.54 lo descartó.
- Causa y alcance: el job fallaba desde el 2026-09-06 sin bloquear integraciones.
- Ajuste reutilizable: el SQL de las migraciones se valida en pruebas unitarias
  sin depender del job de PostgreSQL.
- Decisión humana: Pendiente
