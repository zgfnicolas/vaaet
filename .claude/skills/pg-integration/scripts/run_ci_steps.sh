#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
# Replica los pasos del job `postgres-integration` de .github/workflows/ci.yml
# contra el PostgreSQL local de setup_pg.sh. Borra y recrea las bases `vaaet` y
# `vaaet_fresh` de ese servidor; nunca apuntes estas variables a otra instancia.
set -euo pipefail

PG_HOME="${VAAET_PG_HOME:-${TMPDIR:-/tmp}/vaaet-pg}"
PG_PORT="${VAAET_PG_PORT:-55432}"
REPO_ROOT="$(git rev-parse --show-toplevel)"
if [ -x "$PG_HOME/venv/Scripts/python.exe" ]; then
  VENV_BIN="$PG_HOME/venv/Scripts"
  PY="$VENV_BIN/python.exe"
else
  VENV_BIN="$PG_HOME/venv/bin"
  PY="$VENV_BIN/python"
fi
BIN="$("$PY" -c 'import pathlib, pgserver; print(pathlib.Path(pgserver.__file__).parent / "pginstall" / "bin")')"

native_path() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi
}

ADMIN_SECRET_FILE="$PG_HOME/admin-password"
if [ ! -f "$ADMIN_SECRET_FILE" ]; then
  echo "Falta $ADMIN_SECRET_FILE; ejecutá setup_pg.sh primero." >&2
  exit 1
fi
# Sin credenciales en el repositorio: la del superusuario la genera setup_pg.sh
# y las de los roles de prueba se generan en cada corrida.
random_secret() { "$PY" -c 'import secrets; print(secrets.token_urlsafe(18))'; }

export PATH="$VENV_BIN:$PATH" PYTHONIOENCODING=utf-8
export VAAET_DB_HOST=localhost VAAET_DB_PORT="$PG_PORT" VAAET_DB_SSLMODE=disable
VAAET_ADMIN_DB_USER=postgres
VAAET_ADMIN_DB_PASSWORD="$(< "$ADMIN_SECRET_FILE")"
export VAAET_ADMIN_DB_USER VAAET_ADMIN_DB_PASSWORD
for login in collection inference training review; do
  upper="$(printf '%s' "$login" | tr '[:lower:]' '[:upper:]')"
  export "VAAET_${upper}_DB_USER=vaaet_${login}_test"
  export "VAAET_${upper}_DB_PASSWORD=$(random_secret)"
done
export VAAET_REQUIRE_POSTGRES_INTEGRATION=1
VAAET_PG_RESTORE_PATH="$(native_path "$BIN/pg_restore")"
VAAET_LEGACY_BACKUP_PATH="$(native_path "$PG_HOME/vaaet-legacy.backup")"
VAAET_MODERN_BACKUP_PATH="$(native_path "$PG_HOME/vaaet-modern.backup")"
export VAAET_PG_RESTORE_PATH VAAET_LEGACY_BACKUP_PATH VAAET_MODERN_BACKUP_PATH
export PGHOST=localhost PGPORT="$PG_PORT" PGUSER="$VAAET_ADMIN_DB_USER"
export PGPASSWORD="$VAAET_ADMIN_DB_PASSWORD"
PYTEST=("$PY" -m pytest -q -m postgres -p no:cacheprovider)
CYCLE="tests/integration/test_postgres_schema.py::test_pg17_review_receipt_zip_and_backup_training_cycle"
ROLES_SQL="../vaaet-persistence/src/vaaet_persistence/migrations/provision-roles.sql"

cd "$REPO_ROOT/vaaet-ml"
# Antes de borrar bases, confirmá que el servidor es el desechable de setup_pg.sh.
DATA_DIR="$(PGDATABASE=postgres "$BIN/psql" -tAc 'SHOW data_directory')"
if ! "$PY" -c 'import os, sys; a, b = (os.path.normcase(os.path.realpath(p)) for p in sys.argv[1:]); sys.exit(a != b)' \
    "$DATA_DIR" "$(native_path "$PG_HOME/data")"; then
  echo "localhost:$PG_PORT no es el servidor de $PG_HOME/data ($DATA_DIR); no se borra nada." >&2
  exit 1
