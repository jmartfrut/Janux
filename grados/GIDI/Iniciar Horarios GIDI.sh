#!/bin/bash
# ─────────────────────────────────────────────
#  Gestor de Horarios GIDI — UPCT  (Curso 2026-2027)
#  Doble clic para arrancar servidor y abrir web
# ─────────────────────────────────────────────

# Ir a la carpeta de este grado
cd "$(dirname "$0")"
GRADO_DIR="$(pwd)"
ROOT_DIR="$(cd ../.. && pwd)"
DB_NAME="horariosGIDI.db"
TMP_DB="/tmp/horarios_gidi.db"

# Matar proceso anterior en puerto 8080 si existe
OLD_PID=$(lsof -ti:8080 2>/dev/null)
if [ -n "$OLD_PID" ]; then
    echo "⚠  Puerto 8080 ocupado (PID $OLD_PID) — cerrando proceso anterior..."
    kill "$OLD_PID"
    sleep 1
fi

# Verificar que existe la BD
if [ ! -f "$DB_NAME" ]; then
    echo "✗  No se encuentra $DB_NAME en $GRADO_DIR"
    echo "   Ejecuta primero el editor de configuración para generar la BD."
    exit 1
fi

# Copiar la BD a /tmp para evitar errores de I/O en rutas de red (Dropbox/OneDrive)
echo "📂  Copiando base de datos a directorio local..."
cp "$DB_NAME" "$TMP_DB"
if [ $? -ne 0 ]; then
    echo "✗  Error al copiar $DB_NAME"
    exit 1
fi
echo "✓  Base de datos lista en $TMP_DB"

echo "🚀  Arrancando servidor de horarios GIDI (curso 2026-2027)..."
DB_PATH_OVERRIDE="$TMP_DB" \
CURSO_LABEL="2026-2027" \
CONFIG_PATH_OVERRIDE="$GRADO_DIR/config.json" \
python3 "$ROOT_DIR/servidor_horarios.py" &
SERVER_PID=$!

# Esperar a que el servidor esté listo (max 5 seg)
for i in 1 2 3 4 5; do
    sleep 1
    if curl -s --noproxy '*' http://localhost:8080 > /dev/null 2>&1; then
        echo "✓  Servidor listo en http://localhost:8080"
        break
    fi
    echo "   Esperando... ($i/5)"
done

# Abrir el navegador
xdg-open http://localhost:8080

echo ""
echo "────────────────────────────────────────"
echo "  Servidor corriendo (PID $SERVER_PID)"
echo "  Grado: GIDI   Curso: 2026-2027"
echo "  Cierra esta ventana para detenerlo"
echo "────────────────────────────────────────"

# Al cerrar: devolver la BD actualizada al directorio del grado
trap 'echo ""; echo "💾  Guardando BD actualizada..."; cp "$TMP_DB" "$DB_NAME" && echo "✓  $DB_NAME guardado." || echo "✗  Error al guardar $DB_NAME"' EXIT

# Mantener el script vivo hasta que se cierre la ventana
wait $SERVER_PID
