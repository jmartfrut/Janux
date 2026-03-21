#!/usr/bin/env python3
"""
Servidor de Horarios — Gestor de Horarios Universitarios
Ejecutar: python3 servidor_horarios.py
Abrir: http://localhost:8080
"""
import http.server
import json
import sqlite3
import os
import sys
import webbrowser
from urllib.parse import urlparse, parse_qs

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── CONFIGURACIÓN ───────────────────────────────────────────────────────────
# Carga config.json si existe; si no, usa valores por defecto (compatibilidad)
# CONFIG_PATH_OVERRIDE permite apuntar a la carpeta de un grado concreto:
#   CONFIG_PATH_OVERRIDE="grados/GIDI" python3 servidor_horarios.py
_cfg_override = os.environ.get("CONFIG_PATH_OVERRIDE")
if _cfg_override:
    _cfg_path = os.path.join(_cfg_override, "config.json") if not _cfg_override.endswith(".json") else _cfg_override
else:
    _cfg_path = os.path.join(SCRIPT_DIR, "config.json")
if os.path.exists(_cfg_path):
    with open(_cfg_path, encoding="utf-8") as _f:
        CFG = json.load(_f)
else:
    CFG = {}

def _cfg(*keys, default=None):
    """Acceso seguro a CFG anidado: _cfg('server','port', default=8080)"""
    v = CFG
    for k in keys:
        if not isinstance(v, dict):
            return default
        v = v.get(k)
    return v if v is not None else default

# Institución y titulación
INSTITUTION_NAME    = _cfg("institution", "name",   default="Universidad")
INSTITUTION_ACRONYM = _cfg("institution", "acronym", default="UNIV")
DEGREE_NAME         = _cfg("degree", "name",   default="Titulación")
DEGREE_ACRONYM      = _cfg("degree", "acronym", default="GRADO")
LOGO_PNG            = _cfg("institution", "logo_png", default="docs/logo.png")
LOGO_PDF            = _cfg("institution", "logo_pdf", default="docs/logo.pdf")

# Servidor
PORT       = int(_cfg("server", "port",     default=8080))
DB_NAME    = _cfg("server", "db_name",      default="horarios.db")

# Soporta variable de entorno DB_PATH_OVERRIDE para usar copia local
# y evitar errores de I/O en rutas de red (Dropbox, OneDrive, etc.)
DB_PATH    = os.environ.get("DB_PATH_OVERRIDE") or os.path.join(SCRIPT_DIR, DB_NAME)
CURSO_LABEL = os.environ.get("CURSO_LABEL") or _cfg("server", "curso_label", default="2025-2026")

# Branding (colores CSS)
COLOR_PRIMARY       = _cfg("branding", "primary",       default="#1a3a6b")
COLOR_PRIMARY_LIGHT = _cfg("branding", "primary_light", default="#2855a0")
COLOR_ACCENT        = _cfg("branding", "accent",        default="#e8a020")
COLOR_BG            = _cfg("branding", "bg",            default="#f0f4f8")

# UI
DESTACADAS_BADGE = _cfg("ui", "destacadas_badge", default=f"PCEO {DEGREE_ACRONYM}")
EXPORT_PREFIX    = _cfg("ui", "export_prefix",    default=DEGREE_ACRONYM)

# Aulas por curso (para datalist en fAula — se inyectan como JSON)
# Formato: {"1": ["PS5","PS6"], "2": ["PS7"], ...}
AULAS_POR_CURSO = _cfg("degree_structure", "aulas_por_curso", default={})

# Tipos de actividad (para getActType en JS — se inyectan como JSON)
# Se filtran claves que empiezan por "_" (comentarios internos del JSON)
_DEFAULT_ACT_TYPES = {
    "AF1": {"label": "Teoría",       "aula_exact": [""],      "aula_startswith": [], "fichas_only": False},
    "AF2": {"label": "Laboratorio",  "aula_exact": ["LAB"],   "aula_startswith": [], "fichas_only": False},
    "AF4": {"label": "Informática",  "aula_exact": [],        "aula_startswith": ["INFO", "Aula:"], "fichas_only": False},
    "AF5": {"label": "Eval. continua (lectivo)", "aula_exact": [], "aula_startswith": [], "fichas_only": True},
    "AF6": {"label": "Eval. final",  "aula_exact": [],        "aula_startswith": [], "fichas_only": True},
}
_raw_at = _cfg("activity_types", default=_DEFAULT_ACT_TYPES)
ACTIVITY_TYPES = {k: v for k, v in _raw_at.items() if not k.startswith("_")} or _DEFAULT_ACT_TYPES

def init_db_paths():
    """Verify DB exists in script directory"""
    if not os.path.exists(DB_PATH):
        print(f"ERROR: No se encuentra {DB_PATH}")
        print("Coloca horarios.db en la misma carpeta que este script.")
        sys.exit(1)
    # Clean up any stale local copy from previous versions
    old_local = os.path.join(os.path.expanduser("~"), DB_NAME)
    if old_local != DB_PATH and os.path.exists(old_local):
        try:
            os.remove(old_local)
            print(f"  Eliminada copia antigua: {old_local}")
        except:
            pass

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def ensure_override_table():
    """Crea la tabla fichas_override si no existe (overrides manuales de fichas).
    A partir de la sesión 6: clave compuesta (codigo, grupo_key) para que la
    verificación manual sea independiente por grupo."""
    conn = get_db()
    table_info = conn.execute("PRAGMA table_info(fichas_override)").fetchall()
    cols = [r["name"] for r in table_info]
    if not table_info:
        # Tabla nueva con clave compuesta
        conn.execute("""
            CREATE TABLE fichas_override (
                codigo    TEXT NOT NULL,
                grupo_key TEXT NOT NULL DEFAULT '',
                motivo    TEXT DEFAULT '',
                ts        TEXT DEFAULT '',
                PRIMARY KEY (codigo, grupo_key)
            )
        """)
    elif "grupo_key" not in cols:
        # Migrar schema antiguo (PRIMARY KEY solo codigo) al nuevo (codigo+grupo_key)
        # Los overrides anteriores se descartan (no hay forma de saber a qué grupo pertenecían)
        conn.execute("ALTER TABLE fichas_override RENAME TO fichas_override_v1")
        conn.execute("""
            CREATE TABLE fichas_override (
                codigo    TEXT NOT NULL,
                grupo_key TEXT NOT NULL DEFAULT '',
                motivo    TEXT DEFAULT '',
                ts        TEXT DEFAULT '',
                PRIMARY KEY (codigo, grupo_key)
            )
        """)
        conn.execute("DROP TABLE fichas_override_v1")
    conn.commit()
    conn.close()

# ─── API HANDLERS ───

def api_get_all(params):
    """Get full schedule data structured by group"""
    conn = get_db()
    grupos = conn.execute("SELECT * FROM grupos ORDER BY curso, cuatrimestre, grupo").fetchall()
    franjas = conn.execute("SELECT * FROM franjas ORDER BY orden").fetchall()
    # Detectar si la BD tiene las columnas curso/cuatrimestre (añadidas en setup_grado.py v2)
    _asig_cols = {r["name"] for r in conn.execute("PRAGMA table_info(asignaturas)").fetchall()}
    if "curso" in _asig_cols and "cuatrimestre" in _asig_cols:
        asignaturas = conn.execute(
            "SELECT id, codigo, nombre, curso, cuatrimestre FROM asignaturas ORDER BY nombre"
        ).fetchall()
    else:
        asignaturas = conn.execute(
            "SELECT id, codigo, nombre, NULL as curso, NULL as cuatrimestre FROM asignaturas ORDER BY nombre"
        ).fetchall()

    # Fichas desde la BD (tabla fichas, joineada con asignaturas)
    fichas_rows = conn.execute("""
        SELECT a.codigo, f.creditos, f.af1, f.af2, f.af4, f.af5, f.af6
        FROM fichas f
        JOIN asignaturas a ON a.id = f.asignatura_id
    """).fetchall()
    fichas_by_codigo = {
        r["codigo"]: {
            "creditos": r["creditos"],
            "af1": r["af1"], "af2": r["af2"], "af4": r["af4"],
            "af5": r["af5"], "af6": r["af6"],
        }
        for r in fichas_rows
    }
    print(f"  Fichas cargadas desde BD: {len(fichas_by_codigo)} asignaturas")

    # Overrides manuales de fichas (clave compuesta "codigo::grupo_key" desde sesión 6)
    override_rows = conn.execute("SELECT codigo, grupo_key FROM fichas_override").fetchall() \
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='fichas_override'").fetchone() \
        else []
    fichas_override = [f'{r["codigo"]}::{r["grupo_key"]}' for r in override_rows]

    # Asignaturas destacadas (codigo::grupo_num)
    destacadas_rows = conn.execute("SELECT codigo, grupo_num FROM asignaturas_destacadas").fetchall() \
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='asignaturas_destacadas'").fetchone() \
        else []
    destacadas = [f'{r["codigo"]}::{r["grupo_num"]}' for r in destacadas_rows]

    result = {
        "franjas": [dict(f) for f in franjas],
        "asignaturas": [dict(a) for a in asignaturas],
        "grupos": {},
        "fichas": fichas_by_codigo,          # keyed by asignatura.codigo
        "fichas_override": fichas_override,  # lista de codigos con override manual
        "destacadas": destacadas,            # lista de "codigo::grupo_num" destacadas
    }

    for g in grupos:
        semanas = conn.execute(
            "SELECT * FROM semanas WHERE grupo_id=? ORDER BY numero", (g["id"],)
        ).fetchall()

        weeks = []
        for s in semanas:
            clases = conn.execute("""
                SELECT c.*, f.label as franja_label, f.orden as franja_orden,
                       a.codigo as asig_codigo, a.nombre as asig_nombre
                FROM clases c
                JOIN franjas f ON c.franja_id = f.id
                LEFT JOIN asignaturas a ON c.asignatura_id = a.id
                WHERE c.semana_id = ?
                ORDER BY f.orden
            """, (s["id"],)).fetchall()

            weeks.append({
                "semana_id": s["id"],
                "numero": s["numero"],
                "descripcion": s["descripcion"],
                "clases": [dict(c) for c in clases]
            })

        result["grupos"][g["clave"]] = {
            "id": g["id"],
            "curso": g["curso"],
            "cuatrimestre": g["cuatrimestre"],
            "grupo": g["grupo"],
            "aula": g["aula"],
            "semanas": weeks
        }

    conn.close()
    return result


def api_update_clase(data):
    """Update an existing class"""
    conn = get_db()
    clase_id = data.get("id")
    if not clase_id:
        conn.close()
        return {"error": "ID de clase requerido"}

    asignatura_id = resolve_asignatura(conn, data)

    conn.execute("""
        UPDATE clases SET asignatura_id=?, aula=?, subgrupo=?, observacion=?,
               es_no_lectivo=?, contenido=?
        WHERE id=?
    """, (
        asignatura_id,
        data.get("aula", ""),
        data.get("subgrupo", ""),
        data.get("observacion", ""),
        1 if data.get("es_no_lectivo") else 0,
        data.get("contenido", ""),
        clase_id
    ))
    conn.commit()
    conn.close()
    return {"ok": True, "id": clase_id}


def api_create_clase(data):
    """Create a new class entry"""
    conn = get_db()
    asignatura_id = resolve_asignatura(conn, data)

    scope = data.get("scope", "single")
    semana_id = data.get("semana_id")
    dia = data.get("dia")
    franja_id = data.get("franja_id")

    if scope == "single":
        semana_ids = [semana_id]
    else:
        sem = conn.execute("SELECT grupo_id, numero FROM semanas WHERE id=?", (semana_id,)).fetchone()
        if not sem:
            conn.close()
            return {"error": "Semana no encontrada"}
        if scope == "all":
            rows = conn.execute("SELECT id FROM semanas WHERE grupo_id=? ORDER BY numero", (sem["grupo_id"],)).fetchall()
        else:  # from
            rows = conn.execute("SELECT id FROM semanas WHERE grupo_id=? AND numero>=? ORDER BY numero",
                                (sem["grupo_id"], sem["numero"])).fetchall()
        semana_ids = [r["id"] for r in rows]

    force_insert = data.get("force_insert", False)
    created = []
    for sid in semana_ids:
        existing = None if force_insert else conn.execute(
            "SELECT id FROM clases WHERE semana_id=? AND dia=? AND franja_id=?",
            (sid, dia, franja_id)).fetchone()
        if existing:
            conn.execute("""
                UPDATE clases SET asignatura_id=?, aula=?, subgrupo=?, observacion=?,
                       es_no_lectivo=?, contenido=? WHERE id=?
            """, (asignatura_id, data.get("aula",""), data.get("subgrupo",""),
                  data.get("observacion",""), 1 if data.get("es_no_lectivo") else 0,
                  data.get("contenido",""), existing["id"]))
            created.append(existing["id"])
        else:
            conn.execute("""
                INSERT INTO clases (semana_id,dia,franja_id,asignatura_id,aula,subgrupo,observacion,es_no_lectivo,contenido)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (sid, dia, franja_id, asignatura_id, data.get("aula",""), data.get("subgrupo",""),
                  data.get("observacion",""), 1 if data.get("es_no_lectivo") else 0, data.get("contenido","")))
            created.append(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    conn.commit()
    conn.close()

    return {"ok": True, "ids": created}


def api_delete_clase(data):
    """Delete a class"""
    conn = get_db()
    clase_id = data.get("id")
    conn.execute("DELETE FROM clases WHERE id=?", (clase_id,))
    conn.commit()
    conn.close()

    return {"ok": True}


def api_manage_asignatura(data):
    """Create or update a subject"""
    conn = get_db()
    action = data.get("action", "create")
    if action == "create":
        conn.execute("INSERT OR IGNORE INTO asignaturas (codigo, nombre) VALUES (?,?)",
                     (data["codigo"], data["nombre"]))
    elif action == "update":
        conn.execute("UPDATE asignaturas SET nombre=? WHERE id=?", (data["nombre"], data["id"]))
    elif action == "delete":
        conn.execute("UPDATE clases SET asignatura_id=NULL WHERE asignatura_id=?", (data["id"],))
        conn.execute("DELETE FROM asignaturas WHERE id=?", (data["id"],))
    conn.commit()
    conn.close()

    return {"ok": True}


def resolve_asignatura(conn, data):
    """Resolve or create an asignatura, return its ID"""
    if data.get("es_no_lectivo"):
        return None
    codigo = data.get("asig_codigo", "").strip()
    nombre = data.get("asig_nombre", "").strip()
    if not codigo and not nombre:
        return None
    if codigo:
        row = conn.execute("SELECT id FROM asignaturas WHERE codigo=?", (codigo,)).fetchone()
        if row:
            return row["id"]
        if nombre:
            conn.execute("INSERT INTO asignaturas (codigo, nombre) VALUES (?,?)", (codigo, nombre))
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return None


def api_ficha_override(data):
    """Activa o desactiva el override manual de la comprobación de ficha para una
    asignatura+grupo concretos. grupo_key identifica el grupo (ej. '1_1C_grupo_1')."""
    from datetime import datetime
    codigo    = (data.get("codigo")    or "").strip()
    grupo_key = (data.get("grupo_key") or "").strip()
    action    = (data.get("action")    or "").strip()
    if not codigo:
        return {"error": "Código requerido"}
    conn = get_db()
    if action == "set":
        motivo = (data.get("motivo") or "").strip()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn.execute(
            "INSERT OR REPLACE INTO fichas_override (codigo, grupo_key, motivo, ts) VALUES (?,?,?,?)",
            (codigo, grupo_key, motivo, ts)
        )
    elif action == "unset":
        conn.execute("DELETE FROM fichas_override WHERE codigo=? AND grupo_key=?", (codigo, grupo_key))
    else:
        conn.close()
        return {"error": "Acción inválida (set|unset)"}
    conn.commit()
    conn.close()
    return {"ok": True}


# ─── FESTIVOS / NO-LECTIVOS ───

def ensure_festivos_table():
    """Crea la tabla festivos_calendario si no existe y migra días ya marcados en clases."""
    conn = get_db()
    is_new = not conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='festivos_calendario'"
    ).fetchone()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS festivos_calendario (
            fecha       TEXT PRIMARY KEY,
            tipo        TEXT DEFAULT 'no_lectivo',
            descripcion TEXT DEFAULT ''
        )
    """)
    conn.commit()

    # Migración: si la tabla es nueva, importar los días no-lectivos que ya había en clases
    if is_new:
        mapping = _parse_semana_date_ranges(conn)
        # mapping inverso: (cuatrimestre, numero, dia) -> fecha
        inv = {(v['cuatrimestre'], v['numero'], v['dia']): k for k, v in mapping.items()}
        # Dias únicos con es_no_lectivo=1 (cualquier grupo)
        rows = conn.execute("""
            SELECT DISTINCT g.cuatrimestre, s.numero, c.dia
            FROM clases c
            JOIN semanas s ON c.semana_id = s.id
            JOIN grupos  g ON s.grupo_id  = g.id
            WHERE c.es_no_lectivo = 1
        """).fetchall()
        for r in rows:
            key = (r['cuatrimestre'], r['numero'], r['dia'])
            fecha = inv.get(key)
            if fecha:
                conn.execute(
                    "INSERT OR IGNORE INTO festivos_calendario (fecha, tipo, descripcion) VALUES (?,?,?)",
                    (fecha, 'no_lectivo', 'No lectivo')
                )
        conn.commit()
        print(f"  [festivos] Migrados {len(rows)} días no-lectivos existentes a festivos_calendario")

    conn.close()


def _parse_semana_date_ranges(conn):
    """Parsea las descripciones de semanas y devuelve un dict
    { 'YYYY-MM-DD': {'cuatrimestre': '1C'|'2C', 'numero': N, 'dia': 'LUNES'|...} }"""
    import re
    from datetime import date, timedelta

    MESES = {
        'ENERO': 1, 'FEBRERO': 2, 'MARZO': 3, 'ABRIL': 4,
        'MAYO': 5, 'JUNIO': 6, 'JULIO': 7, 'AGOSTO': 8,
        'SEPTIEMBRE': 9, 'OCTUBRE': 10, 'NOVIEMBRE': 11, 'DICIEMBRE': 12
    }
    DIAS = ['LUNES', 'MARTES', 'MIÉRCOLES', 'JUEVES', 'VIERNES']

    year_parts = CURSO_LABEL.split('-')
    try:
        year_start = int(year_parts[0])
        year_end   = int(year_parts[1])
    except Exception:
        year_start, year_end = 2026, 2027

    rows = conn.execute("""
        SELECT DISTINCT g.cuatrimestre, s.numero, s.descripcion
        FROM semanas s JOIN grupos g ON s.grupo_id = g.id
        ORDER BY g.cuatrimestre, s.numero
    """).fetchall()

    mapping = {}
    for row in rows:
        cuat   = row['cuatrimestre']
        numero = row['numero']
        desc   = row['descripcion']
        m = re.search(r'(\d+)\s+([A-ZÁÉÍÓÚÑ]+)\s+A\s+(\d+)\s+([A-ZÁÉÍÓÚÑ]+)', desc)
        if not m:
            continue
        start_day   = int(m.group(1))
        start_month = MESES.get(m.group(2).upper())
        if not start_month:
            continue
        year = year_end if start_month < 7 else year_start
        try:
            start = date(year, start_month, start_day)
        except Exception:
            continue
        for i, dia in enumerate(DIAS):
            d = start + timedelta(days=i)
            mapping[d.isoformat()] = {'cuatrimestre': cuat, 'numero': numero, 'dia': dia}

    return mapping


def _set_no_lectivo_clases(conn, cuatrimestre, numero, dia, value, descripcion=''):
    """Propaga es_no_lectivo a todas las clases del día indicado en todos los grupos."""
    semana_ids = conn.execute("""
        SELECT s.id FROM semanas s
        JOIN grupos g ON s.grupo_id = g.id
        WHERE g.cuatrimestre = ? AND s.numero = ?
    """, (cuatrimestre, numero)).fetchall()

    franjas = conn.execute("SELECT id FROM franjas ORDER BY orden").fetchall()

    for s in semana_ids:
        sid = s['id']
        existing = conn.execute(
            "SELECT id, asignatura_id FROM clases WHERE semana_id=? AND dia=?",
            (sid, dia)
        ).fetchall()

        if value == 1:
            if existing:
                conn.execute(
                    "UPDATE clases SET es_no_lectivo=1 WHERE semana_id=? AND dia=?",
                    (sid, dia)
                )
            else:
                franja_id = franjas[0]['id'] if franjas else 1
                conn.execute("""
                    INSERT INTO clases
                        (semana_id, dia, franja_id, asignatura_id, aula, subgrupo,
                         observacion, es_no_lectivo, contenido)
                    VALUES (?, ?, ?, NULL, '', '', NULL, 1, ?)
                """, (sid, dia, franja_id, descripcion or 'NO LECTIVO'))
        else:
            if existing:
                has_real = any(r['asignatura_id'] is not None for r in existing)
                if has_real:
                    conn.execute(
                        "UPDATE clases SET es_no_lectivo=0 WHERE semana_id=? AND dia=?",
                        (sid, dia)
                    )
                else:
                    conn.execute(
                        "DELETE FROM clases WHERE semana_id=? AND dia=? AND es_no_lectivo=1",
                        (sid, dia)
                    )


def api_get_festivos(params):
    """GET /api/festivos — devuelve todos los días marcados en festivos_calendario."""
    conn = get_db()
    rows = conn.execute(
        "SELECT fecha, tipo, descripcion FROM festivos_calendario ORDER BY fecha"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def api_set_festivo(data):
    """POST /api/festivos/set — añade, modifica o elimina un día festivo/no-lectivo
    y propaga el cambio a es_no_lectivo en todas las clases correspondientes."""
    conn = get_db()
    fecha       = (data.get('fecha')       or '').strip()
    tipo        = (data.get('tipo')        or 'no_lectivo').strip()
    descripcion = (data.get('descripcion') or '').strip()
    action      = (data.get('action')      or 'set').strip()

    if not fecha:
        conn.close()
        return {'error': 'fecha requerida (YYYY-MM-DD)'}

    mapping = _parse_semana_date_ranges(conn)
    slot    = mapping.get(fecha)

    if action == 'delete':
        conn.execute("DELETE FROM festivos_calendario WHERE fecha=?", (fecha,))
        if slot:
            _set_no_lectivo_clases(conn, slot['cuatrimestre'], slot['numero'],
                                   slot['dia'], 0)
    else:
        conn.execute(
            "INSERT OR REPLACE INTO festivos_calendario (fecha, tipo, descripcion) VALUES (?,?,?)",
            (fecha, tipo, descripcion)
        )
        if slot:
            _set_no_lectivo_clases(conn, slot['cuatrimestre'], slot['numero'],
                                   slot['dia'], 1, descripcion)

    conn.commit()
    conn.close()
    return {'ok': True, 'slot': slot}


def ensure_finales_checklist_table():
    """Crea la tabla finales_excluidas si no existe.
    Guarda las asignaturas DESMARCADAS (excluidas) de cada período.
    Por omisión todas están marcadas; solo se almacenan las excepciones."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS finales_excluidas (
            periodo     TEXT NOT NULL,
            curso       TEXT NOT NULL,
            asig_codigo TEXT NOT NULL,
            asig_nombre TEXT DEFAULT '',
            PRIMARY KEY (periodo, curso, asig_codigo)
        )
    """)
    conn.commit()
    conn.close()


def api_get_finales_checklist(params):
    """GET /api/finales/checklist — devuelve las asignaturas excluidas."""
    conn = get_db()
    rows = conn.execute(
        "SELECT periodo, curso, asig_codigo, asig_nombre FROM finales_excluidas ORDER BY periodo, curso"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def api_toggle_finales_checklist(data):
    """POST /api/finales/checklist/toggle — marca o desmarca una asignatura."""
    conn   = get_db()
    periodo  = (data.get('periodo')     or '').strip()
    curso    = (data.get('curso')       or '').strip()
    asig_cod = (data.get('asig_codigo') or '').strip()
    asig_nom = (data.get('asig_nombre') or '').strip()
    checked  = int(data.get('checked', 1))
    if not periodo or not curso or not asig_cod:
        conn.close()
        return {'error': 'periodo, curso y asig_codigo requeridos'}
    if checked:
        conn.execute(
            "DELETE FROM finales_excluidas WHERE periodo=? AND curso=? AND asig_codigo=?",
            (periodo, curso, asig_cod)
        )
    else:
        conn.execute(
            "INSERT OR REPLACE INTO finales_excluidas (periodo, curso, asig_codigo, asig_nombre) VALUES (?,?,?,?)",
            (periodo, curso, asig_cod, asig_nom)
        )
    conn.commit()
    conn.close()
    return {'ok': True}


def ensure_finales_table():
    """Crea la tabla examenes_finales si no existe y migra columnas nuevas."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS examenes_finales (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha          TEXT NOT NULL,
            curso          TEXT NOT NULL,
            asig_nombre    TEXT DEFAULT '',
            asig_codigo    TEXT DEFAULT '',
            turno          TEXT DEFAULT 'mañana',
            observacion    TEXT DEFAULT '',
            auto_generated INTEGER DEFAULT 0
        )
    """)
    # Migración: añadir auto_generated si la tabla ya existía sin ella
    cols = [r[1] for r in conn.execute("PRAGMA table_info(examenes_finales)").fetchall()]
    if 'auto_generated' not in cols:
        conn.execute("ALTER TABLE examenes_finales ADD COLUMN auto_generated INTEGER DEFAULT 0")
    conn.commit()
    conn.close()


def api_get_finales(params):
    """GET /api/finales — devuelve todos los exámenes finales."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM examenes_finales ORDER BY fecha, curso"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def api_set_final(data):
    """POST /api/finales/set — añade, actualiza o elimina un examen final.
    Al editar manualmente un examen auto-generado, se convierte en manual (auto_generated=0)."""
    conn = get_db()
    action = (data.get('action') or 'set').strip()
    if action == 'delete':
        id_ = data.get('id')
        if id_:
            conn.execute("DELETE FROM examenes_finales WHERE id=?", (id_,))
    else:
        id_      = data.get('id')
        fecha    = (data.get('fecha')       or '').strip()
        curso    = (data.get('curso')       or '').strip()
        asig_nom = (data.get('asig_nombre') or '').strip()
        asig_cod = (data.get('asig_codigo') or '').strip()
        turno    = (data.get('turno')       or 'mañana').strip()
        obs      = (data.get('observacion') or '').strip()
        auto_gen = int(data.get('auto_generated', 0))
        if not fecha or not curso:
            conn.close()
            return {'error': 'fecha y curso requeridos'}
        if id_:
            # Al editar → siempre se vuelve manual (auto_generated=0)
            conn.execute("""
                UPDATE examenes_finales
                SET fecha=?, curso=?, asig_nombre=?, asig_codigo=?, turno=?, observacion=?, auto_generated=0
                WHERE id=?
            """, (fecha, curso, asig_nom, asig_cod, turno, obs, id_))
        else:
            conn.execute("""
                INSERT INTO examenes_finales
                    (fecha, curso, asig_nombre, asig_codigo, turno, observacion, auto_generated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (fecha, curso, asig_nom, asig_cod, turno, obs, auto_gen))
    conn.commit()
    conn.close()
    return {'ok': True}


