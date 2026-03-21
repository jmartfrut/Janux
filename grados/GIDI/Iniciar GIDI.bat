@echo off
REM Launcher — GIDI (2026-2027)
set DIR=%~dp0
set ROOT=%DIR%..\..
set DB_SRC=%DIR%horarios.db
set DB_TMP=%TEMP%\horarios_GIDI.db

copy /Y "%DB_SRC%" "%DB_TMP%" >nul 2>&1

set DB_PATH_OVERRIDE=%DB_TMP%
set CURSO_LABEL=2026-2027
start "" "http://localhost:8080"
python "%ROOT%\servidor_horarios.py" --grado "grados/GIDI"

copy /Y "%DB_TMP%" "%DB_SRC%" >nul 2>&1
echo Base de datos guardada.
pause
