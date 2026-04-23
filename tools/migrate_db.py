#!/usr/bin/env python3
"""
tools/migrate_db.py — Sistema de migraciones de esquema para Janux
==================================================================
Garantiza que cualquier BD creada con versiones anteriores del proyecto
quede compatible con la versión actual al arrancar el servidor o al
crear un grado nuevo.

Uso programático (servidor y herramientas):
    from tools.migrate_db import migrate, stamp
    migrate("/ruta/a/horarios.db", curso_label="2026-2027")   # en cada arranque
    stamp("/ruta/a/horarios.db")                               # solo en BDs nuevas

Uso desde consola (diagnóstico o migración manual):
    python3 tools/migrate_db.py horarios/GIM/horarios_2627.db
    python3 tools/migrate_db.py horarios/GIM/horarios_2627.db --info

Reglas para el futuro:
    - NUNCA modificar una migración ya publicada.
    - Para cualquier cambio de esquema, añadir una entrada nueva al final de MIGRATIONS.
    - Las migraciones nuevas deben ser idempotentes (usar IF NOT EXISTS / columna presente).
    - Añadir también el cambio a create_tables en setup_grado.py y nuevo_dtie.py
      para que las BDs nuevas arranquen ya con el esquema correcto.
"""

import re
import sqlite3
import sys
import os
from datetime import date, timedelta


# ─── MIGRACIONES ─────────────────────────────────────────────────────────────
# Cada función recibe (conn, **ctx) donde ctx puede incluir 'curso_label'.
# NUNCA modificar funciones ya numeradas; añadir nuevas al final de MIGRATIONS.

def _m01_tipo_clases(conn, **ctx):
    """Añade columna 'tipo' a clases y migra datos del campo 'aula'."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(clases)").fetchall()}
    if "tipo" in cols:
        return
    conn.execute("ALTER TABLE clases ADD COLUMN tipo TEXT DEFAULT ''")
    rows = conn.execute(
        "SELECT id, aula FROM clases WHERE aula IS NOT NULL AND aula != ''"
    ).fetchall()
    for r in rows:
        aula_val   = (r["aula"] or "").strip()
        aula_upper = aula_val.upper()
        if aula_val == "LAB":
            conn.execute("UPDATE clases SET tipo='LAB', aula='' WHERE id=?", (r["id"],))
        elif aula_upper == "INFO" or aula_upper.startswith("INFO"):
            conn.execute("UPDATE clases SET tipo='INF', aula='' WHERE id=?", (r["id"],))
        elif aula_upper.startswith("AULA:"):
            room = aula_val[5:].strip()
            conn.execute("UPDATE clases SET tipo='AD', aula=? WHERE id=?", (room, r["id"]))


def _m02_af_cat_clases(conn, **ctx):
    """Añade columna 'af_cat' a clases (destino AF para clases de evaluación)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(clases)").fetchall()}
    if "af_cat" not in cols:
        conn.execute("ALTER TABLE clases ADD COLUMN af_cat TEXT DEFAULT NULL")


