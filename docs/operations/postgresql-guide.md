# Operación PostgreSQL portable — VAAET ML 4.6.1

PostgreSQL es opcional y pertenece exclusivamente a `vaaet-ml`. VAAET admite
AWS RDS, Supabase, Neon o un servidor propio sólo si exponen las capacidades
PostgreSQL descritas en [ADR-0024](../architecture/decisions/0024-provider-neutral-postgresql-and-schema-as-code.md).
El nombre comercial no sustituye el preflight técnico.

## Modelo de configuración

El endpoint, TLS y límites de conexión son comunes; cada workflow recibe una
credencial distinta. No guardes estas variables, certificados ni archivos
`.env` con secretos en Git.

| Propósito | Variables canónicas |
| --- | --- |
| Endpoint compartido | `VAAET_DB_HOST`, `VAAET_DB_PORT`, `VAAET_DB_NAME`, `VAAET_DB_SSLMODE`, `VAAET_DB_SSLROOTCERT` o `VAAET_DB_SSLROOTCERT_PEM`, `VAAET_DB_CONNECT_TIMEOUT` |
| Pool de laboratorio | `VAAET_DB_POOL_SIZE`, `VAAET_DB_MAX_OVERFLOW`, `VAAET_DB_POOL_RECYCLE_SECONDS` |
| Reintentos de health check | `VAAET_DB_RETRY_ATTEMPTS`, `VAAET_DB_RETRY_BASE_DELAY_SECONDS` |
| Workflow | `VAAET_COLLECTION_DB_*`, `VAAET_INFERENCE_DB_*`, `VAAET_TRAINING_DB_*` o `VAAET_REVIEW_DB_*` con sufijos `USER` y `PASSWORD` |
| Administración local/CI | `VAAET_ADMIN_DB_USER`, `VAAET_ADMIN_DB_PASSWORD` |

Los límites predeterminados son `pool_size=2`, `max_overflow=0` y reciclado a
300 segundos. El health check usa tres intentos con espera exponencial desde
0,5 segundos; sólo modificá esos límites tras medir conexiones, latencia y
límites del proveedor. El runtime usa `verify-full` y CA en endpoints remotos.
`require` cifra sin validar identidad; `disable` se permite exclusivamente para
`localhost` en pruebas.

La URL heredada `VAAET_DATABASE_ADMIN_URL` es compatible durante VAAET 4.x,
pero emite advertencia y se elimina en 5.0. No la uses en configuración nueva.

## Provisionamiento y migraciones

Ejecutá estos pasos desde una máquina administrativa o CI, nunca desde Colab o
un notebook. Instalá ambos componentes y los extras necesarios:

```bash
python -m pip install -e "./vaaet-core[inference]"
python -m pip install -e "./vaaet-ml[database,dev]"
```

Configurá el endpoint y una CA local antes de migrar. Este ejemplo omite los
valores reales deliberadamente:

```bash
export VAAET_DB_HOST="postgres.example"
export VAAET_DB_PORT="5432"
export VAAET_DB_NAME="vaaet"
export VAAET_DB_SSLMODE="verify-full"
export VAAET_DB_SSLROOTCERT="/ruta/privada/proveedor-ca.pem"
export VAAET_ADMIN_DB_USER="vaaet_admin"
export VAAET_ADMIN_DB_PASSWORD="<secreto-fuera-de-git>"

cd vaaet-ml
alembic upgrade head
```

Alembic usa `DatabaseAdminSettings`, URL estructurada, TLS y `NullPool`; las
revisiones explícitas son la única autoridad DDL. No uses modelos ORM para crear
tablas, `create_all`, `drop_all` ni autogeneración.

La revisión `20260905_0003` migra a `vaaet-db-v3`: agrega continuidad e
identidad exacta del modelo, conserva filas y validaciones legacy y reemplaza
las claves de predicción sin ejecutar `UPDATE` durante inferencias futuras.
Creá y probá un backup antes de aplicarla. Su downgrade es intencionalmente
irreversible; un rollback operativo restaura ese backup en una base aislada.

Luego ejecutá el provisionamiento versionado con el mismo endpoint y usuario.
Las variables `PG*` existen sólo en el proceso de `psql`; no reemplazan la
configuración canónica de VAAET:

