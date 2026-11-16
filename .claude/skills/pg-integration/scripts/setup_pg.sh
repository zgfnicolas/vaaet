#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
# Prepara un PostgreSQL local desechable con pgserver y lo deja escuchando en
# localhost. Ejecutá desde la raíz del repositorio:
#   VAAET_PG_PYTHON="py -3.11" bash .claude/skills/pg-integration/scripts/setup_pg.sh
set -euo pipefail

PG_HOME="${VAAET_PG_HOME:-${TMPDIR:-/tmp}/vaaet-pg}"
PG_PORT="${VAAET_PG_PORT:-55432}"
BOOTSTRAP_PYTHON="${VAAET_PG_PYTHON:-python3}"
REPO_ROOT="$(git rev-parse --show-toplevel)"

mkdir -p "$PG_HOME"
if [ ! -d "$PG_HOME/venv" ]; then
  $BOOTSTRAP_PYTHON -m venv "$PG_HOME/venv"
fi
if [ -x "$PG_HOME/venv/Scripts/python.exe" ]; then
  PY="$PG_HOME/venv/Scripts/python.exe"
else
  PY="$PG_HOME/venv/bin/python"
fi
"$PY" -c 'import sys; assert (3, 10) <= sys.version_info[:2] <= (3, 13), sys.version'

# Sin TensorFlow ni YOLO: el job de integración no los necesita.
"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q -e "$REPO_ROOT/vaaet-core" joblib "scikit-learn>=1.5,<2"
"$PY" -m pip install -q -e "$REPO_ROOT/vaaet-persistence[admin]" pytest pgserver tzdata
"$PY" -m pip install -q --no-deps -e "$REPO_ROOT/vaaet-ml"

PGINSTALL="$("$PY" -c 'import pathlib, pgserver; print(pathlib.Path(pgserver.__file__).parent / "pginstall")')"
BIN="$PGINSTALL/bin"
# El build de pgserver para Windows no trae la base de zonas horarias; la
# migración legacy necesita America/Argentina/Buenos_Aires.
TZ_DIR="$PGINSTALL/share/postgresql/timezone"
if [ ! -f "$TZ_DIR/America/Argentina/Buenos_Aires" ]; then
  ZONEINFO="$("$PY" -c 'import pathlib, tzdata; print(pathlib.Path(tzdata.__file__).parent / "zoneinfo")')"
  mkdir -p "$TZ_DIR"
  cp -r "$ZONEINFO"/. "$TZ_DIR"/
  find "$TZ_DIR" \( -name '__init__.py' -o -name '__pycache__' \) -prune -exec rm -rf {} +
fi

native_path() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi
}
# Devuelve 0 si en el puerto responde el servidor de $PG_HOME/data, 1 si no
# responde nada y aborta si responde otra instancia.
own_server_running() {
  local data_dir
  data_dir="$(PGPASSWORD=postgres "$BIN/psql" -h localhost -p "$PG_PORT" -U postgres \
    -d postgres -tAc 'SHOW data_directory' 2>/dev/null)" || return 1
  if "$PY" -c 'import os, sys; a, b = (os.path.normcase(os.path.realpath(p)) for p in sys.argv[1:]); sys.exit(a != b)' \
      "$data_dir" "$(native_path "$PG_HOME/data")"; then
    return 0
  fi
  echo "El puerto $PG_PORT ya lo usa otra instancia PostgreSQL ($data_dir); elegí otro VAAET_PG_PORT." >&2
  exit 1
}

if [ ! -d "$PG_HOME/data" ]; then
  printf 'postgres\n' > "$PG_HOME/pwfile"
  "$BIN/initdb" -D "$PG_HOME/data" -U postgres --pwfile="$PG_HOME/pwfile" \
    -A scram-sha-256 -E UTF8 --locale=C >/dev/null
  rm -f "$PG_HOME/pwfile"
fi

if ! own_server_running; then
  # UTC como en el CI: initdb toma la zona del sistema y cambia los instantes
  # que devuelven los tests. En Windows, `pg_ctl start -w` puede quedar
  # esperando la salida del servidor.
  "$BIN/pg_ctl" -D "$PG_HOME/data" \
    -o "-p $PG_PORT -c listen_addresses=localhost -c timezone=UTC -c log_timezone=UTC" \
    -l "$PG_HOME/postgres.log" start >/dev/null 2>&1 &
fi
for _ in $(seq 1 30); do
  if own_server_running; then
    echo "PostgreSQL local listo en localhost:$PG_PORT ($("$BIN/postgres" --version))."
    echo "Python del venv: $PY"
    exit 0
  fi
  sleep 1
done
echo "PostgreSQL no respondió; revisá $PG_HOME/postgres.log" >&2
exit 1
