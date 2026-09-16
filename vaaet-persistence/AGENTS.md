# AGENTS.md — VAAET Persistence

Este componente es la única autoridad de acceso PostgreSQL y migraciones de
VAAET. Puede depender del core base, pero nunca de `vaaet_ml`, TensorFlow, YOLO,
DVC, Google Drive, Colab ni la futura aplicación.

## Invariantes

- Exigí un `DatabaseProfile` explícito y una identidad de aplicación provista
  por el consumidor.
- Construí URLs con `sqlalchemy.URL.create()` y redactá parámetros, secretos y
  certificados en logs y excepciones.
- No reintentes escrituras. Los reintentos automáticos se limitan al health
  check.
- Respetá la propiedad del engine: una operación no dispone un engine recibido.
- Usá nombres SQL completamente cualificados y transacciones para escrituras
  relacionadas.
- Conservá valores continuos como `DOUBLE PRECISION`, conteos como enteros y la
  procedencia `numeric_representation`; no reconstruyas precisión histórica.
- Resolvé feedback por la única cadena terminal válida y aislá conflictos
  históricos del ground truth.
- Conservá la idempotencia de decisiones, los aliases portables verificables y
  la recuperación local definida por
  [`ADR-0030`](../docs/architecture/decisions/0030-operational-idempotency-and-portable-hitl-coherence.md).
- Traducí todos los fallos externos mediante errores de dominio y el SQLSTATE
  validado conforme a
  [`ADR-0031`](../docs/architecture/decisions/0031-hitl-integrity-and-coordinated-catalog-publication.md).
- Seleccioná telemetría `CURRENT` o `LEGACY` sin fallback por excepción y
  reconciliá auditorías sólo después de verificar contenido, conforme a
  [`ADR-0032`](../docs/architecture/decisions/0032-complete-cycle-integrity.md).
- Alembic es la única autoridad DDL. No ejecutes migraciones desde notebooks.
- No modifiques revisiones publicadas; agregá una nueva revisión cuando cambie
  el schema.

## Validación

Ejecutá desde este directorio:

```bash
ruff check src tests
pyright src
pytest
python -m compileall -q src
```

Las pruebas marcadas `postgres` requieren una instancia PostgreSQL 17
desechable y credenciales administrativas efímeras.
