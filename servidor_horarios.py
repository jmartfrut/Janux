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
from urllib.parse import urlparse, parse_qs

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Versión del servidor — incrementar en cada release que cambie esquema o API.
# Formato: MAJOR.MINOR.PATCH
#   MAJOR → cambios de arquitectura o rotura de compatibilidad
#   MINOR → funcionalidades nuevas (vistas, endpoints, herramientas)
#   PATCH → correcciones y mejoras menores
APP_VERSION = "1.34.0"

# ─── CONFIGURACIÓN ───────────────────────────────────────────────────────────
# Carga config.json si existe; si no, usa valores por defecto (compatibilidad)
# CONFIG_PATH_OVERRIDE permite apuntar a la carpeta de un grado concreto:
#   CONFIG_PATH_OVERRIDE="horarios/GIDI" python3 servidor_horarios.py
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
PORT       = int(os.environ.get("PORT") or _cfg("server", "port", default=8080))
DB_NAME    = _cfg("server", "db_name",      default="horarios.db")

# Resolución de la ruta a la BD (por orden de prioridad):
#   1. DB_PATH          — variable Docker-friendly (ej: /app/data/horarios.db)
#   2. DB_PATH_OVERRIDE — compatibilidad con instalaciones anteriores (Dropbox, red)
#   3. Directorio del script — comportamiento por defecto (instalación local macOS)
DB_PATH    = (os.environ.get("DB_PATH")
              or os.environ.get("DB_PATH_OVERRIDE")
              or os.path.join(SCRIPT_DIR, DB_NAME))
CURSO_LABEL = os.environ.get("CURSO_LABEL") or _cfg("server", "curso_label", default="2026-2027")

# Ruta original de la BD cuando se trabaja con copia temporal (Windows).
# Si está definida, el manejador Win32 copia DB_PATH → DB_BACKUP_TARGET al cerrar.
DB_BACKUP_TARGET = os.environ.get("DB_BACKUP_TARGET", "")

# Branding (colores CSS)
COLOR_PRIMARY       = _cfg("branding", "primary",       default="#1a3a6b")
COLOR_PRIMARY_LIGHT = _cfg("branding", "primary_light", default="#2855a0")
COLOR_ACCENT        = _cfg("branding", "accent",        default="#e8a020")
COLOR_BG            = _cfg("branding", "bg",            default="#f0f4f8")

# UI
DESTACADAS_BADGE = _cfg("ui", "destacadas_badge", default=f"DTIE {DEGREE_ACRONYM}")
EXPORT_PREFIX    = _cfg("ui", "export_prefix",    default=DEGREE_ACRONYM)

# Aulas por curso (para datalist en fAula — se inyectan como JSON)
# Formato: {"1": ["PS5","PS6"], "2": ["PS7"], ...}
AULAS_POR_CURSO = _cfg("degree_structure", "aulas_por_curso", default={})

# Aulario por curso (para el desplegable de cursos — se inyectan como JSON)
# Formato: {"1": "PS2", "2": "PS3", ...}
AULARIO_POR_CURSO = _cfg("degree_structure", "aulario_por_curso", default={})

# Generar las <option> del select de curso dinámicamente
_num_cursos  = _cfg("degree_structure", "num_cursos", default=4)
_ordinals_es = {1:'1er', 2:'2o', 3:'3er', 4:'4o'}
def _curso_label(i):
    ord_str = _ordinals_es.get(i, f'{i}o')
    aulario = AULARIO_POR_CURSO.get(str(i), '')
    label   = f'{ord_str} Curso'
    if aulario:
        label += f' ({aulario})'
    return f'      <option value="{i}">{label}</option>'
CURSO_OPTIONS = '\n'.join(_curso_label(i) for i in range(1, _num_cursos + 1))

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

# Mapeo personalizado tipo → AF para tipos editables (config.json: "tipo_to_af")
TIPO_TO_AF = _cfg("tipo_to_af", default={})

# Tipos de clase predefinidos — se leen de tipos_actividad.json (fuente única compartida
# con nuevo_grado.py). Si el fichero no existe, se usa la lista vacía como fallback seguro.
_tipos_path = os.path.join(SCRIPT_DIR, "config", "tipos_actividad.json")
if os.path.exists(_tipos_path):
    with open(_tipos_path, encoding="utf-8") as _tf:
        TIPOS_ACTIVIDAD = json.load(_tf)
else:
    TIPOS_ACTIVIDAD = []
    print(f"AVISO: No se encuentra {_tipos_path} — el desplegable de tipos de actividad estará vacío.")

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

