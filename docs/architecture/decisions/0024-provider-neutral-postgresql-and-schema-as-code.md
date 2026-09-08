# ADR-0024 — PostgreSQL portable y migraciones como código

- Estado: aceptada
- Fecha: 2026-08-30
- Decisores: Facundo Nicolás González
- Actualiza: aspectos operativos de ADR-0015
- Complementa: ADR-0016 y ADR-0021
- Actualizada por: ADR-0028

## Contexto

VAAET ML necesita una base PostgreSQL 14+ opcional para telemetría, snapshots de
features, predicciones, revisión humana y linaje. AWS RDS, Supabase, Neon y un
servidor propio pueden exponer PostgreSQL, pero el nombre del proveedor no
garantiza los privilegios que exige el contrato actual.

Los perfiles operativos ya usaban configuración tipada, TLS y mínimo privilegio.
En cambio, Alembic recibía una URL administrativa independiente, que podía
evitar la validación centralizada de TLS y credenciales.

## Decisión

PostgreSQL se admite por capacidades, no mediante adaptadores ni enums de
proveedor. Una instalación compatible debe ofrecer:

- PostgreSQL 14+ y un endpoint administrativo directo, no un pooler limitado;
- TLS con CA para `verify-full` en endpoints remotos;
- creación y propiedad de schemas, roles NOLOGIN, grants y privilegios por
  defecto;
- funciones `SECURITY DEFINER` y las restricciones del esquema `vaaet-db-v2`.

`DatabaseEndpointSettings` reúne host, puerto, base, TLS, CA y timeout.
`DatabasePoolSettings` limita conexiones y `DatabaseRetrySettings` acota el
health check del laboratorio. `DatabaseSettings` mantiene los cuatro perfiles
operativos y `DatabaseAdminSettings` usa el mismo endpoint con una identidad
administrativa exclusiva de entorno local o CI.

Las variables canónicas son `VAAET_DB_*` para endpoint/TLS, `VAAET_<PROFILE>_DB_*`
para cada workflow y `VAAET_ADMIN_DB_USER/PASSWORD` para Alembic y grants.
`VAAET_DATABASE_ADMIN_URL` queda únicamente como compatibilidad 4.x: se analiza,
valida y reconstruye sin registrarse, emite advertencia y se retira en 5.0.

Las revisiones Alembic escritas explícitamente son la única autoridad de DDL.
El esquema sigue siendo código versionado, pero no se adoptan modelos ORM
declarativos, `Base.metadata.create_all()` ni autogeneración: duplicarían el DDL
SQL, las funciones de seguridad y las migraciones históricas.

## Consecuencias

- No cambian tablas, vistas, roles, grants, migraciones existentes, 19 features
  ni estados públicos.
- Alembic usa URL estructurada, TLS validado y `NullPool`; las migraciones no
  leen Secrets de Colab y nunca exponen un DSN en logs o SQL offline.
- Un proveedor o plan con permisos restringidos se rechaza en el preflight sobre
  una base desechable. No existe un modo reducido que debilite mínimo privilegio.
- La conexión administrativa continúa fuera de notebooks. La futura API y Web
  App no reciben acceso directo a PostgreSQL; el core sigue siendo portable.

## Actualización por ADR-0028

La implementación y las revisiones Alembic pasan a `vaaet-persistence`, sin
cambiar el contrato `vaaet-db-v3` ni crear una revisión `0004`. Los adaptadores
Colab y la compatibilidad con variables legacy permanecen en `vaaet-ml`.

Una futura API podrá usar la biblioteca compartida con una identidad de proceso
propia; la Web App seguirá sin acceso directo. Los nuevos roles o grants de la
aplicación se definirán junto con su contrato HTTP. Consultá
[ADR-0028](0028-shared-postgresql-persistence-layer.md).
