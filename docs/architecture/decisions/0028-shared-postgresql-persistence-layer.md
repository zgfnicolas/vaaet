# ADR-0028 — Persistencia PostgreSQL compartida

- Estado: aceptada
- Fecha: 2026-09-08
- Decisor: Facundo Nicolás González
- Actualiza: ADR-0021 y ADR-0024

## Contexto

La implementación PostgreSQL vivía dentro de `vaaet-ml`, aunque sus operaciones
de conexión, telemetría, inferencia, revisión y linaje no son entrenamiento. Esa
ubicación obligaría a un futuro backend a depender del laboratorio, sus
notebooks y su stack científico, o a duplicar SQL y contratos de seguridad.

La base sigue siendo una capacidad opcional. Los notebooks necesitan adaptadores
para Google Colab y compatibilidad temporal con configuraciones antiguas; esos
detalles no deben formar parte de una biblioteca reutilizable por servicios.

## Decisión

Se incorpora una tercera distribución interna:

```text
vaaet-core          vaaet-persistence          vaaet-ml
import vaaet   ←    import vaaet_persistence ← import vaaet_ml
dominio portable    PostgreSQL compartido      laboratorio y Colab
```

`vaaet-persistence==0.1.0` es la única implementación canónica de:

- perfiles, configuración tipada, URLs redactadas, engines y health checks;
- consultas y persistencia de raw, features, predicciones y validaciones;
- registro de ejecuciones, auditoría y contratos PostgreSQL compartidos;
- Alembic, revisiones `0001`--`0003` y provisionamiento de roles.

Puede depender de `vaaet-core` base para contratos y tiempo. No puede depender
de `vaaet-ml`, TensorFlow, YOLO, DVC, Drive, Colab ni la aplicación.

`vaaet-ml` conserva ingestión de backups y datasets, resolución global HITL,
widgets, entrenamiento, evaluación, holdouts, memoria semilla y adaptadores de
Secrets de Colab. Durante VAAET 4.x mantiene fachadas de imports y variables
legacy que delegan en la implementación compartida, sin duplicar SQL.

Una futura API podrá instalar core base y persistencia, usar una identidad de
servicio propia y convertir los resultados tabulares a contratos HTTP. El
navegador nunca accederá directamente a PostgreSQL. Los permisos de usuarios
web y roles de lectura para pantallas se decidirán junto con la primera API.

Las migraciones se distribuyen como recursos instalables de
`vaaet-persistence`. La configuración anterior de ML delega temporalmente con
advertencia y no contiene una segunda copia de las revisiones.

## Invariantes

- Se conserva `vaaet-db-v3`; la extracción no requiere una revisión `0004`.
- Las revisiones `0001`, `0002` y `0003`, sus identificadores y su contenido no
  cambian. Las bases existentes conservan `public.alembic_version`.
- Cada operación exige un perfil explícito. Credenciales presentes nunca
  habilitan escritura por sí solas.
- Cada consumidor aporta `application_name` y `application_version`; la
  biblioteca no suplanta la identidad del workflow.
- Los engines pueden reutilizarse durante el ciclo de vida del consumidor. Una
  operación libera sus conexiones, pero nunca dispone un engine recibido.
- Sólo el health check puede reintentar fallos transitorios. Las escrituras no
  se repiten automáticamente.
- Alembic y administración permanecen fuera de notebooks y utilizan una
  identidad distinta de los cuatro perfiles operativos.
- Los entornos de desarrollo, pruebas y producción usan bases y credenciales
  separadas.

## Consecuencias

El bootstrap instala core, persistencia y ML en ese orden. CI valida cada
distribución por separado y prueba un consumidor sin laboratorio. PostgreSQL 17
desechable verifica migraciones, roles y compatibilidad de fachadas.

La extracción permite compartir la misma política de integridad entre
notebooks y backend sin convertir la base en una interfaz de frontend ni crear
un repositorio CRUD genérico. Un despliegue puede volver temporalmente al código
anterior porque el esquema y los datos no se reescriben.

Los privilegios por defecto se verifican con el rol administrativo que crea los
objetos: PostgreSQL los asocia al rol creador, no globalmente a la base. Backups,
rotación, TLS y recuperación continúan gobernados por la guía operativa.