def ensure_tipo_column_clases():
    """Añade la columna `tipo` a la tabla `clases` si no existe y migra datos existentes.

    Reglas de migración:
      aula = 'LAB'              → tipo = 'LAB', aula = ''
      aula = 'INFO' / 'INFO*'   → tipo = 'INF', aula = ''
      aula = 'Aula: X'          → tipo = 'AD',  aula = X  (extrae nombre de aula)
      cualquier otra aula       → tipo = '',    aula = aula  (sin cambio)
    """
    conn = get_db()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(clases)").fetchall()}
    if "tipo" not in cols:
        conn.execute("ALTER TABLE clases ADD COLUMN tipo TEXT DEFAULT ''")
        # Migrar datos existentes basándonos en el valor actual del campo aula
        rows = conn.execute("SELECT id, aula FROM clases WHERE aula IS NOT NULL AND aula != ''").fetchall()
        for r in rows:
            aula_val = (r["aula"] or "").strip()
            aula_upper = aula_val.upper()
            if aula_val == "LAB":
                conn.execute("UPDATE clases SET tipo='LAB', aula='' WHERE id=?", (r["id"],))
            elif aula_upper == "INFO" or aula_upper.startswith("INFO"):
                conn.execute("UPDATE clases SET tipo='INF', aula='' WHERE id=?", (r["id"],))
            elif aula_upper.startswith("AULA:"):
                room = aula_val[5:].strip()
                conn.execute("UPDATE clases SET tipo='AD', aula=? WHERE id=?", (room, r["id"]))
        conn.commit()
        print("  ✅ Columna 'tipo' añadida a tabla clases y datos migrados.")
    conn.close()


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
    fichas_cols = {r["name"] for r in conn.execute("PRAGMA table_info(fichas)").fetchall()}
    _cuat_col = "f.cuatrimestre" if "cuatrimestre" in fichas_cols else "NULL as cuatrimestre"
    fichas_rows = conn.execute(f"""
        SELECT a.codigo, f.creditos, f.af1, f.af2, f.af3, f.af4, f.af5, f.af6,
               {_cuat_col}
        FROM fichas f
        JOIN asignaturas a ON a.id = f.asignatura_id
    """).fetchall()
    fichas_by_codigo = {
        r["codigo"]: {
            "creditos": r["creditos"],
            "af1": r["af1"], "af2": r["af2"], "af3": r["af3"],
            "af4": r["af4"], "af5": r["af5"], "af6": r["af6"],
            "cuatrimestre": r["cuatrimestre"],
        }
        for r in fichas_rows
    }

    # Overrides manuales de fichas (clave compuesta "codigo::grupo_key" desde sesión 6)
    override_rows = conn.execute("SELECT codigo, grupo_key FROM fichas_override").fetchall() \
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='fichas_override'").fetchone() \
        else []
    fichas_override = [f'{r["codigo"]}::{r["grupo_key"]}' for r in override_rows]

    # Asignaturas destacadas — dict {key: modo} donde modo=1 (color+badge) o modo=2 (solo badge)
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='asignaturas_destacadas'").fetchone():
        # Compatibilidad: si la columna modo aún no existe (BD pre-v11), tratar todo como modo=1
        dest_cols = {r[1] for r in conn.execute("PRAGMA table_info(asignaturas_destacadas)").fetchall()}
        if "modo" in dest_cols:
            destacadas_rows = conn.execute(
                "SELECT codigo, grupo_num, act_type, subgrupo, modo FROM asignaturas_destacadas"
            ).fetchall()
            destacadas = {
                f'{r["codigo"]}::{r["grupo_num"]}::{r["act_type"]}::{r["subgrupo"]}': (r["modo"] or 1)
                for r in destacadas_rows
            }
        else:
            destacadas_rows = conn.execute(
                "SELECT codigo, grupo_num, act_type, subgrupo FROM asignaturas_destacadas"
            ).fetchall()
            destacadas = {
                f'{r["codigo"]}::{r["grupo_num"]}::{r["act_type"]}::{r["subgrupo"]}': 1
                for r in destacadas_rows
            }
    else:
        destacadas = {}

    # ── BULK LOAD: semanas y clases en 2 queries en lugar de N+1 ─────────────
    # Antes: 1 query por grupo (semanas) + 1 query por semana (clases) = O(grupos×semanas)
    # Ahora: 2 queries que cubren todos los grupos y semanas de una vez
    all_semanas = conn.execute(
        "SELECT id, grupo_id, numero, descripcion FROM semanas ORDER BY grupo_id, numero"
    ).fetchall()
    semanas_by_grupo = {}
    for s in all_semanas:
        semanas_by_grupo.setdefault(s["grupo_id"], []).append(s)

    all_clases = conn.execute("""
        SELECT c.id, c.semana_id, c.dia, c.franja_id, c.asignatura_id,
               c.aula, c.tipo, c.subgrupo, c.observacion,
               c.es_no_lectivo, c.contenido, c.af_cat, c.conjunto_id,
               f.label AS franja_label, f.orden AS franja_orden,
               a.codigo AS asig_codigo, a.nombre AS asig_nombre
        FROM clases c
        JOIN franjas f ON c.franja_id = f.id
        LEFT JOIN asignaturas a ON c.asignatura_id = a.id
        ORDER BY c.semana_id, f.orden
    """).fetchall()
    clases_by_semana = {}
    for c in all_clases:
        clases_by_semana.setdefault(c["semana_id"], []).append(dict(c))

    result = {
        "franjas": [dict(f) for f in franjas],
        "asignaturas": [dict(a) for a in asignaturas],
        "grupos": {},
        "fichas": fichas_by_codigo,          # keyed by asignatura.codigo
        "fichas_override": fichas_override,  # lista de codigos con override manual
        "destacadas": destacadas,            # lista de "codigo::grupo_num" destacadas
        "config": CFG,                       # config.json completo del grado
    }

    for g in grupos:
        semanas = semanas_by_grupo.get(g["id"], [])
        weeks = []
        for s in semanas:
            weeks.append({
                "semana_id": s["id"],
                "numero": s["numero"],
                "descripcion": s["descripcion"],
                "clases": clases_by_semana.get(s["id"], [])
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
    """Update an existing class.
    Si se pasa 'conjunto_id' en data, se asigna ese valor a la clase ('' → NULL).
    Tras guardar, propaga los campos de contenido a todas las clases vinculadas
    (mismo conjunto_id), pero NO modifica su posición (dia/franja/semana).
    """
    conn = get_db()
    clase_id = data.get("id")
    if not clase_id:
        conn.close()
        return {"error": "ID de clase requerido"}

    asignatura_id = resolve_asignatura(conn, data)
    af_cat = data.get("af_cat") or None

    # Campos de contenido que siempre se actualizan
    content_vals = (
        asignatura_id,
        data.get("aula", ""),
        data.get("tipo", ""),
        data.get("subgrupo", ""),
        data.get("observacion", ""),
        1 if data.get("es_no_lectivo") else 0,
        data.get("contenido", ""),
        af_cat,
    )

    tipo_val = data.get("tipo", "")

    # conjunto_id: solo se modifica si viene explícitamente en el payload
    # y la clase es de tipo EXP o EXF — nunca en otros tipos de actividad.
    if "conjunto_id" in data:
        raw_cid = data["conjunto_id"] or None   # '' o None → NULL
        conjunto_id_val = raw_cid if tipo_val in ("EXP", "EXF") else None
        conn.execute("""
            UPDATE clases SET asignatura_id=?, aula=?, tipo=?, subgrupo=?, observacion=?,
                   es_no_lectivo=?, contenido=?, af_cat=?, conjunto_id=?
            WHERE id=?
        """, content_vals + (conjunto_id_val, clase_id))
    else:
        conn.execute("""
            UPDATE clases SET asignatura_id=?, aula=?, tipo=?, subgrupo=?, observacion=?,
                   es_no_lectivo=?, contenido=?, af_cat=?
            WHERE id=?
        """, content_vals + (clase_id,))

    # Propagar a clases vinculadas (mismo conjunto_id, distinta clase).
    # Solo tiene sentido en EXP/EXF; si el tipo cambió a otro, limpiar vínculo.
    row = conn.execute("SELECT conjunto_id, tipo FROM clases WHERE id=?", (clase_id,)).fetchone()
    linked_updated = 0
    if row and row["conjunto_id"] and row["tipo"] in ("EXP", "EXF"):
        linked = conn.execute(
            "SELECT id FROM clases WHERE conjunto_id=? AND id!=? AND tipo IN ('EXP','EXF')",
            (row["conjunto_id"], clase_id)
        ).fetchall()
        for lc in linked:
            conn.execute("""
                UPDATE clases SET asignatura_id=?, aula=?, tipo=?, subgrupo=?, observacion=?,
                       es_no_lectivo=?, contenido=?, af_cat=?
                WHERE id=?
            """, content_vals + (lc["id"],))
            linked_updated += 1

    conn.commit()
    conn.close()
    return {"ok": True, "id": clase_id, "linked_updated": linked_updated}


def api_create_clase(data):
    """Create a new class entry"""
    conn = get_db()
    asignatura_id = resolve_asignatura(conn, data)

    scope = data.get("scope", "single")
    semana_id = data.get("semana_id")
    dia = data.get("dia")
    franja_id = data.get("franja_id")

    # El sábado es un día especial: solo se permiten actividades de tipo EXP.
    if dia == 'SÁBADO' and data.get("tipo", "") != 'EXP':
        conn.close()
        return {"error": "El sábado solo admite actividades de tipo EXP (examen parcial)."}

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
    tipo_val = data.get("tipo", "")
    # conjunto_id solo se persiste en actividades de tipo EXP o EXF
    conjunto_id = (data.get("conjunto_id") or None) if tipo_val in ("EXP", "EXF") else None
    created = []
    for sid in semana_ids:
        existing = None if force_insert else conn.execute(
            "SELECT id FROM clases WHERE semana_id=? AND dia=? AND franja_id=?",
            (sid, dia, franja_id)).fetchone()
        af_cat = data.get("af_cat") or None
        if existing:
            conn.execute("""
                UPDATE clases SET asignatura_id=?, aula=?, tipo=?, subgrupo=?, observacion=?,
                       es_no_lectivo=?, contenido=?, af_cat=?, conjunto_id=? WHERE id=?
            """, (asignatura_id, data.get("aula",""), data.get("tipo",""), data.get("subgrupo",""),
                  data.get("observacion",""), 1 if data.get("es_no_lectivo") else 0,
                  data.get("contenido",""), af_cat, conjunto_id, existing["id"]))
            created.append(existing["id"])
        else:
            conn.execute("""
                INSERT INTO clases (semana_id,dia,franja_id,asignatura_id,aula,tipo,subgrupo,observacion,es_no_lectivo,contenido,af_cat,conjunto_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (sid, dia, franja_id, asignatura_id, data.get("aula",""), data.get("tipo",""),
                  data.get("subgrupo",""), data.get("observacion",""),
                  1 if data.get("es_no_lectivo") else 0, data.get("contenido",""), af_cat, conjunto_id))
            created.append(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    conn.commit()
    conn.close()

    return {"ok": True, "ids": created}


def api_delete_clase(data):
    """Delete a class.
    Si delete_conjunto=True y la clase tiene conjunto_id, elimina también todas
    las clases vinculadas (mismo conjunto_id).
    """
    clase_id = data.get("id")
    if not clase_id:
        return {"error": "ID de clase requerido"}
    conn = get_db()
    deleted = 1
    if data.get("delete_conjunto"):
        row = conn.execute("SELECT conjunto_id FROM clases WHERE id=?", (clase_id,)).fetchone()
        if row and row["conjunto_id"]:
            res = conn.execute(
                "DELETE FROM clases WHERE conjunto_id=?", (row["conjunto_id"],)
            )
            deleted = res.rowcount
            conn.commit()
            conn.close()
            return {"ok": True, "deleted": deleted}
    conn.execute("DELETE FROM clases WHERE id=?", (clase_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": deleted}


def api_clear_group_clases(data):
    """Elimina todas las clases reales (es_no_lectivo=0) de un grupo/cuatrimestre/curso.
    Recibe {grupo_key} — ej. '2_1C_grupo_1'.
    Los días marcados como no-lectivos y los exámenes finales NO se modifican.
    """
    grupo_key = data.get("grupo_key")
    if not grupo_key:
        return {"error": "grupo_key requerido"}
    conn = get_db()
    res = conn.execute("""
        DELETE FROM clases
        WHERE es_no_lectivo = 0
          AND semana_id IN (
              SELECT s.id FROM semanas s
              JOIN grupos g ON s.grupo_id = g.id
              WHERE g.clave = ?
          )
    """, (grupo_key,))
    deleted = res.rowcount
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": deleted, "grupo_key": grupo_key}


def api_unlink_conjunto(data):
    """Elimina el vínculo conjunto_id de una clase.
    Si all=True (defecto), desvincula todas las clases del mismo conjunto.
    Si all=False, solo desvincula la clase indicada por 'id'.
    """
    clase_id = data.get("id")
    if not clase_id:
        return {"error": "ID de clase requerido"}
    conn = get_db()
    row = conn.execute("SELECT conjunto_id FROM clases WHERE id=?", (clase_id,)).fetchone()
    if not row or not row["conjunto_id"]:
        conn.close()
        return {"ok": True, "unlinked": 0}
    cid = row["conjunto_id"]
    if data.get("all", True):
        res = conn.execute("UPDATE clases SET conjunto_id=NULL WHERE conjunto_id=?", (cid,))
        unlinked = res.rowcount
    else:
        conn.execute("UPDATE clases SET conjunto_id=NULL WHERE id=?", (clase_id,))
        unlinked = 1
    conn.commit()
    conn.close()
    return {"ok": True, "unlinked": unlinked}


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


def ensure_af_cat_column():
    """Añade la columna af_cat a la tabla clases si no existe.
    Almacena el destino AF por clase para EXP: 'AF5' | 'AF6' | NULL (→ AF5 por defecto)."""
    conn = get_db()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(clases)").fetchall()}
    if "af_cat" not in cols:
        conn.execute("ALTER TABLE clases ADD COLUMN af_cat TEXT DEFAULT NULL")
        conn.commit()
        print("  ✅ Columna 'af_cat' añadida a tabla clases (NULL = AF5 para EXP).")
    conn.close()


def ensure_af3_fichas_column():
    """Añade la columna af3 a la tabla fichas si no existe (migración de BDs antiguas)."""
    conn = get_db()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(fichas)").fetchall()}
    if "af3" not in cols:
        conn.execute("ALTER TABLE fichas ADD COLUMN af3 INTEGER DEFAULT 0")
        conn.commit()
        print("  ✅ Columna 'af3' añadida a tabla fichas.")
    conn.close()


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
    """Propaga es_no_lectivo a todas las clases del día indicado en todos los grupos.

    Al marcar como no-lectivo (value=1): elimina TODAS las clases del día (reales y
    placeholders) y las sustituye por un único placeholder es_no_lectivo=1. Así no
    quedan clases ocultas con datos de asignatura que puedan causar inconsistencias.

    Al desmarcar (value=0): elimina el placeholder, dejando el día vacío.
    """
    semana_ids = conn.execute("""
        SELECT s.id FROM semanas s
        JOIN grupos g ON s.grupo_id = g.id
        WHERE g.cuatrimestre = ? AND s.numero = ?
    """, (cuatrimestre, numero)).fetchall()

    franjas = conn.execute("SELECT id FROM franjas ORDER BY orden").fetchall()

    for s in semana_ids:
        sid = s['id']

        if value == 1:
            # Eliminar TODAS las clases del día (reales y placeholders)
            # para sustituirlas por un único placeholder no-lectivo limpio.
            conn.execute("DELETE FROM clases WHERE semana_id=? AND dia=?", (sid, dia))
            franja_id = franjas[0]['id'] if franjas else 1
            conn.execute("""
                INSERT INTO clases
                    (semana_id, dia, franja_id, asignatura_id, aula, subgrupo,
                     observacion, es_no_lectivo, contenido)
                VALUES (?, ?, ?, NULL, '', '', NULL, 1, ?)
            """, (sid, dia, franja_id, descripcion or 'NO LECTIVO'))
        else:
            # Al desmarcar: eliminar el placeholder (y cualquier residuo).
            # El día queda vacío; el usuario reintroduce las clases si lo necesita.
            conn.execute("DELETE FROM clases WHERE semana_id=? AND dia=?", (sid, dia))


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


def api_reset_manual_finales(data):
    """POST /api/finales/reset-manual — elimina TODOS los exámenes (manual + auto) de un rango."""
    conn        = get_db()
    fecha_ini   = (data.get('fecha_inicio') or '').strip()
    fecha_fin   = (data.get('fecha_fin')    or '').strip()
    if not fecha_ini or not fecha_fin:
        conn.close()
        return {'error': 'fecha_inicio y fecha_fin requeridos'}
    res = conn.execute(
        "DELETE FROM examenes_finales WHERE fecha>=? AND fecha<=?",
        (fecha_ini, fecha_fin)
    )
    conn.commit()
    conn.close()
    return {'ok': True, 'deleted': res.rowcount}


def ensure_destacadas_table():
    """Crea la tabla asignaturas_destacadas si no existe.
    Almacena tuplas (codigo, grupo_num, act_type, subgrupo, modo) donde
    modo=1 (cambio de color + etiqueta DTIE) o modo=2 (solo etiqueta DTIE)."""
    conn = get_db()
    # Migración: si existe la tabla con el esquema antiguo (sin act_type), se recrea.
    cols = [row[1] for row in conn.execute("PRAGMA table_info(asignaturas_destacadas)").fetchall()]
    if cols and 'act_type' not in cols:
        conn.execute("DROP TABLE IF EXISTS asignaturas_destacadas")
        print("  Migración: tabla asignaturas_destacadas recreada con esquema act_type+subgrupo+modo")
        cols = []
    conn.execute("""
        CREATE TABLE IF NOT EXISTS asignaturas_destacadas (
            codigo    TEXT NOT NULL,
            grupo_num TEXT NOT NULL DEFAULT '',
            act_type  TEXT NOT NULL DEFAULT '',
            subgrupo  TEXT NOT NULL DEFAULT '',
            modo      INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (codigo, grupo_num, act_type, subgrupo)
        )
    """)
    # Migración inline: añadir columna modo si la tabla existía sin ella (pre-v11)
    if cols and 'modo' not in cols:
        conn.execute("ALTER TABLE asignaturas_destacadas ADD COLUMN modo INTEGER DEFAULT 1")
        print("  Migración: columna modo añadida a asignaturas_destacadas")
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM asignaturas_destacadas").fetchone()[0]
    print(f"  Asignaturas destacadas: {count} entradas")
    conn.close()


def ensure_comentarios_table():
    """Crea la tabla comentarios_horario si no existe (comentarios por grupo para PDFs)."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS comentarios_horario (
            grupo_key  TEXT NOT NULL,
            comentario TEXT DEFAULT '',
            ts         TEXT DEFAULT '',
            PRIMARY KEY (grupo_key)
        )
    """)
    conn.commit()
    conn.close()


def api_get_comentario(params):
    """GET /api/comentario?grupo_key=... — devuelve el comentario del grupo."""
    grupo_key = params.get('grupo_key', [''])[0]
    if not grupo_key:
        return {"ok": False, "error": "grupo_key requerido"}
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT comentario FROM comentarios_horario WHERE grupo_key=?", (grupo_key,)
        ).fetchone()
        return {"ok": True, "comentario": row["comentario"] if row else ""}
    finally:
        conn.close()


def api_set_comentario(data):
    """POST /api/comentario/set — guarda el comentario de un grupo."""
    import datetime
    grupo_key  = data.get('grupo_key', '')
    comentario = data.get('comentario', '')
    if not grupo_key:
        return {"ok": False, "error": "grupo_key requerido"}
    conn = get_db()
    try:
        ts = datetime.datetime.now().isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO comentarios_horario (grupo_key, comentario, ts) VALUES (?,?,?)",
            (grupo_key, comentario, ts)
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def api_db_info(_params):
    """GET /api/db/info — devuelve versión del servidor y versión del esquema de la BD."""
    import sys as _sys
    _tools = os.path.join(SCRIPT_DIR, "tools")
    if _tools not in _sys.path:
        _sys.path.insert(0, _tools)
    try:
        from migrate_db import _get_version, _ensure_version_table, LATEST_VERSION
        conn = get_db()
        _ensure_version_table(conn)
        db_version = _get_version(conn)
        conn.close()
    except Exception:
        db_version = None
        LATEST_VERSION = None
    return {
        "app_version":    APP_VERSION,
        "db_version":     db_version,
        "schema_latest":  LATEST_VERSION,
        "db_up_to_date":  db_version == LATEST_VERSION if db_version is not None else None,
    }


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


def api_db_checkpoint(_data):
    """POST /api/db/checkpoint — fuerza WAL checkpoint para que el .db refleje todos los cambios."""
    conn = get_db()
    try:
        conn.execute("PRAGMA wal_checkpoint(FULL)")
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


def api_db_import(raw_bytes):
    """POST /api/db/import — sustituye la base de datos activa por el fichero enviado."""
    import shutil, datetime
    if not raw_bytes:
        return {"ok": False, "error": "No se recibieron datos"}
    # Verificar magic bytes SQLite
    if raw_bytes[:16] != b'SQLite format 3\x00':
        return {"ok": False, "error": "El fichero no parece una base de datos SQLite válida"}
    # Backup automático antes de sobrescribir
    backup_dir = os.path.join(SCRIPT_DIR, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    db_basename = os.path.splitext(os.path.basename(DB_PATH))[0]
    backup_path = os.path.join(backup_dir, f"{db_basename}_preimport_{ts}.db")
    if os.path.exists(DB_PATH):
        shutil.copy2(DB_PATH, backup_path)
    # Escribir el nuevo fichero
    with open(DB_PATH, "wb") as f:
        f.write(raw_bytes)
    # Eliminar WAL y SHM para evitar inconsistencias
    for ext in ("-wal", "-shm"):
        p = DB_PATH + ext
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
    return {"ok": True, "backup": os.path.basename(backup_path)}


def api_toggle_destacada(data):
    """POST /api/destacada/toggle — ciclo de 3 estados para (codigo, grupo_num, act_type, subgrupo):
      · No existe        → INSERT modo=1  (color + etiqueta DTIE)
      · Existe modo=1    → UPDATE modo=2  (solo etiqueta DTIE, sin cambio de color)
      · Existe modo=2    → DELETE         (quitar marca)
    Devuelve {ok, action:'added'|'updated'|'removed', modo:1|2|0}."""
    codigo    = data.get("codigo", "").strip()
    grupo_num = str(data.get("grupo_num", "")).strip()
    act_type  = data.get("act_type", "").strip()
    subgrupo  = data.get("subgrupo", "").strip()
    if not codigo:
        return {"ok": False, "error": "codigo requerido"}
    conn = get_db()
    row = conn.execute(
        "SELECT modo FROM asignaturas_destacadas WHERE codigo=? AND grupo_num=? AND act_type=? AND subgrupo=?",
        (codigo, grupo_num, act_type, subgrupo)
    ).fetchone()
    if row is None:
        # Estado 0 → modo 1
        conn.execute(
            "INSERT INTO asignaturas_destacadas (codigo, grupo_num, act_type, subgrupo, modo) VALUES (?,?,?,?,1)",
            (codigo, grupo_num, act_type, subgrupo)
        )
        action, modo = "added", 1
    elif (row["modo"] or 1) == 1:
        # Modo 1 → modo 2
        conn.execute(
            "UPDATE asignaturas_destacadas SET modo=2 WHERE codigo=? AND grupo_num=? AND act_type=? AND subgrupo=?",
            (codigo, grupo_num, act_type, subgrupo)
        )
        action, modo = "updated", 2
    else:
        # Modo 2 → eliminar
        conn.execute(
            "DELETE FROM asignaturas_destacadas WHERE codigo=? AND grupo_num=? AND act_type=? AND subgrupo=?",
            (codigo, grupo_num, act_type, subgrupo)
        )
        action, modo = "removed", 0
    conn.commit()
    conn.close()
    return {"ok": True, "action": action, "modo": modo,
            "codigo": codigo, "grupo_num": grupo_num, "act_type": act_type, "subgrupo": subgrupo}


def api_move_clase(data):
    """Move a class to a different day/franja, swapping if the target slot is occupied (single class only)."""
    conn = get_db()
    clase_id  = data.get("id")
    nueva_dia    = data.get("dia")
    nuevo_franja = data.get("franja_id")
    if not (clase_id and nueva_dia and nuevo_franja):
        conn.close()
        return {"error": "Faltan parámetros: id, dia, franja_id"}

    # Obtener la clase origen
    origen = conn.execute(
        "SELECT id, semana_id, dia, franja_id FROM clases WHERE id=?", (clase_id,)
    ).fetchone()
    if not origen:
        conn.close()
        return {"error": "Clase no encontrada"}

    semana_id = origen["semana_id"]

    # Validar: si el destino es sábado, la clase origen debe ser de tipo EXP.
    if nueva_dia == 'SÁBADO':
        tipo_origen = conn.execute(
            "SELECT tipo FROM clases WHERE id=?", (clase_id,)
        ).fetchone()
        if not tipo_origen or tipo_origen["tipo"] != 'EXP':
            conn.close()
            return {"error": "Solo se pueden mover al sábado actividades de tipo EXP (examen parcial)."}

    # Buscar clases en el slot destino (dentro de la misma semana)
    destinos = conn.execute(
        "SELECT id FROM clases WHERE semana_id=? AND dia=? AND franja_id=?",
        (semana_id, nueva_dia, nuevo_franja)
    ).fetchall()

    if len(destinos) > 1:
        conn.close()
        return {"error": "El slot destino es un desdoble; no se puede intercambiar"}

    try:
        if len(destinos) == 1:
            # SWAP: no hay UNIQUE constraint en (semana_id, dia, franja_id),
            # así que intercambiamos directamente con dos UPDATEs
            dest_id = destinos[0]["id"]
            conn.execute("UPDATE clases SET dia=?, franja_id=? WHERE id=?",
                         (nueva_dia, nuevo_franja, clase_id))
            conn.execute("UPDATE clases SET dia=?, franja_id=? WHERE id=?",
                         (origen["dia"], origen["franja_id"], dest_id))
        else:
            # MOVE simple a celda vacía
            conn.execute("UPDATE clases SET dia=?, franja_id=? WHERE id=?",
                         (nueva_dia, nuevo_franja, clase_id))

        # Propagar posición a clases vinculadas (mismo conjunto_id, cada una en su semana)
        row = conn.execute("SELECT conjunto_id FROM clases WHERE id=?", (clase_id,)).fetchone()
        linked_moved = 0
        if row and row["conjunto_id"]:
            linked = conn.execute(
                "SELECT id FROM clases WHERE conjunto_id=? AND id!=?",
                (row["conjunto_id"], clase_id)
            ).fetchall()
            for lc in linked:
                # Mover directamente (sin swap) a la nueva posición en su propia semana
                conn.execute("UPDATE clases SET dia=?, franja_id=? WHERE id=?",
                             (nueva_dia, nuevo_franja, lc["id"]))
                linked_moved += 1

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"error": str(e)}

    conn.close()
    return {"ok": True, "swap": len(destinos) == 1}


# ─── MODO ESPEJO — sincronización entre grupos ────────────────────────────────

def ensure_grupos_sinc_table():
    """Crea la tabla grupos_sinc_exclusiones si no existe."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS grupos_sinc_exclusiones (
            grupo_key_origen  TEXT NOT NULL,
            grupo_key_destino TEXT NOT NULL,
            asignatura_codigo TEXT NOT NULL,
            PRIMARY KEY (grupo_key_origen, grupo_key_destino, asignatura_codigo)
        )
    """)
    conn.commit()
    conn.close()


def api_get_sinc_config(params):
    """GET /api/sinc/config?origen=...&destino=...
    Devuelve la lista de códigos de asignatura excluidos de la sincronización
    para el par de grupos indicado. Las exclusiones son simétricas: se consultan
    en ambas direcciones y se devuelve la unión."""
    origen  = params.get('origen',  [''])[0]
    destino = params.get('destino', [''])[0]
    if not origen or not destino:
        return {"ok": False, "error": "Parámetros 'origen' y 'destino' requeridos"}
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT asignatura_codigo FROM grupos_sinc_exclusiones
               WHERE (grupo_key_origen=? AND grupo_key_destino=?)
                  OR (grupo_key_origen=? AND grupo_key_destino=?)""",
            (origen, destino, destino, origen)
        ).fetchall()
        # Devolver códigos únicos (la unión de ambas direcciones)
        codigos = list({r["asignatura_codigo"] for r in rows})
        return {"ok": True, "exclusiones": codigos}
    finally:
        conn.close()


