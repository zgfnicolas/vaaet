---
name: pg-integration
description: Replica localmente el job postgres-integration del CI con un PostgreSQL desechable de pgserver, para diagnosticar fallas de migraciones, SQL, backups o ingestión sin esperar el CI.
disable-model-invocation: true
argument-hint: "[setup|run|stop]"
---

# Integración PostgreSQL local

Acción pedida: $ARGUMENTS (sin argumento: `setup` y después `run`).

La skill descarga e instala `pgserver` (binarios de PostgreSQL) y `tzdata` en
un venv propio. Todo vive en `$VAAET_PG_HOME` (por defecto
`${TMPDIR:-/tmp}/vaaet-pg`) y escucha sólo en `localhost:$VAAET_PG_PORT` (por
defecto 55432). Nunca lo apuntes a una base real: `run` borra y recrea `vaaet`
y `vaaet_fresh`.

1. **setup**: desde la raíz, ejecutá
   `bash .claude/skills/pg-integration/scripts/setup_pg.sh`. En Windows pasá
   un Python 3.10–3.13: `VAAET_PG_PYTHON="py -3.11"`.
2. **run**: ejecutá `bash .claude/skills/pg-integration/scripts/run_ci_steps.sh`.
   Replica en orden los pasos del job de `.github/workflows/ci.yml`: base
   legacy, backups, migraciones `0003` y `head`, roles, tests, auditoría y base
   vacía.
3. **stop**: ejecutá
   `pg_ctl -D "${VAAET_PG_HOME:-${TMPDIR:-/tmp}/vaaet-pg}/data" -m fast stop`
   con el `pg_ctl` de `pgserver/pginstall/bin`. Liberá memoria al terminar.

Los dos scripts comprueban con `SHOW data_directory` que el servidor del
puerto sea el de `$VAAET_PG_HOME/data` y abortan si es otra instancia.

Para encontrar la fila que provoca una falla, consultá la base con `psql` o
envolvé la función sospechosa desde un runner de Python que llame a
`pytest.main()`, sin editar el código.

## Diferencias conocidas con el CI

- `pgserver` trae PostgreSQL 16 y el CI usa 17:
  `test_real_pg17_custom_backups_are_ingested_exactly` exige
  `pg_restore (PostgreSQL) 17` y falla localmente sólo por esa aserción.
- El venv no instala TensorFlow ni YOLO; si un test de integración los
  importa, la falla es del entorno y la confirma el CI.
- Un resultado local en verde no reemplaza el job del CI: reportalo como
  verificación local.