def _m03_af3_fichas(conn, **ctx):
    """Añade columna 'af3' a fichas (Seminarios/Tutorías)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(fichas)").fetchall()}
    if "af3" not in cols:
        conn.execute("ALTER TABLE fichas ADD COLUMN af3 INTEGER DEFAULT 0")


def _m04_fichas_override_composite_pk(conn, **ctx):
    """Migra fichas_override a clave compuesta (codigo, grupo_key).
    BDs antiguas tenían solo 'codigo' como PRIMARY KEY."""
    table_info = conn.execute("PRAGMA table_info(fichas_override)").fetchall()
    cols = [r["name"] for r in table_info]
    if not table_info:
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
        # Esquema antiguo (PK solo codigo): recrear descartando datos
        # (no recuperables porque no se sabe a qué grupo pertenecían)
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


def _m05_festivos_calendario(conn, **ctx):
    """Crea festivos_calendario y migra no-lectivos marcados en clases."""
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
    if not is_new:
        return
    # Migración de datos: importar no-lectivos ya presentes en clases
    curso_label = ctx.get("curso_label", "2026-2027")
    mapping = _parse_semana_date_ranges(conn, curso_label)
    inv = {(v["cuatrimestre"], v["numero"], v["dia"]): k for k, v in mapping.items()}
    rows = conn.execute("""
        SELECT DISTINCT g.cuatrimestre, s.numero, c.dia
        FROM clases c
        JOIN semanas s ON c.semana_id = s.id
        JOIN grupos  g ON s.grupo_id  = g.id
        WHERE c.es_no_lectivo = 1
    """).fetchall()
    for row in rows:
        key   = (row["cuatrimestre"], row["numero"], row["dia"])
        fecha = inv.get(key)
        if fecha:
            conn.execute(
                "INSERT OR IGNORE INTO festivos_calendario (fecha, tipo) VALUES (?, 'no_lectivo')",
                (fecha,)
            )


def _m06_examenes_finales(conn, **ctx):
    """Crea examenes_finales; añade auto_generated si la tabla ya existía sin ella."""
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
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(examenes_finales)").fetchall()}
    if "auto_generated" not in cols:
        conn.execute("ALTER TABLE examenes_finales ADD COLUMN auto_generated INTEGER DEFAULT 0")


def _m07_finales_excluidas(conn, **ctx):
    """Crea finales_excluidas con clave (periodo, curso, asig_codigo).
    BDs antiguas tenían PK (codigo, curso) — se descartan datos incompatibles."""
    info = conn.execute("PRAGMA table_info(finales_excluidas)").fetchall()
    cols = [r["name"] for r in info]
    if info and "periodo" not in cols:
        # Esquema antiguo: no es posible recuperar el periodo, descartar
        conn.execute("DROP TABLE finales_excluidas")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS finales_excluidas (
            periodo     TEXT NOT NULL,
            curso       TEXT NOT NULL,
            asig_codigo TEXT NOT NULL,
            asig_nombre TEXT DEFAULT '',
            PRIMARY KEY (periodo, curso, asig_codigo)
        )
    """)


def _m08_asignaturas_destacadas(conn, **ctx):
    """Crea/actualiza asignaturas_destacadas con act_type y subgrupo.
    BDs antiguas solo tenían (codigo, grupo_num) — los datos se descartan
    porque son incompatibles (no se conoce el act_type original)."""
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(asignaturas_destacadas)").fetchall()]
    if cols and "act_type" not in cols:
        conn.execute("DROP TABLE IF EXISTS asignaturas_destacadas")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS asignaturas_destacadas (
            codigo    TEXT NOT NULL,
            grupo_num TEXT NOT NULL DEFAULT '',
            act_type  TEXT NOT NULL DEFAULT '',
            subgrupo  TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (codigo, grupo_num, act_type, subgrupo)
        )
    """)


def _m09_comentarios_horario(conn, **ctx):
    """Crea tabla comentarios_horario (comentarios al pie de los PDFs de grupo)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS comentarios_horario (
            grupo_key  TEXT NOT NULL,
            comentario TEXT DEFAULT '',
            ts         TEXT DEFAULT '',
            PRIMARY KEY (grupo_key)
        )
    """)


def _m10_fichas_cuatrimestre(conn, **ctx):
    """Añade columna 'cuatrimestre' a fichas (NULL=normal, 'A'=anual → divide AFs por 2 por cuatrimestre)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(fichas)").fetchall()}
    if "cuatrimestre" not in cols:
        conn.execute("ALTER TABLE fichas ADD COLUMN cuatrimestre TEXT DEFAULT NULL")


def _m11_destacadas_modo(conn, **ctx):
    """Añade columna 'modo' a asignaturas_destacadas (1=color+etiqueta, 2=solo etiqueta).
    Los registros existentes quedan con modo=1 (comportamiento anterior preservado)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(asignaturas_destacadas)").fetchall()}
    if cols and "modo" not in cols:
        conn.execute("ALTER TABLE asignaturas_destacadas ADD COLUMN modo INTEGER DEFAULT 1")


def _m12_fix_af_cat_stamp(conn, **ctx):
    """Re-garantiza que 'af_cat' existe en clases.
    Corrección para BDs generadas con nuevo_grado.py/setup_grado.py que fueron
    estampadas directamente a v11 sin pasar por _m02, dejando la columna ausente."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(clases)").fetchall()}
    if "af_cat" not in cols:
        conn.execute("ALTER TABLE clases ADD COLUMN af_cat TEXT DEFAULT NULL")


