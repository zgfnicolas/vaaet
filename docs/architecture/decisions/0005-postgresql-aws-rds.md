<!-- context: VAAET/docs/architecture/decisions/0005-postgresql-aws-rds.md — PostgreSQL en AWS RDS.
Referenciado por AGENTS.md, PRD.md, README.md. -->

# ADR-005: PostgreSQL (AWS RDS) sobre SQLite/Local

**Estado:** Reemplazada por [ADR-0015](0015-postgresql-namespaces-security-and-hitl.md)
> La elección histórica de PostgreSQL permanece, pero proveedor, credenciales,
> schemas, roles y migraciones se rigen desde 4.1.0 por ADR-0015.
**Fecha:** 2026-03-06  
**Decisores:** Equipo VAAET

## Contexto

VAAET genera métricas agregadas por minuto (velocidad promedio, conteos por tipo de vehículo) que deben persistirse para análisis posterior. El entorno de ejecución principal es Google Colab, que tiene almacenamiento efímero — los archivos locales se pierden al finalizar la sesión.

Se evaluaron:
- **SQLite local**: BD embebida, archivo único
- **CSV/JSON local**: Archivos planos en el filesystem de Colab
- **PostgreSQL en AWS RDS**: BD relacional remota
- **Google Sheets API**: Persistencia en la nube via API

## Decisión

Se adopta **PostgreSQL alojado en AWS RDS** como sistema de persistencia, accesible via `psycopg2`. La persistencia es **opcional** — el sistema funciona completamente sin BD.

## Razonamiento

1. **Durabilidad fuera de Colab**: Los datos sobreviven al cierre de la sesión de Colab. SQLite y CSV se perderían
2. **Esquema relacional**: La tabla `traffic_data` con `UNIQUE(clip_id, record_time)` previene duplicados y permite queries SQL estándar
3. **Escalabilidad**: RDS permite análisis multi-sesión — se pueden consultar datos de múltiples ejecuciones
4. **Separación de concerns**: Los datos analíticos viven independientemente del entorno de procesamiento

## Consecuencias

### Positivas
- Datos persisten indefinidamente fuera de Colab
- SQL estándar para queries y reportes
- RDS maneja backups y alta disponibilidad
- Conexión segura via variables de entorno

### Negativas
- **Requiere infraestructura externa**: Una instancia RDS debe ser provisionada y mantenida (costo AWS)
- **Requiere conectividad de red**: Colab necesita acceso a internet para alcanzar RDS
- **Latencia de red**: Cada escritura (por minuto) incurre latencia vs SQLite local
- **Gestión de credenciales**: Se necesitan 5 variables de entorno (DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD) o input manual via `getpass`

### Deuda técnica aceptada
- No hay connection pooling — cada escritura abre y cierra conexión
- No hay retry automático si la conexión falla — degrada silenciosamente
- No hay migración de esquema — se usa `CREATE TABLE IF NOT EXISTS`
- No hay índices adicionales más allá del UNIQUE constraint
