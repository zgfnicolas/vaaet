# Operación PostgreSQL compartida — VAAET Persistence 0.2.0

PostgreSQL es opcional y su implementación pertenece a
`vaaet-persistence`. Los notebooks de `vaaet-ml` y un futuro backend consumen
la misma biblioteca; no comparten usuarios ni contraseñas. Desarrollo, pruebas
y producción deben utilizar bases lógicas y credenciales separadas.

Se admiten AWS RDS, Supabase, Neon o servidores propios cuando ofrecen las
capacidades de [ADR-0024](../architecture/decisions/0024-provider-neutral-postgresql-and-schema-as-code.md).
La frontera compartida está gobernada por
[ADR-0028](../architecture/decisions/0028-shared-postgresql-persistence-layer.md)
y su integridad numérica/HITL por
[ADR-0029](../architecture/decisions/0029-postgresql-numeric-fidelity-and-hitl-consistency.md).

## Configuración

El endpoint y TLS son comunes; cada operación selecciona explícitamente un
perfil con mínimo privilegio. Tener Secrets configurados no activa una lectura
o escritura.

| Propósito | Variables canónicas |
| --- | --- |
| Endpoint | `VAAET_DB_HOST`, `VAAET_DB_PORT`, `VAAET_DB_NAME`, `VAAET_DB_SSLMODE`, `VAAET_DB_SSLROOTCERT` o `VAAET_DB_SSLROOTCERT_PEM`, `VAAET_DB_CONNECT_TIMEOUT`, `VAAET_DB_STATEMENT_TIMEOUT`, `VAAET_DB_LOCK_TIMEOUT` |
| Pool por proceso | `VAAET_DB_POOL_SIZE`, `VAAET_DB_MAX_OVERFLOW`, `VAAET_DB_POOL_RECYCLE_SECONDS`, `VAAET_DB_POOL_TIMEOUT` |
| Health check | `VAAET_DB_RETRY_ATTEMPTS`, `VAAET_DB_RETRY_BASE_DELAY_SECONDS` |
| Workflow | `VAAET_COLLECTION_DB_*`, `VAAET_INFERENCE_DB_*`, `VAAET_TRAINING_DB_*` o `VAAET_REVIEW_DB_*`, con `USER` y `PASSWORD` |
| Administración | `VAAET_ADMIN_DB_USER`, `VAAET_ADMIN_DB_PASSWORD` |

Los valores predeterminados son `pool_size=2`, `max_overflow=0`, reciclado a
300 segundos, espera de pool de 30 segundos, consulta de 120 segundos y bloqueo
de 5 segundos. Cada proceso mantiene su propio pool: no se comparte un engine
entre procesos ni se crea uno por fila. Una operación libera su conexión al
terminar y no dispone un engine recibido del consumidor.

El health check admite reintentos transitorios acotados. Una escritura no se
repite automáticamente porque no puede suponerse que sea seguro hacerlo.

Usá `verify-full` y una CA verificable en endpoints remotos. `require` cifra
sin verificar identidad y sólo se admite como excepción documentada. `disable`
se limita a `localhost` explícito. Nunca registres DSN, contraseñas o PEM.

El adaptador de Colab resuelve Secrets antes del entorno y permanece en ML. La
biblioteca compartida acepta el entorno o un proveedor de valores inyectado.
`.env` es opt-in. Variables `DB_*` y configuraciones antiguas sólo existen en
las fachadas ML durante VAAET 4.x.

## Uso desde un consumidor

El consumidor declara su identidad y el perfil; la biblioteca no elige
silenciosamente `training` ni usa su propia versión como versión del workflow.

```python
from vaaet_persistence import (
    DatabaseProfile,
    database_engine,
    load_database_settings,
)

settings = load_database_settings(
    DatabaseProfile.TRAINING,
    application_name="vaaet-api",
    application_version="0.2.0",
)
with database_engine(settings) as engine:
    # Operación concreta, read-only para este perfil.
    ...
```

Los notebooks mantienen flags operativos deshabilitados por defecto. La futura
API usará identidades de servicio propias; el navegador sólo hablará con HTTP y
nunca recibirá acceso PostgreSQL.

## Provisionamiento y migraciones

Ejecutá administración desde una máquina controlada o CI, nunca desde Colab:

```bash
python -m pip install -e "./vaaet-core"
python -m pip install -e "./vaaet-persistence[admin,dev]"

cd vaaet-persistence
alembic -c alembic.ini upgrade head
```