def _m13_fix_comentarios_stamp(conn, **ctx):
    """Crea comentarios_horario si no existe.
    Corrección para BDs generadas con setup_grado.py que fueron estampadas a v11
    sin incluir esta tabla (omitida en create_tables hasta la v1.18.0)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS comentarios_horario (
            grupo_key  TEXT NOT NULL,
            comentario TEXT DEFAULT '',
            ts         TEXT DEFAULT '',
            PRIMARY KEY (grupo_key)
        )
    """)


def _m14_rename_grupo_unico(conn, **ctx):
    """Renombra el valor 'unico' → '1' en la tabla grupos y actualiza todas las
    referencias derivadas (clave, comentarios_horario, fichas_override,
    asignaturas_destacadas).  BDs con múltiples grupos no se ven afectadas."""
    # 1. grupos: grupo='unico' → '1', clave='..._grupo_unico' → '..._grupo_1'
    conn.execute("UPDATE grupos SET grupo='1' WHERE grupo='unico'")
    conn.execute(
        "UPDATE grupos SET clave=REPLACE(clave,'_grupo_unico','_grupo_1') "
        "WHERE clave LIKE '%_grupo_unico'"
    )
    # 2. comentarios_horario: grupo_key usa el mismo patrón '..._grupo_unico'
    conn.execute(
        "UPDATE comentarios_horario "
        "SET grupo_key=REPLACE(grupo_key,'_grupo_unico','_grupo_1') "
        "WHERE grupo_key LIKE '%_grupo_unico'"
    )
    # 3. fichas_override: grupo_key con el mismo patrón
    conn.execute(
        "UPDATE fichas_override "
        "SET grupo_key=REPLACE(grupo_key,'_grupo_unico','_grupo_1') "
        "WHERE grupo_key LIKE '%_grupo_unico'"
    )
    # 4. asignaturas_destacadas: grupo_num='unico' → '1'
    conn.execute(
        "UPDATE asignaturas_destacadas SET grupo_num='1' WHERE grupo_num='unico'"
    )


def _m15_conjunto_id_clases(conn, **ctx):
    """Añade columna 'conjunto_id' a clases (UUID compartido entre exámenes EXP/EXF
    vinculados entre grupos). NULL = sin vínculo."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(clases)").fetchall()}
    if "conjunto_id" not in cols:
        conn.execute("ALTER TABLE clases ADD COLUMN conjunto_id TEXT DEFAULT NULL")


def _m16_clear_conjunto_id_non_exam(conn, **ctx):
    """Limpia conjunto_id en clases que NO sean de tipo EXP o EXF.
    Corrección de un bug en versiones anteriores donde _saveConjunto podía
    propagar el conjunto_id a clases de teoría/laboratorio al usar scope='all'."""
    conn.execute("""
        UPDATE clases SET conjunto_id = NULL
        WHERE tipo NOT IN ('EXP', 'EXF')
          AND conjunto_id IS NOT NULL
    """)


def _m17_grupos_sinc_exclusiones(conn, **ctx):
    """Crea tabla grupos_sinc_exclusiones para el modo espejo entre grupos.
    Almacena las asignaturas excluidas de la sincronización para un par de grupos.
    La lógica es 'sync por defecto, con excepciones': todos los cambios se
    replican al grupo espejo salvo las asignaturas listadas aquí."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS grupos_sinc_exclusiones (
            grupo_key_origen  TEXT NOT NULL,
            grupo_key_destino TEXT NOT NULL,
            asignatura_codigo TEXT NOT NULL,
            PRIMARY KEY (grupo_key_origen, grupo_key_destino, asignatura_codigo)
        )
    """)


def _m18_repair_conjunto_id(conn, **ctx):
    """Garantiza que 'conjunto_id' existe en clases aunque m15 quedara registrada
    sin aplicarse realmente (BD restaurada de backup o fallo silencioso previo).
    Idempotente: solo actúa si la columna está ausente."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(clases)").fetchall()}
    if "conjunto_id" not in cols:
        conn.execute("ALTER TABLE clases ADD COLUMN conjunto_id TEXT DEFAULT NULL")