def api_sinc_exclusion_toggle(data):
    """POST /api/sinc/exclusion/toggle
    Añade o elimina una asignatura de la lista de exclusiones del modo espejo.
    Las exclusiones se guardan en AMBAS direcciones para garantizar simetría.
    Parámetros: { origen, destino, codigo }
    Devuelve { ok, action: 'added'|'removed' }"""
    origen  = data.get("origen",  "")
    destino = data.get("destino", "")
    codigo  = data.get("codigo",  "")
    if not (origen and destino and codigo):
        return {"ok": False, "error": "Faltan parámetros: origen, destino, codigo"}
    conn = get_db()
    try:
        # Comprobar si ya existe en cualquiera de las dos direcciones
        existing = conn.execute(
            """SELECT 1 FROM grupos_sinc_exclusiones
               WHERE asignatura_codigo=?
                 AND ((grupo_key_origen=? AND grupo_key_destino=?)
                   OR (grupo_key_origen=? AND grupo_key_destino=?))""",
            (codigo, origen, destino, destino, origen)
        ).fetchone()
        if existing:
            # Eliminar en ambas direcciones
            conn.execute(
                """DELETE FROM grupos_sinc_exclusiones
                   WHERE asignatura_codigo=?
                     AND ((grupo_key_origen=? AND grupo_key_destino=?)
                       OR (grupo_key_origen=? AND grupo_key_destino=?))""",
                (codigo, origen, destino, destino, origen)
            )
            conn.commit()
            return {"ok": True, "action": "removed"}
        else:
            # Insertar en ambas direcciones (INSERT OR IGNORE por idempotencia)
            conn.execute(
                """INSERT OR IGNORE INTO grupos_sinc_exclusiones
                   (grupo_key_origen, grupo_key_destino, asignatura_codigo)
                   VALUES (?,?,?)""",
                (origen, destino, codigo)
            )
            conn.execute(
                """INSERT OR IGNORE INTO grupos_sinc_exclusiones
                   (grupo_key_origen, grupo_key_destino, asignatura_codigo)
                   VALUES (?,?,?)""",
                (destino, origen, codigo)
            )
            conn.commit()
            return {"ok": True, "action": "added"}
    finally:
        conn.close()


