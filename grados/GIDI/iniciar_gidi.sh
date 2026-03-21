#!/bin/bash
# Launcher — GIDI (2026-2027)
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
DB_SRC="$DIR/horarios.db"
DB_TMP="/tmp/horarios_GIDI.db"

cp "$DB_SRC" "$DB_TMP" 2>/dev/null || true

cleanup() {
  kill "$SERVER_PID" 2>/dev/null
  [ -f "$DB_TMP" ] && cp "$DB_TMP" "$DB_SRC" && echo "BD guardada."
}
trap cleanup EXIT INT TERM

DB_PATH_OVERRIDE="$DB_TMP" CURSO_LABEL="2026-2027" \
  python3 "$ROOT/servidor_horarios.py" --grado "grados/GIDI" &
SERVER_PID=$!

sleep 1.5 && (xdg-open "http://localhost:8080" 2>/dev/null || true)
wait "$SERVER_PID"