fi
PGDATABASE=postgres "$BIN/psql" -q -c "DROP DATABASE IF EXISTS vaaet" \
  -c "DROP DATABASE IF EXISTS vaaet_fresh" -c "CREATE DATABASE vaaet"

echo "== Aplicar migración y roles (base legacy)"
export VAAET_DB_NAME=vaaet PGDATABASE=vaaet VAAET_EXPECT_LEGACY_FIXTURE=1
"$PY" -c "import pathlib, psycopg2; c = psycopg2.connect(); c.autocommit = True; c.cursor().execute(pathlib.Path('tests/fixtures/postgres-legacy.sql').read_text()); c.close()"
"$BIN/pg_dump" --format=custom --data-only --table=public.traffic_data --file="$VAAET_LEGACY_BACKUP_PATH"
"$VENV_BIN/alembic" -c ../vaaet-persistence/alembic.ini upgrade 20260905_0003
"$VENV_BIN/alembic" -c ../vaaet-persistence/alembic.ini upgrade head
"$BIN/psql" -q -v ON_ERROR_STOP=1 -f "$ROLES_SQL"
for login in collection inference training review; do
  role="vaaet_${login}_test"
  secret_var="VAAET_$(printf '%s' "$login" | tr '[:lower:]' '[:upper:]')_DB_PASSWORD"
  # token_urlsafe sólo usa [A-Za-z0-9_-]: es seguro entre comillas simples.
  if [ -z "$("$BIN/psql" -tAc "SELECT 1 FROM pg_roles WHERE rolname = '$role'")" ]; then
    "$BIN/psql" -q -v ON_ERROR_STOP=1 -c "CREATE ROLE $role LOGIN PASSWORD '${!secret_var}'"
  else
    "$BIN/psql" -q -v ON_ERROR_STOP=1 -c "ALTER ROLE $role PASSWORD '${!secret_var}'"
  fi
done
"$BIN/psql" -q -v ON_ERROR_STOP=1 \
  -c "GRANT vaaet_collection_role TO vaaet_collection_test" \
  -c "GRANT vaaet_inference_role TO vaaet_inference_test" \
  -c "GRANT vaaet_training_role TO vaaet_training_test" \
  -c "GRANT vaaet_reviewer_role TO vaaet_review_test"
"$BIN/pg_dump" --format=custom --data-only --table=vaaet_raw.traffic_data --file="$VAAET_MODERN_BACKUP_PATH"

status=0
echo "== Probar schema, constraints y mínimo privilegio"
"${PYTEST[@]}" "$CYCLE" --basetemp="$PG_HOME/t1" || status=1
"${PYTEST[@]}" ../vaaet-persistence/tests/integration tests/integration --basetemp="$PG_HOME/t2" || status=1

echo "== Auditar PostgreSQL sin mutaciones"
AUDIT="$(native_path "$PG_HOME/postgres-audit.json")"
HEAD_REVISION="$("$VENV_BIN/alembic" -c ../vaaet-persistence/alembic.ini heads 2>/dev/null | awk '{print $1}' | head -1)"
if "$VENV_BIN/vaaet-postgres-audit" --output "$AUDIT" >/dev/null; then
  "$PY" -c "import json, sys; r = json.load(open(sys.argv[1])); assert r['alembic_revision'] == sys.argv[2], r['alembic_revision']; assert r['integrity']['automatic_accident_states'] == 0; assert r['integrity']['conflicting_validation_chains'] >= 0; print('auditoría ok:', r['alembic_revision'])" "$AUDIT" "$HEAD_REVISION" || status=1
else
  status=1
fi

echo "== Probar migración desde base vacía"
PGDATABASE=postgres "$BIN/psql" -q -c "CREATE DATABASE vaaet_fresh"
export VAAET_DB_NAME=vaaet_fresh PGDATABASE=vaaet_fresh VAAET_EXPECT_LEGACY_FIXTURE=0
"$VENV_BIN/alembic" -c ../vaaet-persistence/alembic.ini upgrade head
"$BIN/psql" -q -v ON_ERROR_STOP=1 -f "$ROLES_SQL"
"${PYTEST[@]}" "$CYCLE" --basetemp="$PG_HOME/t3" || status=1
"${PYTEST[@]}" ../vaaet-persistence/tests/integration tests/integration --basetemp="$PG_HOME/t4" || status=1
exit "$status"
