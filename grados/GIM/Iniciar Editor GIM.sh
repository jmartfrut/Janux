#!/bin/bash
# ─────────────────────────────────────────────
#  Editor de Configuración GIM — UPCT
#  Doble clic para abrir el editor gráfico
# ─────────────────────────────────────────────

cd "$(dirname "$0")"
GRADO_DIR="$(pwd)"
ROOT_DIR="$(cd ../.. && pwd)"

# Matar proceso anterior en puerto 8090 si existe
OLD_PID=$(lsof -ti:8090 2>/dev/null)
if [ -n "$OLD_PID" ]; then
    echo "⚠  Puerto 8090 ocupado (PID $OLD_PID) — cerrando proceso anterior..."
    kill "$OLD_PID"
    sleep 1
fi

echo "🚀  Arrancando editor de configuración para GIM..."
python3 "$ROOT_DIR/editor_server.py" "$GRADO_DIR"
