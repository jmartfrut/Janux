#!/bin/bash
# ─────────────────────────────────────────────
#  IAnus — Asistente de Nuevo Grado
#  Doble clic para abrir el asistente en el navegador
# ─────────────────────────────────────────────
cd "$(dirname "$0")"
echo "🚀  Arrancando asistente en http://localhost:8091 ..."
python3 nuevo_grado.py