def api_batch_set_finales(data):
    """POST /api/finales/batch-set — inserta múltiples exámenes en una transacción."""
    conn  = get_db()
    exams = data.get('exams', [])
    if not isinstance(exams, list):
        conn.close()
        return {'error': 'exams debe ser una lista'}
    inserted = 0
    for e in exams:
        fecha    = (e.get('fecha')       or '').strip()
        curso    = (e.get('curso')       or '').strip()
        asig_nom = (e.get('asig_nombre') or '').strip()
        asig_cod = (e.get('asig_codigo') or '').strip()
        turno    = (e.get('turno')       or 'mañana').strip()
        obs      = (e.get('observacion') or '').strip()
        auto_gen = int(e.get('auto_generated', 1))
        if not fecha or not curso:
            continue
        conn.execute("""
            INSERT INTO examenes_finales
                (fecha, curso, asig_nombre, asig_codigo, turno, observacion, auto_generated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (fecha, curso, asig_nom, asig_cod, turno, obs, auto_gen))
        inserted += 1
    conn.commit()
    conn.close()
    return {'ok': True, 'inserted': inserted}


def api_reset_auto_finales(data):
    """POST /api/finales/reset-auto — elimina los exámenes auto-generados de un rango de fechas."""
    conn        = get_db()
    fecha_ini   = (data.get('fecha_inicio') or '').strip()
    fecha_fin   = (data.get('fecha_fin')    or '').strip()
    if not fecha_ini or not fecha_fin:
        conn.close()
        return {'error': 'fecha_inicio y fecha_fin requeridos'}
    res = conn.execute(
        "DELETE FROM examenes_finales WHERE auto_generated=1 AND fecha>=? AND fecha<=?",
        (fecha_ini, fecha_fin)
    )
    conn.commit()
    conn.close()
    return {'ok': True, 'deleted': res.rowcount}


def ensure_destacadas_table():
    """Crea la tabla asignaturas_destacadas si no existe e inserta datos iniciales.
    Almacena pares (codigo, grupo_num) para resaltar asignaturas específicas
    con fondo verde y bordes sombreados en la vista de horario."""
    # Datos iniciales de asignaturas a destacar (codigo, grupo_num)
    INITIAL_DESTACADAS = [
        ("508102010", "2"),  # Elast. y Resist. de Materiales grupo 2
        ("508103002", "1"),  # Teor. De Mec. y Maquinas grupo 1
        ("508103003", "1"),  # Teor. de Estructuras grupo 1
        ("508103011", "1"),  # Diseño de Elementos. de Maq. I grupo 1
        ("508103006", "2"),  # Materiales en Ingeniería grupo 2
        ("508103004", "2"),  # Ing. de Fluidos y Maq. Hidr. grupo 2
        ("508103008", "1"),  # Const. Industriales I grupo 1
        ("508103012", "1"),  # Diseño de Elementos. de Maq. II grupo 1
        ("508103009", "1"),  # Ingeniería de Fabricación grupo 1
        ("508104003", "1"),  # Máquinas Térmicas grupo 1 1c
        ("508104002", "1"),  # Fund. Elect. Industrial grupo 1 1c
    ]
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS asignaturas_destacadas (
            codigo    TEXT NOT NULL,
            grupo_num TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (codigo, grupo_num)
        )
    """)
    for codigo, grupo_num in INITIAL_DESTACADAS:
        conn.execute(
            "INSERT OR IGNORE INTO asignaturas_destacadas (codigo, grupo_num) VALUES (?,?)",
            (codigo, grupo_num)
        )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM asignaturas_destacadas").fetchone()[0]
    print(f"  Asignaturas destacadas: {count} entradas")
    conn.close()


def api_db_backup(_data):
    """POST /api/db/backup — fuerza WAL checkpoint y crea copia de seguridad con timestamp."""
    import shutil, datetime
    # 1. Forzar WAL checkpoint para vaciar el journal a la BD principal
    conn = get_db()
    try:
        conn.execute("PRAGMA wal_checkpoint(FULL)")
        conn.commit()
    finally:
        conn.close()
    # 2. Crear carpeta backups/ junto a la BD si no existe
    db_dir = os.path.dirname(os.path.abspath(DB_PATH))
    backup_dir = os.path.join(db_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    # 3. Copiar la BD con timestamp
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    db_basename = os.path.splitext(os.path.basename(DB_PATH))[0]
    backup_name = f"{db_basename}_backup_{ts}.db"
    backup_path = os.path.join(backup_dir, backup_name)
    shutil.copy2(DB_PATH, backup_path)
    # 4. Mantener solo los 10 backups más recientes
    all_backups = sorted(
        [f for f in os.listdir(backup_dir) if f.startswith(f"{db_basename}_backup_") and f.endswith(".db")]
    )
    for old in all_backups[:-10]:
        try:
            os.remove(os.path.join(backup_dir, old))
        except Exception:
            pass
    return {"ok": True, "backup": backup_name, "path": backup_path}


def api_toggle_destacada(data):
    """POST /api/destacada/toggle — añade o elimina un par (codigo, grupo_num) de asignaturas_destacadas."""
    codigo    = data.get("codigo", "").strip()
    grupo_num = str(data.get("grupo_num", "")).strip()
    if not codigo:
        return {"ok": False, "error": "codigo requerido"}
    conn = get_db()
    exists = conn.execute(
        "SELECT 1 FROM asignaturas_destacadas WHERE codigo=? AND grupo_num=?",
        (codigo, grupo_num)
    ).fetchone()
    if exists:
        conn.execute(
            "DELETE FROM asignaturas_destacadas WHERE codigo=? AND grupo_num=?",
            (codigo, grupo_num)
        )
        action = "removed"
    else:
        conn.execute(
            "INSERT OR IGNORE INTO asignaturas_destacadas (codigo, grupo_num) VALUES (?,?)",
            (codigo, grupo_num)
        )
        action = "added"
    conn.commit()
    conn.close()
    return {"ok": True, "action": action, "codigo": codigo, "grupo_num": grupo_num}


# ─── ROUTE MAP ───

API_ROUTES = {
    "/api/schedule":       ("GET",  api_get_all),
    "/api/clase/update":   ("POST", api_update_clase),
    "/api/clase/create":   ("POST", api_create_clase),
    "/api/clase/delete":   ("POST", api_delete_clase),
    "/api/asignatura":     ("POST", api_manage_asignatura),
    "/api/ficha-override": ("POST", api_ficha_override),
    "/api/festivos":       ("GET",  api_get_festivos),
    "/api/festivos/set":   ("POST", api_set_festivo),
    "/api/finales":                  ("GET",  api_get_finales),
    "/api/finales/set":              ("POST", api_set_final),
    "/api/finales/batch-set":        ("POST", api_batch_set_finales),
    "/api/finales/reset-auto":       ("POST", api_reset_auto_finales),
    "/api/finales/checklist":        ("GET",  api_get_finales_checklist),
    "/api/finales/checklist/toggle": ("POST", api_toggle_finales_checklist),
    "/api/db/backup":                ("POST", api_db_backup),
    "/api/destacada/toggle":         ("POST", api_toggle_destacada),
}

TEMPLATE_PATH = None  # Plantilla no requerida; el Excel se genera desde cero


class HorarioHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.serve_html()
        elif parsed.path == "/api/exportar_excel":
            self.serve_excel_export()
        elif parsed.path == "/api/finales/export-pdf":
            params = parse_qs(parsed.query)
            self.serve_finales_pdf(params)
        elif parsed.path == "/api/logo":
            self.serve_logo()
        elif parsed.path == "/api/logo_svg":
            self.serve_logo_svg()
        elif parsed.path in API_ROUTES and API_ROUTES[parsed.path][0] == "GET":
            params = parse_qs(parsed.query)
            result = API_ROUTES[parsed.path][1](params)
            self.send_json(result)
        else:
            self.send_error(404)

    def serve_excel_export(self):
        import tempfile, importlib.util, zipfile
        try:
            export_mod_path = os.path.join(SCRIPT_DIR, "exportar_excel.py")
            if not os.path.exists(export_mod_path):
                self.send_json({"error": "exportar_excel.py no encontrado"}, 500)
                return
            spec = importlib.util.spec_from_file_location("exportar_excel", export_mod_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            # Generar un xlsx por curso en directorio temporal
            tmp_dir = tempfile.mkdtemp()
            archivos = mod.exportar_todos_por_curso(DB_PATH, TEMPLATE_PATH, tmp_dir, degree_acronym=DEGREE_ACRONYM)

            # Empaquetar en ZIP
            curso_label = CURSO_LABEL.replace("-", "_")
            zip_name = f"Horarios_{EXPORT_PREFIX}_{curso_label}.zip"
            import io
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for curso_num, xlsx_path in archivos:
                    arcname = os.path.basename(xlsx_path)
                    zf.write(xlsx_path, arcname)
                    os.unlink(xlsx_path)
            try:
                os.rmdir(tmp_dir)
            except Exception:
                pass
            data = buf.getvalue()

            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{zip_name}"')
            self.send_header("Content-Length", len(data))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            import traceback
            self.send_json({"error": str(e), "trace": traceback.format_exc()}, 500)

    def serve_logo(self):
        """GET /api/logo — devuelve el logo de la institución como PNG (genera si no existe desde PDF)."""
        import subprocess as _sp
        logo_pdf = os.path.join(SCRIPT_DIR, LOGO_PDF)
        logo_png = os.path.join(SCRIPT_DIR, LOGO_PNG)
        if not os.path.exists(logo_png) and os.path.exists(logo_pdf):
            try:
                _sp.run(['pdftoppm', '-r', '150', '-png', '-singlefile',
                         logo_pdf, logo_png[:-4]], capture_output=True, timeout=15)
            except Exception:
                pass
        if not os.path.exists(logo_png):
            self.send_response(404); self.end_headers(); return
        data = open(logo_png, 'rb').read()
        self.send_response(200)
        self.send_header('Content-Type', 'image/png')
        self.send_header('Content-Length', len(data))
        self.send_header('Cache-Control', 'public, max-age=86400')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)

    def serve_logo_svg(self):
        """GET /api/logo_svg — devuelve el logo IAnus en formato SVG."""
        svg_path = os.path.join(SCRIPT_DIR, "docs", "logo_ianus.svg")
        if not os.path.exists(svg_path):
            self.send_response(404); self.end_headers(); return
        data = open(svg_path, 'rb').read()
        self.send_response(200)
        self.send_header('Content-Type', 'image/svg+xml')
        self.send_header('Content-Length', len(data))
        self.send_header('Cache-Control', 'public, max-age=86400')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)

    def serve_finales_pdf(self, params):
        """GET /api/finales/export-pdf — genera PDF completo con los 3 períodos."""
        import importlib.util, traceback
        try:
            mod_path = os.path.join(SCRIPT_DIR, "exportar_finales_pdf.py")
            if not os.path.exists(mod_path):
                self.send_json({"error": "exportar_finales_pdf.py no encontrado"}, 500)
                return

            spec = importlib.util.spec_from_file_location("exportar_finales_pdf", mod_path)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            yEnd = int(CURSO_LABEL.split('-')[1]) if '-' in CURSO_LABEL else 2026
            PERIODS = [
                ('Enero - 1er Cuatrimestre',  f'{yEnd}-01-07', f'{yEnd}-01-31'),
                ('Junio - 2o Cuatrimestre',   f'{yEnd}-05-31', f'{yEnd}-06-22'),
                ('Extraordinaria (Jun-Jul)',   f'{yEnd}-06-24', f'{yEnd}-07-17'),
            ]

            conn = get_db()
            conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))

            # Mapa nombre→código desde la tabla de asignaturas (para rellenar códigos vacíos)
            # La tabla clases usa FK asignatura_id → asignaturas(id, codigo, nombre)
            code_map = {}
            try:
                for row in conn.execute(
                    "SELECT DISTINCT a.nombre AS asig_nombre, a.codigo AS asig_codigo "
                    "FROM clases c JOIN asignaturas a ON a.id = c.asignatura_id "
                    "WHERE a.codigo IS NOT NULL AND a.codigo != ''"
                ).fetchall():
                    if row['asig_nombre'] and row['asig_codigo']:
                        code_map[row['asig_nombre']] = row['asig_codigo']
            except Exception:
                pass

            periods_data = []
            for label, start, end in PERIODS:
                rows = conn.execute(
                    "SELECT * FROM examenes_finales "
                    "WHERE fecha >= ? AND fecha <= ? ORDER BY fecha, curso",
                    (start, end)
                ).fetchall()
                # Rellenar asig_codigo si está vacío
                exams = []
                for r in rows:
                    e = dict(r)
                    if not e.get('asig_codigo'):
                        e['asig_codigo'] = code_map.get(e.get('asig_nombre', ''), '')
                    exams.append(e)
                periods_data.append({'label': label, 'start': start, 'end': end, 'exams': exams})
            conn.close()

            pdf_bytes = mod.generar_pdf_finales_all(periods_data, CURSO_LABEL, degree_name=DEGREE_NAME, degree_acronym=DEGREE_ACRONYM)
            safe_label = CURSO_LABEL.replace('-', '_')
            filename   = f"Finales_{EXPORT_PREFIX}_{safe_label}.pdf"

            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", len(pdf_bytes))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(pdf_bytes)
        except Exception as e:
            self.send_json({"error": str(e), "trace": traceback.format_exc()}, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path in API_ROUTES and API_ROUTES[parsed.path][0] == "POST":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body) if body else {}
            try:
                result = API_ROUTES[parsed.path][1](data)
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
        else:
            self.send_error(404)

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def serve_html(self):
        html = generate_html()
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        msg = format % args
        if "/api/" in msg:
            sys.stderr.write(f"  📡 {msg}\n")


def generate_html():
    return (HTML_TEMPLATE
            .replace('MIERCOLES_PLACEHOLDER',           'MIÉRCOLES')
            .replace('CURSO_LABEL_PLACEHOLDER',         CURSO_LABEL)
            .replace('DEGREE_ACRONYM_PLACEHOLDER',      DEGREE_ACRONYM)
            .replace('DEGREE_NAME_PLACEHOLDER',         DEGREE_NAME)
            .replace('INSTITUTION_ACRONYM_PLACEHOLDER', INSTITUTION_ACRONYM)
            .replace('INSTITUTION_NAME_PLACEHOLDER',    INSTITUTION_NAME)
            .replace('COLOR_PRIMARY_PLACEHOLDER',       COLOR_PRIMARY)
            .replace('COLOR_PRIMARY_LIGHT_PLACEHOLDER', COLOR_PRIMARY_LIGHT)
            .replace('COLOR_ACCENT_PLACEHOLDER',        COLOR_ACCENT)
            .replace('COLOR_BG_PLACEHOLDER',            COLOR_BG)
            .replace('DESTACADAS_BADGE_PLACEHOLDER',    DESTACADAS_BADGE)
            .replace('EXPORT_PREFIX_PLACEHOLDER',       EXPORT_PREFIX)
            .replace('AULAS_POR_CURSO_PLACEHOLDER',     json.dumps(AULAS_POR_CURSO, ensure_ascii=False)))


# ─── HTML ───

HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Horario DEGREE_ACRONYM_PLACEHOLDER – Base de Datos</title>
<style>
:root {
  --primary: COLOR_PRIMARY_PLACEHOLDER; --primary-light: COLOR_PRIMARY_LIGHT_PLACEHOLDER; --accent: COLOR_ACCENT_PLACEHOLDER; --bg: COLOR_BG_PLACEHOLDER;
  --card: #fff; --border: #d0d8e4; --text: #1e2a3a; --text-light: #5a6a7a;
  --success: #27ae60; --danger: #e74c3c; --warning: #f39c12; --no-lectivo: #e8ecf0; --hover: #eef2f8;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
header{background:linear-gradient(135deg,var(--primary),var(--primary-light));color:#fff;padding:18px 30px;display:flex;align-items:center;justify-content:space-between;box-shadow:0 3px 10px rgba(0,0,0,.2)}
header h1{font-size:1.4rem;font-weight:700}
.subtitle{font-size:.85rem;opacity:.8;margin-top:3px}
.header-right{display:flex;gap:10px;align-items:center}
.db-badge{background:var(--success);color:#fff;padding:4px 10px;border-radius:12px;font-size:.72rem;font-weight:700;letter-spacing:.5px;display:flex;align-items:center;gap:5px}
.toolbar{background:var(--card);border-bottom:1px solid var(--border);padding:14px 30px;display:flex;gap:14px;align-items:center;flex-wrap:wrap;box-shadow:0 2px 4px rgba(0,0,0,.05)}
.toolbar-group{display:flex;gap:8px;align-items:center}
.toolbar label{font-size:.8rem;font-weight:600;color:var(--text-light);text-transform:uppercase;letter-spacing:.5px}
select,input{border:1.5px solid var(--border);border-radius:6px;padding:7px 11px;font-size:.88rem;background:#fff;color:var(--text);outline:none;transition:border .2s}
select:focus,input:focus{border-color:var(--primary-light)}
.btn{padding:7px 16px;border:none;border-radius:6px;font-size:.85rem;font-weight:600;cursor:pointer;transition:all .2s;display:flex;align-items:center;gap:6px}
.btn-primary{background:var(--primary);color:#fff} .btn-primary:hover{background:var(--primary-light);transform:translateY(-1px)}
.btn-success{background:var(--success);color:#fff} .btn-success:hover{background:#219a52}
.btn-danger{background:var(--danger);color:#fff}
.btn-outline{background:#fff;color:var(--primary);border:1.5px solid var(--primary)} .btn-outline:hover{background:var(--hover)}
.btn-sm{padding:4px 10px;font-size:.78rem}
.view-tabs{display:flex;gap:0;background:var(--bg);border-radius:8px;padding:3px}
.tab-btn{padding:6px 16px;border:none;border-radius:6px;cursor:pointer;font-size:.82rem;font-weight:600;background:transparent;color:var(--text-light);transition:all .2s}
.tab-btn.active{background:#fff;color:var(--primary);box-shadow:0 1px 4px rgba(0,0,0,.12)}
.main{padding:24px 30px}
.schedule-container{background:var(--card);border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.08);overflow:hidden}
.schedule-table{width:100%;border-collapse:collapse;table-layout:fixed}
.schedule-table th,.schedule-table td{border:1px solid var(--border)}
.sch-th-time{background:var(--primary-light);color:#fff;padding:12px 10px;text-align:center;font-size:.82rem;font-weight:700;text-transform:uppercase;width:110px}
.sch-th-day{background:var(--primary);color:#fff;padding:12px 10px;text-align:center;font-size:.82rem;font-weight:700;text-transform:uppercase}
.sch-time-cell{padding:10px 8px;text-align:center;font-size:.78rem;font-weight:700;color:#fff;background:var(--primary);width:110px}
.sch-cell{padding:6px 8px;min-height:70px;cursor:pointer;transition:background .15s;vertical-align:middle}
.sch-cell:hover{background:#e8f0fc}
.sch-empty{background:#fafbfc} .sch-empty:hover{background:#eef2f8}
.sch-no-lectivo{background:linear-gradient(135deg,#e8ecf0,#d5dbe3);cursor:default;text-align:center;vertical-align:middle}
.sch-no-lectivo-single{background:var(--no-lectivo);cursor:default;text-align:center;vertical-align:middle}
.sch-divider-row td{background:#c8d0db;padding:3px 0;border:none;height:6px;line-height:0}
.no-lectivo-full{font-size:1.1rem;font-weight:700;color:var(--text-light);display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%}
.subject-card{width:100%;border-radius:6px;padding:6px 8px;font-size:.76rem;line-height:1.4;position:relative}
.pceo-btn{position:absolute;top:3px;right:3px;background:rgba(0,0,0,.12);border:none;cursor:pointer;font-size:.85rem;line-height:1;padding:3px 4px;border-radius:4px;opacity:0;transition:opacity .15s,background .15s;color:#888}
.subject-card:hover .pceo-btn{opacity:1}
.pceo-btn.active{opacity:1!important;color:#e8a020;text-shadow:0 0 8px rgba(232,160,32,.7);background:rgba(0,0,0,.15)}
.pceo-btn:hover{background:rgba(0,0,0,.22);color:#555}
.color-destacada .pceo-btn{color:rgba(255,255,255,.6)}
.color-destacada .pceo-btn.active{color:#f5b940;background:rgba(0,0,0,.2)}
.color-destacada .pceo-btn:hover{background:rgba(0,0,0,.25);color:#fff}
.subject-name{font-weight:700;font-size:.79rem;margin-bottom:2px}
.subject-code{font-size:.7rem;opacity:.7}
.subject-tags{display:flex;flex-wrap:wrap;gap:3px;margin-top:4px}
.tag{font-size:.65rem;padding:1px 5px;border-radius:3px;font-weight:600;background:rgba(255,255,255,.35);border:1px solid rgba(0,0,0,.1)}
.obs-tag{background:#fff3cd;color:#856404;border-color:#ffc107}
.color-0{background:#f2e2e2;border-left:3px solid #a91818;color:#620e0e}
.color-1{background:#f2e8e2;border-left:3px solid #a95218;color:#622f0e}
.color-2{background:#f2efe2;border-left:3px solid #a98c18;color:#62510e}
.color-3{background:#eff2e2;border-left:3px solid #8ca918;color:#51620e}
.color-4{background:#e8f2e2;border-left:3px solid #52a918;color:#2f620e}
.color-5{background:#e2f2e2;border-left:3px solid #18a918;color:#0e620e}
.color-6{background:#e2f2e8;border-left:3px solid #18a952;color:#0e622f}
.color-7{background:#e2f2ef;border-left:3px solid #18a98c;color:#0e6251}
.color-8{background:#e2eff2;border-left:3px solid #188ca9;color:#0e5162}
.color-9{background:#e2e8f2;border-left:3px solid #1852a9;color:#0e2f62}
.color-10{background:#e2e2f2;border-left:3px solid #1818a9;color:#0e0e62}
.color-11{background:#e8e2f2;border-left:3px solid #5218a9;color:#2f0e62}
.color-12{background:#efe2f2;border-left:3px solid #8c18a9;color:#510e62}
.color-13{background:#f2e2ef;border-left:3px solid #a9188c;color:#620e51}
.color-14{background:#f2e2e8;border-left:3px solid #a91852;color:#620e2f}
.color-parcial{background:#fee2e2;border-left:4px solid #dc2626;color:#7f1d1d}
.color-parcial .tag{background:rgba(220,38,38,.15);border-color:rgba(220,38,38,.3)}
.color-destacada{background:#1a7a2e;border-left:4px solid #14571f;color:#ffffff;box-shadow:0 2px 8px rgba(26,122,46,.35)}
.color-destacada .subject-name,.color-destacada .subject-code{color:#ffffff}
.color-destacada .tag{background:rgba(255,255,255,.2);border-color:rgba(255,255,255,.35);color:#ffffff}
.sch-cell-destacada{background:#ffffff!important;box-shadow:none!important}
.parcial-badge{font-size:.68rem;font-weight:800;color:#dc2626;letter-spacing:.04em;display:block;margin-bottom:2px}
.no-lectivo-label{font-size:.72rem;color:var(--text-light);font-style:italic;text-align:center;width:100%}
.empty-label{font-size:.72rem;color:#c5cdd6;text-align:center;width:100%}
.sch-split{padding:0;vertical-align:top}
.split-badge{font-size:.6rem;font-weight:800;color:#92400e;background:#fef3c7;border-bottom:1px solid #fcd34d;text-align:center;padding:2px 4px;letter-spacing:.08em;text-transform:uppercase}
.split-cards{display:flex;flex-direction:column}
.split-divider{height:1px;background:var(--border);margin:0}
.split-cards .subject-card{border-radius:0;margin:0;border-left-width:4px;padding:5px 7px}
.split-cards .subject-card:first-child{border-top-left-radius:0}
.split-add{font-size:.65rem;color:#c5cdd6;text-align:center;padding:3px;cursor:pointer;transition:color .15s}
.split-add:hover{color:var(--primary)}
.week-nav{display:flex;align-items:center;gap:12px;background:var(--card);border-radius:10px;padding:12px 20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.06);flex-wrap:wrap}
.week-dots{display:flex;gap:5px;flex-wrap:wrap;justify-content:center}
.week-dot{width:22px;height:22px;border-radius:50%;border:2px solid var(--border);cursor:pointer;font-size:.65rem;font-weight:700;display:flex;align-items:center;justify-content:center;transition:all .2s;background:#fff;color:var(--text-light)}
.week-dot:hover{border-color:var(--primary-light);color:var(--primary)}
.week-dot.active{background:var(--primary);border-color:var(--primary);color:#fff}
.modal-overlay{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.5);z-index:1000;align-items:center;justify-content:center}
.modal-overlay.open{display:flex}
.modal{background:#fff;border-radius:12px;padding:28px;width:520px;max-width:95vw;max-height:90vh;overflow-y:auto;box-shadow:0 10px 40px rgba(0,0,0,.2);animation:slideIn .2s ease}
@keyframes slideIn{from{transform:translateY(-20px);opacity:0}to{transform:translateY(0);opacity:1}}
.modal-title{font-size:1.1rem;font-weight:700;color:var(--primary);margin-bottom:6px}
.modal-subtitle{font-size:.82rem;color:var(--text-light);margin-bottom:20px;padding-bottom:14px;border-bottom:1px solid var(--border)}
.form-row{margin-bottom:14px}
.form-label{display:block;font-size:.8rem;font-weight:600;color:var(--text-light);margin-bottom:5px;text-transform:uppercase;letter-spacing:.4px}
.form-control{width:100%;padding:9px 12px;border:1.5px solid var(--border);border-radius:7px;font-size:.9rem;transition:border .2s}
.form-control:focus{border-color:var(--primary-light);outline:none}
.form-row-2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.modal-actions{display:flex;gap:10px;justify-content:flex-end;margin-top:20px;padding-top:16px;border-top:1px solid var(--border)}
.all-weeks{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}
.week-card{background:var(--card);border-radius:10px;box-shadow:0 2px 6px rgba(0,0,0,.07);overflow:hidden}
.week-card-header{background:var(--primary);color:#fff;padding:10px 14px;font-size:.82rem;font-weight:700;cursor:pointer}
.week-card-body{padding:10px}
.mini-slot{display:flex;gap:6px;padding:4px 0;border-bottom:1px solid var(--border);font-size:.75rem}
.mini-slot:last-child{border-bottom:none}
.mini-day{color:var(--text-light);width:65px;flex-shrink:0;font-weight:600}
.mini-time{color:var(--text-light);width:90px;flex-shrink:0}
.mini-subj{color:var(--text);font-weight:600}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px;margin-bottom:24px}
.stat-card{background:#fff;border-radius:10px;padding:16px 20px;box-shadow:0 2px 6px rgba(0,0,0,.07);border-left:4px solid var(--primary)}
.stat-value{font-size:2rem;font-weight:800;color:var(--primary)}
.stat-label{font-size:.8rem;color:var(--text-light);margin-top:3px}
.subjects-table{background:#fff;border-radius:10px;box-shadow:0 2px 6px rgba(0,0,0,.07);overflow:hidden}
.act-table-wrap{background:#fff;border-radius:10px;box-shadow:0 2px 6px rgba(0,0,0,.07);overflow-x:auto}
.act-table{width:100%;border-collapse:collapse;font-size:.82rem}
.act-table th{padding:10px 12px;font-size:.76rem;font-weight:700;text-align:center;white-space:nowrap;border-bottom:2px solid var(--border)}
.act-table th:first-child{text-align:left;background:var(--primary);color:#fff;padding-left:16px}
.act-table td{padding:9px 12px;border-bottom:1px solid var(--border);text-align:center;vertical-align:middle}
.act-table td:first-child{text-align:left;padding-left:16px}
.act-table tbody tr:hover td{background:var(--hover)}
.act-table small{display:block;font-size:.68rem;color:var(--text-light);font-weight:400}
.act-asig-name strong{font-size:.85rem}
.act-code{color:var(--text-light);font-size:.72rem}
.act-total{font-weight:700;color:var(--primary);background:#f0f4ff}
.act-teoria-th{background:#dbeafe;color:#1e3a5f}
.act-info-th{background:#ede9fe;color:#4c1d95}
.act-lab-th{background:#dcfce7;color:#14532d}
.act-ps-th{background:#ffedd5;color:#7c2d12}
.act-parcial-th{background:#fee2e2;color:#7f1d1d}
.act-teoria-td{background:#f8fbff}
.act-info-td{background:#faf8ff}
.act-lab-td{background:#f7fff9}
.act-ps-td{background:#fffaf5}
.act-parcial-td{background:#fff7f7;font-weight:700;color:#dc2626}
.sg-breakdown{display:flex;flex-direction:column;gap:3px;min-width:100px}
.sg-row{display:flex;justify-content:space-between;align-items:center;gap:6px;padding:2px 4px;border-radius:4px;background:rgba(0,0,0,.04);font-size:.73rem}
.sg-label{font-weight:700;white-space:nowrap;color:var(--text)}
.sg-hours{font-weight:700;color:inherit;white-space:nowrap}
.sg-ses{font-size:.67rem;color:var(--text-light);white-space:nowrap}
.sg-cell{padding:6px 8px!important;vertical-align:middle}
.sg-err{color:#dc2626;font-weight:800;font-size:.75rem;margin-left:3px;cursor:default}
.ficha-badge{font-size:.62rem;font-weight:700;margin-top:3px;padding:1px 5px;border-radius:3px;display:inline-block}
.ficha-badge.ok{background:#dcfce7;color:#166534}
.ficha-badge.err{background:#fee2e2;color:#dc2626}
.ficha-err-badge{display:block;margin-top:2px;font-size:.62rem;font-weight:700;color:#dc2626;background:#fee2e2;padding:1px 4px;border-radius:3px}
.ficha-ok-badge{display:block;margin-top:2px;font-size:.62rem;font-weight:700;color:#166534;background:#dcfce7;padding:1px 4px;border-radius:3px}
.ficha-override-badge{display:block;margin-top:2px;font-size:.62rem;font-weight:700;color:#7c3aed;background:#ede9fe;padding:1px 4px;border-radius:3px}
.btn-override{margin-top:4px;padding:2px 7px;font-size:.6rem;font-weight:700;border:1.5px solid #7c3aed;border-radius:4px;background:#fff;color:#7c3aed;cursor:pointer;display:inline-block;transition:background .15s}
.btn-override:hover{background:#ede9fe}
.btn-unoverride{border-color:#9ca3af;color:#6b7280}
.btn-unoverride:hover{background:#f3f4f6}
.cum-panel{margin-top:18px;background:var(--card);border-radius:10px;box-shadow:0 2px 6px rgba(0,0,0,.07);overflow:hidden}
.cum-header{display:flex;align-items:center;justify-content:space-between;padding:10px 18px;background:linear-gradient(135deg,#1a3a6b,#2d5faa);color:#fff;cursor:pointer;user-select:none}
.cum-header-title{font-size:.88rem;font-weight:700;display:flex;align-items:center;gap:8px}
.cum-header-meta{font-size:.76rem;opacity:.85;display:flex;gap:16px;align-items:center}
.cum-toggle{font-size:.75rem;background:rgba(255,255,255,.18);border-radius:4px;padding:2px 8px;transition:background .2s}
.cum-header:hover .cum-toggle{background:rgba(255,255,255,.3)}
.cum-body{overflow-x:auto;transition:max-height .3s ease}
.cum-table{width:100%;border-collapse:collapse;font-size:.78rem}
.cum-table th{padding:8px 10px;font-size:.72rem;font-weight:700;text-align:center;white-space:nowrap;border-bottom:2px solid var(--border);position:sticky;top:0;z-index:1}
.cum-table th:first-child{text-align:left;background:var(--primary);color:#fff;padding-left:14px;min-width:160px}
.cum-table td{padding:6px 10px;border-bottom:1px solid var(--border);text-align:center;vertical-align:middle}
.cum-table td:first-child{text-align:left;padding-left:14px;font-weight:600;font-size:.78rem}
.cum-table tbody tr:hover td{background:var(--hover)}
.cum-table .cum-total{font-weight:700;color:var(--primary);background:#f0f4ff}
.cum-table small{display:block;font-size:.65rem;color:var(--text-light)}
.cum-sg{display:flex;flex-direction:column;gap:2px}
.cum-sg-row{display:flex;justify-content:space-between;align-items:center;gap:4px;padding:1px 4px;border-radius:3px;background:rgba(0,0,0,.04);font-size:.7rem}
.cum-sg-lbl{font-weight:700;color:var(--text);white-space:nowrap}
.cum-sg-h{font-weight:700;white-space:nowrap}
.cum-sg-s{font-size:.63rem;color:var(--text-light);white-space:nowrap}
.cum-sg-cell{padding:4px 8px!important;vertical-align:middle}
.cum-progress-bar{height:4px;background:linear-gradient(90deg,#2d5faa,#4a9eda);border-radius:0 0 2px 2px}
.group-stats-section{margin-bottom:28px}
.group-stats-header{display:flex;align-items:baseline;gap:14px;padding:12px 16px;background:var(--primary);color:#fff;border-radius:10px 10px 0 0;margin-bottom:0}
.group-stats-title{font-size:1rem;font-weight:800;letter-spacing:.03em}
.group-stats-summary{font-size:.78rem;opacity:.85}
.group-stats-section .act-table-wrap{border-radius:0 0 10px 10px;box-shadow:0 2px 6px rgba(0,0,0,.07)}
/* ─── Calendario de Parciales ─── */
.parc-calendar{padding:4px 0}
.parc-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;flex-wrap:wrap;gap:10px}
.parc-title{font-size:1.05rem;font-weight:800;color:var(--primary)}
.parc-legend{display:flex;gap:8px;flex-wrap:wrap;align-items:center;font-size:.73rem;font-weight:600}
.parc-legend-item{display:flex;align-items:center;gap:4px}
.parc-legend-dot{width:12px;height:12px;border-radius:3px;display:inline-block}
.parc-table-wrap{overflow-x:auto;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.09)}
.parc-table{width:100%;border-collapse:collapse;font-size:.80rem;min-width:700px;background:#fff}
.parc-table thead th{padding:9px 10px;font-weight:700;text-align:center;border-bottom:2px solid var(--border);white-space:nowrap;font-size:.76rem;position:sticky;top:0;z-index:2;background:#fff}
.parc-table thead th.th-semana{background:var(--primary);color:#fff;min-width:70px;text-align:center}
.parc-table thead th.th-curso{background:var(--primary);color:#fff;width:46px;text-align:center}
.parc-table thead th.th-dia{min-width:120px}
.parc-table thead th.th-dia.lun{background:#e8f0fe;color:#1a3a6b}
.parc-table thead th.th-dia.mar{background:#e8f4ea;color:#14532d}
.parc-table thead th.th-dia.mie{background:#fef3e2;color:#78350f}
.parc-table thead th.th-dia.jue{background:#f3e8ff;color:#581c87}
.parc-table thead th.th-dia.vie{background:#fee2e2;color:#7f1d1d}
.parc-table td{padding:6px 8px;border:1px solid #e5e7eb;vertical-align:middle;text-align:center}
.parc-semana-cell{background:var(--primary);color:#fff;font-weight:800;font-size:.82rem;text-align:center;vertical-align:middle;white-space:nowrap;padding:6px 10px}
.parc-curso-cell{font-weight:800;font-size:.85rem;text-align:center;width:44px;white-space:nowrap;vertical-align:middle}
.parc-curso-1{background:#dbeafe;color:#1e3a8a}
.parc-curso-2{background:#dcfce7;color:#14532d}
.parc-curso-3{background:#fef9c3;color:#78350f}
.parc-curso-4{background:#fce7f3;color:#831843}
.parc-cell{padding:5px 7px!important;vertical-align:middle}
.parc-empty{background:#fafafa}
.parc-entry{display:flex;flex-direction:column;gap:1px;padding:4px 6px;border-radius:5px;margin:2px 0;text-align:left;border-left:3px solid}
.parc-entry-1{background:#dbeafe;border-color:#2563eb}
.parc-entry-2{background:#dcfce7;border-color:#16a34a}
.parc-entry-3{background:#fef9c3;border-color:#ca8a04}
.parc-entry-4{background:#fce7f3;border-color:#db2777}
.parc-name{font-weight:700;font-size:.75rem;color:var(--text);line-height:1.3}
.parc-obs{font-size:.65rem;font-weight:800;color:#dc2626;text-transform:uppercase;letter-spacing:.04em}
.parc-time{font-size:.63rem;color:var(--text-light)}
.parc-grupo{font-size:.62rem;color:#6b7280;font-style:italic}
.parc-row-sep td{height:4px;background:#f3f4f6;border:none}
.parc-conflict{outline:2px solid #f59e0b;outline-offset:-2px}
.parc-summary{margin-top:18px;display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
.parc-summary-card{background:#fff;border-radius:8px;box-shadow:0 1px 5px rgba(0,0,0,.08);padding:12px 16px;border-left:4px solid}
.parc-summary-card h4{margin:0 0 6px;font-size:.85rem;font-weight:800}
.parc-summary-card ul{margin:0;padding-left:14px;font-size:.76rem;color:var(--text-light)}
.parc-summary-card ul li{margin:2px 0}
/* ─── Conflictos de turno ─── */
.parc-turno-conflict td.parc-cell{outline:3px solid #f59e0b!important;outline-offset:-2px;background:#fffbeb!important}
.parc-entry.conflict-entry{outline:2px solid #dc2626;outline-offset:1px;position:relative}
.parc-conflict-badge{display:inline-block;font-size:.6rem;font-weight:800;color:#fff;background:#dc2626;border-radius:3px;padding:1px 4px;margin-left:3px;vertical-align:middle;white-space:nowrap}
.parc-turno-tag{display:inline-block;font-size:.6rem;font-weight:700;padding:1px 5px;border-radius:3px;margin-bottom:2px}
.parc-turno-man{background:#dbeafe;color:#1e40af}
.parc-turno-tar{background:#fef3c7;color:#92400e}
.parc-alert-panel{background:#fff7ed;border:1.5px solid #f59e0b;border-radius:8px;padding:12px 16px;margin-bottom:14px;font-size:.82rem}
.parc-alert-panel h4{margin:0 0 8px;color:#b45309;font-size:.88rem;font-weight:800;display:flex;align-items:center;gap:6px}
.parc-conflict-list{display:flex;flex-direction:column;gap:4px;max-height:200px;overflow-y:auto}
.parc-conflict-row{display:flex;align-items:baseline;gap:6px;padding:4px 8px;border-radius:5px;background:#fff;border-left:3px solid #f59e0b;font-size:.78rem}
.parc-conflict-sem{font-weight:800;color:#92400e;min-width:54px}
.parc-conflict-dia{font-weight:700;min-width:80px}
.parc-conflict-turno{font-size:.68rem;font-weight:700;padding:1px 5px;border-radius:3px}
.parc-conflict-detail{color:var(--text-light)}
.toast{position:fixed;bottom:24px;right:24px;background:var(--success);color:#fff;padding:12px 20px;border-radius:8px;font-weight:600;font-size:.88rem;box-shadow:0 4px 12px rgba(0,0,0,.2);display:none;z-index:2000}
.search-highlight{background:#fff176!important}
.saving-indicator{position:fixed;top:12px;right:20px;background:var(--accent);color:#fff;padding:6px 14px;border-radius:6px;font-size:.78rem;font-weight:700;display:none;z-index:2000;box-shadow:0 2px 8px rgba(0,0,0,.2)}
@media(max-width:768px){.toolbar{padding:10px 15px}.main{padding:16px 15px}header{padding:14px 16px}header h1{font-size:1.1rem}}
@media print{
  @page{size:A4 landscape;margin:10mm}
  *{-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}
  body{background:#fff}
  header,div.toolbar,div.week-nav,#weekDots,#view-stats,
  .modal-overlay,.toast,.saving-indicator,button,.tab-btn,
  .sch-empty,#weekCumulative{display:none!important}
  .main{padding:0}
  .schedule-container{box-shadow:none;border:none}
  .schedule-table{width:100%;font-size:.75rem}
  .sch-cell{min-height:50px;padding:4px 6px}
  .subject-card{font-size:.7rem;padding:4px 6px}
  #print-header{display:block!important}
  #view-semana{display:block!important}
  #weekLabel{display:block!important;font-size:1rem;font-weight:700;color:#000;text-align:center;margin-bottom:10px}
}
#print-header{display:none;text-align:center;margin-bottom:12px;padding-bottom:10px;border-bottom:2px solid #1a3a6b}
#print-header h2{font-size:1.1rem;color:#1a3a6b;margin-bottom:3px}
#print-header p{font-size:.85rem;color:#5a6a7a}
.pdf-progress{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.55);z-index:9999;display:none;align-items:center;justify-content:center}
.pdf-progress-box{background:#fff;border-radius:14px;padding:32px 40px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,.3);min-width:280px}
.pdf-progress-title{font-size:1.05rem;font-weight:700;color:var(--primary);margin-bottom:12px}
.pdf-progress-bar-wrap{height:8px;background:#e2e8f0;border-radius:4px;overflow:hidden;margin-bottom:10px}
.pdf-progress-bar-fill{height:100%;background:linear-gradient(90deg,#2d5faa,#4a9eda);border-radius:4px;transition:width .3s ease}
.pdf-progress-msg{font-size:.82rem;color:var(--text-light)}
/* ── Gráficos evolución prácticas ── */
.evol-section{margin-top:28px}
.evol-section-title{font-size:.9rem;font-weight:800;color:var(--primary);letter-spacing:.03em;padding:10px 16px;background:linear-gradient(90deg,#2d5faa,#4a9eda);color:#fff;border-radius:10px 10px 0 0}
.evol-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;padding:16px;background:#fff;border-radius:0 0 10px 10px;box-shadow:0 2px 6px rgba(0,0,0,.07)}
.evol-card{border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;background:#fafbfc}
.evol-card-header{padding:7px 12px;font-size:.78rem;font-weight:700;color:#1a3a6b;background:#e8edf5;border-bottom:1px solid #dbe3f0}
.evol-card-body{padding:10px 10px 6px 10px}
.evol-card svg{display:block;width:100%}
.evol-legend{display:flex;flex-wrap:wrap;gap:6px 14px;padding:5px 10px 8px 10px;font-size:.7rem;color:#555}
.evol-legend-item{display:flex;align-items:center;gap:4px}
.evol-legend-line{display:inline-block;width:22px;height:3px;border-radius:2px}
.evol-empty{padding:12px 16px;font-size:.8rem;color:var(--text-light);font-style:italic}
/* ── Calendario festivos ── */
.cal-wrap{max-width:1100px;margin:0 auto}
.cal-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;flex-wrap:wrap;gap:10px}
.cal-top h3{font-size:1.05rem;font-weight:800;color:var(--primary)}
.cal-top p{font-size:.82rem;color:var(--text-light);margin-top:3px}
.cal-legend{display:flex;gap:18px;align-items:center;flex-wrap:wrap;background:#fff;border-radius:8px;padding:10px 16px;box-shadow:0 1px 4px rgba(0,0,0,.07);margin-bottom:20px}
.cal-leg-item{display:flex;align-items:center;gap:7px;font-size:.8rem;font-weight:600;color:var(--text)}
.cal-dot{width:18px;height:18px;border-radius:4px;display:inline-block;flex-shrink:0}
.cal-dot-no_lectivo{background:#f59e0b}
.cal-dot-festivo{background:#e74c3c}
.cal-dot-lectivo{background:#e8f4ea;border:1.5px solid #27ae60}
.cal-dot-finde{background:#e8ecf0;border:1.5px solid #b0bec5}
.cal-dot-fuera{background:#f3f4f6;border:1.5px solid #d1d5db}
.cal-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}
.cal-month{background:#fff;border-radius:10px;box-shadow:0 2px 6px rgba(0,0,0,.08);overflow:hidden}
.cal-month-header{background:linear-gradient(135deg,var(--primary),var(--primary-light));color:#fff;padding:9px 14px;font-size:.88rem;font-weight:700;text-align:center;letter-spacing:.04em}
.cal-month-body{padding:8px 10px}
.cal-days-header{display:grid;grid-template-columns:repeat(7,1fr);gap:1px;margin-bottom:4px}
.cal-days-header span{text-align:center;font-size:.6rem;font-weight:700;color:var(--text-light);text-transform:uppercase;padding:3px 0}
.cal-days-header span:nth-child(6),.cal-days-header span:nth-child(7){color:#e74c3c}
.cal-days-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:2px}
.cal-day{aspect-ratio:1;display:flex;align-items:center;justify-content:center;font-size:.72rem;font-weight:600;border-radius:5px;transition:all .15s;border:1.5px solid transparent;line-height:1;flex-direction:column;gap:1px}
.cal-day.empty{visibility:hidden}
.cal-day.finde{background:#f1f3f5;color:#9ca3af;cursor:default}
.cal-day.fuera{background:#f8f9fa;color:#c9cdd3;cursor:default}
.cal-day.lectivo{background:#e8f4ea;color:#166534;cursor:pointer;border-color:#a7f3d0}
.cal-day.lectivo:hover{background:#c6f6d5;transform:scale(1.12);z-index:1;box-shadow:0 2px 8px rgba(39,174,96,.3)}
.cal-day.no_lectivo{background:#fef3c7;color:#92400e;cursor:pointer;border-color:#f59e0b}
.cal-day.no_lectivo:hover{background:#fde68a;transform:scale(1.12);z-index:1}
.cal-day.festivo{background:#fee2e2;color:#991b1b;cursor:pointer;border-color:#e74c3c}
.cal-day.festivo:hover{background:#fecaca;transform:scale(1.12);z-index:1}
.cal-day .cal-day-num{font-size:.73rem;font-weight:700}
.cal-day .cal-day-dot{width:5px;height:5px;border-radius:50%;background:currentColor;opacity:.6}
/* Popup festivo */
.festivo-popup{position:fixed;z-index:9999;background:#fff;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,.22);padding:22px 24px;min-width:280px;max-width:340px;border-top:4px solid var(--primary)}
.festivo-popup h4{font-size:.95rem;font-weight:800;color:var(--primary);margin-bottom:14px}
.festivo-popup label{display:block;font-size:.76rem;font-weight:700;color:var(--text-light);text-transform:uppercase;margin-bottom:5px;margin-top:10px}
.festivo-popup input,.festivo-popup select{width:100%;padding:7px 10px;border:1.5px solid var(--border);border-radius:6px;font-size:.88rem}
.festivo-popup .popup-btns{display:flex;gap:8px;margin-top:16px;justify-content:flex-end}
.festivo-popup .popup-overlay{position:fixed;inset:0;z-index:9998;background:rgba(0,0,0,.18)}
/* ─── Calendario de Exámenes Finales ─── */
.final-period-btn{padding:7px 16px;border-radius:8px;border:2px solid var(--border);background:#fff;cursor:pointer;font-size:.82rem;font-weight:700;color:var(--text-light);transition:all .15s}
.final-period-btn:hover:not(.active){border-color:var(--primary-light);color:var(--primary)}
.final-period-btn.active{color:#fff}
.final-period-btn.p1.active{background:#1e40af;border-color:#1e40af}
.final-period-btn.p2.active{background:#166534;border-color:#166534}
.final-period-btn.p3.active{background:#7c2d12;border-color:#7c2d12}
.final-table-wrap{overflow-x:auto;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.09)}
.final-table{width:100%;border-collapse:collapse;font-size:.80rem;min-width:760px;background:#fff}
.final-table thead th{padding:9px 10px;font-weight:700;text-align:center;border-bottom:2px solid var(--border);white-space:nowrap;font-size:.76rem;position:sticky;top:0;z-index:2;background:#fff}
.final-table thead th.th-semana{background:var(--primary);color:#fff;min-width:70px;text-align:center}
.final-table thead th.th-curso{background:var(--primary);color:#fff;width:46px;text-align:center}
.final-table thead th.th-dia{min-width:110px}
.final-table thead th.th-dia.lun{background:#e8f0fe;color:#1a3a6b}
.final-table thead th.th-dia.mar{background:#e8f4ea;color:#14532d}
.final-table thead th.th-dia.mie{background:#fef3e2;color:#78350f}
.final-table thead th.th-dia.jue{background:#f3e8ff;color:#581c87}
.final-table thead th.th-dia.vie{background:#fee2e2;color:#7f1d1d}
.final-table thead th.th-dia.sab{background:#fdf4ff;color:#6b21a8}
.final-table td{padding:5px 7px;border:1px solid #e5e7eb;vertical-align:middle;text-align:center}
.final-semana-cell{background:var(--primary);color:#fff;font-weight:800;font-size:.75rem;text-align:center;vertical-align:middle;white-space:nowrap;padding:6px 8px;line-height:1.5}
.final-cell{padding:4px 6px!important;vertical-align:top!important;cursor:pointer;min-height:36px;position:relative}
.final-cell:hover{background:#f0f9ff!important}
.final-cell-out{background:#f3f4f6!important;cursor:default!important}
.final-cell-out:hover{background:#f3f4f6!important}
.final-add-btn{display:block;width:100%;text-align:center;font-size:.62rem;color:#c7d2e0;padding:3px 0;cursor:pointer;border-radius:3px;margin-top:1px}
.final-add-btn:hover{background:#e8f0fe;color:#2563eb}
.final-entry{display:flex;flex-direction:column;gap:1px;padding:3px 5px;border-radius:5px;margin:2px 0;text-align:left;border-left:3px solid;cursor:pointer}
.final-entry:hover{filter:brightness(.93)}
.final-entry-1{background:#dbeafe;border-color:#2563eb}
.final-entry-2{background:#dcfce7;border-color:#16a34a}
.final-entry-3{background:#fef9c3;border-color:#ca8a04}
.final-entry-4{background:#fce7f3;border-color:#db2777}
.final-name{font-weight:700;font-size:.74rem;color:var(--text);line-height:1.3}
.final-obs{font-size:.64rem;font-weight:800;color:#dc2626;text-transform:uppercase;letter-spacing:.04em}
.final-turno{display:inline-block;font-size:.6rem;font-weight:700;padding:1px 5px;border-radius:3px;margin-bottom:2px}
.final-turno-man{background:#dbeafe;color:#1e40af}
.final-turno-tar{background:#fef3c7;color:#92400e}
.final-row-sep td{height:4px;background:#f3f4f6;border:none}
.final-entry.auto-entry{border-style:dashed;opacity:.88}
.final-auto-badge{font-size:.58rem;color:#9ca3af;font-weight:600;letter-spacing:.02em}
.final-action-bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
.btn-auto{background:linear-gradient(135deg,#2d5faa,#4a9eda);color:#fff;border:none;padding:8px 16px;border-radius:8px;font-size:.82rem;font-weight:700;cursor:pointer;display:flex;align-items:center;gap:6px;transition:all .15s}
.btn-auto:hover{filter:brightness(1.1);transform:translateY(-1px);box-shadow:0 4px 12px rgba(45,95,170,.3)}
.btn-auto:disabled{opacity:.55;cursor:not-allowed;transform:none}
.btn-reset-auto{background:#fff;color:#dc2626;border:2px solid #dc2626;padding:7px 14px;border-radius:8px;font-size:.82rem;font-weight:700;cursor:pointer;display:flex;align-items:center;gap:5px;transition:all .15s}
.btn-reset-auto:hover{background:#fee2e2}
.btn-reset-auto:disabled{opacity:.45;cursor:not-allowed}
.btn-export-pdf{background:linear-gradient(135deg,#166534,#22c55e);color:#fff;border:none;padding:8px 16px;border-radius:8px;font-size:.82rem;font-weight:700;cursor:pointer;display:flex;align-items:center;gap:6px;transition:all .15s}
.btn-export-pdf:hover{filter:brightness(1.1);transform:translateY(-1px);box-shadow:0 4px 12px rgba(22,101,52,.3)}
.btn-export-pdf:disabled{opacity:.55;cursor:not-allowed;transform:none}
/* ─── Checklist de asignaturas por período ─── */
.final-checklist-section{margin-top:22px;background:#fff;border-radius:10px;box-shadow:0 2px 6px rgba(0,0,0,.08);padding:16px 20px}
.final-checklist-title{font-size:.9rem;font-weight:800;color:var(--primary);margin-bottom:14px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.final-checklist-title span{font-size:.75rem;font-weight:500;color:var(--text-light)}
.final-checklist-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
@media(max-width:900px){.final-checklist-grid{grid-template-columns:repeat(2,1fr)}}
.final-checklist-col{border-radius:8px;overflow:hidden;border:1px solid #e5e7eb}
.final-checklist-col-header{padding:7px 12px;font-size:.82rem;font-weight:800;text-align:center}
.final-checklist-col-body{padding:6px 10px;max-height:280px;overflow-y:auto}
.final-checklist-item{display:flex;align-items:flex-start;gap:6px;padding:4px 2px;font-size:.76rem;border-radius:3px;cursor:pointer;line-height:1.4}
.final-checklist-item:hover{background:#f5f7ff}
.final-checklist-item input[type=checkbox]{margin-top:2px;cursor:pointer;accent-color:var(--primary);flex-shrink:0}
.final-checklist-item.unchecked .final-chk-nom{color:#b0b8c1;text-decoration:line-through}
.final-chk-nom{flex:1}
.final-chk-ok{font-size:.65rem;font-weight:800;color:#16a34a;margin-left:3px;flex-shrink:0}
.final-checklist-footer{margin-top:10px;font-size:.75rem;color:var(--text-light);display:flex;gap:16px;flex-wrap:wrap}
.final-checklist-footer b{color:var(--text)}
/* Popup finales */
.final-popup{position:fixed;z-index:9999;background:#fff;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,.22);padding:20px 24px;min-width:300px;max-width:380px;border-top:4px solid #dc2626}
.final-popup h4{font-size:.95rem;font-weight:800;color:#dc2626;margin-bottom:14px}
.final-popup label{display:block;font-size:.76rem;font-weight:700;color:var(--text-light);text-transform:uppercase;margin-bottom:5px;margin-top:10px}
.final-popup input,.final-popup select{width:100%;padding:7px 10px;border:1.5px solid var(--border);border-radius:6px;font-size:.88rem;box-sizing:border-box}
.final-popup .popup-btns{display:flex;gap:8px;margin-top:16px;justify-content:flex-end;flex-wrap:wrap}
</style>
</head>
<body>

<header>
  <div style="display:flex;align-items:center;gap:16px">
    <img src="/api/logo_svg" alt="IAnus" style="height:68px;width:68px;border-radius:14px;flex-shrink:0;box-shadow:0 2px 8px rgba(0,0,0,0.3)"/>
    <div>
      <h1>Gestor de Horarios — DEGREE_ACRONYM_PLACEHOLDER &nbsp;Curso CURSO_LABEL_PLACEHOLDER</h1>
      <div class="subtitle" id="headerSubtitle">DEGREE_NAME_PLACEHOLDER · INSTITUTION_ACRONYM_PLACEHOLDER</div>
    </div>
  </div>
  <div class="header-right">
    <div class="db-badge"><span>&#9679;</span> SQLite conectado</div>
    <button class="btn btn-outline btn-sm" id="btnBackupDB" onclick="backupDB()" title="Fuerza WAL checkpoint y crea copia de seguridad en backups/">&#128190; Guardar copia</button>
  </div>
</header>

<div class="toolbar">
  <div class="toolbar-group">
    <label>Curso</label>
    <select id="cursoSelect" onchange="onFilterChange()">
      <option value="1">1er Curso (PS2)</option>
      <option value="2">2o Curso (PS3)</option>
      <option value="3">3er Curso (PS4)</option>
      <option value="4">4o Curso (PS5)</option>
    </select>
  </div>
  <div class="toolbar-group">
    <label>Cuatrimestre</label>
    <select id="cuatSelect" onchange="onFilterChange()">
      <option value="1C">1er Cuatrimestre</option>
      <option value="2C">2o Cuatrimestre</option>
    </select>
  </div>
  <div class="toolbar-group">
    <label>Grupo</label>
    <select id="grupoSelect" onchange="onFilterChange()">
      <option value="1">Grupo 1</option>
      <option value="2">Grupo 2</option>
    </select>
  </div>
  <div class="toolbar-group">
    <label>Vista</label>
    <div class="view-tabs">
      <button class="tab-btn active" onclick="setView('semana',this)">Por Semana</button>
      <button class="tab-btn" onclick="setView('stats',this)">Estadisticas</button>
      <button class="tab-btn" onclick="setView('parciales',this)">&#128221; Parciales</button>
      <button class="tab-btn" onclick="setView('finales',this)">&#127891; Finales</button>
      <button class="tab-btn" onclick="setView('festivos',this)">&#128197; Festivos</button>
    </div>
  </div>
  <div class="toolbar-group" style="margin-left:auto">
    <input type="text" id="searchInput" placeholder="Buscar asignatura..." style="width:190px" oninput="render()">
  </div>
  <button class="btn btn-success" onclick="exportPDF()">&#128438; PDF semana</button>
  <button class="btn btn-success" onclick="exportAllPDF()">&#128438; PDF todas las semanas</button>
  <button class="btn btn-success" id="btnExportExcel" onclick="exportarExcel()" title="Exporta un Excel por curso con todos los grupos y cuatrimestres">&#128196; Exportar horarios INSTITUTION_ACRONYM_PLACEHOLDER</button>
  <button class="btn btn-primary" onclick="openAddModal()">+ Nueva clase</button>
</div>

<div class="main">
  <div id="print-header">
    <h2 id="print-title">Gestor de Horarios — DEGREE_ACRONYM_PLACEHOLDER &nbsp; Curso CURSO_LABEL_PLACEHOLDER</h2>
    <p id="print-subtitle"></p>
  </div>
  <div id="view-semana">
    <div class="week-nav">
      <button class="btn btn-outline btn-sm" onclick="prevWeek()">&#9664; Anterior</button>
      <div class="week-dots" id="weekDots"></div>
      <button class="btn btn-outline btn-sm" onclick="nextWeek()">Siguiente &#9654;</button>
    </div>
    <div id="weekLabel" style="margin-bottom:14px;font-size:.95rem;color:var(--primary);font-weight:700;text-align:center"></div>
    <div class="schedule-container" id="scheduleGrid"></div>
    <div id="weekCumulative"></div>
  </div>
  <div id="view-stats" style="display:none"><div class="stats-grid" id="statsGrid"></div><div class="subjects-table" id="subjectsTable"></div><div id="evolucionSection"></div></div>
  <div id="view-parciales" style="display:none"><div class="parc-calendar" id="parcGrid"></div></div>
  <div id="view-finales" style="display:none"><div class="parc-calendar" id="finalesContainer"></div></div>
  <div id="view-festivos" style="display:none">
    <div class="cal-wrap">
      <div class="cal-top">
        <div>
          <h3>&#128197; Calendario de D&iacute;as Festivos y No Lectivos</h3>
          <p>Haz clic en un d&iacute;a lectivo para marcarlo/desmarcarlo. Los cambios se propagan autom&aacute;ticamente a <strong>todos los horarios</strong>.</p>
        </div>
        <button class="btn btn-outline btn-sm" onclick="loadFestivos()">&#8635; Actualizar</button>
      </div>
      <div class="cal-legend">
        <span class="cal-leg-item"><span class="cal-dot cal-dot-festivo"></span> Festivo nacional</span>
        <span class="cal-leg-item"><span class="cal-dot cal-dot-no_lectivo"></span> No lectivo / Puente</span>
        <span class="cal-leg-item"><span class="cal-dot cal-dot-lectivo"></span> D&iacute;a lectivo</span>
        <span class="cal-leg-item"><span class="cal-dot cal-dot-finde"></span> Fin de semana</span>
        <span class="cal-leg-item"><span class="cal-dot cal-dot-fuera"></span> Fuera de cuatrimestre</span>
      </div>
      <div id="calendarGrid" class="cal-grid"></div>
    </div>
  </div>
</div>

<!-- MODAL -->
<div class="modal-overlay" id="modalOverlay" onclick="if(event.target===this)closeModal()">
  <div class="modal">
    <div class="modal-title" id="modalTitle">Editar Clase</div>
    <div class="modal-subtitle" id="modalSubtitle"></div>
    <div class="form-row">
      <label class="form-label">Asignatura</label>
      <select id="fAsignatura" class="form-control" onchange="onAsignaturaSelect()">
        <option value="">(Vacio)</option>
      </select>
    </div>
    <div class="form-row-2">
      <div class="form-row" style="margin-bottom:0">
        <label class="form-label">Aula / Tipo</label>
        <input type="text" id="fAula" class="form-control" placeholder="LAB, INFO, PS2..." list="fAulaList" autocomplete="off">
        <datalist id="fAulaList"></datalist>
      </div>
      <div class="form-row" style="margin-bottom:0">
        <label class="form-label">Subgrupo(s)</label>
        <input type="text" id="fSubgrupo" class="form-control" placeholder="1, 2, 3...">
      </div>
    </div>
    <div class="form-row" style="margin-top:12px">
      <label class="form-label">Observacion</label>
      <input type="text" id="fObs" class="form-control" placeholder="Parcial 1, Examen...">
    </div>
    <div class="form-row">
      <label class="form-label"><input type="checkbox" id="fNoLectivo" onchange="toggleNoLectivo()"> Marcar como NO LECTIVO</label>
    </div>
    <div id="addFields" style="display:none">
      <div class="form-row-2">
        <div class="form-row" style="margin-bottom:0">
          <label class="form-label">Dia</label>
          <select id="fDia" class="form-control">
            <option>LUNES</option><option>MARTES</option><option>MIERCOLES_PLACEHOLDER</option><option>JUEVES</option><option>VIERNES</option>
          </select>
        </div>
        <div class="form-row" style="margin-bottom:0">
          <label class="form-label">Franja horaria</label>
          <select id="fHora" class="form-control"></select>
        </div>
      </div>
      <div class="form-row" style="margin-top:12px">
        <label class="form-label">Aplicar a</label>
        <select id="fScope" class="form-control">
          <option value="single">Solo esta semana</option>
          <option value="all">Todas las semanas</option>
          <option value="from">Desde esta semana en adelante</option>
        </select>
      </div>
    </div>
    <div class="modal-actions">
      <button class="btn btn-outline" onclick="closeModal()">Cancelar</button>
      <button class="btn btn-danger btn-sm" id="btnDelete" onclick="deleteSlot()" style="margin-right:auto">Eliminar</button>
      <button class="btn btn-primary" id="btnSave" onclick="saveSlot()">Guardar</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>
<div class="saving-indicator" id="saving">Guardando en base de datos...</div>
<div class="pdf-progress" id="pdfOverlay">
  <div class="pdf-progress-box">
    <div class="pdf-progress-title">&#128438; Generando PDF&hellip;</div>
    <div class="pdf-progress-bar-wrap"><div class="pdf-progress-bar-fill" id="pdfProgressFill" style="width:0%"></div></div>
    <div class="pdf-progress-msg" id="pdfProgressMsg">Preparando&hellip;</div>
  </div>
</div>

<script>
let DB = null;
let currentCurso = '1', currentCuat = '1C', currentGroup = '1', currentWeekIdx = 0, currentView = 'semana';
let editCtx = null;
const DAYS = ['LUNES','MARTES','MIERCOLES_PLACEHOLDER','JUEVES','VIERNES'];
const COLORS = ['color-0','color-1','color-2','color-3','color-4','color-5','color-6','color-7','color-8','color-9','color-10','color-11','color-12','color-13','color-14'];

// ─── API ───
async function api(path, body) {
  const saving = document.getElementById('saving');
  if (body !== undefined) {
    saving.style.display = 'block';
    const res = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    saving.style.display = 'none';
    return res.json();
  }
  const res = await fetch(path);
  return res.json();
}

async function backupDB() {
  const btn = document.getElementById('btnBackupDB');
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '&#9203; Guardando...';
  try {
    const res = await api('/api/db/backup', {});
    if (res.ok) {
      btn.innerHTML = '&#10003; Guardado';
      btn.style.background = 'rgba(39,174,96,.25)';
      showToast('Copia guardada: backups/' + res.backup);
      setTimeout(() => { btn.innerHTML = orig; btn.style.background = ''; btn.disabled = false; }, 3000);
    } else {
      throw new Error(res.error || 'Error desconocido');
    }
  } catch(e) {
    btn.innerHTML = '&#10007; Error';
    btn.style.background = 'rgba(231,76,60,.25)';
    showToast('Error al guardar: ' + e.message, true);
    setTimeout(() => { btn.innerHTML = orig; btn.style.background = ''; btn.disabled = false; }, 3000);
  }
}

async function toggleFichaOverride(codigo, action, grupoKey) {
  await api('/api/ficha-override', { codigo, action, grupo_key: grupoKey || '' });
  DB = await api('/api/schedule');
  DB._overrideSet = new Set(DB.fichas_override || []);
  DB._destacadasSet = new Set(DB.destacadas || []);
  _subjectColorCache = null;
  renderStats();
}

async function loadData() {
  DB = await api('/api/schedule');
  DB._overrideSet = new Set(DB.fichas_override || []);
  DB._destacadasSet = new Set(DB.destacadas || []);
  _subjectColorCache = null;
  // DEBUG: mostrar indicador de fichas cargadas
  const fichasN = DB && DB.fichas ? Object.keys(DB.fichas).length : 0;
  console.log('[loadData] DB.fichas cargadas:', fichasN, Object.keys(DB.fichas || {}).slice(0,3));
  populateAsignaturaSelect();
  populateFranjaSelect();
  updateGrupoOptions();
  updateAulaDatalist();
  updateHeaderSubtitle();
  render();
}

function getKey() { return currentCurso + '_' + currentCuat + '_grupo_' + currentGroup; }
function getGrupo() { return DB ? DB.grupos[getKey()] : null; }
function getWeeks() { const g = getGrupo(); return g ? g.semanas : []; }
function getCurrentWeek() { return getWeeks()[currentWeekIdx]; }

let _subjectColorCache = null;
function buildSubjectColorCache() {
  _subjectColorCache = {};
  // Mapear cada asig_codigo a su curso recorriendo todos los grupos
  const codigoCurso = {};
  for (const key of Object.keys(DB.grupos)) {
    const g = DB.grupos[key];
    const curso = String(g.curso);
    for (const semana of g.semanas) {
      for (const cls of semana.clases) {
        if (cls.asig_codigo && !codigoCurso[cls.asig_codigo]) {
          codigoCurso[cls.asig_codigo] = curso;
        }
      }
    }
  }
  // Agrupar codigos por curso (orden alfabetico para estabilidad)
  const cursoCodes = {};
  for (const [codigo, curso] of Object.entries(codigoCurso)) {
    if (!cursoCodes[curso]) cursoCodes[curso] = [];
    cursoCodes[curso].push(codigo);
  }
  for (const curso of Object.keys(cursoCodes)) cursoCodes[curso].sort();
  // Asignar color segun posicion dentro del curso
  for (const [curso, codes] of Object.entries(cursoCodes)) {
    codes.forEach((codigo, idx) => {
      _subjectColorCache[codigo] = COLORS[idx % COLORS.length];
    });
  }
}
function getSubjectColor(codigo) {
  if (!codigo) return '';
  if (!_subjectColorCache) buildSubjectColorCache();
  return _subjectColorCache[codigo] || COLORS[0];
}

function populateAsignaturaSelect() {
  const sel = document.getElementById('fAsignatura');
  // Filtrar asignaturas para el selector de asignación de clase.
  // Prioridad: usar curso/cuatrimestre de la tabla asignaturas (si disponibles).
  // Fallback: buscar qué asignaturas ya aparecen en clases de este grupo (BDs legacy).
  let asigsFiltradas;
  const tieneMetadatos = DB.asignaturas.some(a => a.curso != null);
  if (tieneMetadatos) {
    asigsFiltradas = DB.asignaturas.filter(a =>
      a.curso == currentCurso && a.cuatrimestre === currentCuat
    );
  } else {
    const asigIdsEnCurso = new Set();
    const prefijo = currentCurso + '_' + currentCuat + '_';
    for (const [key, grupo] of Object.entries(DB.grupos)) {
      if (!key.startsWith(prefijo)) continue;
      for (const semana of grupo.semanas) {
        for (const clase of semana.clases) {
          if (clase.asignatura_id) asigIdsEnCurso.add(clase.asignatura_id);
        }
      }
    }
    asigsFiltradas = DB.asignaturas.filter(a => asigIdsEnCurso.has(a.id));
  }
  sel.innerHTML = '<option value="">(Vacio)</option>' +
    asigsFiltradas.map(a => `<option value="${a.id}" data-codigo="${a.codigo}">[${a.codigo}] ${a.nombre}</option>`).join('');
}

function populateFranjaSelect() {
  const sel = document.getElementById('fHora');
  sel.innerHTML = DB.franjas.map(f => `<option value="${f.id}">${f.label}</option>`).join('');
}

// ─── RENDER ───
function render() {
  if (!DB) return;
  if (currentView === 'semana') renderWeek();
  else if (currentView === 'parciales') renderParciales();
  else renderStats();
  renderWeekDots();
}

function renderWeekDots() {
  const weeks = getWeeks();
  document.getElementById('weekDots').innerHTML = weeks.map((w,i) =>
    `<div class="week-dot ${i===currentWeekIdx?'active':''}" onclick="goWeek(${i})" title="${w.descripcion}">${i+1}</div>`
  ).join('');
}

function isParcial(cls) {
  return cls.observacion && cls.observacion.toLowerCase().startsWith('parcial');
}

function isDestacada(cls) {
  if (!DB || !DB._destacadasSet || !cls.asig_codigo) return false;
  return DB._destacadasSet.has(cls.asig_codigo + '::' + currentGroup);
}

function buildSubjectCard(cls, color, search, interactive) {
  const parcial = isParcial(cls);
  const destacada = !parcial && isDestacada(cls);
  const cardColor = parcial ? 'color-parcial' : (destacada ? 'color-destacada' : color);
  const match = search && cls.asig_nombre && cls.asig_nombre.toLowerCase().includes(search);
  const onclick = interactive ? ` onclick="openEdit(${cls.id})"` : '';
  const pceoBtnHtml = (!parcial && interactive && cls.asig_codigo) ? `<button class="pceo-btn${destacada?' active':''}" onclick="event.stopPropagation();togglePceo('${cls.asig_codigo}',currentGroup)" title="${destacada?'Quitar PCEO':'Marcar como PCEO'}">&#11088;</button>` : '';
  return `<div class="subject-card ${cardColor}${match?' search-highlight':''}"${onclick} style="cursor:${interactive?'pointer':'default'}">
    ${pceoBtnHtml}
    ${parcial ? `<span class="parcial-badge">&#128221; EXAMEN ${cls.observacion.toUpperCase()}</span>` : ''}
    ${destacada ? `<span class="parcial-badge" style="color:#ffffff;background:rgba(255,255,255,.15);font-size:.6rem">&#11088; DESTACADAS_BADGE_PLACEHOLDER</span>` : ''}
    <div class="subject-name">${cls.asig_nombre||cls.contenido||''}</div>
    ${cls.asig_codigo?`<div class="subject-code">[${cls.asig_codigo}]</div>`:''}
    <div class="subject-tags">
      ${cls.aula?`<span class="tag">&#127979; ${cls.aula}</span>`:''}
      ${cls.subgrupo?`<span class="tag">&#128101; Sg.${cls.subgrupo}</span>`:''}
    </div>
  </div>`;
}

async function togglePceo(codigo, grupo_num) {
  const res = await api('/api/destacada/toggle', {codigo, grupo_num});
  if (res.ok) {
    const key = codigo + '::' + grupo_num;
    if (res.action === 'added') {
      DB._destacadasSet.add(key);
    } else {
      DB._destacadasSet.delete(key);
    }
    renderWeek();
  }
}

function buildWeekTableHTML(week, interactive) {
  const franjas = DB.franjas;
  const days = DAYS;
  const search = interactive ? document.getElementById('searchInput').value.toLowerCase() : '';
  // classMap ahora almacena arrays (puede haber múltiples entradas por slot)
  const classMap = {};
  week.clases.forEach(c => {
    const k = c.dia + '|' + c.franja_id;
    if (!classMap[k]) classMap[k] = [];
    classMap[k].push(c);
  });
  const noLectivoDays = {};
  days.forEach(day => {
    const dc = week.clases.filter(c => c.dia === day);
    noLectivoDays[day] = dc.some(c => c.es_no_lectivo);
  });
  const noLecRendered = {};
  let html = `<table class="schedule-table"><thead><tr>
    <th class="sch-th-time">Franja</th>
    ${days.map(d => `<th class="sch-th-day">${d}</th>`).join('')}
  </tr></thead><tbody>`;
  franjas.forEach(f => {
    if (f.orden === 4) {
      let divRow = `<tr class="sch-divider-row"><td></td>`;
      days.forEach(day => { if (!noLectivoDays[day]) divRow += `<td></td>`; });
      divRow += `</tr>`;
      html += divRow;
    }
    html += `<tr><td class="sch-time-cell">${f.label}</td>`;
    days.forEach(day => {
      if (noLectivoDays[day]) {
        if (!noLecRendered[day]) {
          noLecRendered[day] = true;
          html += `<td class="sch-cell sch-no-lectivo" rowspan="${franjas.length + 1}">
            <div class="no-lectivo-full">&#128683;<br>NO LECTIVO</div></td>`;
        }
        return;
      }
      const arr = classMap[day + '|' + f.id] || [];
      if (!arr.length) {
        // Celda vacía
        html += interactive
          ? `<td class="sch-cell sch-empty" onclick="openAdd(${week.semana_id},'${day}',${f.id})"><span class="empty-label">+ Anadir</span></td>`
          : `<td class="sch-cell sch-empty"></td>`;
      } else if (arr.length === 1 && arr[0].es_no_lectivo) {
        html += `<td class="sch-cell sch-no-lectivo-single"><span class="no-lectivo-label">&#128683; No lectivo</span></td>`;
      } else if (arr.length === 1) {
        // Celda normal — una sola asignatura
        const cls = arr[0];
        const color = getSubjectColor(cls.asig_codigo);
        const match = search && cls.asig_nombre && cls.asig_nombre.toLowerCase().includes(search);
        const onclick = interactive ? ` onclick="openEdit(${cls.id})"` : '';
        const destacadaCls = isDestacada(cls) ? ' sch-cell-destacada' : '';
        const addDesdobleBtn = interactive
          ? `<div class="split-add" onclick="event.stopPropagation();openAdd(${week.semana_id},'${day}',${f.id},true)">+ Desdoble</div>`
          : '';
        html += `<td class="sch-cell${destacadaCls} ${match?'search-highlight':''}"${onclick}>
          ${buildSubjectCard(cls, color, search, interactive)}
          ${addDesdobleBtn}
        </td>`;
      } else {
        // Celda DIVIDIDA — desdoble
        const cards = arr.map((cls, idx) =>
          (idx > 0 ? '<div class="split-divider"></div>' : '') +
          buildSubjectCard(cls, getSubjectColor(cls.asig_codigo), search, interactive)
        ).join('');
        const addBtn = interactive
          ? `<div class="split-add" onclick="openAdd(${week.semana_id},'${day}',${f.id},true)">+ Desdoble</div>`
          : '';
        html += `<td class="sch-cell sch-split">
          <div class="split-badge">${interactive ? '&#9851; Desdoble' : 'Subgrupos paralelos'}</div>
          <div class="split-cards">${cards}</div>
          ${addBtn}
        </td>`;
      }
    });
    html += '</tr>';
  });
  html += '</tbody></table>';
  return html;
}

function buildCumulativePanel() {
  const weeks    = getWeeks();
  const upTo     = currentWeekIdx;          // índice de la semana actual (0-based)
  const total    = weeks.length;
  const weeksUpTo = weeks.slice(0, upTo + 1);

  // Reutilizamos computeGroupStats con las semanas acumuladas hasta ahora
  const asigs = computeGroupStats(weeksUpTo).filter(a =>
    a.counts.teoria > 0 || a.counts.ps > 0 || a.counts.parcial > 0 ||
    Object.keys(a.infoBySubgrupo).length > 0 || Object.keys(a.labBySubgrupo).length > 0
  );
  if (!asigs.length) return '';

  const ACT_META = {
    teoria:  { label: '&#128218; Teor&iacute;a',     thCls: 'act-teoria-th', tdCls: 'act-teoria-td' },
    info:    { label: '&#128187; Inform&aacute;t.',   thCls: 'act-info-th',   tdCls: 'act-info-td'   },
    lab:     { label: '&#128300; Lab.',               thCls: 'act-lab-th',    tdCls: 'act-lab-td'    },
    ps:      { label: '&#127981; Aula Esp.',          thCls: 'act-ps-th',     tdCls: 'act-ps-td'     },
    parcial: { label: '&#128221; Parcial',            thCls: 'act-parcial-th',tdCls: 'act-parcial-td'},
  };

  const hasTeoria  = asigs.some(a => a.counts.teoria  > 0);
  const hasInfo    = asigs.some(a => Object.keys(a.infoBySubgrupo).length > 0);
  const hasLab     = asigs.some(a => Object.keys(a.labBySubgrupo).length  > 0);
  const hasPs      = asigs.some(a => a.counts.ps      > 0);
  const hasParcial = asigs.some(a => a.counts.parcial > 0);

  const cols = [];
  if (hasTeoria)  cols.push('teoria');
  if (hasInfo)    cols.push('info');
  if (hasLab)     cols.push('lab');
  if (hasPs)      cols.push('ps');
  if (hasParcial) cols.push('parcial');

  function sgCell(map, tdCls) {
    const entries = Object.entries(map).sort((a,b) => a[0].localeCompare(b[0], undefined, {numeric:true}));
    if (!entries.length) return `<td class="${tdCls}">&mdash;</td>`;
    if (entries.length === 1 && entries[0][0] === '') {
      const n = entries[0][1], h = n * 2;
      return `<td class="${tdCls}"><strong>${h}h</strong><small>${n}&nbsp;ses.</small></td>`;
    }
    const rows = entries.map(([sg,n]) => {
      const lbl = sg ? `Sg.${sg}` : 'Todos';
      return `<div class="cum-sg-row"><span class="cum-sg-lbl">${lbl}</span><span class="cum-sg-h">${n*2}h</span><span class="cum-sg-s">${n}&nbsp;ses.</span></div>`;
    }).join('');
    return `<td class="${tdCls} cum-sg-cell"><div class="cum-sg">${rows}</div></td>`;
  }

  // Total global acumulado
  let grandTotal = 0;
  asigs.forEach(a => {
    const maxInfo = Object.values(a.infoBySubgrupo).length ? Math.max(...Object.values(a.infoBySubgrupo)) : 0;
    const maxLab  = Object.values(a.labBySubgrupo).length  ? Math.max(...Object.values(a.labBySubgrupo))  : 0;
    grandTotal += (a.counts.teoria + a.counts.ps + maxInfo + maxLab) * 2;
  });

  const pct = Math.round(((upTo + 1) / total) * 100);

  const thead = `<thead><tr>
    <th style="text-align:left;min-width:160px">Asignatura</th>
    ${cols.map(t => `<th class="${ACT_META[t].thCls}">${ACT_META[t].label}</th>`).join('')}
    <th style="background:#e8edf5;color:var(--primary)">Acum.</th>
  </tr></thead>`;

  const tbody = asigs.map(a => {
    const maxInfo = Object.values(a.infoBySubgrupo).length ? Math.max(...Object.values(a.infoBySubgrupo)) : 0;
    const maxLab  = Object.values(a.labBySubgrupo).length  ? Math.max(...Object.values(a.labBySubgrupo))  : 0;
    const acumH = (a.counts.teoria + a.counts.ps + maxInfo + maxLab) * 2;
    const cells = cols.map(t => {
      if (t === 'info')    return sgCell(a.infoBySubgrupo, ACT_META.info.tdCls);
      if (t === 'lab')     return sgCell(a.labBySubgrupo,  ACT_META.lab.tdCls);
      if (t === 'parcial') {
        const n = a.counts.parcial;
        return `<td class="${ACT_META.parcial.tdCls}">${n ? n+'&nbsp;ex.' : '&mdash;'}</td>`;
      }
      const h = a.counts[t]*2, n = a.counts[t];
      return `<td class="${ACT_META[t].tdCls}">${h ? `<strong>${h}h</strong><small>${n}&nbsp;ses.</small>` : '&mdash;'}</td>`;
    }).join('');
    return `<tr>
      <td><strong>${a.nombre}</strong><br><span style="color:var(--text-light);font-size:.68rem">[${a.codigo}]</span></td>
      ${cells}
      <td class="cum-total">${acumH}h</td>
    </tr>`;
  }).join('');

  const semLabel = `Semana ${upTo + 1} de ${total}`;
  const cumId = 'cumBody_' + upTo;

  return `<div class="cum-panel">
    <div class="cum-header" onclick="toggleCum()">
      <div class="cum-header-title">&#128202; Horas acumuladas hasta ${semLabel}</div>
      <div class="cum-header-meta">
        <span>${grandTotal}h lectivas acumuladas</span>
        <span>${pct}% del cuatrimestre</span>
        <span class="cum-toggle" id="cumToggleBtn">&#9650; Ocultar</span>
      </div>
    </div>
    <div style="height:4px;background:linear-gradient(90deg,#2d5faa ${pct}%,#e2e8f0 ${pct}%)"></div>
    <div class="cum-body" id="${cumId}">
      <div class="act-table-wrap" style="box-shadow:none;border-radius:0">
        <table class="cum-table">${thead}<tbody>${tbody}</tbody></table>
      </div>
    </div>
  </div>`;
}

let cumVisible = true;
function toggleCum() {
  cumVisible = !cumVisible;
  const body = document.querySelector('.cum-body');
  const btn  = document.getElementById('cumToggleBtn');
  if (body) body.style.display = cumVisible ? '' : 'none';
  if (btn)  btn.innerHTML = cumVisible ? '&#9650; Ocultar' : '&#9660; Ver';
}

function renderWeek() {
  const week = getCurrentWeek();
  if (!week) return;
  const g = getGrupo();
  const aulaInfo = g && g.aula ? ' — ' + formatAula(g.aula) : '';
  document.getElementById('weekLabel').textContent = week.descripcion + aulaInfo;
  document.getElementById('scheduleGrid').innerHTML = buildWeekTableHTML(week, true);
  document.getElementById('weekCumulative').innerHTML = buildCumulativePanel();
  // Restaurar estado visible/oculto
  const body = document.querySelector('.cum-body');
  const btn  = document.getElementById('cumToggleBtn');
  if (body && !cumVisible) body.style.display = 'none';
  if (btn  && !cumVisible) btn.innerHTML = '&#9660; Ver';
}

function renderAllWeeks() {
  const weeks = getWeeks();
  const search = document.getElementById('searchInput').value.toLowerCase();
  let html = '';
  weeks.forEach((week, wi) => {
    const entries = week.clases.filter(c => c.asig_nombre && (!search || c.asig_nombre.toLowerCase().includes(search)));
    if (!entries.length && search) return;
    html += `<div class="week-card"><div class="week-card-header" onclick="goWeek(${wi});setView('semana',null)">${week.descripcion}</div>
      <div class="week-card-body">${entries.length?entries.map(e =>
        `<div class="mini-slot"><span class="mini-day">${e.dia.slice(0,3)}</span>
        <span class="mini-time">${e.franja_label}</span>
        <span class="mini-subj">${e.asig_nombre}${e.observacion?' <em style="color:var(--warning);font-size:.7rem">('+e.observacion+')</em>':''}</span></div>`
      ).join(''):'<div style="font-size:.78rem;color:var(--text-light);padding:6px">Sin clases</div>'}</div></div>`;
  });
  document.getElementById('allWeeksContainer').innerHTML = html || '<div style="color:var(--text-light);padding:20px">Sin resultados.</div>';
}

// ─── FICHAS LOOKUP (keyed by asignatura.codigo, resuelto server-side) ────────
function getFichas(codigo) {
  if (!DB || !DB.fichas || !codigo) return null;
  return DB.fichas[codigo] || null;
}

function getActType(cls) {
  if (cls.observacion && /^parcial/i.test(cls.observacion.trim())) return 'parcial';
  const a = (cls.aula || '').trim();
  if (a === 'LAB') return 'lab';
  if (a === 'INFO' || a === 'Aula:') return 'info';
  if (a !== '') return 'ps';
  return 'teoria';
}

function computeGroupStats(weeks) {
  // Devuelve array de {nombre, codigo, counts, infoBySubgrupo, labBySubgrupo}
  // INFO y LAB se desglozan por subgrupo; el resto se deduplica ignorando subgrupo.
  const asigData = {};
  const seenShared   = new Set(); // teoria / ps / parcial — dedup sin subgrupo
  const seenPractica = new Set(); // info / lab — dedup con subgrupo

  weeks.forEach(w => {
    w.clases.forEach(c => {
      if (!c.asig_codigo || c.es_no_lectivo) return;
      const tipo = getActType(c);

      if (!asigData[c.asig_codigo]) {
        asigData[c.asig_codigo] = {
          nombre: c.asig_nombre, codigo: c.asig_codigo,
          counts: { teoria:0, ps:0, parcial:0 },
          infoBySubgrupo: {},
          labBySubgrupo: {},
          fichas: getFichas(c.asig_codigo)   // datos esperados de la ficha (keyed by codigo)
        };
      }
      const d = asigData[c.asig_codigo];

      if (tipo === 'info' || tipo === 'lab') {
        // Dedup por subgrupo: cada subgrupo cuenta sus propias sesiones
        const sg = (c.subgrupo || '').trim();
        const dedupKey = `${c.asig_codigo}|${tipo}|${sg}|${w.numero}|${c.dia}|${c.franja_id}`;
        if (seenPractica.has(dedupKey)) return;
        seenPractica.add(dedupKey);
        const map = tipo === 'info' ? d.infoBySubgrupo : d.labBySubgrupo;
        map[sg] = (map[sg] || 0) + 1;
      } else {
        // teoria / ps / parcial: dedup global (todos los subgrupos comparten la misma sesión)
        const dedupKey = `${c.asig_codigo}|${tipo}|${w.numero}|${c.dia}|${c.franja_id}`;
        if (seenShared.has(dedupKey)) return;
        seenShared.add(dedupKey);
        d.counts[tipo]++;
      }
    });
  });
  return Object.values(asigData).sort((a,b) => a.nombre.localeCompare(b.nombre));
}

function buildActTable(allAsigs, groupKey) {
  // DEBUG: verificar fichas
  const conFichas = allAsigs.filter(a => a.fichas !== null).length;
  const dbFichasCount = DB && DB.fichas ? Object.keys(DB.fichas).length : 0;
  console.log('[buildActTable] asigs:', allAsigs.length, '| con fichas:', conFichas, '| DB.fichas keys:', dbFichasCount);
  if (allAsigs.length > 0) {
    const a0 = allAsigs[0];
    console.log('[buildActTable] Primer asig:', a0.nombre, '| fichas:', JSON.stringify(a0.fichas), '| counts:', JSON.stringify(a0.counts));
  }

  const ACT_META = {
    teoria:  { label: '&#128218; Teor&iacute;a',       thCls: 'act-teoria-th', tdCls: 'act-teoria-td' },
    info:    { label: '&#128187; Inform&aacute;tica',   thCls: 'act-info-th',   tdCls: 'act-info-td'   },
    lab:     { label: '&#128300; Laboratorio',          thCls: 'act-lab-th',    tdCls: 'act-lab-td'    },
    ps:      { label: '&#127981; Aula Espec&iacute;f.', thCls: 'act-ps-th',     tdCls: 'act-ps-td'     },
    parcial: { label: '&#128221; Examen Parcial',       thCls: 'act-parcial-th',tdCls: 'act-parcial-td'},
  };

  const hasInfo    = allAsigs.some(a => Object.keys(a.infoBySubgrupo).length > 0);
  const hasLab     = allAsigs.some(a => Object.keys(a.labBySubgrupo).length > 0);
  const hasTeoria  = allAsigs.some(a => a.counts.teoria  > 0);
  const hasPs      = allAsigs.some(a => a.counts.ps      > 0);
  const hasParcial = allAsigs.some(a => a.counts.parcial > 0);

  const cols = [];
  if (hasTeoria)  cols.push('teoria');
  if (hasInfo)    cols.push('info');
  if (hasLab)     cols.push('lab');
  if (hasPs)      cols.push('ps');
  if (hasParcial) cols.push('parcial');

  // ── Helper: comprueba si las horas reales de una práctica por subgrupo
  //    coinciden con el valor esperado de fichas (esperado en horas).
  //    Devuelve {ok: bool, rows: [{sg, actual_h, esp_h, ok}]}
  function checkPractica(map, espH) {
    const entries = Object.entries(map).sort((a,b) => a[0].localeCompare(b[0], undefined, {numeric:true}));
    if (!entries.length) {
      // No hay sesiones → OK solo si esperado = 0
      return { ok: espH === 0, rows: [] };
    }
    const rowChecks = entries.map(([sg, n]) => ({
      sg, actual_h: n * 2, esp_h: espH, ok: (n * 2 === espH)
    }));
    return { ok: rowChecks.every(r => r.ok), rows: rowChecks };
  }

  // ── Renderiza celda de práctica con desglose por subgrupo y colores fichas
  function practicaCell(map, tdCls, espH) {
    const entries = Object.entries(map).sort((a,b) => a[0].localeCompare(b[0], undefined, {numeric:true}));
    if (!entries.length) {
      // Sin sesiones: si fichas espera 0 → normal; si espera >0 → rojo
      if (espH === null || espH === undefined) return `<td class="${tdCls}">&mdash;</td>`;
      const ok = (espH === 0);
      const style = ok ? '' : 'background:#fee2e2;border-left:3px solid #dc2626';
      const badge = ok ? '' : `<div class="ficha-badge err">Ficha: ${espH}h</div>`;
      return `<td class="${tdCls}" style="${style}">&mdash;${badge}</td>`;
    }
    // Sin subgrupos nombrados
    if (entries.length === 1 && entries[0][0] === '') {
      const n = entries[0][1], h = n * 2;
      const ok = (espH === null || espH === undefined || h === espH);
      const style = ok ? '' : 'background:#fee2e2;border-left:3px solid #dc2626';
      const espBadge = (!ok) ? `<div class="ficha-badge err">Ficha: ${espH}h</div>` :
                       (espH !== null && espH !== undefined) ? `<div class="ficha-badge ok">&#10003; ${espH}h</div>` : '';
      return `<td class="${tdCls}" style="${style}"><strong>${h}h</strong><small>${n}&nbsp;ses.</small>${espBadge}</td>`;
    }
    // Con subgrupos
    const rows = entries.map(([sg, n]) => {
      const h = n * 2;
      const lbl = sg ? `Sg.${sg}` : 'Todos';
      const ok = (espH === null || espH === undefined || h === espH);
      const rowStyle = ok ? '' : 'background:#fecaca;border-radius:3px';
      const errTip = ok ? '' : `<span class="sg-err" title="Fichas: ${espH}h">&#9888;</span>`;
      return `<div class="sg-row" style="${rowStyle}"><span class="sg-label">${lbl}</span><span class="sg-hours">${h}h</span><span class="sg-ses">${n}&nbsp;ses.</span>${errTip}</div>`;
    }).join('');
    const anyErr = espH !== null && espH !== undefined && entries.some(([,n]) => n*2 !== espH);
    const cellStyle = anyErr ? 'background:#fee2e2;border-left:3px solid #dc2626' : '';
    const espBadge = (espH !== null && espH !== undefined)
      ? `<div class="ficha-badge ${anyErr?'err':'ok'}">${anyErr?'&#9888;':'&#10003;'} Ficha: ${espH}h/sg</div>` : '';
    return `<td class="${tdCls} sg-cell" style="${cellStyle}"><div class="sg-breakdown">${rows}</div>${espBadge}</td>`;
  }

  const thead = `<thead><tr>
    <th style="text-align:left;min-width:180px">Asignatura</th>
    ${cols.map(t => `<th class="${ACT_META[t].thCls}">${ACT_META[t].label}</th>`).join('')}
    <th style="background:#e8edf5;color:var(--primary)">Total<br><small style="font-weight:400;font-size:.68rem">real / ficha</small></th>
  </tr></thead>`;

  const tbody = allAsigs.map(a => {
    const f = a.fichas;  // datos de fichas (puede ser null)
    const espAf1  = f ? f.af1  : null;
    const espAf2  = f ? f.af2  : null;
    const espAf4  = f ? f.af4  : null;
    const espAf5  = f ? f.af5  : null;
    const espAf6  = f ? f.af6  : null;
    // Total esperado = AF1+AF2+AF4+AF5+AF6
    const espTot  = f ? (f.af1 + f.af2 + f.af4 + f.af5 + f.af6) : null;

    // Total real presencial (sesiones × 2h): teoría + PS + INFO + LAB
    const maxInfo = Object.values(a.infoBySubgrupo).length ? Math.max(...Object.values(a.infoBySubgrupo)) : 0;
    const maxLab  = Object.values(a.labBySubgrupo).length  ? Math.max(...Object.values(a.labBySubgrupo))  : 0;
    const totalReal = (a.counts.teoria + a.counts.ps + maxInfo + maxLab) * 2;

    // ── Chequeos fichas ──────────────────────────────────────────────────
    // Teoría (AF1): sesiones × 2h vs ficha
    const teorReal = a.counts.teoria * 2;
    const teorOk   = (espAf1 === null) || (teorReal === espAf1);

    // Informática (AF4): por subgrupo
    const infoEntries = Object.entries(a.infoBySubgrupo);
    const infoOk = (espAf4 === null) || (
      infoEntries.length === 0 ? espAf4 === 0
      : infoEntries.every(([,n]) => n*2 === espAf4)
    );

    // Laboratorio (AF2): por subgrupo
    const labEntries = Object.entries(a.labBySubgrupo);
    const labOk = (espAf2 === null) || (
      labEntries.length === 0 ? espAf2 === 0
      : labEntries.every(([,n]) => n*2 === espAf2)
    );

    // Total AF1+AF2+AF4+AF5+AF6 (AF5 y AF6 no se miden en el horario,
    // así que sólo se compara el bloque presencial: teoría + lab + info)
    const presReal = totalReal;  // horas presenciales en horario
    const presEsp  = f ? (f.af1 + f.af2 + f.af4) : null;  // AF1+AF2+AF4 de ficha
    const totalOk  = (presEsp === null) || (presReal === presEsp);

    // ¿Algún error en la asignatura? (con soporte de override manual por grupo)
    const rawErr = !teorOk || !infoOk || !labOk || !totalOk;
    const overrideKey = a.codigo + '::' + (groupKey || '');
    const isOverride = (DB._overrideSet || new Set()).has(overrideKey);
    const rowErr = rawErr && !isOverride;
    const rowErrStyle = isOverride
      ? 'background:#f5f3ff'
      : rowErr ? 'background:#fde8e8' : 'background:#f0fdf4';
    const nameStyle = isOverride
      ? 'border-left:5px solid #7c3aed;background:#ede9fe;padding-left:12px'
      : rowErr
        ? 'border-left:5px solid #dc2626;background:#fee2e2;color:#991b1b;padding-left:12px'
        : 'border-left:5px solid #16a34a;background:#dcfce7;padding-left:12px';

    // ── Celdas ───────────────────────────────────────────────────────────
    const cells = cols.map(t => {
      if (t === 'info') return practicaCell(a.infoBySubgrupo, ACT_META.info.tdCls, espAf4);
      if (t === 'lab')  return practicaCell(a.labBySubgrupo,  ACT_META.lab.tdCls,  espAf2);
      if (t === 'parcial') {
        const n = a.counts.parcial;
        return `<td class="${ACT_META.parcial.tdCls}">${n ? n+'&nbsp;ex.' : '&mdash;'}</td>`;
      }
      if (t === 'teoria') {
        const h = a.counts.teoria * 2, n = a.counts.teoria;
        const espBadge = (espAf1 !== null)
          ? `<div class="ficha-badge ${teorOk?'ok':'err'}">${teorOk?'&#10003;':'&#9888;'} Ficha: ${espAf1}h</div>` : '';
        const cellStyle = teorOk ? '' : 'background:#fee2e2;border-left:3px solid #dc2626';
        return `<td class="${ACT_META.teoria.tdCls}" style="${cellStyle}">${h ? `<strong>${h}h</strong><small>${n}&nbsp;ses.</small>` : '&mdash;'}${espBadge}</td>`;
      }
      // ps
      const h = a.counts[t] * 2, n = a.counts[t];
      return `<td class="${ACT_META[t].tdCls}">${h ? `<strong>${h}h</strong><small>${n}&nbsp;ses.</small>` : '&mdash;'}</td>`;
    }).join('');

    // Columna total — muestra horas presenciales reales vs AF1+AF2+AF4
    // y debajo informa de AF5+AF6 (eval. continua lectivo + eval. final) como referencia
    const af56info = f ? `<small style="display:block;color:#6b7280;font-size:.62rem">AF5:${f.af5}h AF6:${f.af6}h</small>` : '';
    const totalBadge = (presEsp !== null)
      ? `<small style="display:block;color:${totalOk?'#166534':'#dc2626'};font-weight:700">${totalOk?'&#10003;':('&#9888; pres.'+presEsp+'h')}</small>${af56info}` : '';
    const totalStyle = totalOk ? '' : 'background:#fee2e2;color:#dc2626';

    // Badge de estado y botón de override
    let statusBadge = '';
    let overrideBtn = '';
    if (isOverride) {
      statusBadge = '<span class="ficha-override-badge">&#10003; Verificado manualmente</span>';
      overrideBtn = `<button class="btn-override btn-unoverride" onclick="toggleFichaOverride('${a.codigo}','unset','${groupKey||''}')" title="Quitar override y volver a mostrar el estado real">&#10006; Quitar verificación</button>`;
    } else if (rawErr && f) {
      statusBadge = '<span class="ficha-err-badge">&#9888; No cumple ficha</span>';
      overrideBtn = `<button class="btn-override" onclick="toggleFichaOverride('${a.codigo}','set','${groupKey||''}')" title="Marcar como correcto aunque no cuadre con la ficha">&#10003; Marcar sin conflicto</button>`;
    } else if (f) {
      statusBadge = '<span class="ficha-ok-badge">&#10003; OK ficha</span>';
    }

    return `<tr style="${rowErrStyle}">
      <td class="act-asig-name" style="${nameStyle}">
        <strong>${a.nombre}</strong><br>
        <span class="act-code">[${a.codigo}]</span>
        ${statusBadge}${overrideBtn}
      </td>
      ${cells}
      <td class="act-total" style="${totalStyle}">${totalReal}h${totalBadge}</td>
    </tr>`;
  }).join('');

  return `<div class="act-table-wrap"><table class="act-table">${thead}<tbody>${tbody}</tbody></table></div>`;
}

// ─── VISTA PARCIALES ────────────────────────────────────────────────────────
function renderParciales() {
  const cuat = currentCuat;
  const dias = ['LUNES','MARTES','MIÉRCOLES','JUEVES','VIERNES'];
  const diaCls = ['lun','mar','mie','jue','vie'];
  const cursos = ['1','2','3','4'];
  const cursoLabel = {'1':'1º','2':'2º','3':'3º','4':'4º'};
  const cursoBg = {'1':'parc-curso-1','2':'parc-curso-2','3':'parc-curso-3','4':'parc-curso-4'};
  const entryBg = {'1':'parc-entry-1','2':'parc-entry-2','3':'parc-entry-3','4':'parc-entry-4'};
  const borderColors = {'1':'#2563eb','2':'#16a34a','3':'#ca8a04','4':'#db2777'};
  // Franjas 1-3 = mañana, 4-6 = tarde
  function getTurno(franjaOrden) { return franjaOrden <= 3 ? 'mañana' : 'tarde'; }

  // ── 1. Recopilar parciales
  // byWeek[sNum][curso][dia] = Map{ key -> {nombre, obs, franja, franjaOrden, grupos[]} }
  const byWeek = {};

  for (const [clave, grupo] of Object.entries(DB.grupos)) {
    if (grupo.cuatrimestre !== cuat) continue;
    const curso = String(grupo.curso);
    for (const semana of grupo.semanas) {
      for (const cls of semana.clases) {
        if (!cls.observacion || !/^parcial/i.test(cls.observacion.trim())) continue;
        const sNum = semana.numero;
        if (!byWeek[sNum]) byWeek[sNum] = {};
        if (!byWeek[sNum][curso]) byWeek[sNum][curso] = {};
        if (!byWeek[sNum][curso][cls.dia]) byWeek[sNum][curso][cls.dia] = new Map();
        const key = (cls.asig_nombre || '') + '|||' + cls.observacion;
        const ex = byWeek[sNum][curso][cls.dia].get(key);
        if (ex) {
          if (!ex.grupos.includes(grupo.grupo)) ex.grupos.push(grupo.grupo);
          // conservar la franja de menor orden (más temprana del día)
          if (cls.franja_orden < ex.franjaOrden) { ex.franjaOrden = cls.franja_orden; ex.franja = cls.franja_label; }
        } else {
          byWeek[sNum][curso][cls.dia].set(key, {
            nombre: cls.asig_nombre || '—',
            obs: cls.observacion,
            franja: cls.franja_label,
            franjaOrden: cls.franja_orden,
            grupos: [grupo.grupo]
          });
        }
      }
    }
  }

  const semanas = Object.keys(byWeek).map(Number).sort((a,b) => a-b);
  if (semanas.length === 0) {
    document.getElementById('parcGrid').innerHTML =
      '<p style="color:var(--text-light);padding:24px;text-align:center">No hay exámenes parciales registrados para '+cuat+'.</p>';
    return;
  }

  // ── 2. Detectar conflictos entre cursos CONSECUTIVOS mismo día+turno
  // conflictSet: Set de claves "sNum|curso|dia|turno" → esa celda tiene conflicto
  // conflictList: array de {sNum, dia, turno, cursosAfectados[], detalle}
  const conflictSet = new Set();
  const conflictList = [];
  const pairs = [['1','2'],['2','3'],['3','4']];

  for (const sNum of semanas) {
    for (const dia of dias) {
      // Para cada turno: qué cursos tienen al menos un parcial en ese turno
      const cursosByTurno = { 'mañana': new Set(), 'tarde': new Set() };
      for (const curso of cursos) {
        const entries = byWeek[sNum]?.[curso]?.[dia];
        if (!entries) continue;
        for (const [,e] of entries) {
          cursosByTurno[getTurno(e.franjaOrden)].add(curso);
        }
      }
      for (const turno of ['mañana','tarde']) {
        const cursosEnTurno = cursosByTurno[turno];
        for (const [cA, cB] of pairs) {
          if (cursosEnTurno.has(cA) && cursosEnTurno.has(cB)) {
            conflictSet.add(`${sNum}|${cA}|${dia}|${turno}`);
            conflictSet.add(`${sNum}|${cB}|${dia}|${turno}`);
            // Recoger nombres de asignaturas para el detalle
            const nombresA = [...(byWeek[sNum]?.[cA]?.[dia]?.values() || [])].filter(e=>getTurno(e.franjaOrden)===turno).map(e=>e.nombre);
            const nombresB = [...(byWeek[sNum]?.[cB]?.[dia]?.values() || [])].filter(e=>getTurno(e.franjaOrden)===turno).map(e=>e.nombre);
            conflictList.push({ sNum, dia, turno, cA, cB, nombresA, nombresB });
          }
        }
      }
    }
  }

  // ── 3. Contar exámenes por curso
  const countByCurso = {'1':0,'2':0,'3':0,'4':0};
  for (const sNum of semanas) {
    for (const curso of cursos) {
      for (const dia of dias) {
        const entries = byWeek[sNum]?.[curso]?.[dia];
        if (entries) countByCurso[curso] += entries.size;
      }
    }
  }

  // ── 4. Panel de alertas de conflicto ──
  let html = '';
  if (conflictList.length > 0) {
    const turnoCls = t => t === 'mañana' ? 'parc-turno-man' : 'parc-turno-tar';
    html += `<div class="parc-alert-panel">
      <h4>&#9888;&#65039; ${conflictList.length} conflicto${conflictList.length>1?'s':''} detectado${conflictList.length>1?'s':''} — cursos consecutivos en mismo día y turno</h4>
      <div class="parc-conflict-list">
        ${conflictList.map(c => `
          <div class="parc-conflict-row">
            <span class="parc-conflict-sem">Sem ${c.sNum}</span>
            <span class="parc-conflict-dia">${c.dia.charAt(0)+c.dia.slice(1).toLowerCase()}</span>
            <span class="parc-conflict-turno ${turnoCls(c.turno)}">${c.turno}</span>
            <span class="parc-conflict-detail">
              <strong style="color:${borderColors[c.cA]}">${cursoLabel[c.cA]}</strong>: ${c.nombresA.join(', ')}
              &nbsp;&bull;&nbsp;
              <strong style="color:${borderColors[c.cB]}">${cursoLabel[c.cB]}</strong>: ${c.nombresB.join(', ')}
            </span>
          </div>`).join('')}
      </div>
    </div>`;
  } else {
    html += `<div style="background:#dcfce7;border:1.5px solid #16a34a;border-radius:8px;padding:10px 16px;margin-bottom:14px;font-size:.82rem;color:#166534">
      &#10003; Sin conflictos — no hay cursos consecutivos con examen el mismo día y turno en ${cuat}.
    </div>`;
  }

  // ── 5. Cabecera ──
  html += `<div class="parc-header">
    <div class="parc-title">&#128221; Exámenes Parciales — ${cuat} · Todos los cursos</div>
    <div class="parc-legend">
      ${cursos.map(c => `<div class="parc-legend-item"><span class="parc-legend-dot ${cursoBg[c]}"></span>${cursoLabel[c]} (${countByCurso[c]})</div>`).join('')}
      <div class="parc-legend-item"><span class="parc-legend-dot" style="background:#f59e0b;border-radius:50%"></span>Conflicto turno</div>
      <div class="parc-legend-item"><span class="parc-turno-tag parc-turno-man">mañana</span> fr. 1–3</div>
      <div class="parc-legend-item"><span class="parc-turno-tag parc-turno-tar">tarde</span> fr. 4–6</div>
    </div>
  </div>`;

  // ── 6. Tabla calendario ──
  html += `<div class="parc-table-wrap"><table class="parc-table">
    <thead><tr>
      <th class="th-semana">Semana</th>
      <th class="th-curso">Curso</th>
      ${dias.map((d,i) => `<th class="th-dia ${diaCls[i]}">${d.charAt(0)+d.slice(1).toLowerCase()}</th>`).join('')}
    </tr></thead>
    <tbody>`;

  const turnoCls = t => t === 'mañana' ? 'parc-turno-man' : 'parc-turno-tar';

  for (const sNum of semanas) {
    const weekData = byWeek[sNum];

    cursos.forEach((curso, idx) => {
      html += `<tr>`;
      if (idx === 0) {
        html += `<td class="parc-semana-cell" rowspan="${cursos.length}">SEM<br><strong>${sNum}</strong></td>`;
      }
      html += `<td class="parc-curso-cell ${cursoBg[curso]}">${cursoLabel[curso]}</td>`;

      for (const dia of dias) {
        const entries = weekData[curso]?.[dia];
        if (!entries || entries.size === 0) {
          html += `<td class="parc-empty"></td>`;
          continue;
        }
        let cellHtml = '';
        let cellHasConflict = false;
        for (const [,e] of entries) {
          const turno = getTurno(e.franjaOrden);
          const hasConflict = conflictSet.has(`${sNum}|${curso}|${dia}|${turno}`);
          if (hasConflict) cellHasConflict = true;
          const grupoStr = e.grupos.length < 2 ? `<span class="parc-grupo">Gr ${e.grupos[0]}</span>` : '';
          const conflictBadge = hasConflict
            ? `<span class="parc-conflict-badge">&#9888; conflicto ${turno}</span>` : '';
          cellHtml += `<div class="parc-entry ${entryBg[curso]}${hasConflict?' conflict-entry':''}">
            <span class="parc-turno-tag ${turnoCls(turno)}">${turno}</span>
            <span class="parc-name">${e.nombre}${conflictBadge}</span>
            <span class="parc-obs">${e.obs}</span>
            <span class="parc-time">${e.franja}</span>
            ${grupoStr}
          </div>`;
        }
        const cellStyle = cellHasConflict
          ? 'style="outline:3px solid #f59e0b;outline-offset:-2px;background:#fffbeb"' : '';
        html += `<td class="parc-cell" ${cellStyle}>${cellHtml}</td>`;
      }
      html += `</tr>`;
    });
    html += `<tr class="parc-row-sep"><td colspan="7"></td></tr>`;
  }
  html += `</tbody></table></div>`;

  // ── 7. Resumen por curso ──
  html += `<div class="parc-summary">`;
  for (const curso of cursos) {
    if (countByCurso[curso] === 0) continue;
    const asigSet = new Map();
    for (const sNum of semanas) {
      for (const dia of dias) {
        const entries = byWeek[sNum]?.[curso]?.[dia];
        if (!entries) continue;
        for (const [,e] of entries) {
          if (!asigSet.has(e.nombre)) asigSet.set(e.nombre, new Set());
          asigSet.get(e.nombre).add(e.obs);
        }
      }
    }
    html += `<div class="parc-summary-card" style="border-color:${borderColors[curso]}">
      <h4 style="color:${borderColors[curso]}">${cursoLabel[curso]} Curso — ${countByCurso[curso]} exámenes</h4>
      <ul>${[...asigSet.entries()].map(([n,obs]) =>
        `<li><strong>${n}</strong>: ${[...obs].join(', ')}</li>`).join('')}</ul>
    </div>`;
  }
  html += `</div>`;

  document.getElementById('parcGrid').innerHTML = html;
}

// ─── VISTA EXÁMENES FINALES ──────────────────────────────────────────────────
let FINALES_DATA = [];
let FINALES_EXCLUIDAS = new Set(); // claves "periodo|curso|asig_codigo"
let currentFinalPeriod = '1';

function getFinalesPeriods() {
  const parts = (CURSO_STR || '2025-2026').split('-');
  const yEnd = parseInt(parts[1]) || 2026;
  return {
    '1': { label: 'Enero &mdash; 1er Cuatrimestre', shortLabel: 'Enero',
           start: `${yEnd}-01-07`, end: `${yEnd}-01-31`, color: '#1e40af' },
    '2': { label: 'Junio &mdash; 2&ordm; Cuatrimestre', shortLabel: 'Junio',
           start: `${yEnd}-05-31`, end: `${yEnd}-06-22`, color: '#166534' },
    '3': { label: 'Extraordinaria (Jun&ndash;Jul)', shortLabel: 'Extraord.',
           start: `${yEnd}-06-24`, end: `${yEnd}-07-17`, color: '#7c2d12' },
  };
}

function getWeeksInPeriod(startStr, endStr) {
  const [sy, sm, sd] = startStr.split('-').map(Number);
  const [ey, em, ed] = endStr.split('-').map(Number);
  const start = new Date(sy, sm - 1, sd);
  const end   = new Date(ey, em - 1, ed);
  // Find the Monday of the week containing start
  let ws = new Date(start);
  const dow = ws.getDay(); // 0=Sun
  ws.setDate(ws.getDate() + ((dow === 0) ? -6 : 1 - dow));
  const weeks = [];
  while (ws <= end) {
    const days = [];
    for (let i = 0; i < 6; i++) { // Mon(0)…Sat(5)
      const d = new Date(ws);
      d.setDate(d.getDate() + i);
      days.push({ date: d, iso: isoLocal(d), inPeriod: d >= start && d <= end });
    }
    if (days.some(d => d.inPeriod)) weeks.push(days);
    ws.setDate(ws.getDate() + 7);
  }
  return weeks;
}

async function loadFinales() {
  try { FINALES_DATA = await api('/api/finales'); }
  catch(e) { FINALES_DATA = []; }
  try {
    const excl = await api('/api/finales/checklist');
    FINALES_EXCLUIDAS = new Set(excl.map(e => `${e.periodo}|${e.curso}|${e.asig_codigo}`));
  } catch(e) { FINALES_EXCLUIDAS = new Set(); }
  renderFinales();
}

function renderFinales() {
  const container = document.getElementById('finalesContainer');
  if (!container) return;

  const periods    = getFinalesPeriods();
  const period     = periods[currentFinalPeriod];
  const cursos     = ['1','2','3','4'];
  const cursoLabel = {'1':'1&ordm;','2':'2&ordm;','3':'3&ordm;','4':'4&ordm;'};
  const cursoBg    = {'1':'parc-curso-1','2':'parc-curso-2','3':'parc-curso-3','4':'parc-curso-4'};
  const entryBg    = {'1':'final-entry-1','2':'final-entry-2','3':'final-entry-3','4':'final-entry-4'};
  const borderColors = {'1':'#2563eb','2':'#16a34a','3':'#ca8a04','4':'#db2777'};
  const DIAS_LABEL = ['Lun','Mar','Mi&eacute;','Jue','Vie','S&aacute;b'];
  const DIAS_CLS   = ['lun','mar','mie','jue','vie','sab'];
  const MONTH_ABBR = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];

  // Agrupar exámenes: iso -> curso -> [entradas]
  const byDate = {};
  for (const f of FINALES_DATA) {
    if (!byDate[f.fecha]) byDate[f.fecha] = {};
    if (!byDate[f.fecha][f.curso]) byDate[f.fecha][f.curso] = [];
    byDate[f.fecha][f.curso].push(f);
  }

  const weeks = getWeeksInPeriod(period.start, period.end);

  // Detectar conflictos entre cursos CONSECUTIVOS mismo día + turno
  const conflictSet  = new Set();
  const conflictList = [];
  const pairs = [['1','2'],['2','3'],['3','4']];
  for (const week of weeks) {
    for (const dayObj of week) {
      if (!dayObj.inPeriod) continue;
      const dayE = byDate[dayObj.iso] || {};
      const cbt = { 'mañana': new Set(), 'tarde': new Set() };
      for (const c of cursos)
        for (const e of (dayE[c] || []))
          cbt[e.turno === 'tarde' ? 'tarde' : 'mañana'].add(c);
      for (const turno of ['mañana','tarde']) {
        for (const [cA, cB] of pairs) {
          if (cbt[turno].has(cA) && cbt[turno].has(cB)) {
            conflictSet.add(`${dayObj.iso}|${cA}|${turno}`);
            conflictSet.add(`${dayObj.iso}|${cB}|${turno}`);
            const nA = (dayE[cA]||[]).filter(e=>(e.turno==='tarde'?'tarde':'mañana')===turno).map(e=>e.asig_nombre||'—');
            const nB = (dayE[cB]||[]).filter(e=>(e.turno==='tarde'?'tarde':'mañana')===turno).map(e=>e.asig_nombre||'—');
            conflictList.push({ iso: dayObj.iso, turno, cA, cB, nA, nB });
          }
        }
      }
    }
  }

  // Contar exámenes por curso dentro del período
  const countByCurso = {'1':0,'2':0,'3':0,'4':0};
  const [psy,psm,psd] = period.start.split('-').map(Number);
  const [pey,pem,ped] = period.end.split('-').map(Number);
  const pStart = new Date(psy, psm-1, psd);
  const pEnd   = new Date(pey, pem-1, ped);
  for (const iso of Object.keys(byDate)) {
    const [iy,im,id2] = iso.split('-').map(Number);
    const dObj = new Date(iy, im-1, id2);
    if (dObj < pStart || dObj > pEnd) continue;
    for (const c of cursos) countByCurso[c] += (byDate[iso][c]||[]).length;
  }

  let html = '';

  // ── Selector de período + botones de acción ──
  html += `<div class="parc-header" style="margin-bottom:14px;flex-wrap:wrap;gap:10px">
    <div class="parc-title" style="color:${period.color}">&#127891; Ex&aacute;menes Finales &mdash; ${period.label}</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      ${Object.entries(periods).map(([k,p]) => `
        <button class="final-period-btn${currentFinalPeriod===k?' active':''} p${k}"
          onclick="currentFinalPeriod='${k}';renderFinales()">${p.shortLabel}</button>`).join('')}
    </div>
  </div>
  <div class="final-action-bar">
    <button class="btn-auto" id="btnAutoDistrib" onclick="autoDistributeExams()">
      &#9881; Distribuci&oacute;n autom&aacute;tica
    </button>
    <button class="btn-reset-auto" id="btnResetAuto" onclick="resetAutoExams()">
      &#10006; Reset autom&aacute;tico
    </button>
    <button class="btn-export-pdf" id="btnExportFinalPdf" onclick="exportFinalesPdf()">
      &#128438; Exportar PDF
    </button>
    <span style="font-size:.75rem;color:var(--text-light)">
      Las asignaturas a&ntilde;adidas manualmente no se modifican
    </span>
  </div>`;

  // ── Panel de conflictos ──
  if (conflictList.length > 0) {
    const tCls = t => t==='mañana' ? 'parc-turno-man' : 'parc-turno-tar';
    html += `<div class="parc-alert-panel">
      <h4>&#9888;&#65039; ${conflictList.length} conflicto${conflictList.length>1?'s':''} — cursos consecutivos en el mismo d&iacute;a y turno</h4>
      <div class="parc-conflict-list">
        ${conflictList.map(c => {
          const [,cm,cd] = c.iso.split('-').map(Number);
          return `<div class="parc-conflict-row">
            <span class="parc-conflict-sem">${cd} ${MONTH_ABBR[cm-1]}</span>
            <span class="parc-conflict-turno ${tCls(c.turno)}">${c.turno}</span>
            <span class="parc-conflict-detail">
              <strong style="color:${borderColors[c.cA]}">${c.cA}&ordm;</strong>: ${c.nA.join(', ')}
              &nbsp;&bull;&nbsp;
              <strong style="color:${borderColors[c.cB]}">${c.cB}&ordm;</strong>: ${c.nB.join(', ')}
            </span>
          </div>`;
        }).join('')}
      </div>
    </div>`;
  } else {
    html += `<div style="background:#dcfce7;border:1.5px solid #16a34a;border-radius:8px;padding:10px 16px;margin-bottom:14px;font-size:.82rem;color:#166534">
      &#10003; Sin conflictos en el per&iacute;odo seleccionado.
    </div>`;
  }

  // ── Leyenda ──
  html += `<div class="parc-legend" style="margin-bottom:14px;flex-wrap:wrap;gap:8px">
    ${cursos.map(c=>`<div class="parc-legend-item"><span class="parc-legend-dot ${cursoBg[c]}"></span>${c}&ordm; (${countByCurso[c]})</div>`).join('')}
    <div class="parc-legend-item"><span class="parc-legend-dot" style="background:#f59e0b;border-radius:50%"></span>Conflicto turno</div>
    <div class="parc-legend-item" style="color:var(--text-light);font-size:.73rem">&#128204; Clic en celda = a&ntilde;adir examen</div>
  </div>`;

  // ── Tabla calendario ──
  html += `<div class="final-table-wrap"><table class="final-table">
    <thead><tr>
      <th class="th-semana">Semana</th>
      <th class="th-curso">Curso</th>
      ${DIAS_LABEL.map((d,i)=>`<th class="th-dia ${DIAS_CLS[i]}">${d}</th>`).join('')}
    </tr></thead>
    <tbody>`;

  const turnoCls = t => t==='tarde' ? 'final-turno-tar' : 'final-turno-man';
  const turnoStr = t => t==='tarde' ? 'tarde' : 'ma&ntilde;ana';

  for (const week of weeks) {
    const firstD = week.find(d => d.inPeriod);
    const lastD  = [...week].reverse().find(d => d.inPeriod);
    const wkLabel = (firstD && lastD)
      ? `${firstD.date.getDate()}&ndash;${lastD.date.getDate()}<br><span style="font-weight:500;font-size:.7rem">${MONTH_ABBR[firstD.date.getMonth()]}</span>`
      : '';

    cursos.forEach((curso, idx) => {
      html += `<tr>`;
      if (idx === 0)
        html += `<td class="final-semana-cell" rowspan="${cursos.length}">${wkLabel}</td>`;
      html += `<td class="parc-curso-cell ${cursoBg[curso]}">${curso}&ordm;</td>`;

      for (let di = 0; di < 6; di++) { // Mon(0)…Sat(5)
        const dayObj = week[di];
        if (!dayObj.inPeriod) {
          html += `<td class="final-cell final-cell-out"></td>`;
          continue;
        }
        const iso     = dayObj.iso;
        const entries = byDate[iso]?.[curso] || [];
        let cellConflict = false;
        let cellHtml = '';

        for (const e of entries) {
          const turno   = e.turno === 'tarde' ? 'tarde' : 'mañana';
          const hasCfl  = conflictSet.has(`${iso}|${curso}|${turno}`);
          if (hasCfl) cellConflict = true;
          const isAuto  = !!e.auto_generated;
          const badge   = hasCfl ? `<span class="parc-conflict-badge">&#9888;</span>` : '';
          const autoBadge = isAuto ? ` <span class="final-auto-badge" title="Colocado autom\u00e1ticamente">&#9881;</span>` : '';
          cellHtml += `<div class="final-entry ${entryBg[curso]}${hasCfl?' conflict-entry':''}${isAuto?' auto-entry':''}"
            onclick="event.stopPropagation();openFinalEdit(${e.id},'${iso}','${curso}')">
            <span class="final-turno ${turnoCls(turno)}">${turnoStr(turno)}</span>
            <span class="final-name">${_escHtml(e.asig_nombre||'\u2014')}${badge}${autoBadge}</span>
            ${e.observacion?`<span class="final-obs">${_escHtml(e.observacion)}</span>`:''}
          </div>`;
        }
        cellHtml += `<div class="final-add-btn" onclick="openFinalAdd('${iso}','${curso}')">+ a&ntilde;adir</div>`;

        const cflStyle = cellConflict ? 'style="outline:3px solid #f59e0b;outline-offset:-2px;background:#fffbeb"' : '';
        html += `<td class="final-cell" ${cflStyle}>${cellHtml}</td>`;
      }
      html += `</tr>`;
    });
    html += `<tr class="final-row-sep"><td colspan="8"></td></tr>`;
  }
  html += `</tbody></table></div>`;

  // ── Checklist de asignaturas ──
  const cuatChk    = { '1': '1C', '2': '2C', '3': null }[currentFinalPeriod];
  const asigMapChk = _getAsigsByCursoCuat(cuatChk);
  const cuatChkLabel = cuatChk ? cuatChk : '1C + 2C';

  // Para cada asignatura, verificar si ya tiene examen registrado en este período
  const [psy2,psm2,psd2] = period.start.split('-').map(Number);
  const [pey2,pem2,ped2] = period.end.split('-').map(Number);
  const pS2 = new Date(psy2, psm2-1, psd2);
  const pE2 = new Date(pey2, pem2-1, ped2);
  function hasExamEntry(curso, nom) {
    return FINALES_DATA.some(f => {
      if (f.curso !== curso || f.asig_nombre !== nom) return false;
      const [fy,fm,fd] = f.fecha.split('-').map(Number);
      const d = new Date(fy, fm-1, fd);
      return d >= pS2 && d <= pE2;
    });
  }

  // Contadores para el footer
  let totalAsigs = 0, totalMarcadas = 0, totalConExamen = 0;

  const chkCols = cursos.map(curso => {
    const asigsCurso = [...(asigMapChk[curso]?.entries() || [])]
      .sort((a, b) => a[1].localeCompare(b[1], 'es'));
    totalAsigs += asigsCurso.length;

    const items = asigsCurso.map(([cod, nom]) => {
      const key       = `${currentFinalPeriod}|${curso}|${cod}`;
      const checked   = !FINALES_EXCLUIDAS.has(key);
      const hasExam   = hasExamEntry(curso, nom);
      if (checked)  totalMarcadas++;
      if (hasExam)  totalConExamen++;
      return `<label class="final-checklist-item${checked ? '' : ' unchecked'}"
          data-periodo="${currentFinalPeriod}" data-curso="${curso}"
          data-cod="${_escHtml(cod)}" data-nom="${_escHtml(nom)}">
        <input type="checkbox" ${checked ? 'checked' : ''}
               onchange="toggleFinalChecklist(this)">
        <span class="final-chk-nom">${_escHtml(nom)}</span>
        ${hasExam ? '<span class="final-chk-ok" title="Examen registrado en el calendario">&#10003;</span>' : ''}
      </label>`;
    }).join('');

    const hdr = {'1':'parc-curso-1','2':'parc-curso-2','3':'parc-curso-3','4':'parc-curso-4'}[curso];
    return `<div class="final-checklist-col">
      <div class="final-checklist-col-header ${hdr}">${curso}&ordm; Curso &mdash; ${asigsCurso.length} asig.</div>
      <div class="final-checklist-col-body">${items || '<span style="color:var(--text-light);font-size:.75rem;padding:4px 2px;display:block">Sin asignaturas</span>'}</div>
    </div>`;
  }).join('');

  html += `<div class="final-checklist-section">
    <div class="final-checklist-title">
      &#9745; Asignaturas convocadas &mdash; ${cuatChkLabel}
      <span>(desmarcar las que NO tendr&aacute;n examen; &#10003; = fecha ya registrada)</span>
    </div>
    <div class="final-checklist-grid">${chkCols}</div>
    <div class="final-checklist-footer">
      <span>Total: <b>${totalAsigs}</b> asig.</span>
      <span>Convocadas: <b>${totalMarcadas}</b></span>
      <span>Con fecha: <b>${totalConExamen}</b></span>
      <span>Sin fecha: <b>${totalMarcadas - totalConExamen}</b></span>
    </div>
  </div>`;

  container.innerHTML = html;
}

// ─── DISTRIBUCIÓN AUTOMÁTICA ─────────────────────────────────────────────────

/* Devuelve todos los días (Lun-Sáb) dentro del rango de fechas del período */
function _getDaysInPeriod(startStr, endStr) {
  const [sy,sm,sd] = startStr.split('-').map(Number);
  const [ey,em,ed] = endStr.split('-').map(Number);
  const start = new Date(sy, sm-1, sd);
  const end   = new Date(ey, em-1, ed);
  const days  = [];
  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    if (d.getDay() !== 0) days.push(isoLocal(new Date(d))); // excluir domingos
  }
  return days;
}

/* True si la fecha ISO es sábado */
function _isSaturday(iso) {
  const [y,m,d] = iso.split('-').map(Number);
  return new Date(y, m-1, d).getDay() === 6;
}

/* Días naturales entre dos fechas ISO (positivo si isoB > isoA) */
function _daysBetween(isoA, isoB) {
  const [ay,am,ad] = isoA.split('-').map(Number);
  const [by,bm,bd] = isoB.split('-').map(Number);
  return Math.round((new Date(by,bm-1,bd) - new Date(ay,am-1,ad)) / 86400000);
}

/* ¿Se pueden colocar n exámenes en 'days' con al menos minGap días naturales entre sí? */
function _canPlaceWithGap(days, n, minGap) {
  if (n === 0) return true;
  if (days.length < n) return false;
  let count = 1, lastIdx = 0;
  for (let i = 1; i < days.length && count < n; i++) {
    if (_daysBetween(days[lastIdx], days[i]) >= minGap) { count++; lastIdx = i; }
  }
  return count >= n;
}

/* Calcula las posiciones ideales (índices en allDays) para n exámenes de un curso.
   Usa búsqueda binaria para maximizar el hueco mínimo entre exámenes consecutivos. */
function _idealPositions(allDays, n) {
  if (n === 0) return [];
  if (n === 1) return [Math.floor(allDays.length / 2)];
  // Búsqueda binaria sobre el gap mínimo
  let lo = 1, hi = Math.ceil((allDays.length - 1) / (n - 1)) + 1;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (_canPlaceWithGap(allDays, n, mid)) lo = mid; else hi = mid - 1;
  }
  // Extraer posiciones greedy con el gap óptimo encontrado
  const pos = [0]; let lastIdx = 0;
  while (pos.length < n) {
    let found = false;
    for (let i = lastIdx + 1; i < allDays.length; i++) {
      if (_daysBetween(allDays[lastIdx], allDays[i]) >= lo) {
        pos.push(i); lastIdx = i; found = true; break;
      }
    }
    if (!found) { pos.push(allDays.length - 1); break; }
  }
  return pos;
}

/* Devuelve el turno disponible para `curso` en el día `iso`, o null si no es posible.
   Restricciones:
   - Cursos consecutivos (1-2, 2-3, 3-4) NO pueden coincidir el mismo día (ningún turno).
   - Cursos no consecutivos pueden coincidir pero en turnos distintos.
   - Cada turno admite solo un curso.
   - Los sábados NO tienen turno de tarde. */
function _getSlot(dayUsage, iso, curso) {
  const day    = dayUsage[iso] || { m: null, t: null };
  const consec = { '1':['2'], '2':['1','3'], '3':['2','4'], '4':['3'] };
  const onDay  = [day.m, day.t].filter(Boolean);
  for (const other of onDay)
    if ((consec[curso] || []).includes(String(other))) return null; // bloqueo total
  if (!day.m) return 'mañana';
  if (!_isSaturday(iso) && !day.t) return 'tarde';
  return null; // día lleno (o sábado con mañana ya ocupada)
}

/* Algoritmo de distribución óptima (máxima separación mínima + búsqueda binaria):
   1. Calcula posiciones ideales maximizando el hueco mínimo por curso.
   2. Procesa los exámenes intercalando cursos (por posición ideal).
   3. Para cada examen, busca el día más cercano a la ideal que cumpla TODAS las restricciones:
      - No cursos consecutivos el mismo día.
      - No sábados por la tarde.
      - No exámenes en días consecutivos para el mismo curso (≥ 2 días de diferencia). */
function _runDistribution(allDays, subsByCurso, dayUsage) {
  const cursos = ['1','2','3','4'];
  const result = [];

  // Días ya asignados por curso (manual + auto en construcción), para control de días consecutivos
  const daysByCurso = { '1':[], '2':[], '3':[], '4':[] };
  for (const [iso, usage] of Object.entries(dayUsage)) {
    if (usage.m) { const c = String(usage.m); if (daysByCurso[c]) daysByCurso[c].push(iso); }
    if (usage.t) { const c = String(usage.t); if (daysByCurso[c]) daysByCurso[c].push(iso); }
  }

  // Posiciones ideales por curso y construcción de items
  const items = [];
  for (const curso of cursos) {
    const subs = subsByCurso[curso] || [];
    if (!subs.length) continue;
    const pos = _idealPositions(allDays, subs.length);
    subs.forEach((sub, i) => items.push({
      curso, nom: sub.nom, cod: sub.cod || '',
      idealIdx: pos[i] !== undefined ? pos[i] : Math.floor(allDays.length / 2)
    }));
  }

  // Ordenar por posición ideal, con interleaving de cursos como desempate
  items.sort((a, b) => a.idealIdx - b.idealIdx || a.curso.localeCompare(b.curso));

  // ¿El día 'iso' viola la restricción de días consecutivos para 'curso'?
  const hasConsecConflict = (curso, iso) =>
    daysByCurso[curso].some(d => Math.abs(_daysBetween(d, iso)) < 2);

  for (const item of items) {
    let placed = false;
    for (let off = 0; off < allDays.length && !placed; off++) {
      const candidates = off === 0 ? [item.idealIdx] : [item.idealIdx + off, item.idealIdx - off];
      for (const idx of candidates) {
        if (idx < 0 || idx >= allDays.length) continue;
        const iso = allDays[idx];
        // Restricción: no días consecutivos para el mismo curso
        if (hasConsecConflict(item.curso, iso)) continue;
        // El mismo curso no puede tener dos exámenes el mismo día
        const day = dayUsage[iso] || { m: null, t: null };
        if (String(day.m) === item.curso || String(day.t) === item.curso) continue;
        const slot = _getSlot(dayUsage, iso, item.curso);
        if (slot !== null) {
          if (!dayUsage[iso]) dayUsage[iso] = { m: null, t: null };
          dayUsage[iso][slot === 'mañana' ? 'm' : 't'] = item.curso;
          daysByCurso[item.curso].push(iso);
          result.push({ fecha: iso, curso: item.curso, asig_nombre: item.nom, asig_codigo: item.cod || '', turno: slot });
          placed = true;
          break;
        }
      }
    }
    if (!placed) console.warn(`[Finales] No se pudo colocar: ${item.curso}º - ${item.nom}`);
  }
  return result;
}

async function autoDistributeExams() {
  const btn = document.getElementById('btnAutoDistrib');
  if (btn) { btn.disabled = true; btn.textContent = '⟳ Calculando…'; }

  try {
    const periods = getFinalesPeriods();
    const period  = periods[currentFinalPeriod];
    const cuatChk = { '1': '1C', '2': '2C', '3': null }[currentFinalPeriod];

    // 1. Días disponibles del período (Lun-Sáb)
    const allDays = _getDaysInPeriod(period.start, period.end);

    // 2. Asignaturas marcadas por curso (excluir desmarcadas)
    const asigMap = _getAsigsByCursoCuat(cuatChk);
    const subsByCurso = {};
    for (const curso of ['1','2','3','4']) {
      subsByCurso[curso] = [...(asigMap[curso]?.entries() || [])]
        .filter(([cod]) => !FINALES_EXCLUIDAS.has(`${currentFinalPeriod}|${curso}|${cod}`))
        .map(([cod, nom]) => ({ cod, nom }));
    }

    // 3. Exámenes manuales ya colocados en este período (son prioritarios)
    const [psy,psm,psd] = period.start.split('-').map(Number);
    const [pey,pem,ped] = period.end.split('-').map(Number);
    const pS = new Date(psy, psm-1, psd);
    const pE = new Date(pey, pem-1, ped);
    const manualExams = FINALES_DATA.filter(f => {
      if (f.auto_generated) return false;
      const [fy,fm,fd] = f.fecha.split('-').map(Number);
      const d = new Date(fy, fm-1, fd);
      return d >= pS && d <= pE;
    });

    // 4. Eliminar de la lista de "por colocar" las que ya están en manual
    const manualSet = new Set(manualExams.map(f => `${f.curso}|${f.asig_nombre}`));
    for (const curso of ['1','2','3','4'])
      subsByCurso[curso] = subsByCurso[curso].filter(s => !manualSet.has(`${curso}|${s.nom}`));

    // 5. Inicializar dayUsage con los exámenes manuales
    const dayUsage = {};
    for (const e of manualExams) {
      if (!dayUsage[e.fecha]) dayUsage[e.fecha] = { m: null, t: null };
      dayUsage[e.fecha][e.turno === 'tarde' ? 't' : 'm'] = e.curso;
    }

    // 6. Borrar exámenes auto anteriores del período y recalcular
    await api('/api/finales/reset-auto', { fecha_inicio: period.start, fecha_fin: period.end });

    // 7. Ejecutar algoritmo
    const placements = _runDistribution(allDays, subsByCurso, dayUsage);

    // 8. Guardar en bloque
    if (placements.length > 0) {
      const res = await api('/api/finales/batch-set', {
        exams: placements.map(p => ({ ...p, auto_generated: 1, observacion: '' }))
      });
      showToast(`${res.inserted} ex\u00e1menes distribuidos \u2714`);
    } else {
      showToast('No hay asignaturas pendientes de colocar');
    }
    await loadFinales();
  } catch(e) {
    alert('Error en distribución: ' + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '&#9881; Distribuci\u00f3n autom\u00e1tica'; }
  }
}

async function resetAutoExams() {
  const btn = document.getElementById('btnResetAuto');
  if (!confirm('¿Eliminar todos los exámenes colocados automáticamente en este período?')) return;
  if (btn) { btn.disabled = true; btn.textContent = '⟳ Eliminando…'; }
  try {
    const period = getFinalesPeriods()[currentFinalPeriod];
    const res = await api('/api/finales/reset-auto', {
      fecha_inicio: period.start, fecha_fin: period.end
    });
    await loadFinales();
    showToast(`${res.deleted} ex\u00e1menes autom\u00e1ticos eliminados \u2714`);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '&#10006; Reset autom\u00e1tico'; }
  }
}

async function exportFinalesPdf() {
  const btn = document.getElementById('btnExportFinalPdf');
  if (btn) { btn.disabled = true; btn.textContent = '\u23f3 Generando\u2026'; }
  try {
    const url = `/api/finales/export-pdf?periodo=${currentFinalPeriod}`;
    const resp = await fetch(url);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: resp.statusText }));
      throw new Error(err.error || resp.statusText);
    }
    const blob = await resp.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    const periods = getFinalesPeriods();
    const shortLabel = periods[currentFinalPeriod]?.shortLabel || 'periodo';
    a.download = `Finales_EXPORT_PREFIX_PLACEHOLDER_${CURSO_STR.replace('-','_')}_${shortLabel}.pdf`;
    a.click();
    URL.revokeObjectURL(a.href);
    showToast('\u2714 PDF generado');
  } catch(e) {
    alert('Error al generar el PDF: ' + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '&#128438; Exportar PDF'; }
  }
}

// ─── FIN DISTRIBUCIÓN AUTOMÁTICA ─────────────────────────────────────────────

function openFinalAdd(iso, curso) {
  _openFinalPopup(null, iso, curso, '', '', 'mañana', '');
}
function openFinalEdit(id, iso, curso) {
  const e = FINALES_DATA.find(f => f.id === id);
  if (!e) return;
  _openFinalPopup(id, iso, curso, e.asig_nombre||'', e.asig_codigo||'', e.turno||'mañana', e.observacion||'');
}

/* Construye un mapa curso -> Map(codigo->nombre).
   cuat = '1C' | '2C' | null  (null = ambos cuatrimestres) */
function _getAsigsByCursoCuat(cuat) {
  const map = {};
  for (const grupo of Object.values(DB.grupos || {})) {
    if (cuat && grupo.cuatrimestre !== cuat) continue;
    const c = String(grupo.curso);
    if (!map[c]) map[c] = new Map();
    for (const sem of grupo.semanas || [])
      for (const cls of sem.clases || [])
        if (cls.asig_codigo && cls.asig_nombre && !cls.es_no_lectivo)
          map[c].set(cls.asig_codigo, cls.asig_nombre);
  }
  return map;
}

/* Escapa caracteres especiales HTML para usar en atributos value */
function _escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _openFinalPopup(id, iso, curso, asigNombre, asigCodigo, turno, obs) {
  closeFinalPopup();
  const [y, m, d] = iso.split('-').map(Number);
  const MN = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Ago','Sep','Oct','Nov','Dic'];
  const label = `${d} de ${MN[m-1]} ${y} \u00b7 ${curso}\u00ba curso`;

  /* Período 1 (Enero) → solo 1C | Período 2 (Junio) → solo 2C | Período 3 → todos */
  const cuatPorPeriodo = { '1': '1C', '2': '2C', '3': null };
  const cuat = cuatPorPeriodo[currentFinalPeriod];
  const cuatLabel = cuat ? cuat : '1C + 2C';

  /* Asignaturas filtradas por curso + cuatrimestre, ordenadas alfabéticamente */
  const asigMap    = _getAsigsByCursoCuat(cuat);
  const asigsCurso = [...(asigMap[curso]?.entries() || [])]
    .sort((a, b) => a[1].localeCompare(b[1], 'es'));

  /* Si la asignatura guardada no está en la lista la añadimos marcada con aviso */
  const inList = asigsCurso.some(([, nom]) => nom === asigNombre);

  /* Construir opciones usando el DOM (evita problemas con comillas/caracteres especiales) */
  const overlay = document.createElement('div');
  overlay.className = 'festivo-popup-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:9998;';
  overlay.onclick = closeFinalPopup;
  document.body.appendChild(overlay);

  const popup = document.createElement('div');
  popup.id = 'finalPopup';
  popup.className = 'final-popup';

  /* Esqueleto del popup sin las opciones */
  popup.innerHTML = `
    <h4>&#127891; ${_escHtml(label)}</h4>
    <label>Asignatura
      <span style="color:var(--text-light);font-weight:500;text-transform:none;font-size:.72rem">
        (${curso}\u00ba &mdash; ${cuatLabel} &mdash; ${asigsCurso.length} asig.)
      </span>
    </label>
    <select id="fpAsig"></select>
    <label>Turno</label>
    <select id="fpTurnoFinal">
      <option value="ma\u00f1ana">Ma\u00f1ana (fr. 1\u20133)</option>
      <option value="tarde">Tarde (fr. 4\u20136)</option>
    </select>
    <label>Observaci\u00f3n (opcional)</label>
    <input type="text" id="fpObsFinal" placeholder="Ej: Final, Recuperaci\u00f3n...">
    <div class="popup-btns">
      ${id !== null
        ? `<button class="btn btn-danger btn-sm" id="fpBtnDel">&#128465; Eliminar</button>`
        : ''}
      <button class="btn btn-outline btn-sm" id="fpBtnCan">Cancelar</button>
      <button class="btn btn-primary btn-sm" id="fpBtnSave">&#10004; Guardar</button>
    </div>`;

  popup.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:9999';
  document.body.appendChild(popup);

  /* Rellenar el select de asignaturas via DOM (sin riesgo de inyección HTML) */
  const sel = document.getElementById('fpAsig');
  const opt0 = new Option('— Seleccionar asignatura —', '');
  sel.appendChild(opt0);

  if (asigNombre && !inList) {
    const optExtra = new Option('\u26a0 ' + asigNombre, asigNombre);
    optExtra.selected = true;
    sel.appendChild(optExtra);
  }
  for (const [cod, nom] of asigsCurso) {
    const o = new Option(nom, nom);
    o.dataset.cod = cod;
    if (nom === asigNombre) o.selected = true;
    sel.appendChild(o);
  }

  /* Rellenar turno y observación */
  const selTurno = document.getElementById('fpTurnoFinal');
  selTurno.value = (turno === 'tarde') ? 'tarde' : 'ma\u00f1ana';

  document.getElementById('fpObsFinal').value = obs || '';

  /* Botones via JS para evitar problemas con comillas en los parámetros */
  document.getElementById('fpBtnCan').onclick = closeFinalPopup;
  document.getElementById('fpBtnSave').onclick = () => saveFinal(id, iso, curso, 'set');
  if (id !== null) {
    document.getElementById('fpBtnDel').onclick = () => saveFinal(id, iso, curso, 'delete');
  }

  sel.focus();
}

function closeFinalPopup() {
  document.getElementById('finalPopup')?.remove();
  document.querySelector('.festivo-popup-overlay')?.remove();
}

async function toggleFinalChecklist(checkbox) {
  const label   = checkbox.closest('.final-checklist-item');
  const periodo = label.dataset.periodo;
  const curso   = label.dataset.curso;
  const cod     = label.dataset.cod;
  const nom     = label.dataset.nom;
  const checked = checkbox.checked;

  /* Actualizar estado visual inmediatamente (sin esperar al servidor) */
  label.classList.toggle('unchecked', !checked);

  /* Actualizar Set local */
  const key = `${periodo}|${curso}|${cod}`;
  if (checked) FINALES_EXCLUIDAS.delete(key);
  else         FINALES_EXCLUIDAS.add(key);

  /* Actualizar contadores del footer sin re-renderizar todo */
  const section = label.closest('.final-checklist-section');
  if (section) {
    const allItems   = section.querySelectorAll('.final-checklist-item');
    const marcadas   = section.querySelectorAll('.final-checklist-item:not(.unchecked)').length;
    const conExamen  = section.querySelectorAll('.final-checklist-item:not(.unchecked) .final-chk-ok').length;
    const footer     = section.querySelector('.final-checklist-footer');
    if (footer) {
      const bs = footer.querySelectorAll('b');
      if (bs[1]) bs[1].textContent = marcadas;
      if (bs[3]) bs[3].textContent = marcadas - conExamen;
    }
  }

  /* Persistir en la BD */
  await api('/api/finales/checklist/toggle', {
    periodo, curso, asig_codigo: cod, asig_nombre: nom, checked: checked ? 1 : 0
  });
}

async function saveFinal(id, iso, curso, action) {
  /* Leer valores del formulario ANTES de cerrar el popup */
  let asigNombre = '', turno = 'mañana', obs = '';
  if (action !== 'delete') {
    asigNombre = document.getElementById('fpAsig')?.value || '';
    turno      = document.getElementById('fpTurnoFinal')?.value || 'mañana';
    obs        = document.getElementById('fpObsFinal')?.value || '';
    if (!asigNombre) {
      document.getElementById('fpAsig')?.focus();
      return;
    }
  }
  closeFinalPopup();

  let res;
  if (action === 'delete') {
    res = await api('/api/finales/set', { id, action: 'delete' });
  } else {
    res = await api('/api/finales/set', {
      id: (id !== null && id !== 'null') ? id : null,
      fecha: iso, curso, asig_nombre: asigNombre, turno, observacion: obs, action: 'set'
    });
  }
  if (res?.error) { alert('Error: ' + res.error); return; }
  await loadFinales();
  showToast(action === 'delete' ? 'Examen eliminado \u2714' : 'Examen guardado \u2714');
}

// ─── EVOLUCIÓN ACUMULADA DE PRÁCTICAS ────────────────────────────────────────

// Paleta de colores para subgrupos (hasta 6 subgrupos)
const EVOL_COLORS = ['#2d5faa','#e74c3c','#27ae60','#f39c12','#8e44ad','#16a085'];

/**
 * Calcula la evolución acumulada semana a semana de sesiones LAB/INFO
 * para cada asignatura y subgrupo de un grupo.
 * Devuelve: { asig_codigo: { nombre, weekNums:[…], sgLab:{sg:[acum…]}, sgInfo:{sg:[acum…]} } }
 */
function computeEvolucionData(weeks) {
  const asigEvol = {};
  const seenPrac = new Set();

  weeks.forEach((w, wi) => {
    w.clases.forEach(c => {
      if (!c.asig_codigo || c.es_no_lectivo) return;
      const tipo = getActType(c);
      if (tipo !== 'lab' && tipo !== 'info') return;

      const sg = (c.subgrupo || '').trim() || 'todos';
      const dk = `${c.asig_codigo}|${tipo}|${sg}|${w.numero}|${c.dia}|${c.franja_id}`;
      if (seenPrac.has(dk)) return;
      seenPrac.add(dk);

      if (!asigEvol[c.asig_codigo]) {
        asigEvol[c.asig_codigo] = {
          nombre: c.asig_nombre,
          weekNums: weeks.map(ww => ww.numero),
          sgLab: {},
          sgInfo: {}
        };
        // Inicializar arrays a 0 para todas las semanas
        asigEvol[c.asig_codigo]._n = weeks.length;
      }
      const target = tipo === 'lab' ? asigEvol[c.asig_codigo].sgLab : asigEvol[c.asig_codigo].sgInfo;
      if (!target[sg]) target[sg] = new Array(weeks.length).fill(0);
      target[sg][wi]++;
    });
  });

  // Convertir a acumulado
  for (const cod of Object.keys(asigEvol)) {
    const a = asigEvol[cod];
    for (const map of [a.sgLab, a.sgInfo]) {
      for (const sg of Object.keys(map)) {
        let acc = 0;
        map[sg] = map[sg].map(v => { acc += v; return acc; });
      }
    }
  }
  return asigEvol;
}

/**
 * Genera un <svg> de evolución acumulada para una asignatura.
 * sgLab / sgInfo: { subgrupo: [val0, val1, ...valN] }
 * weekNums: [1, 2, 3, ...]
 */
function buildEvolucionSVG(weekNums, sgLab, sgInfo) {
  const W = 320, H = 170;
  const ML = 34, MT = 12, MR = 14, MB = 26;
  const PW = W - ML - MR;   // plot width
  const PH = H - MT - MB;   // plot height

  const allSeries = [];
  const sgKeys = [...new Set([...Object.keys(sgLab), ...Object.keys(sgInfo)])].sort((a,b) => a.localeCompare(b,undefined,{numeric:true}));
  sgKeys.forEach((sg, ci) => {
    const color = EVOL_COLORS[ci % EVOL_COLORS.length];
    if (sgLab[sg])  allSeries.push({ sg, tipo: 'lab',  vals: sgLab[sg],  color, dash: '' });
    if (sgInfo[sg]) allSeries.push({ sg, tipo: 'info', vals: sgInfo[sg], color, dash: '5,3' });
  });

  const maxY = Math.max(1, ...allSeries.map(s => Math.max(...s.vals)));
  const nW   = weekNums.length;

  // Ejes y grid
  const yTicks = [];
  const yStep = maxY <= 4 ? 1 : maxY <= 8 ? 2 : maxY <= 12 ? 3 : 4;
  for (let y = 0; y <= maxY; y += yStep) yTicks.push(y);

  function xPos(i)  { return ML + (i / Math.max(nW - 1, 1)) * PW; }
  function yPos(v)  { return MT + PH - (v / maxY) * PH; }

  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="font-family:sans-serif">`;

  // Grid horizontal
  yTicks.forEach(y => {
    const yp = yPos(y);
    svg += `<line x1="${ML}" y1="${yp}" x2="${W-MR}" y2="${yp}" stroke="#e2e8f0" stroke-width="1"/>`;
    svg += `<text x="${ML-4}" y="${yp+3.5}" text-anchor="end" font-size="9" fill="#888">${y}</text>`;
  });

  // Eje X — marcas de semana (mostrar cada 1 si ≤10, cada 2 si ≤16, cada 3 si más)
  const xEvery = nW <= 10 ? 1 : nW <= 16 ? 2 : 3;
  weekNums.forEach((wn, i) => {
    const xp = xPos(i);
    if (i % xEvery === 0 || i === nW - 1) {
      svg += `<line x1="${xp}" y1="${MT}" x2="${xp}" y2="${MT+PH}" stroke="#e8edf5" stroke-width="1"/>`;
      svg += `<text x="${xp}" y="${H - MB + 10}" text-anchor="middle" font-size="9" fill="#888">S${wn}</text>`;
    }
  });

  // Ejes principales
  svg += `<line x1="${ML}" y1="${MT}" x2="${ML}" y2="${MT+PH}" stroke="#94a3b8" stroke-width="1.5"/>`;
  svg += `<line x1="${ML}" y1="${MT+PH}" x2="${W-MR}" y2="${MT+PH}" stroke="#94a3b8" stroke-width="1.5"/>`;

  // Series
  allSeries.forEach(s => {
    const pts = s.vals.map((v, i) => `${xPos(i)},${yPos(v)}`).join(' ');
    svg += `<polyline points="${pts}" fill="none" stroke="${s.color}" stroke-width="2.2"
      stroke-dasharray="${s.dash}" stroke-linejoin="round" stroke-linecap="round"/>`;
    // Puntos en cambios de valor
    s.vals.forEach((v, i) => {
      if (i === 0 || s.vals[i-1] !== v || i === s.vals.length - 1) {
        svg += `<circle cx="${xPos(i)}" cy="${yPos(v)}" r="2.8" fill="${s.color}" stroke="#fff" stroke-width="1"/>`;
      }
    });
  });

  // Label eje Y
  svg += `<text x="8" y="${MT + PH/2}" text-anchor="middle" font-size="9" fill="#64748b"
    transform="rotate(-90,8,${MT + PH/2})">ses. acum.</text>`;

  svg += `</svg>`;
  return { svg, series: allSeries.map((s,i) => ({ sg: s.sg, tipo: s.tipo, color: s.color, dash: s.dash })) };
}

/**
 * Construye y renderiza la sección completa de gráficos de evolución.
 */
function renderEvolucionSection() {
  const prefix = currentCurso + '_' + currentCuat + '_grupo_';
  const groupKeys = Object.keys(DB.grupos).filter(k => k.startsWith(prefix)).sort();
  const container = document.getElementById('evolucionSection');
  if (!container) return;

  let html = '';

  groupKeys.forEach(gKey => {
    const g = DB.grupos[gKey];
    const groupLabel = g.grupo === 'unico' ? 'Grupo Único' : 'Grupo ' + g.grupo;
    const weeks = g.semanas;
    const evol = computeEvolucionData(weeks);
    const codsWithData = Object.keys(evol).filter(cod => {
      const a = evol[cod];
      return Object.keys(a.sgLab).length > 0 || Object.keys(a.sgInfo).length > 0;
    }).sort((a,b) => evol[a].nombre.localeCompare(evol[b].nombre));

    if (codsWithData.length === 0) return;

    html += `<div class="evol-section">
      <div class="evol-section-title">&#128202; Evolución acumulada de prácticas — ${groupLabel}</div>
      <div class="evol-grid">`;

    codsWithData.forEach(cod => {
      const a = evol[cod];
      const { svg, series } = buildEvolucionSVG(a.weekNums, a.sgLab, a.sgInfo);

      // Leyenda
      const sgKeys = [...new Set(series.map(s => s.sg))].sort((a,b) => a.localeCompare(b,undefined,{numeric:true}));
      let legendHtml = '';
      sgKeys.forEach((sg, ci) => {
        const color = EVOL_COLORS[ci % EVOL_COLORS.length];
        const lbl = sg === 'todos' ? 'Todos' : 'Sg.' + sg;
        const hasLab  = a.sgLab[sg];
        const hasInfo = a.sgInfo[sg];
        if (hasLab)  legendHtml += `<span class="evol-legend-item"><span class="evol-legend-line" style="background:${color};height:2px"></span>${lbl} LAB</span>`;
        if (hasInfo) legendHtml += `<span class="evol-legend-item"><span class="evol-legend-line" style="background:${color};background:repeating-linear-gradient(90deg,${color} 0,${color} 5px,transparent 5px,transparent 8px)"></span>${lbl} INFO</span>`;
      });

      html += `<div class="evol-card">
        <div class="evol-card-header">${a.nombre}</div>
        <div class="evol-card-body">${svg}</div>
        <div class="evol-legend">${legendHtml}</div>
      </div>`;
    });

    html += `</div></div>`;
  });

  container.innerHTML = html || '';
}

// ─── ESTADÍSTICAS ─────────────────────────────────────────────────────────────

function renderStats() {
  // Todos los grupos del curso+cuatrimestre actual
  const prefix = currentCurso + '_' + currentCuat + '_grupo_';
  const groupKeys = Object.keys(DB.grupos).filter(k => k.startsWith(prefix)).sort();

  document.getElementById('statsGrid').innerHTML = '';

  // Banner de diagnóstico fichas
  const fichasN = DB && DB.fichas ? Object.keys(DB.fichas).length : 0;
  const fichasBanner = fichasN > 0
    ? `<div style="background:#dcfce7;border:1px solid #16a34a;border-radius:8px;padding:8px 16px;margin-bottom:12px;font-size:.82rem;color:#166534">
        &#10003; <strong>Fichas cargadas: ${fichasN} asignaturas</strong> (desde base de datos).
        Se verifica AF1 (Teor&iacute;a) + AF2 (Lab) + AF4 (Info) contra el horario.
        AF5 (eval. continua en horario lectivo) y AF6 (eval. final/continua fuera de horario) se muestran como referencia en la columna Total.
        Las filas <span style="background:#fde8e8;padding:1px 6px;border-radius:3px;border:1px solid #dc2626">rojas</span> no cumplen AF1+AF2+AF4 de la ficha.
       </div>`
    : `<div style="background:#fee2e2;border:1px solid #dc2626;border-radius:8px;padding:8px 16px;margin-bottom:12px;font-size:.82rem;color:#991b1b">
        &#9888; <strong>Sin datos de fichas en BD</strong> — ejecuta <code>rebuild_fichas.py</code> para cargarlos.
       </div>`;

  let sectionsHtml = fichasBanner;
  groupKeys.forEach(gKey => {
    const g      = DB.grupos[gKey];
    const weeks  = g.semanas;
    const asigs  = computeGroupStats(weeks);
    let totalH = 0, totalParciales = 0;
    asigs.forEach(a => {
      const maxInfo = Object.values(a.infoBySubgrupo).length ? Math.max(...Object.values(a.infoBySubgrupo)) : 0;
      const maxLab  = Object.values(a.labBySubgrupo).length  ? Math.max(...Object.values(a.labBySubgrupo))  : 0;
      totalH         += (a.counts.teoria + a.counts.ps + maxInfo + maxLab) * 2;
      totalParciales += a.counts.parcial;
    });
    const groupLabel = g.grupo === 'unico' ? 'Grupo &Uacute;nico' : 'Grupo ' + g.grupo;
    const aula = g.aula ? ' &nbsp;&middot;&nbsp; ' + formatAula(g.aula) : '';

    // Contar errores fichas para el badge de cabecera (excluye overrides manuales por grupo)
    const overrideSet = DB._overrideSet || new Set();
    let fichasErrCount = 0;
    asigs.forEach(a => {
      const f = a.fichas;
      if (!f) return;
      if (overrideSet.has(a.codigo + '::' + gKey)) return;  // override manual de este grupo
      const teorReal = a.counts.teoria * 2;
      const maxInfo = Object.values(a.infoBySubgrupo).length ? Math.max(...Object.values(a.infoBySubgrupo)) : 0;
      const maxLab  = Object.values(a.labBySubgrupo).length  ? Math.max(...Object.values(a.labBySubgrupo))  : 0;
      const presReal = (a.counts.teoria + a.counts.ps + maxInfo + maxLab) * 2;
      const presEsp  = f.af1 + f.af2 + f.af4;
      const infoE = Object.entries(a.infoBySubgrupo);
      const labE  = Object.entries(a.labBySubgrupo);
      const teorOk  = (teorReal === f.af1);
      const infoOk  = infoE.length === 0 ? f.af4 === 0 : infoE.every(([,n]) => n*2 === f.af4);
      const labOk   = labE.length  === 0 ? f.af2 === 0 : labE.every(([,n]) => n*2 === f.af2);
      const totOk   = presReal === presEsp;
      if (!teorOk || !infoOk || !labOk || !totOk) fichasErrCount++;
    });
    const fichasErrBadge = fichasErrCount > 0
      ? `<span style="background:#dc2626;color:#fff;font-size:.72rem;font-weight:700;padding:2px 8px;border-radius:10px;margin-left:10px">&#9888; ${fichasErrCount} asig. no cumplen ficha</span>`
      : `<span style="background:#16a34a;color:#fff;font-size:.72rem;font-weight:700;padding:2px 8px;border-radius:10px;margin-left:10px">&#10003; Todas cumplen ficha</span>`;

    sectionsHtml += `
      <div class="group-stats-section">
        <div class="group-stats-header">
          <span class="group-stats-title">${groupLabel}${aula}${fichasErrBadge}</span>
          <span class="group-stats-summary">
            ${weeks.length} semanas &nbsp;&middot;&nbsp;
            ${asigs.length} asignaturas &nbsp;&middot;&nbsp;
            ${totalH}h lectivas &nbsp;&middot;&nbsp;
            ${totalParciales} ex&aacute;menes parciales
          </span>
        </div>
        ${buildActTable(asigs, gKey)}
      </div>`;
  });

  document.getElementById('subjectsTable').innerHTML =
    sectionsHtml || '<div style="padding:20px;color:var(--text-light)">Sin datos para este cuatrimestre.</div>';

  renderEvolucionSection();
}

// ─── NAVIGATION ───
function onFilterChange() {
  currentCurso = document.getElementById('cursoSelect').value;
  currentCuat = document.getElementById('cuatSelect').value;
  currentGroup = document.getElementById('grupoSelect').value;
  currentWeekIdx = 0;
  updateGrupoOptions();
  updateHeaderSubtitle();
  populateAsignaturaSelect();
  updateAulaDatalist();
  render();
}

function updateAulaDatalist() {
  const dl = document.getElementById('fAulaList');
  if (!dl) return;
  const aulas = AULAS_POR_CURSO[String(currentCurso)] || [];
  dl.innerHTML = aulas.map(a => `<option value="${a}">`).join('');
}
function updateGrupoOptions() {
  const sel = document.getElementById('grupoSelect');
  const key = currentCurso + '_' + currentCuat + '_grupo_';
  // Find available groups for this curso+cuat
  const available = Object.keys(DB.grupos).filter(k => k.startsWith(key)).map(k => k.replace(key, ''));
  sel.innerHTML = available.map(g => {
    const label = g === 'unico' ? 'Grupo Unico' : 'Grupo ' + g;
    return '<option value="' + g + '">' + label + '</option>';
  }).join('');
  if (!available.includes(currentGroup)) {
    currentGroup = available[0] || '1';
  }
  sel.value = currentGroup;
}
function formatAula(aula) { return aula ? aula.replace('#', '') : ''; }
function updateHeaderSubtitle() {
  const ordinals = {'1':'1er','2':'2o','3':'3er','4':'4o'};
  const g = getGrupo();
  const aula = g ? ' · Aula: ' + formatAula(g.aula) : '';
  document.getElementById('headerSubtitle').textContent = ordinals[currentCurso] + ' Curso · DEGREE_ACRONYM_PLACEHOLDER · INSTITUTION_ACRONYM_PLACEHOLDER' + aula;
}
function goWeek(i) { currentWeekIdx = i; render(); }
function prevWeek() { if (currentWeekIdx > 0) { currentWeekIdx--; render(); } }
function nextWeek() { if (currentWeekIdx < getWeeks().length-1) { currentWeekIdx++; render(); } }
function setView(v, btn) {
  currentView = v;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  document.getElementById('view-semana').style.display = v==='semana'?'':'none';
  document.getElementById('view-stats').style.display = v==='stats'?'':'none';
  document.getElementById('view-parciales').style.display = v==='parciales'?'':'none';
  document.getElementById('view-finales').style.display = v==='finales'?'':'none';
  document.getElementById('view-festivos').style.display = v==='festivos'?'':'none';
  if (v==='festivos') { loadFestivos(); return; }
  if (v==='finales')  { loadFinales();  return; }
  render();
}
function showStats() { setView('stats', null); }

// ─── MODAL ───
function closeModal() { document.getElementById('modalOverlay').classList.remove('open'); editCtx = null; }
function toggleNoLectivo() {
  const no = document.getElementById('fNoLectivo').checked;
  ['fAsignatura','fAula','fSubgrupo','fObs'].forEach(id => document.getElementById(id).disabled = no);
}
function onAsignaturaSelect() {}

function openEdit(claseId) {
  const week = getCurrentWeek();
  const cls = week.clases.find(c => c.id === claseId);
  if (!cls) return;
  editCtx = { mode: 'edit', claseId, semana_id: week.semana_id };
  document.getElementById('modalTitle').textContent = 'Editar Clase';
  document.getElementById('modalSubtitle').textContent = week.descripcion + ' · ' + cls.dia + ' · ' + cls.franja_label;
  document.getElementById('addFields').style.display = 'none';
  document.getElementById('btnDelete').style.display = 'inline-flex';
  document.getElementById('fAsignatura').value = cls.asignatura_id || '';
  document.getElementById('fAula').value = cls.aula || '';
  document.getElementById('fSubgrupo').value = cls.subgrupo || '';
  document.getElementById('fObs').value = cls.observacion || '';
  document.getElementById('fNoLectivo').checked = !!cls.es_no_lectivo;
  toggleNoLectivo();
  document.getElementById('modalOverlay').classList.add('open');
}

function openAdd(semanaId, dia, franjaId, isDesdoble=false) {
  editCtx = { mode: 'add', semana_id: semanaId, dia, franja_id: franjaId, force_insert: isDesdoble };
  const week = getCurrentWeek();
  const franja = DB.franjas.find(f => f.id === franjaId);
  document.getElementById('modalTitle').textContent = isDesdoble ? '&#9851; Añadir Desdoble' : 'Nueva Clase';
  document.getElementById('modalSubtitle').textContent = week.descripcion + ' · ' + dia + ' · ' + (franja ? franja.label : '') + (isDesdoble ? ' · (segunda asignatura en paralelo)' : '');
  document.getElementById('addFields').style.display = 'block';
  document.getElementById('btnDelete').style.display = 'none';
  document.getElementById('fAsignatura').value = '';
  document.getElementById('fAula').value = '';
  document.getElementById('fSubgrupo').value = '';
  document.getElementById('fObs').value = '';
  document.getElementById('fNoLectivo').checked = false;
  document.getElementById('fDia').value = dia;
  if (franja) document.getElementById('fHora').value = franjaId;
  toggleNoLectivo();
  document.getElementById('modalOverlay').classList.add('open');
}

function openAddModal() {
  const week = getCurrentWeek();
  if (!week) return;
  openAdd(week.semana_id, 'LUNES', DB.franjas[0].id);
}

async function saveSlot() {
  if (!editCtx) return;
  const noLec = document.getElementById('fNoLectivo').checked;
  const asigSel = document.getElementById('fAsignatura');
  const asigId = asigSel.value ? parseInt(asigSel.value) : null;
  const asig = asigId ? DB.asignaturas.find(a => a.id === asigId) : null;

  const payload = {
    aula: document.getElementById('fAula').value.trim(),
    subgrupo: document.getElementById('fSubgrupo').value.trim(),
    observacion: document.getElementById('fObs').value.trim(),
    es_no_lectivo: noLec,
    asig_codigo: asig ? asig.codigo : '',
    asig_nombre: asig ? asig.nombre : '',
    contenido: noLec ? 'NO LECTIVO' : (asig ? '['+asig.codigo+'] '+asig.nombre : '')
  };

  if (editCtx.mode === 'edit') {
    payload.id = editCtx.claseId;
    payload.asignatura_id = asigId;
    await api('/api/clase/update', payload);
  } else {
    payload.semana_id = editCtx.semana_id;
    payload.dia = document.getElementById('fDia').value;
    payload.franja_id = parseInt(document.getElementById('fHora').value);
    payload.scope = document.getElementById('fScope').value;
    payload.force_insert = editCtx.force_insert || false;
    await api('/api/clase/create', payload);
  }

  closeModal();
  await loadData();
  showToast('Guardado en base de datos');
}

async function deleteSlot() {
  if (!editCtx || editCtx.mode !== 'edit') return;
  await api('/api/clase/delete', { id: editCtx.claseId });
  closeModal();
  await loadData();
  showToast('Eliminado de base de datos');
}

function getPrintInfo() {
  const g = getGrupo();
  const ordinals = {'1':'1er','2':'2o','3':'3er','4':'4o'};
  const grupoLabel = currentGroup === 'unico' ? 'Grupo Unico' : 'Grupo ' + currentGroup;
  const cuatLabel = currentCuat === '1C' ? '1er Cuatrimestre' : '2o Cuatrimestre';
  const aulaLabel = g && g.aula ? ' — ' + formatAula(g.aula) : '';
  return ordinals[currentCurso] + ' Curso DEGREE_ACRONYM_PLACEHOLDER · ' + cuatLabel + ' · ' + grupoLabel + aulaLabel;
}

// ─── PDF GENERATION (html2canvas + jsPDF, sin diálogo de impresora) ───

// Carga el logo UPCT como data-URL (resultado cacheado)
let _logoDataUrl = null;
async function _loadLogo() {
  if (_logoDataUrl !== null) return _logoDataUrl;
  try {
    const resp = await fetch('/api/logo');
    if (!resp.ok) { _logoDataUrl = ''; return ''; }
    const blob = await resp.blob();
    _logoDataUrl = await new Promise(resolve => {
      const fr = new FileReader();
      fr.onload = () => resolve(fr.result);
      fr.readAsDataURL(blob);
    });
  } catch(e) { _logoDataUrl = ''; }
  return _logoDataUrl;
}

let _pdfLibsPromise = null;
function loadPdfLibs() {
  if (_pdfLibsPromise) return _pdfLibsPromise;
  _pdfLibsPromise = new Promise((resolve, reject) => {
    function loadScript(src) {
      return new Promise((res, rej) => {
        const s = document.createElement('script');
        s.src = src; s.onload = res; s.onerror = rej;
        document.head.appendChild(s);
      });
    }
    loadScript('https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js')
      .then(() => loadScript('https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js'))
      .then(resolve).catch(reject);
  });
  return _pdfLibsPromise;
}

function setPdfProgress(pct, msg) {
  document.getElementById('pdfProgressFill').style.width = pct + '%';
  document.getElementById('pdfProgressMsg').textContent = msg;
}

function showPdfOverlay() { document.getElementById('pdfOverlay').style.display = 'flex'; }
function hidePdfOverlay() { document.getElementById('pdfOverlay').style.display = 'none'; }

// Captura un elemento DOM como imagen y la añade al PDF jsPDF.
// Si la imagen es más alta que la página, la escala para que quepa.
async function captureAndAddPage(pdf, element, isFirstPage) {
  const canvas = await html2canvas(element, {
    scale: 2, useCORS: true, backgroundColor: '#ffffff',
    logging: false, allowTaint: false
  });
  if (!isFirstPage) pdf.addPage('a4', 'l');
  const pw = pdf.internal.pageSize.getWidth();
  const ph = pdf.internal.pageSize.getHeight();
  const ratio = canvas.width / canvas.height;
  let iw = pw, ih = pw / ratio;
  if (ih > ph) { ih = ph; iw = ph * ratio; }
  const ox = (pw - iw) / 2, oy = (ph - ih) / 2;
  pdf.addImage(canvas.toDataURL('image/jpeg', 0.92), 'JPEG', ox, oy, iw, ih);
}

// Construye un contenedor off-screen con el CSS del documento para capturar semanas
function makeCaptureContainer() {
  const cap = document.createElement('div');
  cap.style.cssText = 'position:fixed;left:-9999px;top:0;width:1280px;background:#fff;padding:16px;box-sizing:border-box;z-index:-9999;font-family:"Segoe UI",Arial,sans-serif';
  // Copiar variables CSS del root
  const rootStyle = getComputedStyle(document.documentElement);
  const vars = ['--primary','--success','--warning','--border','--card','--hover','--text','--text-light'];
  vars.forEach(v => cap.style.setProperty(v, rootStyle.getPropertyValue(v)));
  document.body.appendChild(cap);
  return cap;
}

async function exportarExcel() {
  const btn = document.getElementById('btnExportExcel');
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '&#9203; Generando Excel…';
  try {
    const resp = await fetch('/api/exportar_excel');
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({error: 'Error desconocido'}));
      alert('Error al exportar: ' + (err.error || resp.statusText));
      return;
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const cd = resp.headers.get('Content-Disposition') || '';
    const match = cd.match(/filename="([^"]+)"/);
    a.download = match ? match[1] : `Horarios_${EXPORT_PREFIX}.zip`;
    a.href = url;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch(e) {
    alert('Error al exportar: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

async function exportPDF() {
  const week = getCurrentWeek();
  if (!week) return;
  showPdfOverlay();
  setPdfProgress(10, 'Cargando librerías PDF…');
  try {
    const [, logo] = await Promise.all([loadPdfLibs(), _loadLogo()]);
    setPdfProgress(40, 'Capturando horario…');
    const { jsPDF } = window.jspdf;
    const pdf = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' });
    const PW = pdf.internal.pageSize.getWidth();
    // Logo UPCT en cabecera derecha
    if (logo) {
      const lh = 11, lw = lh * (1528.08/181.707);
      pdf.addImage(logo, 'PNG', PW - 8 - lw, 1.5, lw, lh);
    }
    // Cabecera de texto
    const info = getPrintInfo();
    pdf.setFontSize(9); pdf.setTextColor(90, 106, 122);
    pdf.text('Horarios DEGREE_ACRONYM_PLACEHOLDER — Curso CURSO_LABEL_PLACEHOLDER — ' + info, 8, 7);
    pdf.setFontSize(11); pdf.setTextColor(26, 58, 107);
    pdf.text(week.descripcion, 8, 13);
    // Captura la tabla
    const cap = makeCaptureContainer();
    cap.innerHTML = buildWeekTableHTML(week, false);
    await new Promise(r => setTimeout(r, 80));
    const canvas = await html2canvas(cap, {
      scale: 2, useCORS: true, backgroundColor: '#ffffff', logging: false
    });
    document.body.removeChild(cap);
    const pw = pdf.internal.pageSize.getWidth() - 16;
    const ratio = canvas.width / canvas.height;
    let iw = pw, ih = pw / ratio;
    const maxH = pdf.internal.pageSize.getHeight() - 20;
    if (ih > maxH) { ih = maxH; iw = maxH * ratio; }
    pdf.addImage(canvas.toDataURL('image/jpeg', 0.93), 'JPEG', 8, 16, iw, ih);
    setPdfProgress(90, 'Guardando archivo…');
    const fname = `horario_${currentCurso}curso_${currentCuat}_grupo${currentGroup}_sem${currentWeekIdx+1}.pdf`;
    pdf.save(fname);
    setPdfProgress(100, '¡Listo!');
    setTimeout(hidePdfOverlay, 600);
  } catch(e) {
    hidePdfOverlay();
    console.error(e);
    alert('Error al generar PDF: ' + e.message + '\n\nComprueba la conexión a internet (necesaria la primera vez).');
  }
}

async function exportAllPDF() {
  const weeks = getWeeks();
  if (!weeks.length) return;
  showPdfOverlay();
  setPdfProgress(5, 'Cargando librerías PDF…');
  try {
    const [, logo] = await Promise.all([loadPdfLibs(), _loadLogo()]);
    const { jsPDF } = window.jspdf;
    const pdf = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' });
    const PW = pdf.internal.pageSize.getWidth();
    const info = getPrintInfo();
    const cap = makeCaptureContainer();
    for (let i = 0; i < weeks.length; i++) {
      const w = weeks[i];
      const pct = Math.round(10 + (i / weeks.length) * 82);
      setPdfProgress(pct, `Semana ${i+1} de ${weeks.length}: ${w.descripcion}`);
      // Cabecera
      if (i > 0) pdf.addPage('a4', 'l');
      // Logo UPCT en cabecera derecha
      if (logo) {
        const lh = 11, lw = lh * (1528.08/181.707);
        pdf.addImage(logo, 'PNG', PW - 8 - lw, 1.5, lw, lh);
      }
      pdf.setFontSize(8); pdf.setTextColor(90, 106, 122);
      pdf.text('Horarios DEGREE_ACRONYM_PLACEHOLDER — Curso CURSO_LABEL_PLACEHOLDER — ' + info, 8, 6);
      pdf.setFontSize(10); pdf.setTextColor(26, 58, 107);
      pdf.text(w.descripcion, 8, 12);
      // Tabla
      cap.innerHTML = buildWeekTableHTML(w, false);
      await new Promise(r => setTimeout(r, 60));
      const canvas = await html2canvas(cap, {
        scale: 1.8, useCORS: true, backgroundColor: '#ffffff', logging: false
      });
      const pw = pdf.internal.pageSize.getWidth() - 16;
      const ratio = canvas.width / canvas.height;
      let iw = pw, ih = pw / ratio;
      const maxH = pdf.internal.pageSize.getHeight() - 18;
      if (ih > maxH) { ih = maxH; iw = maxH * ratio; }
      pdf.addImage(canvas.toDataURL('image/jpeg', 0.90), 'JPEG', 8, 14, iw, ih);
    }
    document.body.removeChild(cap);
    setPdfProgress(97, 'Guardando archivo…');
    const fname = `horarios_EXPORT_PREFIX_PLACEHOLDER_${currentCurso}curso_${currentCuat}_grupo${currentGroup}_todas.pdf`;
    pdf.save(fname);
    setPdfProgress(100, '¡Listo!');
    setTimeout(hidePdfOverlay, 700);
  } catch(e) {
    hidePdfOverlay();
    console.error(e);
    alert('Error al generar PDF: ' + e.message + '\n\nComprueba la conexión a internet (necesaria la primera vez).');
  }
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 2500);
}

// ─── FESTIVOS CALENDAR ───
let FESTIVOS_MAP = {};   // fecha -> {tipo, descripcion}
let CAL_SEMANA_MAP = {}; // fecha -> {cuatrimestre, numero, dia}  (built from DB.grupos)

/* Devuelve la fecha local como YYYY-MM-DD (evita desfase UTC de toISOString) */
function isoLocal(d) {
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, '0');
  const da = String(d.getDate()).padStart(2, '0');
  return `${y}-${mo}-${da}`;
}

function buildSemanaDateMap() {
  /* Construye CAL_SEMANA_MAP a partir de las semanas de DB */
  CAL_SEMANA_MAP = {};
  if (!DB) return;
  const MESES = {
    'ENERO':1,'FEBRERO':2,'MARZO':3,'ABRIL':4,'MAYO':5,'JUNIO':6,
    'JULIO':7,'AGOSTO':8,'SEPTIEMBRE':9,'OCTUBRE':10,'NOVIEMBRE':11,'DICIEMBRE':12
  };
  const DIAS = ['LUNES','MARTES','MIÉRCOLES','JUEVES','VIERNES'];
  const [yStart, yEnd] = (CURSO_STR || '2026-2027').split('-').map(Number);
  const seen = new Set();
  for (const gkey of Object.keys(DB.grupos)) {
    const g = DB.grupos[gkey];
    for (const sem of g.semanas) {
      const key = g.cuatrimestre + '|' + sem.numero;
      if (seen.has(key)) continue;
      seen.add(key);
      const m = sem.descripcion.match(/(\d+)\s+([A-ZÁÉÍÓÚÑ]+)\s+A\s+(\d+)\s+([A-ZÁÉÍÓÚÑ]+)/i);
      if (!m) continue;
      const startDay = parseInt(m[1]);
      const startMonthStr = m[2].toUpperCase();
      const startMonth = MESES[startMonthStr];
      if (!startMonth) continue;
      const year = (startMonth < 7) ? yEnd : yStart;
      const startDate = new Date(year, startMonth - 1, startDay);
      for (let i = 0; i < 5; i++) {
        const d = new Date(startDate);
        d.setDate(startDate.getDate() + i);
        const iso = isoLocal(d);   // ← fecha local, sin desfase UTC
        if (!CAL_SEMANA_MAP[iso]) {
          CAL_SEMANA_MAP[iso] = { cuatrimestre: g.cuatrimestre, numero: sem.numero, dia: DIAS[i] };
        }
      }
    }
  }
}

async function loadFestivos() {
  const btn = document.querySelector('#view-festivos .btn-outline');
  if (btn) { btn.disabled = true; btn.textContent = '⟳ Cargando…'; }
  try {
    const rows = await api('/api/festivos');
    FESTIVOS_MAP = {};
    for (const r of rows) FESTIVOS_MAP[r.fecha] = { tipo: r.tipo, descripcion: r.descripcion };
    buildSemanaDateMap();
    renderCalendar();
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '&#8635; Actualizar'; }
  }
}

function renderCalendar() {
  const grid = document.getElementById('calendarGrid');
  if (!grid) return;

  /* Determinar el rango del curso */
  const [yStart, yEnd] = (CURSO_STR || '2026-2027').split('-').map(Number);
  /* Meses del calendario académico: Sep año_start … Jun año_end */
  const months = [];
  for (let m = 8; m <= 11; m++) months.push([yStart, m]);   // Sep-Dic
  for (let m = 0; m <= 5;  m++) months.push([yEnd,   m]);   // Ene-Jun

  const MONTH_NAMES = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                       'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
  const DAY_ABBR = ['Lu','Ma','Mi','Ju','Vi','Sá','Do'];

  let html = '';
  for (const [year, monthIdx] of months) {
    const firstDay = new Date(year, monthIdx, 1);
    const daysInMonth = new Date(year, monthIdx + 1, 0).getDate();
    let startWd = firstDay.getDay(); // 0=Dom
    startWd = (startWd === 0) ? 6 : startWd - 1; // 0=Lun

    html += `<div class="cal-month">
      <div class="cal-month-header">${MONTH_NAMES[monthIdx]} ${year}</div>
      <div class="cal-month-body">
        <div class="cal-days-header">
          ${DAY_ABBR.map(d => `<span>${d}</span>`).join('')}
        </div>
        <div class="cal-days-grid">`;

    /* empty cells before 1st */
    for (let i = 0; i < startWd; i++) html += `<div class="cal-day empty"></div>`;

    for (let day = 1; day <= daysInMonth; day++) {
      const d = new Date(year, monthIdx, day);
      const wd = d.getDay(); // 0=Dom,6=Sáb
      const iso = isoLocal(d);   // ← fecha local, sin desfase UTC
      const isWeekend = (wd === 0 || wd === 6);
      const inSemana  = !!CAL_SEMANA_MAP[iso];
      const festivo   = FESTIVOS_MAP[iso];

      let cls = 'cal-day ';
      let tooltip = '';
      let onclick = '';

      if (isWeekend) {
        cls += 'finde';
      } else if (!inSemana) {
        cls += 'fuera';
      } else if (festivo) {
        cls += festivo.tipo;
        tooltip = festivo.descripcion || festivo.tipo;
        onclick = `onclick="openFestivoPopup('${iso}',event)"`;
      } else {
        cls += 'lectivo';
        onclick = `onclick="openFestivoPopup('${iso}',event)"`;
      }

      const dotHtml = festivo ? '<span class="cal-day-dot"></span>' : '';
      html += `<div class="${cls}" title="${tooltip}" ${onclick}>
        <span class="cal-day-num">${day}</span>${dotHtml}
      </div>`;
    }
    html += `</div></div></div>`;
  }
  grid.innerHTML = html;
}

function openFestivoPopup(fecha, evt) {
  closeFestivoPopup();
  const existing = FESTIVOS_MAP[fecha] || {};
  const [y, m, d] = fecha.split('-');
  const label = `${parseInt(d)}/${parseInt(m)}/${y}`;

  const overlay = document.createElement('div');
  overlay.className = 'festivo-popup-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:9998;';
  overlay.onclick = closeFestivoPopup;
  document.body.appendChild(overlay);

  const popup = document.createElement('div');
  popup.id = 'festivoPopup';
  popup.className = 'festivo-popup';
  const isMarcado = !!existing.tipo;
  popup.innerHTML = `
    <h4>&#128197; ${label}</h4>
    <label>Tipo de día</label>
    <select id="fpTipo">
      <option value="no_lectivo" ${existing.tipo==='no_lectivo'?'selected':''}>🟠 No lectivo / Puente</option>
      <option value="festivo" ${existing.tipo==='festivo'?'selected':''}>🔴 Festivo nacional</option>
    </select>
    <label>Descripción (opcional)</label>
    <input type="text" id="fpDesc" value="${existing.descripcion||''}" placeholder="Ej: Día de la Hispanidad">
    <div class="popup-btns">
      ${isMarcado?`<button class="btn btn-danger btn-sm" onclick="saveFestivo('${fecha}','delete')">🗑 Quitar</button>`:''}
      <button class="btn btn-outline btn-sm" onclick="closeFestivoPopup()">Cancelar</button>
      <button class="btn btn-primary btn-sm" onclick="saveFestivo('${fecha}','set')">✔ Guardar</button>
    </div>`;

  /* Position near click */
  const x = Math.min(evt.clientX, window.innerWidth - 360);
  const y2 = Math.min(evt.clientY, window.innerHeight - 280);
  popup.style.left = x + 'px';
  popup.style.top  = y2 + 'px';
  document.body.appendChild(popup);
}

function closeFestivoPopup() {
  document.getElementById('festivoPopup')?.remove();
  document.querySelector('.festivo-popup-overlay')?.remove();
}

async function saveFestivo(fecha, action) {
  const tipo = document.getElementById('fpTipo')?.value || 'no_lectivo';
  const desc = document.getElementById('fpDesc')?.value || '';
  closeFestivoPopup();

  const res = await api('/api/festivos/set', { fecha, tipo, descripcion: desc, action });
  if (res.error) { alert('Error: ' + res.error); return; }

  /* Recargar BD y calendario */
  DB = await api('/api/schedule');
  DB._overrideSet = new Set(DB.fichas_override || []);
  _subjectColorCache = null;
  await loadFestivos();
  showToast(action === 'delete' ? 'Día eliminado del calendario ✔' : 'Día guardado en todos los horarios ✔');
}

// Constantes inyectadas por el servidor desde config.json
const CURSO_STR           = 'CURSO_LABEL_PLACEHOLDER';
const DEGREE_ACRONYM      = 'DEGREE_ACRONYM_PLACEHOLDER';
const INSTITUTION_ACRONYM = 'INSTITUTION_ACRONYM_PLACEHOLDER';
const EXPORT_PREFIX       = 'EXPORT_PREFIX_PLACEHOLDER';
const AULAS_POR_CURSO     = AULAS_POR_CURSO_PLACEHOLDER;

// ─── INIT ───
(async function() {
  await loadData();
  const rows = await api('/api/festivos');
  FESTIVOS_MAP = {};
  for (const r of rows) FESTIVOS_MAP[r.fecha] = { tipo: r.tipo, descripcion: r.descripcion };
  buildSemanaDateMap();
})();
</script>
<footer style="text-align:center;padding:14px 20px;font-size:.72rem;color:var(--text-light);border-top:1px solid var(--border);margin-top:24px;background:var(--card)">
  &copy; <span id="footer-year"></span> Jes&uacute;s Mart&iacute;nez-Frutos &mdash; DEGREE_ACRONYM_PLACEHOLDER &middot; INSTITUTION_ACRONYM_PLACEHOLDER
  <script>document.getElementById('footer-year').textContent = new Date().getFullYear();</script>
</footer>
</body>
</html>'''


# ─── MAIN ───
if __name__ == "__main__":
    init_db_paths()
    ensure_override_table()
    ensure_festivos_table()
    ensure_finales_table()
    ensure_finales_checklist_table()
    ensure_destacadas_table()

    title = f"GESTOR DE HORARIOS {DEGREE_ACRONYM} — {INSTITUTION_ACRONYM}"
    print(f"\n  ╔══════════════════════════════════════════════╗")
    print(f"  ║   {title:<44s}║")
    print(f"  ║   Base de datos: {DB_PATH:<28s}║")
    print(f"  ║   Servidor: http://localhost:{PORT:<17d}║")
    print(f"  ╚══════════════════════════════════════════════╝\n")

    try:
        webbrowser.open(f"http://localhost:{PORT}")
    except:
        pass

    server = http.server.HTTPServer(("0.0.0.0", PORT), HorarioHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Servidor detenido.")
        server.server_close()