# ─── ROUTE MAP ───

API_ROUTES = {
    "/api/schedule":       ("GET",  api_get_all),
    "/api/clase/update":          ("POST", api_update_clase),
    "/api/clase/create":          ("POST", api_create_clase),
    "/api/clase/delete":          ("POST", api_delete_clase),
    "/api/clases/clear-group":    ("POST", api_clear_group_clases),
    "/api/clase/move":            ("POST", api_move_clase),
    "/api/clase/conjunto/unlink": ("POST", api_unlink_conjunto),
    "/api/asignatura":     ("POST", api_manage_asignatura),
    "/api/ficha-override": ("POST", api_ficha_override),
    "/api/festivos":       ("GET",  api_get_festivos),
    "/api/festivos/set":   ("POST", api_set_festivo),
    "/api/finales":                  ("GET",  api_get_finales),
    "/api/finales/set":              ("POST", api_set_final),
    "/api/finales/batch-set":        ("POST", api_batch_set_finales),
    "/api/finales/reset-auto":       ("POST", api_reset_auto_finales),
    "/api/finales/reset-manual":     ("POST", api_reset_manual_finales),
    "/api/finales/checklist":        ("GET",  api_get_finales_checklist),
    "/api/finales/checklist/toggle": ("POST", api_toggle_finales_checklist),
    "/api/db/info":                  ("GET",  api_db_info),
    "/api/db/backup":                ("POST", api_db_backup),
    "/api/db/checkpoint":            ("POST", api_db_checkpoint),
    "/api/destacada/toggle":         ("POST", api_toggle_destacada),
    "/api/comentario":               ("GET",  api_get_comentario),
    "/api/comentario/set":           ("POST", api_set_comentario),
    "/api/sinc/config":              ("GET",  api_get_sinc_config),
    "/api/sinc/exclusion/toggle":    ("POST", api_sinc_exclusion_toggle),
}

