#!/bin/bash
# Launcher — GIDI (2026-2027)
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
DB_SRC="$DIR/horarios.db"
DB_TMP="/tmp/horarios_GIDI.db"

cp "$DB_SRC" "$DB_TMP" 2>/dev/null || true

cleanup() {
  kill "$SERVER_PID" 2>/dev/null
  if [ -f "$DB_TMP" ]; then
    cp "$DB_TMP" "$DB_SRC"
    echo "Base de datos guardada."
  fi
}
trap cleanup EXIT INT TERM

DB_PATH_OVERRIDE="$DB_TMP" CURSO_LABEL="2026-2027" \
  python3 "$ROOT/servidor_horarios.py" \
  --grado "grados/GIDI" &
SERVER_PID=$!

sleep 1.5 && open "http://localhost:8080"
wait "$SERVER_PID"