# ─── REGISTRO DE MIGRACIONES ─────────────────────────────────────────────────
# NUNCA modificar entradas ya publicadas. Solo añadir nuevas al final.

MIGRATIONS = [
    (1,  "Añade columna 'tipo' a clases y migra datos del campo aula",          _m01_tipo_clases),
    (2,  "Añade columna 'af_cat' a clases",                                     _m02_af_cat_clases),
    (3,  "Añade columna 'af3' a fichas",                                        _m03_af3_fichas),
    (4,  "Migra fichas_override a clave compuesta (codigo, grupo_key)",          _m04_fichas_override_composite_pk),
    (5,  "Crea festivos_calendario y migra no-lectivos desde clases",            _m05_festivos_calendario),
    (6,  "Crea examenes_finales con columna auto_generated",                     _m06_examenes_finales),
    (7,  "Crea finales_excluidas con clave (periodo, curso, asig_codigo)",       _m07_finales_excluidas),
    (8,  "Crea/actualiza asignaturas_destacadas con act_type y subgrupo",        _m08_asignaturas_destacadas),
    (9,  "Crea tabla comentarios_horario",                                       _m09_comentarios_horario),
    (10, "Añade columna 'cuatrimestre' a fichas (A=anual, divide AFs por 2)",   _m10_fichas_cuatrimestre),
    (11, "Añade columna 'modo' a asignaturas_destacadas (1=color+badge, 2=solo badge)", _m11_destacadas_modo),
    (12, "Re-garantiza columna 'af_cat' en clases (fix stamp sin columna)",     _m12_fix_af_cat_stamp),
    (13, "Crea comentarios_horario si no existe (fix stamp sin tabla)",         _m13_fix_comentarios_stamp),
    (14, "Renombra grupo 'unico' → '1' en grupos y tablas relacionadas",        _m14_rename_grupo_unico),
    (15, "Añade columna 'conjunto_id' a clases (vínculo persistente EXP/EXF)",  _m15_conjunto_id_clases),
    (16, "Limpia conjunto_id en clases no-EXP/EXF (fix propagación incorrecta)", _m16_clear_conjunto_id_non_exam),
    (17, "Crea grupos_sinc_exclusiones para modo espejo entre grupos",           _m17_grupos_sinc_exclusiones),
    (18, "Repair: garantiza conjunto_id en clases si m15 quedó sin aplicarse",  _m18_repair_conjunto_id),
]

LATEST_VERSION = MIGRATIONS[-1][0]


# ─── FUNCIÓN AUXILIAR (autónoma respecto a servidor_horarios.py) ─────────────

def _parse_semana_date_ranges(conn, curso_label):
    """Parsea descripciones de semanas → dict {fecha_iso: {cuatrimestre, numero, dia}}."""
    MESES = {
        "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4,
        "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
        "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
    }
    DIAS = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES"]
    parts = curso_label.split("-")
    try:
        year_start, year_end = int(parts[0]), int(parts[1])
    except Exception:
        year_start, year_end = 2026, 2027
    rows = conn.execute("""
        SELECT DISTINCT g.cuatrimestre, s.numero, s.descripcion
        FROM semanas s JOIN grupos g ON s.grupo_id = g.id
        ORDER BY g.cuatrimestre, s.numero
    """).fetchall()
    mapping = {}
    for row in rows:
        m = re.search(r"(\d+)\s+([A-ZÁÉÍÓÚÑ]+)\s+A\s+(\d+)\s+([A-ZÁÉÍÓÚÑ]+)", row["descripcion"])
        if not m:
            continue
        start_month = MESES.get(m.group(2).upper())
        if not start_month:
            continue
        year = year_end if start_month < 7 else year_start
        try:
            start = date(year, start_month, int(m.group(1)))
        except Exception:
            continue
        for i, dia in enumerate(DIAS):
            mapping[(start + timedelta(days=i)).isoformat()] = {
                "cuatrimestre": row["cuatrimestre"],
                "numero":       row["numero"],
                "dia":          dia,
            }
    return mapping


# ─── TABLA DE VERSIONES ───────────────────────────────────────────────────────