Las revisiones `0001`, `0002` y `0003` se conservan byte a byte. La revisión
`0004` migra medidas continuas a `DOUBLE PRECISION`, registra su procedencia,
añade identidad de aplicación y fortalece cadenas HITL. Una base en `0003`
requiere ensayo sobre una restauración y una ventana administrativa para subir
a `0004`; `public.alembic_version` conserva la revisión exacta.
La configuración histórica de ML delega temporalmente con advertencia.
Los cuatro roles de workflow reciben sólo `SELECT` sobre esa tabla de control:
es el permiso mínimo necesario para bloquear escrituras cuando la revisión no
coincide con la requerida por el consumidor.

Aplicá luego los roles con la misma identidad administrativa:

```bash
psql -v ON_ERROR_STOP=1 \
  -f vaaet-persistence/src/vaaet_persistence/migrations/provision-roles.sql
```

El script crea group roles `NOLOGIN`. Los usuarios `LOGIN` se crean fuera del
repositorio y reciben exactamente el grupo requerido:

```sql
GRANT vaaet_collection_role TO vaaet_collection_user;
GRANT vaaet_inference_role TO vaaet_inference_user;
GRANT vaaet_training_role TO vaaet_training_user;
GRANT vaaet_reviewer_role TO vaaet_reviewer_user;
```

Los privilegios por defecto pertenecen al rol que crea los objetos. Verificalos
bajo la identidad administrativa real; configurarlos con otro administrador no
protege automáticamente objetos futuros.

No uses `create_all`, `drop_all`, autogeneración ni DDL desde notebooks. Alembic
explícito es la única autoridad del esquema.

## Preflight de proveedor

Antes de adoptar un servicio, probá en una base descartable:

- PostgreSQL 14+ y endpoint administrativo directo;
- TLS con hostname y CA verificables;
- creación de schemas y roles, grants y default privileges;
- funciones `SECURITY DEFINER` para linaje;
- migración limpia y actualización de una base existente en `0003`;
- backups/PITR y restauración en una base aislada;
- operaciones permitidas y prohibidas de los cuatro perfiles.

Si el plan del proveedor no permite el contrato, no sustituyas los perfiles por
un administrador compartido ni debilites constraints.

## Auditoría, rotación y rendimiento

La auditoría es read-only:

```bash
vaaet-postgres-audit --output postgres-audit.json
```

Reporta revisión, TLS y rol activo, owners, grants, default privileges,
constraints pendientes, cobertura de comentarios, índices, tamaños, autovacuum,
integridad HITL, representación numérica y `EXPLAIN`
sin `ANALYZE`; nunca incluye secretos.

Para rotar una credencial, creá otra para un único perfil, actualizá el gestor
de secretos, verificá el health check, revocá la anterior y auditá conexiones.
No uses la identidad administrativa en notebooks o servicios.

Medí latencia, throughput, planes, bloqueos y conexiones antes de aumentar el
pool o agregar índices. El particionamiento se evalúa al superar 10 millones de
filas o cuando tamaño y planes demuestren degradación.

## Backup y recuperación

El proveedor debe cifrar datos en reposo y mantenerse actualizado. Como piso
operativo:

- backup lógico diario o política equivalente;
- retención mínima de 30 días;
- restauración trimestral en una base aislada;
- RPO objetivo de hasta 24 horas;
- RTO medido y registrado por entorno y proveedor.

```bash
pg_dump --format=custom --no-owner --no-acl \
  --schema=vaaet_raw --schema=vaaet_ml --schema=vaaet_feedback --schema=vaaet_ops \
  --file=vaaet-db-v3.backup

pg_restore -l vaaet-db-v3.backup
```

El entrenamiento sólo extrae `TABLE DATA` mediante una TOC controlada; nunca
restaura DDL o roles sobre una base viva. `0004` no tiene downgrade que vuelva a
redondear filas nuevas: ante una falla, aplicá una corrección hacia adelante o
restaurá el backup probado.

## Diagnóstico rápido

- **Timeout:** revisá firewall, allowlist, DNS y si se usó un pooler limitado.
- **TLS:** renová CA/hostname; no bajes silenciosamente a `disable`.
- **Permisos:** auditá grants y rol creador; corregí fuera de Colab.
- **Esquema:** comprobá `alembic current` y `alembic heads` desde persistencia.
- **Escritura fallida:** preservá CSV, video y manifiesto local; no reintentes a
  ciegas.
- **Recuperación Colab:** mantené las salidas locales y reiniciá sólo después de
  verificar configuración y migración.
