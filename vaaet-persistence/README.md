# VAAET Persistence 0.2.0

`vaaet-persistence` es la única implementación compartida del acceso PostgreSQL
de VAAET. Centraliza configuración segura, conexiones, consultas operacionales,
escrituras transaccionales, auditoría y migraciones Alembic.

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
