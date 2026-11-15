# Roles y permisos

Define quién puede hacer qué en el laboratorio y con qué identidad PostgreSQL.
Es la única matriz de permisos del repositorio: la guía PostgreSQL, el modelo de
datos y la política de seguridad la enlazan en lugar de repetirla. La fuente de
verdad de los grants es
[`provision-roles.sql`](../../vaaet-persistence/src/vaaet_persistence/migrations/provision-roles.sql).

## Roles de persona

| Rol | Quién es | Cómo obtiene el rol |
|---|---|---|
| Operador | Persona que analiza un clip autorizado | Accede al notebook y, si persiste, recibe credenciales de `collection` o `inference` |
| Investigador | Persona que entrena, evalúa y mantiene datasets y bundles | Accede a los cuatro notebooks y recibe credenciales de `training` |
| Revisor | Persona que confirma o corrige predicciones | Recibe credenciales de `review` y un `VAAET_REVIEWER_ID` seudónimo |
| Administrador | Persona que gestiona la instancia PostgreSQL | Identidad `VAAET_ADMIN_DB_*`, fuera de Colab |

Una persona puede tener más de un rol, pero cada rol usa su propia credencial.

## Matriz de acciones

| Acción | Operador | Investigador | Revisor | Administrador |
|---|:-:|:-:|:-:|:-:|
| Recolectar telemetría desde video | ✓ | ✓ | | |
| Analizar un video con un bundle | ✓ | ✓ | | |
| Entrenar un bundle candidato | | ✓ | | |
| Comparar Champion y Challenger | | ✓ | | |
| Validar o corregir una predicción | | | ✓ | |
| Confirmar `Accident` | | | ✓ | |
| Publicar el catálogo HITL desde el runtime designado | | ✓ | | |
| Decidir la promoción de un bundle | | ✓ | | |
| Aplicar migraciones Alembic y `provision-roles.sql` | | | | ✓ |
| Crear usuarios `LOGIN` y asignar un rol de grupo | | | | ✓ |

## Perfiles PostgreSQL

Cada workflow declara un `DatabaseProfile` y usa un usuario `LOGIN` distinto,
miembro de un único rol de grupo.

| Perfil | Rol de grupo | Lectura | Escritura |
|---|---|---|---|
| `collection` | `vaaet_collection_role` | `vaaet_raw.traffic_data` | `INSERT` en `vaaet_raw.traffic_data` |
| `inference` | `vaaet_inference_role` | Features y predicciones | `INSERT` en `vaaet_ml.telemetry_features` y `vaaet_ml.traffic_predictions`; `UPDATE` y `DELETE` revocados |
| `training` | `vaaet_training_role` | Todas las tablas de `vaaet_raw`, `vaaet_ml`, `vaaet_feedback` y `vaaet_ops` | Ninguna |
| `review` | `vaaet_reviewer_role` | Features, predicciones, `review_queue` y `human_validation_conflicts` | `INSERT` en `vaaet_feedback.human_validations` |
| Administrador | Identidad propia | — | DDL mediante Alembic, roles y grants |

Los cuatro perfiles de workflow leen `public.alembic_version` para bloquear
escrituras si la revisión del schema no coincide. Corridas y comprobantes se
registran sólo mediante las funciones controladas de `vaaet_ops`.

## Reglas especiales

- Ningún perfil automático puede insertar el estado 3 (`Accident`); sólo una
  validación humana con nota y contexto temporal confirmado
  ([RN-02](business-rules.md#rn-02--accident-es-exclusivamente-humano)).
- El revisor agrega validaciones; no puede modificar ni borrar predicciones ni
  validaciones anteriores. Una corrección es una validación nueva que sustituye
  a la anterior.
- El perfil `inference` no puede escribir feedback humano.
- La identidad administrativa nunca se usa desde Colab.
- Dos runtimes no publican el catálogo HITL a la vez: sólo el designado con un
  `HitlCatalogPublisher` activo puede modificarlo.
- El notebook de evaluación no escribe en PostgreSQL, DVC ni artefactos.

La operación detallada está en la [guía PostgreSQL](../operations/postgresql-guide.md)
y el modelo de seguridad en
[ADR-0015](../architecture/decisions/0015-postgresql-namespaces-security-and-hitl.md).