def _ensure_version_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version    INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now')),
            description TEXT DEFAULT ''
        )
    """)


def _get_version(conn):
    """Devuelve la versión de esquema actual (0 si no existe la tabla)."""
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if not exists:
        return 0
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


# ─── API PÚBLICA ──────────────────────────────────────────────────────────────

def migrate(db_path, curso_label="2026-2027", verbose=True):
    """
    Aplica sobre db_path todas las migraciones pendientes.

    Es seguro llamarlo en cada arranque: si la BD ya está actualizada,
    no hace nada y retorna 0. Si falla alguna migración, lanza RuntimeError
    y la BD queda sin cambios (la transacción se revierte).

    Devuelve el número de migraciones aplicadas.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")   # seguro durante ALTER TABLE

    _ensure_version_table(conn)
    conn.commit()

    current = _get_version(conn)
    pending = [(v, d, fn) for v, d, fn in MIGRATIONS if v > current]

    if not pending:
        if verbose:
            print(f"  ✅ Esquema BD actualizado (v{current})")
        conn.close()
        return 0

    applied = 0
    for version, description, fn in pending:
        try:
            fn(conn, curso_label=curso_label)
            conn.execute(
                "INSERT OR REPLACE INTO schema_version (version, applied_at, description) "
                "VALUES (?, datetime('now'), ?)",
                (version, description)
            )
            conn.commit()
            if verbose:
                print(f"  ✅ Migración v{version}: {description}")
            applied += 1
        except Exception as exc:
            conn.rollback()
            conn.close()
            raise RuntimeError(
                f"Error en migración v{version} ({description}): {exc}\n"
                f"La BD no fue modificada. Restaura desde backups/ si es necesario."
            ) from exc

    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()
    return applied


def stamp(db_path):
    """
    Marca db_path como actualizada al esquema más reciente sin ejecutar migraciones.
    Usar solo en BDs recién creadas por setup_grado.py o nuevo_dtie.py,
    que ya incorporan el esquema actualizado desde create_tables().
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_version_table(conn)
    conn.commit()
    for version, description, _ in MIGRATIONS:
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at, description) "
            "VALUES (?, datetime('now'), ?)",
            (version, description)
        )
    conn.commit()
    conn.close()


def info(db_path):
    """Muestra el estado de migraciones de una BD (para diagnóstico)."""
    if not os.path.exists(db_path):
        print(f"ERROR: No existe {db_path}")
        return
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_version_table(conn)
    current = _get_version(conn)
    rows = conn.execute(
        "SELECT version, applied_at, description FROM schema_version ORDER BY version"
    ).fetchall()
    conn.close()

    print(f"\n  BD: {db_path}")
    print(f"  Esquema actual: v{current}  |  Última versión disponible: v{LATEST_VERSION}")
    if current < LATEST_VERSION:
        pending_n = LATEST_VERSION - current
        print(f"  ⚠️  {pending_n} migración(es) pendiente(s)")
    else:
        print(f"  ✅ Al día")
    if rows:
        print(f"\n  Historial de migraciones aplicadas:")
        for r in rows:
            print(f"    v{r['version']:>2}  {r['applied_at']}  {r['description']}")
    else:
        print(f"\n  Sin historial (BD antigua o recién creada sin stamp).")
    print()


# ─── USO DESDE CONSOLA ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Aplica migraciones de esquema a una BD Janux."
    )
    parser.add_argument("db_path", help="Ruta al fichero .db")
    parser.add_argument("--curso-label", default="2026-2027",
                        help="Etiqueta del curso (ej: 2026-2027)")
    parser.add_argument("--info", action="store_true",
                        help="Solo mostrar estado; no aplicar migraciones")
    args = parser.parse_args()

    if not os.path.exists(args.db_path):
        print(f"ERROR: No existe {args.db_path}")
        sys.exit(1)

    if args.info:
        info(args.db_path)
    else:
        try:
            n = migrate(args.db_path, curso_label=args.curso_label)
            if n == 0:
                print("No hay migraciones pendientes.")
            else:
                print(f"\n{n} migración(es) aplicada(s) correctamente.")
        except RuntimeError as e:
            print(f"\n❌ {e}")
            sys.exit(1)
