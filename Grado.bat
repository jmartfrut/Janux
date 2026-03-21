@echo off
chcp 65001 > nul
title Asistente — Crear Nuevo Grado (IAnus)
cd /d "%~dp0"
echo ----------------------------------------
echo  IAnus - Asistente de Nuevo Grado
echo ----------------------------------------
python --version > nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Python no esta instalado o no esta en el PATH.
    echo.
    echo  1. Ve a https://www.python.org/downloads/
    echo  2. Descarga Python 3.9 o superior
    echo  3. En el instalador marca "Add Python to PATH"
    echo  4. Completa la instalacion y vuelve a ejecutar este fichero
    echo.
    pause
    exit /b 1
)
echo [INFO] Arrancando asistente en http://localhost:8091 ...
start "" http://localhost:8091
python nuevo_grado.py
pause