```bash
export PGHOST="$VAAET_DB_HOST" PGPORT="$VAAET_DB_PORT" PGDATABASE="$VAAET_DB_NAME"
export PGUSER="$VAAET_ADMIN_DB_USER" PGPASSWORD="$VAAET_ADMIN_DB_PASSWORD"
export PGSSLMODE="$VAAET_DB_SSLMODE" PGSSLROOTCERT="$VAAET_DB_SSLROOTCERT"
psql -v ON_ERROR_STOP=1 -f migrations/provision-roles.sql
```

El script crea sólo group roles `NOLOGIN`; creá usuarios `LOGIN` desde el panel
del proveedor o una sesión administrativa y asignales exactamente un grupo:

```sql
GRANT vaaet_collection_role TO vaaet_collection_user;
GRANT vaaet_inference_role TO vaaet_inference_user;
GRANT vaaet_training_role TO vaaet_training_user;
GRANT vaaet_reviewer_role TO vaaet_reviewer_user;
```

## Preflight de proveedor y perfiles

Antes de elegir un servicio o plan, aplicá migraciones y roles en una base
aislada que puedas descartar. Debe completar estas verificaciones:

| Capacidad | Motivo |
| --- | --- |
| PostgreSQL 14+ y endpoint administrativo directo | Alembic y el provisionamiento no deben pasar por un pooler limitado. |
| TLS y CA verificable | Protege el endpoint remoto con `verify-full`. |
| `CREATE SCHEMA`, `CREATE ROLE`, grants y default privileges | Mantiene los cuatro perfiles de mínimo privilegio. |
| Funciones `SECURITY DEFINER` | Protege el linaje `pipeline_run` sin conceder inserción directa. |
| Backups/PITR y base aislada | Permite restauración y rollback administrativo seguro. |

Aplicá `alembic upgrade head`, `provision-roles.sql` y la integración marcada
`postgres` sobre esa base. Si alguna capacidad falla, el proveedor o plan no es
compatible: no crees un usuario administrador compartido ni debilites grants.

En Colab, almacená el endpoint compartido, CA PEM y sólo las credenciales del
perfil necesario en Secrets. Un workflow selecciona exactamente uno de
`collection`, `inference`, `training` o `review`; administrador, Alembic y DDL
quedan siempre fuera de Colab.

## Diagnóstico, rotación y backup

Con un perfil `training` de sólo lectura, ejecutá la auditoría sin mutaciones:

```bash
python vaaet-ml/scripts/audit-postgres-database.py --output postgres-audit.json
```

El informe registra revisión Alembic, TLS, owner, constraints, índices, tamaños
y planes `EXPLAIN` sin `ANALYZE`; no contiene DSN, contraseñas, CA ni errores
externos sin redactar.

Para rotar una credencial: crear una nueva para un único perfil, actualizar el
gestor de secretos, verificar el health check de ese workflow, revocar la
anterior y auditar conexiones. Nunca uses la identidad administrativa en Colab.

Un backup lógico se genera con el cliente PostgreSQL compatible y se restaura
sólo en una base aislada:

```bash
pg_dump --format=custom --no-owner --no-acl \
  --schema=vaaet_raw --schema=vaaet_ml --schema=vaaet_feedback --schema=vaaet_ops \
  --file=vaaet-db-v3.backup

pg_restore -l vaaet-db-v3.backup
```

El notebook de entrenamiento inspecciona el catálogo y extrae exclusivamente
`TABLE DATA` mediante una TOC controlada. Nunca restaura DDL, roles ni un backup
directamente sobre la base viva. Los backups administrados o PITR pueden
sustituir el dump si cumplen al menos el RPO definido por el responsable.

## Diagnóstico rápido

- timeout o red: comprobar firewall, allowlist y que el endpoint administrativo
  no sea un pooler transaccional;
- TLS: renovar CA y hostname; no degradar silenciosamente a `disable`;
- permisos o schema: ejecutar Alembic y `provision-roles.sql` fuera de Colab en
  una base aislada antes de corregir producción;
- backup incompatible: usar PostgreSQL client 17 o exportar CSV;
- escritura fallida: preservar CSV, video y manifiesto local redactado antes de
  reiniciar el runtime.
