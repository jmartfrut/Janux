#!/bin/bash
# ─────────────────────────────────────────────
#  IAnus — Configuración de Grados
#  Doble clic para abrir el asistente en el navegador
#  Opciones: Grado nuevo · Doble Grado (PCEO)
# ─────────────────────────────────────────────
cd "$(dirname "$0")"
echo "🚀  Arrancando IAnus en http://localhost:8091 ..."
python3 nuevo_grado.py
