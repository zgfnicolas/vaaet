# Política de seguridad y privacidad — VAAET ML 4.6.1

PostgreSQL usa identidades separadas por workflow, TLS `verify-full`, permisos
mínimos y funciones operativas con `search_path` fijo. La base exclusiva revoca
`CREATE` global sobre `public` y los default privileges niegan acceso a objetos
nuevos hasta que una migración conceda permisos explícitos.

El cifrado en reposo, logs de conexión/DDL, retención y parcheo corresponden al
proveedor o al administrador de la instancia. VAAET exige backups con retención
de 30 días, RPO máximo de 24 horas y una restauración trimestral documentada.
`pipeline_runs` guarda categorías de error, nunca mensajes, secretos o DSN.

## Principios

VAAET aplica mínimo privilegio, cifrado en tránsito, degradación segura y
separación entre administración y ejecución. Los notebooks pueden operar sin base
y conservan CSV/video local si falla la persistencia.

## Secretos y conexión

- Colab: panel Secrets; el paquete consulta valores sin copiarlos a celdas u outputs.
- Local: entorno o `.env` cargado sólo al pasar `env_file=` explícitamente.
- CI: credenciales efímeras del servicio PostgreSQL.
- La URL se construye con `sqlalchemy.URL.create()`; passwords con caracteres
  especiales no se concatenan ni se imprimen.
- `DatabaseSettings.__repr__`, health checks, logs y excepciones redactan usuario
  sensible, password, DSN y certificados.
- TLS `verify-full` con CA del proveedor es el valor recomendado. `require` cifra
  sin verificar identidad y genera advertencia. `disable` sólo acepta localhost.

Nunca guardar en Git `.env`, certificados privados, backups, videos o artefactos
ML. Rotar por separado cada credencial de workflow si se sospecha exposición.

## Roles

| Perfil | Acceso |
|---|---|
| collection | SELECT/INSERT en `vaaet_raw.traffic_data` |
| inference | SELECT/INSERT en features y predicciones inmutables |
| training | SELECT en los tres schemas |
| review | SELECT de cola e INSERT append-only en validaciones |
| administrator | Alembic, roles y grants; prohibido en Colab |

Las consultas usan parámetros y nombres completamente cualificados; no dependen
de `search_path`. Predicciones automáticas no pueden insertar estado 3 y el rol de
inferencia no puede escribir feedback.

## Datos

VAAET persiste agregados por minuto: conteos, velocidades, métricas de calidad,
features, predicciones y revisiones pseudónimas. No extrae patentes, identidades
ni frames individuales. El video anotado puede contener información visual y debe
tratarse conforme a la política del operador, aunque no se versiona en Git.

## Operación

1. Aplicar migraciones sobre un backup verificado.
2. Crear usuarios LOGIN específicos del proveedor y conceder un único group role.
3. Probar permisos negativos antes de habilitar persistencia.
4. Rotar passwords y CA según la política del proveedor.
5. Ante exposición: revocar credencial, auditar conexiones y logs, emitir una nueva
   identidad y documentar el incidente. Nunca reescribir historia sin preservar
   evidencia y coordinación administrativa.

El diseño completo está en [ADR-0015](../architecture/decisions/0015-postgresql-namespaces-security-and-hitl.md).
