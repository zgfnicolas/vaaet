# Operación PostgreSQL compartida — VAAET Persistence 0.3.1

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
La idempotencia operacional y la coherencia con paquetes portables se precisan
en [ADR-0030](../architecture/decisions/0030-operational-idempotency-and-portable-hitl-coherence.md).
La asociación estricta del feedback y la redacción uniforme de errores públicos
se definen en
[ADR-0031](../architecture/decisions/0031-hitl-integrity-and-coordinated-catalog-publication.md).
El orden determinista, la lectura legacy explícita y la reconciliación sin
reinserciones se definen en
[ADR-0032](../architecture/decisions/0032-complete-cycle-integrity.md).
Los comprobantes transaccionales y el bloqueo uniforme de auditorías HITL
pendientes se definen en
[ADR-0033](../architecture/decisions/0033-verifiable-persistence-recovery-and-hitl-audit.md).

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
`inspect_database()` devuelve un diagnóstico tipado o una excepción de dominio;
`test_connection()` devuelve `False` ante indisponibilidad o agotamiento del
pool. Ninguno expone el mensaje o los parámetros del driver. Sólo un SQLSTATE de
cinco caracteres validado puede incorporarse al error público.

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
    application_name="vaaet-batch-consumer",
    application_version="1.0.0",
)
with database_engine(settings) as engine:
    # Operación concreta, read-only para este perfil.
    ...
```

Los notebooks mantienen flags operativos deshabilitados por defecto. La futura
API usará identidades de servicio propias; el navegador sólo hablará con HTTP y
nunca recibirá acceso PostgreSQL.

### Lectura moderna y legacy

La telemetría raw selecciona un contrato de forma explícita. `CURRENT` es el
valor predeterminado y consulta únicamente el schema vigente. `LEGACY` se usa
sólo para importar una tabla histórica declarada y conserva lineage y métricas
modernas como desconocidas:

```python
from vaaet_persistence import TelemetryReadMode, load_telemetry

current = load_telemetry(engine=engine, mode=TelemetryReadMode.CURRENT)
legacy = load_telemetry(engine=engine, mode=TelemetryReadMode.LEGACY)
```

Un error de permisos, SQL, timeout o schema en `CURRENT` se informa; nunca
activa `LEGACY`. El modo legacy no se admite como fuente de feedback humano.

## Provisionamiento y migraciones

Ejecutá administración desde una máquina controlada o CI, nunca desde Colab:

```bash
python -m pip install -e "./vaaet-core"
python -m pip install -e "./vaaet-persistence[admin,dev]"

cd vaaet-persistence
alembic -c alembic.ini upgrade head
```

Las revisiones `0001` a `0005` se conservan byte a byte. La revisión
`0004` migra medidas continuas a `DOUBLE PRECISION`, registra su procedencia,
añade identidad de aplicación y fortalece cadenas HITL. Una base en `0003`
requiere ensayo sobre una restauración y una ventana administrativa para subir
a `0006`; `public.alembic_version` conserva la revisión exacta. `0005` corrige
la serialización append-only del reviewer sin exigir privilegio `UPDATE` y
`0006` agrega comprobantes inmutables y reconciliaciones enlazadas.
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

Las escrituras agrupan hasta 500 filas por sentencia parametrizada y conservan
una sola transacción por operación pública. La observabilidad informa
sentencias realmente ejecutadas, lotes, filas procesadas y duración; una
repetición idempotente puede insertar cero filas nuevas sin convertir una
corrida de entrada válida en una corrida de cero filas procesadas.

Una operación confirmada puede quedar con `audit_complete=False` si falla sólo
el cierre de su corrida. Eso significa «datos guardados, auditoría pendiente»,
no rollback. Conservá el resultado y el `pipeline_run_id`; las operaciones
`reconcile_raw_telemetry()`, `reconcile_classified_telemetry()` y
`reconcile_human_validation()` verifican identidad y contenido almacenados y
completan únicamente la auditoría. Nunca reinsertan filas. Mientras la
reconciliación no termine, los pasos que exigen trazabilidad completa permanecen
bloqueados.

Cada escritura de datos crea en su misma transacción un registro de
`vaaet_ops.persistence_receipts`. Su fingerprint incluye el contenido
contractual tipado, timestamps UTC, schemas y revisión exacta; no depende de IDs
autogenerados por PostgreSQL. Un reintento idéntico recupera el recibo original
y un contenido distinto bajo la misma corrida se rechaza. Las corridas
históricas sin comprobante no se cierran automáticamente.

En revisión humana, una decisión pendiente conserva su UUID y fecha. No avanza
el formulario, no entra al ZIP y el entrenamiento detiene la fuente hasta que
`reconcile_human_validation()` verifique el comprobante y el contenido original.
Una revisión exclusivamente portable declara esa procedencia y no necesita una
corrida PostgreSQL. Una decisión PostgreSQL sólo es admisible para exportación
y entrenamiento con corrida terminada y comprobante verificable. Los ZIP
históricos sin procedencia inequívoca se pueden inspeccionar, pero no usar como
targets; sus checksums prueban integridad del archivo, no autenticidad del
productor. Consultá [ADR-0034](../architecture/decisions/0034-uniform-review-audit-evidence.md).

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