TEMPLATE_PATH = None  # Plantilla no requerida; el Excel se genera desde cero


class HorarioHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.serve_html()
        elif parsed.path.startswith('/static/'):
            self.serve_static(parsed.path)
        elif parsed.path == "/api/exportar_excel":
            self.serve_excel_export()
        elif parsed.path == "/api/exportar_institucional":
            self.serve_institucional_export()
        elif parsed.path == "/api/finales/export-pdf":
            params = parse_qs(parsed.query)
            self.serve_finales_pdf(params)
        elif parsed.path == "/api/parciales/export-pdf":
            params = parse_qs(parsed.query)
            self.serve_parciales_pdf(params)
        elif parsed.path == "/api/logo":
            self.serve_logo()
        elif parsed.path == "/api/logo_svg":
            self.serve_logo_svg()
        elif parsed.path == "/api/db/download":
            self.serve_db_download()
        elif parsed.path == "/api/classrooms":
            self.serve_classrooms()
        elif parsed.path in API_ROUTES and API_ROUTES[parsed.path][0] == "GET":
            params = parse_qs(parsed.query)
            result = API_ROUTES[parsed.path][1](params)
            self.send_json(result)
        else:
            self.send_error(404)

    def serve_excel_export(self):
        import tempfile, importlib.util, zipfile
        try:
            export_mod_path = os.path.join(SCRIPT_DIR, "tools", "exportar_excel.py")
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

    def serve_institucional_export(self):
        """GET /api/exportar_institucional — Excel formato BD institucional UPCT."""
        import tempfile, importlib.util
        try:
            mod_path = os.path.join(SCRIPT_DIR, "tools", "exportar_institucional.py")
            if not os.path.exists(mod_path):
                self.send_json({"error": "exportar_institucional.py no encontrado"}, 500)
                return

            # Prioridad: config/weeks.json → weeks.xls (raíz)
            weeks_json = os.path.join(SCRIPT_DIR, "config", "weeks.json")
            weeks_xls  = os.path.join(SCRIPT_DIR, "weeks.xls")
            weeks_path = weeks_json if os.path.exists(weeks_json) else weeks_xls
            if not os.path.exists(weeks_path):
                self.send_json({"error": "No se encuentra config/weeks.json ni weeks.xls"}, 500)
                return

            spec = importlib.util.spec_from_file_location("exportar_institucional", mod_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            classrooms_path = os.path.join(SCRIPT_DIR, "config", "classrooms.json")
            curso_label = CURSO_LABEL.replace("-", "_")
            filename = f"Horarios_Institucional_{EXPORT_PREFIX}_{curso_label}.xlsx"

            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
            os.close(tmp_fd)
            try:
                mod.exportar(DB_PATH, _cfg_path, weeks_path, tmp_path, classrooms_path)
                with open(tmp_path, 'rb') as f:
                    data = f.read()
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", len(data))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            import traceback
            self.send_json({"error": str(e), "trace": traceback.format_exc()}, 500)

    def serve_classrooms(self):
        """GET /api/classrooms — devuelve classrooms.json como lista de aulas."""
        classrooms_path = os.path.join(SCRIPT_DIR, "config", "classrooms.json")
        if os.path.exists(classrooms_path):
            with open(classrooms_path, encoding="utf-8") as f:
                data = json.load(f)
            self.send_json(data)
        else:
            self.send_json([])

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
        # Convertir a RGB con fondo blanco para máxima compatibilidad con jsPDF
        # (evita problemas con PNGs RGBA / canal alfa)
        try:
            from PIL import Image as _PIL_Image
            import io as _io
            img = _PIL_Image.open(logo_png).convert('RGBA')
            bg = _PIL_Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            buf = _io.BytesIO()
            bg.save(buf, format='PNG', optimize=False)
            data = buf.getvalue()
        except Exception:
            data = open(logo_png, 'rb').read()
        self.send_response(200)
        self.send_header('Content-Type', 'image/png')
        self.send_header('Content-Length', len(data))
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)

    def serve_logo_svg(self):
        """GET /api/logo_svg — devuelve el logo Janux en formato SVG."""
        svg_path = os.path.join(SCRIPT_DIR, "docs", "logo_janux.svg")
        if not os.path.exists(svg_path):
            self.send_response(404); self.end_headers(); return
        data = open(svg_path, 'rb').read()
        self.send_response(200)
        self.send_header('Content-Type', 'image/svg+xml')
        self.send_header('Content-Length', len(data))
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)

    def serve_finales_pdf(self, params):
        """GET /api/finales/export-pdf — genera PDF completo con los 3 períodos."""
        import importlib.util, traceback
        try:
            mod_path = os.path.join(SCRIPT_DIR, "tools", "exportar_finales_pdf.py")
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

    def serve_parciales_pdf(self, params):
        """GET /api/parciales/export-pdf?cuat=1C|2C — genera PDF de parciales en formato finales."""
        import importlib.util, traceback
        from datetime import date, timedelta
        try:
            mod_path = os.path.join(SCRIPT_DIR, "tools", "exportar_finales_pdf.py")
            if not os.path.exists(mod_path):
                self.send_json({"error": "exportar_finales_pdf.py no encontrado"}, 500)
                return

            spec = importlib.util.spec_from_file_location("exportar_finales_pdf", mod_path)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            cuat_filter = (params.get('cuat', [''])[0] or '').strip().upper() or None  # '1C', '2C' o None

            conn = get_db()
            conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))

            # ── Obtener mapa semana+día → fecha ISO ──
            date_map = _parse_semana_date_ranges(conn)
            # date_map: { 'YYYY-MM-DD': {'cuatrimestre': '1C'|'2C', 'numero': N, 'dia': 'LUNES'|...} }
            # _parse_semana_date_ranges solo genera Lun-Vie; derivamos el Sábado desde cada Lunes.
            # Invertir para buscar: (cuatrimestre, numero, dia) → fecha ISO
            inv_map = {}
            for iso, info in date_map.items():
                inv_map[(info['cuatrimestre'], info['numero'], info['dia'])] = iso
                if info['dia'] == 'LUNES':
                    sabado_iso = (date.fromisoformat(iso) + timedelta(days=5)).isoformat()
                    inv_map[(info['cuatrimestre'], info['numero'], 'SÁBADO')] = sabado_iso

            # ── Consultar todos los parciales (EXP / EXF) ──
            rows = conn.execute("""
                SELECT
                    g.curso,
                    g.cuatrimestre,
                    g.grupo,
                    s.numero  AS semana_num,
                    c.dia,
                    c.tipo,
                    c.observacion,
                    a.codigo  AS asig_codigo,
                    a.nombre  AS asig_nombre,
                    f.orden   AS franja_orden
                FROM clases c
                JOIN semanas     s ON s.id = c.semana_id
                JOIN grupos      g ON g.id = s.grupo_id
                JOIN asignaturas a ON a.id = c.asignatura_id
                JOIN franjas     f ON f.id = c.franja_id
                WHERE c.tipo IN ('EXP','EXF')
                  AND (c.es_no_lectivo IS NULL OR c.es_no_lectivo = 0)
                ORDER BY g.cuatrimestre, s.numero, c.dia, g.curso
            """).fetchall()
            conn.close()

            # ── Agrupar y deduplicar por (fecha, curso, asig_codigo, tipo); acumular grupos ──
            seen = {}
            for r in rows:
                cuat = r['cuatrimestre']
                if cuat_filter and cuat != cuat_filter:
                    continue
                iso = inv_map.get((cuat, r['semana_num'], r['dia']))
                if not iso:
                    continue
                turno = 'mañana' if r['franja_orden'] <= 3 else 'tarde'
                key = (iso, str(r['curso']), r['asig_codigo'], r['tipo'])
                if key not in seen:
                    obs = ('Examen final' if r['tipo'] == 'EXF' else 'Examen parcial')
                    if r['observacion']:
                        obs += ' · ' + r['observacion']
                    seen[key] = {
                        'fecha':       iso,
                        'curso':       r['curso'],
                        'asig_codigo': r['asig_codigo'] or '',
                        'asig_nombre': r['asig_nombre'] or '',
                        'turno':       turno,
                        'observacion': obs,
                        'grupos':      [],
                    }
                grupo_num = str(r.get('grupo', '') or '')
                if grupo_num and grupo_num not in seen[key]['grupos']:
                    seen[key]['grupos'].append(grupo_num)

            # Convertir lista de grupos a cadena legible: 'Gr 1' / 'G1-G2-G3'
            for v in seen.values():
                grupos = sorted(v.pop('grupos', []))
                if len(grupos) == 1:
                    v['grupo'] = f"Gr {grupos[0]}"
                elif len(grupos) > 1:
                    v['grupo'] = '-'.join(f"G{g}" for g in grupos)
                else:
                    v['grupo'] = ''

            exams = sorted(seen.values(), key=lambda e: (e['fecha'], str(e['curso'])))

            if not exams:
                self.send_json({"error": "No hay exámenes parciales registrados"}, 404)
                return

            # ── Calcular rango de fechas ──
            fechas = [date.fromisoformat(e['fecha']) for e in exams]
            start_iso = min(fechas).isoformat()
            end_iso   = max(fechas).isoformat()

            # ── Determinar etiqueta del cuatrimestre ──
            if cuat_filter == '1C':
                cuat_label = '1er Cuatrimestre'
            elif cuat_filter == '2C':
                cuat_label = '2o Cuatrimestre'
            else:
                cuat_label = '1C + 2C'

            periodo_label = f"Exámenes Parciales — {cuat_label}"
            periods_data = [{'label': periodo_label, 'start': start_iso, 'end': end_iso, 'exams': exams}]

            pdf_bytes = mod.generar_pdf_finales_all(
                periods_data, CURSO_LABEL,
                degree_name=DEGREE_NAME, degree_acronym=DEGREE_ACRONYM
            )

            safe_label  = CURSO_LABEL.replace('-', '_')
            safe_cuat   = (cuat_filter or 'todos').replace(' ', '_')
            filename    = f"Parciales_{EXPORT_PREFIX}_{safe_label}_{safe_cuat}.pdf"

            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", len(pdf_bytes))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(pdf_bytes)
        except Exception as e:
            self.send_json({"error": str(e), "trace": traceback.format_exc()}, 500)

    def serve_db_download(self):
        """GET /api/db/download — fuerza WAL checkpoint y sirve el .db como descarga binaria."""
        import shutil, datetime
        # Checkpoint para que el .db esté actualizado
        conn = get_db()
        try:
            conn.execute("PRAGMA wal_checkpoint(FULL)")
            conn.commit()
        finally:
            conn.close()
        db_basename = os.path.splitext(os.path.basename(DB_PATH))[0]
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        suggested_name = f"{db_basename}_copia_{ts}.db"
        try:
            with open(DB_PATH, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{suggested_name}"')
            self.send_header("Content-Length", len(data))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def do_POST(self):
        parsed = urlparse(self.path)

        # ── Leer Content-Length de forma segura (puede faltar o ser no numérico) ──
        def _read_length():
            raw = self.headers.get("Content-Length") or "0"
            try:
                return int(raw)
            except (ValueError, TypeError):
                return None

        if parsed.path == "/api/db/import":
            length = _read_length()
            if length is None:
                self.send_json({"error": "Content-Length inválido o ausente"}, 400)
                return
            raw_bytes = self.rfile.read(length)
            try:
                result = api_db_import(raw_bytes)
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif parsed.path == "/api/verificar":
            # Recibe el PDF como bytes crudos; grupo_id en query string
            params = parse_qs(parsed.query)
            grupo_id_str = (params.get("grupo_id") or [""])[0]
            if not grupo_id_str.isdigit():
                self.send_json({"error": "grupo_id inválido o ausente"}, 400)
                return
            grupo_id = int(grupo_id_str)
            length = _read_length()
            if length is None:
                self.send_json({"error": "Content-Length inválido o ausente"}, 400)
                return
            raw_bytes = self.rfile.read(length)
            try:
                import tempfile, importlib.util
                verif_path = os.path.join(SCRIPT_DIR, "tools", "verificar_pdf.py")
                if not os.path.exists(verif_path):
                    self.send_json({"error": "verificar_pdf.py no encontrado en tools/"}, 500)
                    return
                spec = importlib.util.spec_from_file_location("verificar_pdf", verif_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                # Escribir PDF en fichero temporal
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(raw_bytes)
                    tmp_path = tmp.name
                try:
                    conn = get_db()
                    resultado = mod.verificar_pdf(tmp_path, grupo_id, conn)
                    conn.close()
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                self.send_json(resultado)
            except Exception as e:
                import traceback
                self.send_json({"error": str(e), "trace": traceback.format_exc()}, 500)

        elif parsed.path == "/api/verificar/marcar_nolectivo":
            # Recibe JSON {grupo_id, sem_num, dia}
            # Marca es_no_lectivo=1 en todas las clases de ese día/semana/grupo
            length = _read_length()
            if length is None:
                self.send_json({"error": "Content-Length inválido o ausente"}, 400)
                return
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            try:
                data = json.loads(body) if body else {}
                grupo_id = int(data.get("grupo_id", 0))
                sem_num  = int(data.get("sem_num",  0))
                dia      = str(data.get("dia",      ""))
                if not grupo_id or not sem_num or not dia:
                    self.send_json({"error": "Faltan parámetros: grupo_id, sem_num, dia"}, 400)
                    return
                conn = get_db()
                cur  = conn.execute(
                    """UPDATE clases SET es_no_lectivo = 1
                       WHERE grupo_id = ? AND sem_num = ? AND dia = ?""",
                    (grupo_id, sem_num, dia)
                )
                conn.commit()
                actualizadas = cur.rowcount
                conn.close()
                self.send_json({"ok": True, "actualizadas": actualizadas})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif parsed.path in API_ROUTES and API_ROUTES[parsed.path][0] == "POST":
            length = _read_length()
            if length is None:
                self.send_json({"error": "Content-Length inválido o ausente"}, 400)
                return
            # Decodificar con reemplazo para no crashear ante bytes ilegales
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            # Parsear JSON dentro del try/except para devolver 400 en lugar de 500
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError as e:
                self.send_json({"error": f"JSON inválido en el cuerpo: {e}"}, 400)
                return
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

    def serve_static(self, path):
        """Sirve ficheros estáticos desde la carpeta static/."""
        rel = path.lstrip('/')   # 'static/horarios.js' etc.
        abs_path = os.path.join(SCRIPT_DIR, rel)
        if not os.path.isfile(abs_path):
            self.send_error(404)
            return
        ext = os.path.splitext(abs_path)[1].lower()
        mime = {
            '.js':  'application/javascript; charset=utf-8',
            '.css': 'text/css; charset=utf-8',
        }.get(ext, 'application/octet-stream')
        with open(abs_path, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', len(data))
        self.send_header('Cache-Control', 'no-cache, must-revalidate')
        self.end_headers()
        self.wfile.write(data)

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



_html_cache = None  # Caché del HTML generado; la configuración no cambia en runtime

def generate_html():
    global _html_cache
    if _html_cache is not None:
        return _html_cache
    from jinja2 import Environment, FileSystemLoader
    templates_dir = os.path.join(SCRIPT_DIR, "templates")
    env = Environment(loader=FileSystemLoader(templates_dir), autoescape=False)
    template = env.get_template("index.html")
    _html_cache = template.render(
        CURSO_LABEL            = CURSO_LABEL,
        DEGREE_ACRONYM         = DEGREE_ACRONYM,
        DEGREE_NAME            = DEGREE_NAME,
        INSTITUTION_ACRONYM    = INSTITUTION_ACRONYM,
        INSTITUTION_NAME       = INSTITUTION_NAME,
        COLOR_PRIMARY          = COLOR_PRIMARY,
        COLOR_PRIMARY_LIGHT    = COLOR_PRIMARY_LIGHT,
        COLOR_ACCENT           = COLOR_ACCENT,
        COLOR_BG               = COLOR_BG,
        DESTACADAS_BADGE       = DESTACADAS_BADGE,
        EXPORT_PREFIX          = EXPORT_PREFIX,
        AULAS_POR_CURSO_JSON    = json.dumps(AULAS_POR_CURSO, ensure_ascii=False),
        AULARIO_POR_CURSO_JSON  = json.dumps(AULARIO_POR_CURSO, ensure_ascii=False),
        TIPOS_ACTIVIDAD_JSON    = json.dumps(TIPOS_ACTIVIDAD, ensure_ascii=False),
        TIPO_TO_AF_JSON         = json.dumps(TIPO_TO_AF, ensure_ascii=False),
        CURSO_OPTIONS           = CURSO_OPTIONS,
        NUM_CURSOS              = _num_cursos,
        APP_VERSION             = APP_VERSION,
    )
    return _html_cache


# ─── WINDOWS: COPIA DE SEGURIDAD AL CERRAR VENTANA ───────────────────────────
def _setup_win32_backup_handler():
    """Registra un manejador de consola Windows (SetConsoleCtrlHandler) que copia
    la BD temporal de vuelta al fichero original (DB_BACKUP_TARGET) cuando el
    usuario cierra la ventana CMD con la X (CTRL_CLOSE_EVENT).

    Sin esto, el comando 'copy' que sigue al servidor en el .bat generado nunca
    llega a ejecutarse al cerrar con la X, y los cambios de la sesión se pierden.
    Solo se activa si DB_BACKUP_TARGET está definido y la plataforma es win32.
    """
    if not DB_BACKUP_TARGET or sys.platform != "win32":
        return
    import ctypes, shutil

    _HandlerRoutine = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)

    def _handler(event):
        # Eventos relevantes: 0=CTRL_C, 1=CTRL_BREAK, 2=CTRL_CLOSE, 5=CTRL_LOGOFF, 6=CTRL_SHUTDOWN
        try:
            if os.path.isfile(DB_PATH):
                shutil.copy2(DB_PATH, DB_BACKUP_TARGET)
                print(f"\n[OK] BD guardada en {DB_BACKUP_TARGET}", flush=True)
        except Exception as exc:
            print(f"\n[ERROR] al guardar BD: {exc}", flush=True)
        return False  # propagar al manejador por defecto (cierra el proceso)

    _h = _HandlerRoutine(_handler)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(_h, True)
    # Mantener referencia para evitar que el GC elimine el callback
    _setup_win32_backup_handler._handler_ref = _h
    print(f"  [Win32] Guardado automático activado → {DB_BACKUP_TARGET}")


# ─── MAIN ───
if __name__ == "__main__":
    init_db_paths()

    # Migraciones de esquema: aplica automáticamente cualquier cambio pendiente
    # sobre la BD del grado activo. Seguro en cada arranque (idempotente).
    import sys as _sys
    _tools_dir = os.path.join(SCRIPT_DIR, "tools")
    if _tools_dir not in _sys.path:
        _sys.path.insert(0, _tools_dir)
    from migrate_db import migrate as _migrate_db
    _migrate_db(DB_PATH, curso_label=CURSO_LABEL)

    # Belt-and-suspenders: verificar columnas/tablas críticas de forma directa e
    # independiente del sistema de migraciones. Cubre el caso de BDs con
    # schema_version correcto pero objeto ausente (p.ej. BDs nuevas creadas con
    # setup_grado.py antes de que create_tables() incluyera la tabla).
    import sqlite3 as _sqlite3
    with _sqlite3.connect(DB_PATH) as _chk:
        _cols = {r[1] for r in _chk.execute("PRAGMA table_info(clases)").fetchall()}
        if "conjunto_id" not in _cols:
            _chk.execute("ALTER TABLE clases ADD COLUMN conjunto_id TEXT DEFAULT NULL")
            _chk.commit()
            print("  ✅ [repair] Columna 'conjunto_id' añadida a tabla clases.")
        _tables = {r[0] for r in _chk.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "grupos_sinc_exclusiones" not in _tables:
            _chk.execute("""
                CREATE TABLE IF NOT EXISTS grupos_sinc_exclusiones (
                    grupo_key_origen  TEXT NOT NULL,
                    grupo_key_destino TEXT NOT NULL,
                    asignatura_codigo TEXT NOT NULL,
                    PRIMARY KEY (grupo_key_origen, grupo_key_destino, asignatura_codigo)
                )
            """)
            _chk.commit()
            print("  ✅ [repair] Tabla 'grupos_sinc_exclusiones' creada.")

    title = f"GESTOR DE HORARIOS {DEGREE_ACRONYM} — {INSTITUTION_ACRONYM}"
    print(f"\n  ╔══════════════════════════════════════════════╗")
    print(f"  ║   {title:<44s}║")
    print(f"  ║   Base de datos: {DB_PATH:<28s}║")
    print(f"  ║   Servidor: http://localhost:{PORT:<17d}║")
    print(f"  ╚══════════════════════════════════════════════╝\n")

    _setup_win32_backup_handler()

    server = http.server.HTTPServer(("0.0.0.0", PORT), HorarioHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Servidor detenido.")
        server.server_close()
