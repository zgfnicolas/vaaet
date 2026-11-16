---
paths:
  - "vaaet-persistence/**"
---

# PostgreSQL y migraciones

- Un cambio de schema es siempre una revisión Alembic nueva. Las publicadas no
  se editan (RN-21); el hook `guard_paths.py` lo bloquea. La única excepción
  registrada es ADR-0037.
- En SQL pasado a `op.execute()` o `text()`, un `:nombre` dentro de un literal
  se lee como parámetro: escribilo `\:nombre`. `test_migration_sql.py` lo
  verifica para cada revisión.
- `has_table_privilege` con un nombre textual falla si el rol no tiene `USAGE`
  sobre el schema; para chequear privilegios, resolvé la tabla por OID.
- Para la integración real, usá la skill `pg-integration`.
