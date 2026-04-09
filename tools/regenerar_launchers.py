#!/usr/bin/env python3
"""
regenerar_launchers.py
Genera los ficheros .bat de los grados GIM y GIDI con los terminadores de
línea correctos para Windows (CRLF) y las redirecciones Windows (nul).

Ejecutar UNA VEZ en Windows desde la raíz del proyecto:
    python tools/regenerar_launchers.py
"""
import pathlib

ROOT = pathlib.Path(__file__).parent.parent  # raíz del proyecto


def bat(siglas: str, titulo: str, port: int) -> bytes:
    """Devuelve el contenido del launcher en bytes con CRLF."""
    NULL = "nul"          # dispositivo nulo de Windows
    lines = [
        "@echo off",
        "chcp 65001 > " + NULL,
        f"title Gestor de Horarios {titulo}",
        "set DIR=%~dp0",
        r"set ROOT=%DIR%..\..",
        "set DB_SRC=%DIR%horarios.db",
        f"set DB_TMP=%TEMP%\\horarios_{siglas}.db",
        "",
        "echo ----------------------------------------",
        f"echo  Gestor de Horarios {siglas}  (2026-2027)",
        "echo  UPCT",
        "echo ----------------------------------------",
        "",
        "REM Detectar comando Python (python o py launcher de Windows)",
        'set "PYTHON_CMD="',
        f"python --version > {NULL} 2>&1",
        'if not errorlevel 1 set "PYTHON_CMD=python"',
        "if not defined PYTHON_CMD (",
        f"    py --version > {NULL} 2>&1",
        '    if not errorlevel 1 set "PYTHON_CMD=py"',
        ")",
        "if not defined PYTHON_CMD (",
        "    echo.",
        "    echo [ERROR] Python no esta instalado o no esta en el PATH.",
        "    echo  1. Ve a https://www.python.org/downloads/",
        '    echo  2. Marca "Add Python to PATH" durante la instalacion',
        "    echo.",
        "    pause",
        "    exit /b 1",
        ")",
        "",
        "REM Verificar e instalar dependencias Python",
        "echo [INFO] Verificando dependencias...",
        r'%PYTHON_CMD% -m pip install -r "%ROOT%\requirements.txt" --quiet 2>' + NULL,
        "if errorlevel 1 (",
        "    echo [AVISO] No se pudieron instalar algunas dependencias. Continuando...",
        ")",
        "",
        "REM Copiar BD al directorio temporal (evita errores en Dropbox/OneDrive)",
        f'copy /Y "%DB_SRC%" "%DB_TMP%" >{NULL} 2>&1',
        "if errorlevel 1 (",
        "    echo [ERROR] No se pudo copiar la base de datos al directorio temporal.",
        "    echo         Verifica que existe horarios.db en la misma carpeta que este script.",
        "    pause",
        "    exit /b 1",
        ")",
        "",
        f"REM Matar proceso anterior en puerto {port}",
        f'for /f "tokens=5" %%a in (\'netstat -aon 2^>{NULL} ^| findstr /r ":{port} "\') do (',
        f"    taskkill /F /PID %%a > {NULL} 2>&1",
        ")",
        "",
        "set DB_PATH_OVERRIDE=%DB_TMP%",
        "set DB_BACKUP_TARGET=%DB_SRC%",
        "set CURSO_LABEL=2026-2027",
        "set CONFIG_PATH_OVERRIDE=%DIR%",
        f'start "" "http://localhost:{port}"',
        r'%PYTHON_CMD% "%ROOT%\servidor_horarios.py"',
        "",
        f'copy /Y "%DB_TMP%" "%DB_SRC%" >{NULL} 2>&1',
        "if errorlevel 1 (",
        "    echo [AVISO] No se pudo guardar la BD automaticamente.",
        "    echo         La copia temporal sigue en: %DB_TMP%",
        ") else (",
        "    echo [OK] Base de datos guardada.",
        ")",
        "pause",
    ]
    return "\r\n".join(lines).encode("utf-8")


GRADOS = [
    ("GIM",  "GIM \u2014 UPCT (2026-2027)",  "Iniciar Horarios GIM.bat",  8080),
    ("GIDI", "GIDI \u2014 UPCT (2026-2027)", "Iniciar GIDI.bat",          8080),
]

for siglas, titulo, filename, port in GRADOS:
    dest = ROOT / "horarios" / siglas / filename
    content = bat(siglas, titulo, port)
    dest.write_bytes(content)
    # Verificar
    crlf    = content.count(b"\r\n")
    lf_solo = content.count(b"\n") - crlf
    devnull = content.count(b"/dev/null")
    print(f"[OK] {dest.relative_to(ROOT)}  CRLF:{crlf}  LF-solo:{lf_solo}  /dev/null:{devnull}")

print("\nListo. Prueba a hacer doble clic en los .bat de GIM y GIDI.")
