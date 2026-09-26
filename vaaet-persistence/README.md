# VAAET Persistence 0.3.2

`vaaet-persistence` es la única implementación compartida del acceso PostgreSQL
de VAAET. Centraliza configuración segura, conexiones, consultas operacionales,
escrituras transaccionales, auditoría y migraciones Alembic.

Las operaciones públicas validan contratos antes de escribir y traducen fallos
externos a excepciones de dominio con operación y SQLSTATE seguro. Los mensajes
del driver, parámetros, DSN, contraseñas y certificados no forman parte del
traceback público. `test_connection()` es el diagnóstico booleano para fallos de
infraestructura; los errores de configuración continúan siendo explícitos.

Cada escritura de datos registra un comprobante inmutable en la misma
transacción. Si los datos se confirmaron y falló sólo el cierre de auditoría,
las APIs de reconciliación verifican corrida, fingerprint, soporte y filas
exactas sin reinsertar contenido. Una validación humana pendiente no se exporta
ni se ofrece como ground truth hasta completar esa auditoría.

La biblioteca puede ser consumida por los notebooks a través de `vaaet-ml` y,
en el futuro, por un backend sin instalar TensorFlow, YOLO, DVC, Colab ni el
laboratorio de entrenamiento. El navegador nunca debe conectarse directamente
a PostgreSQL.

```bash
python -m pip install -e "../vaaet-core"
python -m pip install -e ".[admin,dev]"
```

Las migraciones se ejecutan exclusivamente con una identidad administrativa:

```bash
alembic -c alembic.ini upgrade head
```

Consultá la [guía PostgreSQL](../docs/operations/postgresql-guide.md) para perfiles,
TLS, roles, backups y recuperación.
