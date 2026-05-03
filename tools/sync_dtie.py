#!/usr/bin/env python3
"""
sync_dtie.py — Sincroniza el horario y los exámenes finales de un grado DTIE
               a partir de los grados de origen, usando fichas_DTIE_*.csv como
               tabla de distribución.

Uso:
    python3 tools/sync_dtie.py horarios/<SIGLAS_DTIE>
    python3 tools/sync_dtie.py horarios/<SIGLAS_DTIE> --csv config/fichas_DTIE_GIDI_GIM.csv
    python3 tools/sync_dtie.py horarios/<SIGLAS_DTIE> --dry-run

El script:
  - Lee fichas_DTIE_*.csv para saber qué asignaturas copiar y de qué grado origen.
  - Borra y reinsertar clases en la BD DTIE desde las BDs de origen.
  - Borra y reinsertar exámenes finales (sin distinción de subgrupo).
  - Solo escribe en la BD del DTIE; no toca las BDs de los grados de origen.
  - No modifica nuevo_dtie.py.

Formato del CSV (config/fichas_DTIE_<SIGLAS_B>_<SIGLAS_A>.csv):
    codigo,nombre,grado_origen,curso_dtie,cuatrimestre,grupo_origen
    - codigo       : código de la asignatura (enlaza con asignaturas.codigo en las BDs origen)
    - nombre       : nombre informativo
    - grado_origen : siglas del grado origen (ej. 'GIM' o 'GIDI')
    - curso_dtie   : curso en el DTIE (1-5); puede diferir del grado origen
    - cuatrimestre : cuatrimestre en el DTIE (ej. 'C1', 'C2', 'A', 'I')
    - grupo_origen : número del grupo fuente a copiar (vacío = grupo con más clases)
"""

import argparse
import csv
import io
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

# Forzar UTF-8 en stdout/stderr para evitar errores con emojis en Windows (cp1252)
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).parent.parent  # raíz del proyecto


# ─────────────────────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────────────────────

def open_db_safe(db_path, readonly=False):
    """
    Abre una BD SQLite. Si falla con disk I/O error (habitual en rutas de red
    como Dropbox/OneDrive), copia el fichero a un directorio temporal y lo abre
    desde allí. Devuelve (conn, tmp_path_o_None).
    """
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")  # fuerza apertura real
        if readonly:
            conn.execute("PRAGMA query_only=1")
        return conn, None
    except sqlite3.OperationalError:
        # Copiar a /tmp y reintentar
        tmp_file = tempfile.NamedTemporaryFile(
            suffix='.db', prefix='sync_dtie_', delete=False
        )
        tmp_path = Path(tmp_file.name)
        tmp_file.close()
        shutil.copy2(str(db_path), str(tmp_path))
        conn = sqlite3.connect(str(tmp_path))
        if readonly:
            conn.execute("PRAGMA query_only=1")
        return conn, tmp_path


def log(msg, tipo='info'):
    prefix = {'info': '  ℹ️ ', 'ok': '  ✅', 'warn': '  ⚠️ ', 'error': '  ❌'}.get(tipo, '  ')
    print(f"{prefix} {msg}")


def get_table_columns(conn, table):
    """Devuelve el conjunto de columnas de una tabla SQLite."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def table_exists(conn, table):
    """Comprueba si una tabla existe en la BD."""
    return bool(conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone())


# ─────────────────────────────────────────────────────────────────────────────
# Filtro DTIE por marcas ⭐ — réplica de los helpers en tools/nuevo_dtie.py
# (mantener ambos sincronizados; el JS getActType() es la fuente de verdad).
# ─────────────────────────────────────────────────────────────────────────────

def _clase_act_type(tipo, af_cat, tipo_to_af=None):
    """Calcula act_type de una clase a partir de (tipo, af_cat).

    Réplica de getActType() en static/horarios.js.
    """
    t = (tipo or '').strip().upper()
    if t == 'LAB': return 'lab'
    if t == 'INF': return 'info'
    if t == 'EXF': return 'parcial6'
    if t == 'EXP':
        return 'parcial6' if (af_cat or '') == 'AF6' else 'parcial5'
    if t == 'CPA': return 'teoria'
    if t == 'SEM': return 'af3'
    if t and tipo_to_af:
        af = tipo_to_af.get(t)
        if af == 'AF2': return 'lab'
        if af == 'AF4': return 'info'
        if af == 'AF5' or af == 'AF6': return 'parcial'
        if af == 'AF1': return 'teoria'
        if af == 'AF3': return 'af3'
    if t in ('AE', 'AEO', 'EPYOAE'):
        return 'parcial'
    return 'teoria'


def _expand_subgrupos(sg):
    """Expande subgrupo: '1,2,3' o '1-4' o '2'. Réplica de expandSubgrupos() en JS."""
    import re
    s = (sg or '').strip()
    m = re.fullmatch(r'(\d+)-(\d+)', s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return [str(i) for i in range(a, b + 1)]
    if ',' in s:
        return [x.strip() for x in s.split(',') if x.strip()]
    return [s]


def _load_marcas_destacadas(src_conn, codigo, grupo_num):
    """Devuelve dict[act_type] -> set(subgrupo) leído de asignaturas_destacadas.

    Busca primero por (codigo, grupo_num). Si no hay resultado — porque las
    marcas se guardaron desde un grupo distinto al indicado en grupo_origen del
    CSV — hace fallback a cualquier grupo del mismo código. Esto evita que un
    desfase entre el grupo donde se puso la ⭐ y el grupo fuente del CSV deje
    la asignatura sin clases en el DTIE.
    """
    if not table_exists(src_conn, 'asignaturas_destacadas'):
        return {}
    rows = src_conn.execute(
        "SELECT act_type, subgrupo FROM asignaturas_destacadas "
        "WHERE codigo = ? AND grupo_num = ?",
        (codigo, grupo_num)
    ).fetchall()
    if not rows:
        # Fallback: usar marcas de cualquier grupo del mismo código
        rows = src_conn.execute(
            "SELECT act_type, subgrupo FROM asignaturas_destacadas "
            "WHERE codigo = ?",
            (codigo,)
        ).fetchall()
    marcas = {}
    for act, sg in rows:
        marcas.setdefault(act or '', set()).add(sg or '')
    return marcas


def _clase_pasa_filtro(clase_tipo, clase_af_cat, clase_subgrupo, marcas, tipo_to_af=None):
    """Determina si una clase debe copiarse al DTIE según las marcas ⭐.

    Reglas (idénticas a nuevo_dtie.py):
      - Si la asignatura no tiene ninguna ⭐ → fuera.
      - EXP/EXF (parciales y exámenes en horario) son eventos de grupo
        completo: si la asignatura tiene ⭐, se copian siempre.
      - Si act_type de la clase no está en marcas → fuera.
      - 'todos' ∈ marcas[act_type] → entra.
      - subgrupo vacío y '' ∈ marcas[act_type] → entra.
      - Intersección de subgrupos expandidos con marcas[act_type] → entra.
    """
    if not marcas:
        return False
    t_upper = (clase_tipo or '').strip().upper()
    if t_upper in ('EXP', 'EXF'):
        return True
    act = _clase_act_type(clase_tipo, clase_af_cat, tipo_to_af)
    sg_marcados = marcas.get(act)
    if sg_marcados is None:
        return False
    if 'todos' in sg_marcados or 'Todos' in sg_marcados:
        return True
    sg_clase = (clase_subgrupo or '').strip()
    if sg_clase == '' and '' in sg_marcados:
        return True
    expandidos = set(_expand_subgrupos(sg_clase))
    return bool(expandidos & sg_marcados)


def _load_tipo_to_af(src_conn):
    """Lee tipo_to_af del config.json del grado fuente.

    Usa PRAGMA database_list para localizar el .db abierto y de ahí el
    config.json hermano.
    """
    try:
        path_row = src_conn.execute("PRAGMA database_list").fetchone()
        if not path_row or len(path_row) < 3:
            return {}
        db_path = path_row[2]
        if not db_path:
            return {}
        cfg_path = Path(db_path).parent / 'config.json'
        if cfg_path.exists():
            with open(cfg_path, encoding='utf-8') as f:
                cfg = json.load(f)
            return cfg.get('tipo_to_af', {}) or {}
    except Exception:
        pass
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# Construcción de mapas de franjas y semanas
# ─────────────────────────────────────────────────────────────────────────────

def build_franja_map(src_conn, dtie_conn):
    """
    Construye mapa src_franja_id → dtie_franja_id usando 'orden' como clave común.
    Las franjas se identifican por su orden (1-6), que es el mismo en todos los grados.
    """
    src_franjas  = src_conn.execute("SELECT id, orden FROM franjas").fetchall()
    dtie_franjas = dtie_conn.execute("SELECT id, orden FROM franjas").fetchall()
    orden_to_dtie = {orden: fid for fid, orden in dtie_franjas}
    return {src_id: orden_to_dtie.get(orden) for src_id, orden in src_franjas}


# ─────────────────────────────────────────────────────────────────────────────
# Localización del grupo fuente
# ─────────────────────────────────────────────────────────────────────────────

def find_source_grupo_id(src_conn, src_asig_id, grupo_origen):
    """
    Encuentra el grupo_id en la BD fuente adecuado para copiar la asignatura.

    Estrategia:
      1. Si grupo_origen está especificado, busca el grupo cuya clave termine
         en '_grupo_{grupo_origen}' (formato estándar: '1_1C_grupo_1').
      2. Si no hay coincidencia o grupo_origen está vacío, usa el grupo
         con más clases de esa asignatura (mismo criterio que nuevo_dtie.py).

    Devuelve el grupo_id o None si no hay clases.
    """
    candidates = src_conn.execute("""
        SELECT g.id, g.clave, COUNT(*) AS cnt
        FROM clases c
        JOIN semanas s ON s.id = c.semana_id
        JOIN grupos g ON g.id = s.grupo_id
        WHERE c.asignatura_id = ? AND c.es_no_lectivo = 0
        GROUP BY g.id
        ORDER BY cnt DESC
    """, (src_asig_id,)).fetchall()

    if not candidates:
        return None

    if grupo_origen:
        suffix = f'_grupo_{grupo_origen}'
        filtered = [r for r in candidates if r[1] and r[1].endswith(suffix)]
        if filtered:
            return filtered[0][0]
        # Segundo intento: último segmento de la clave coincide con grupo_origen
        filtered = [r for r in candidates
                    if r[1] and r[1].split('_')[-1] == str(grupo_origen)]
        if filtered:
            return filtered[0][0]
        # Solo avisa si hay más de un grupo disponible; con uno solo el fallback es trivial
        if len(candidates) > 1:
            log(f"grupo_origen='{grupo_origen}' no coincide con ningún grupo fuente, "
                f"se usa el grupo con más clases", 'warn')

    return candidates[0][0]


# ─────────────────────────────────────────────────────────────────────────────
# Sincronización de clases (horario semanal)
# ─────────────────────────────────────────────────────────────────────────────

def sync_clases(csv_rows, src_conns_by_siglas, dtie_conn, dry_run=False):
    """
    Para cada asignatura del CSV:
      1. Borra sus clases actuales en la BD DTIE (solo en el grupo que le corresponde).
      2. Reinserta las clases desde el grupo fuente, mapeando franjas y semanas.
      3. Actualiza curso/cuatrimestre de la asignatura en el DTIE según el CSV.

    Detecta conflictos de slot (dos asignaturas distintas en la misma semana/día/franja)
    y los reporta sin abortar.
    """
    log("── Sincronizando clases ─────────────────────────────────────")

    # Mapas de franjas por grado origen
    franja_maps = {
        siglas: build_franja_map(conn, dtie_conn)
        for siglas, conn in src_conns_by_siglas.items()
    }

    # tipo_to_af por grado origen (clasificación correcta de tipos editables
    # como AE/AEO al aplicar el filtro de marcas ⭐).
    tipo_to_af_by_siglas = {
        siglas: _load_tipo_to_af(conn)
        for siglas, conn in src_conns_by_siglas.items()
    }

    # Mapa de semanas DTIE: (grupo_id, numero) → semana_id
    dtie_semanas = dtie_conn.execute(
        "SELECT id, grupo_id, numero FROM semanas"
    ).fetchall()
    semana_map = {(gid, num): sid for sid, gid, num in dtie_semanas}

    # Mapa de grupos DTIE: (curso, cuatrimestre) → grupo_id
    dtie_grupos = dtie_conn.execute(
        "SELECT id, curso, cuatrimestre FROM grupos"
    ).fetchall()
    dtie_grupo_map = {}
    for gid, curso, cuat in dtie_grupos:
        dtie_grupo_map[(str(curso), cuat)] = gid
        try:
            dtie_grupo_map[(int(curso), cuat)] = gid
        except (ValueError, TypeError):
            pass

    # Columnas disponibles en la tabla clases del DTIE
    dtie_clases_cols = get_table_columns(dtie_conn, 'clases')

    # Mapa rápido codigo → {nombre, curso_dtie, cuatrimestre} para enriquecer conflictos
    asig_info_map = {
        row['codigo'].strip(): {
            'nombre':       row['nombre'].strip(),
            'curso_dtie':   int(row['curso_dtie']),
            'cuatrimestre': row['cuatrimestre'].strip(),
        }
        for row in csv_rows
    }

    # Mapa franja_id → label (ej. "9:00 - 10:50") para mensajes legibles
    franja_label_map = {
        fid: (label or f"franja {orden}")
        for fid, label, orden in dtie_conn.execute(
            "SELECT id, label, orden FROM franjas"
        ).fetchall()
    }

    total_copiadas = 0
    total_borradas = 0
    conflictos     = []
    slot_map       = {}   # (dtie_grupo_id, sem_num, dia, franja_id) → codigo

    for row in csv_rows:
        codigo       = row['codigo'].strip()
        nombre       = row['nombre'].strip()
        grado_origen = row['grado_origen'].strip().upper()
        curso_dtie   = int(row['curso_dtie'])
        cuatrimestre = row['cuatrimestre'].strip()
        grupo_origen = row.get('grupo_origen', '').strip()

        src_conn = src_conns_by_siglas.get(grado_origen)
        if src_conn is None:
            log(f"{codigo} ({grado_origen}): grado origen no disponible, se omite", 'warn')
            continue

        franja_map = franja_maps[grado_origen]

        # Asignatura en el DTIE
        dtie_asig = dtie_conn.execute(
            "SELECT id FROM asignaturas WHERE codigo = ?", (codigo,)
        ).fetchone()
        if not dtie_asig:
            log(f"{codigo} ({nombre}): no encontrada en BD DTIE, se omite", 'warn')
            continue
        dtie_asig_id = dtie_asig[0]

        # Verificar que la asignatura está marcada con ⭐ en la BD origen.
        # Si no lo está, borrar sus clases actuales del DTIE y pasar a la siguiente.
        # Así se limpian clases copiadas anteriormente de asignaturas que ya no son destacadas.
        if table_exists(src_conn, 'asignaturas_destacadas'):
            starred = src_conn.execute(
                "SELECT 1 FROM asignaturas_destacadas WHERE codigo = ? LIMIT 1",
                (codigo,)
            ).fetchone()
            if not starred:
                if not dry_run:
                    n_limpiadas = dtie_conn.execute(
                        "DELETE FROM clases WHERE asignatura_id = ?",
                        (dtie_asig_id,)
                    ).rowcount
                    total_borradas += n_limpiadas
                    if n_limpiadas:
                        log(f"{codigo} ({nombre}): sin ⭐ en {grado_origen} — {n_limpiadas} clases eliminadas del DTIE", 'warn')
                    else:
                        log(f"{codigo} ({nombre}): sin ⭐ en {grado_origen}, se omite", 'warn')
                else:
                    log(f"{codigo} ({nombre}): sin ⭐ en {grado_origen}, se omitiría", 'warn')
                continue

        # Asignatura en la fuente
        src_asig = src_conn.execute(
            "SELECT id FROM asignaturas WHERE codigo = ?", (codigo,)
        ).fetchone()
        if not src_asig:
            log(f"{codigo}: no encontrada en BD {grado_origen}, se omite", 'warn')
            continue
        src_asig_id = src_asig[0]

        # Grupo fuente
        src_grupo_id = find_source_grupo_id(src_conn, src_asig_id, grupo_origen)
        if src_grupo_id is None:
            log(f"{codigo}: sin clases en {grado_origen}, se omite", 'warn')
            continue

        # Grupo DTIE: (curso_dtie, cuatrimestre)
        dtie_grupo_id = (dtie_grupo_map.get((curso_dtie, cuatrimestre)) or
                         dtie_grupo_map.get((str(curso_dtie), cuatrimestre)))
        if dtie_grupo_id is None:
            log(f"{codigo}: grupo DTIE ({curso_dtie}, {cuatrimestre}) no encontrado, se omite", 'warn')
            continue

        # Borrar clases existentes de esta asignatura en el grupo DTIE correspondiente
        n_borradas = dtie_conn.execute(
            """DELETE FROM clases
               WHERE asignatura_id = ?
                 AND semana_id IN (SELECT id FROM semanas WHERE grupo_id = ?)""",
            (dtie_asig_id, dtie_grupo_id)
        ).rowcount
        total_borradas += n_borradas

        # Actualizar curso/cuatrimestre de la asignatura en el DTIE (según CSV)
        dtie_conn.execute(
            "UPDATE asignaturas SET curso = ?, cuatrimestre = ? WHERE id = ?",
            (curso_dtie, cuatrimestre, dtie_asig_id)
        )

        # Columnas extra opcionales presentes en ambas BDs (tipo, af_cat)
        src_clases_cols = get_table_columns(src_conn, 'clases')
        extra_cols = [c for c in ('tipo', 'af_cat')
                      if c in src_clases_cols and c in dtie_clases_cols]
        extra_select = (', ' + ', '.join(f'c.{c}' for c in extra_cols)) if extra_cols else ''

        # Leer clases desde la fuente
        clases = src_conn.execute(f"""
            SELECT c.dia, c.franja_id, c.aula, c.subgrupo, c.observacion,
                   c.es_no_lectivo, c.contenido, s.numero{extra_select}
            FROM clases c
            JOIN semanas s ON s.id = c.semana_id
            WHERE s.grupo_id = ? AND c.asignatura_id = ?
        """, (src_grupo_id, src_asig_id)).fetchall()

        # Filtrar por (act_type, subgrupo) marcado con ⭐ en la BD origen.
        # Política: las asignaturas sin ninguna ⭐ NO se sincronizan. Las que
        # tienen marcas conservan solo las clases cuya pareja (act_type,
        # subgrupo) esté presente — incluyendo el caso 'todos' para LAB/INF
        # compartidos. Réplica de la lógica de nuevo_dtie.py.
        src_grupo_clave_row = src_conn.execute(
            "SELECT clave FROM grupos WHERE id = ?", (src_grupo_id,)
        ).fetchone()
        src_grupo_num = src_grupo_clave_row[0].split('_grupo_')[-1] if src_grupo_clave_row else ''
        marcas = _load_marcas_destacadas(src_conn, codigo, src_grupo_num)
        if not marcas:
            log(f"{codigo} ({grado_origen}): sin ⭐ en grupo {src_grupo_num}, "
                f"se omite (asignaturas sin estrella no se incluyen)", 'warn')
            clases = []
        else:
            tipo_to_af = tipo_to_af_by_siglas.get(grado_origen, {})
            tipo_idx = (8 + extra_cols.index('tipo')) if 'tipo' in extra_cols else None
            af_cat_idx = (8 + extra_cols.index('af_cat')) if 'af_cat' in extra_cols else None
            clases = [
                c for c in clases
                if _clase_pasa_filtro(
                    c[tipo_idx] if tipo_idx is not None else '',
                    c[af_cat_idx] if af_cat_idx is not None else '',
                    c[3], marcas, tipo_to_af
                )
            ]

        n_copiadas = 0
        for clase in clases:
            dia, src_franja_id, aula, subgrupo, observacion, \
                es_no_lectivo, contenido, sem_num = clase[:8]
            extra_vals = list(clase[8:])

            dtie_semana_id = semana_map.get((dtie_grupo_id, sem_num))
            if dtie_semana_id is None:
                continue

            new_franja_id = franja_map.get(src_franja_id, src_franja_id)

            # Detección de conflictos de slot entre asignaturas distintas
            if not es_no_lectivo:
                slot_key = (dtie_grupo_id, sem_num, dia, new_franja_id)
                if slot_key in slot_map and slot_map[slot_key] != codigo:
                    prev     = slot_map[slot_key]
                    conf_key = tuple(sorted([prev, codigo])) + (sem_num, dia, new_franja_id)
                    known    = {
                        tuple(sorted([c['asig1'], c['asig2']])) + (c['semana'], c['dia'], c['franja'])
                        for c in conflictos
                    }
                    if conf_key not in known:
                        info1 = asig_info_map.get(prev, {})
                        info2 = asig_info_map.get(codigo, {})
                        conflictos.append({
                            'asig1':       prev,
                            'asig2':       codigo,
                            'nombre1':     info1.get('nombre', prev),
                            'nombre2':     info2.get('nombre', codigo),
                            'curso':       info2.get('curso_dtie', '?'),
                            'cuatrimestre': info2.get('cuatrimestre', '?'),
                            'semana':      sem_num,
                            'dia':         dia,
                            'franja':      new_franja_id,
                            'franja_label': franja_label_map.get(new_franja_id,
                                                                  f"franja {new_franja_id}"),
                        })
                else:
                    slot_map[slot_key] = codigo

            if not dry_run:
                if extra_cols:
                    ph  = ', '.join(['?'] * len(extra_cols))
                    col = ', '.join(extra_cols)
                    dtie_conn.execute(
                        f"""INSERT INTO clases
                            (semana_id, dia, franja_id, asignatura_id, aula,
                             subgrupo, observacion, es_no_lectivo, contenido, {col})
                            VALUES (?,?,?,?,?,?,?,?,?,{ph})""",
                        (dtie_semana_id, dia, new_franja_id, dtie_asig_id,
                         aula, subgrupo, observacion, es_no_lectivo, contenido)
                        + tuple(extra_vals)
                    )
                else:
                    dtie_conn.execute(
                        """INSERT INTO clases
                           (semana_id, dia, franja_id, asignatura_id, aula,
                            subgrupo, observacion, es_no_lectivo, contenido)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (dtie_semana_id, dia, new_franja_id, dtie_asig_id,
                         aula, subgrupo, observacion, es_no_lectivo, contenido)
                    )
            n_copiadas += 1

        total_copiadas += n_copiadas
        log(f"{codigo} ({grado_origen}): {n_borradas} borradas → {n_copiadas} copiadas", 'ok')

    if not dry_run:
        dtie_conn.commit()

    print()
    log(f"Clases totales: {total_borradas} borradas, {total_copiadas} copiadas")

    if conflictos:
        log(f"{len(conflictos)} conflicto(s) de slot detectados:", 'warn')
        for c in conflictos:
            log(
                f"  Curso {c['curso']} {c['cuatrimestre']} · "
                f"Sem {c['semana']} · {c['dia']} · {c['franja_label']}\n"
                f"    {c['asig1']} {c['nombre1']}\n"
                f"    {c['asig2']} {c['nombre2']}",
                'warn'
            )

    return conflictos


# ─────────────────────────────────────────────────────────────────────────────
# Sincronización de exámenes finales
# ─────────────────────────────────────────────────────────────────────────────

def sync_examenes_finales(csv_rows, src_conns_by_siglas, dtie_conn, dry_run=False):
    """
    Para cada asignatura del CSV:
      1. Borra su examen final en la BD DTIE (si existe).
      2. Reinsertar desde la BD fuente, sin distinción de subgrupo.
         El curso asignado es el de la columna 'curso_dtie' del CSV,
         no el curso en el grado origen.

    Adapta dinámicamente las columnas según el esquema de cada BD
    (compatible con el esquema documentado en TECHNICAL.md y con el
    esquema antiguo generado por nuevo_dtie.py antes de las migraciones).
    """
    log("── Sincronizando exámenes finales ──────────────────────────")

    if not table_exists(dtie_conn, 'examenes_finales'):
        log("La BD DTIE no tiene tabla examenes_finales, se omite este paso", 'warn')
        return

    dtie_ef_cols = get_table_columns(dtie_conn, 'examenes_finales')
    total_copiados = 0
    total_borrados = 0

    for row in csv_rows:
        codigo       = row['codigo'].strip()
        nombre       = row['nombre'].strip()
        grado_origen = row['grado_origen'].strip().upper()
        curso_dtie   = str(row['curso_dtie']).strip()

        src_conn = src_conns_by_siglas.get(grado_origen)
        if src_conn is None:
            continue

        if not table_exists(src_conn, 'examenes_finales'):
            continue

        src_ef_cols = get_table_columns(src_conn, 'examenes_finales')

        # Verificar que la asignatura está marcada con ⭐ en la BD origen.
        # Si no lo está, borrar su examen del DTIE (limpieza) y pasar a la siguiente.
        if table_exists(src_conn, 'asignaturas_destacadas'):
            starred = src_conn.execute(
                "SELECT 1 FROM asignaturas_destacadas WHERE codigo = ? LIMIT 1",
                (codigo,)
            ).fetchone()
            if not starred:
                n_borrados = dtie_conn.execute(
                    "DELETE FROM examenes_finales WHERE asig_codigo = ?", (codigo,)
                ).rowcount
                total_borrados += n_borrados
                if n_borrados:
                    log(f"{codigo} ({nombre}): sin ⭐ en {grado_origen} — "
                        f"{n_borrados} examen(es) final(es) eliminados del DTIE", 'warn')
                else:
                    log(f"{codigo} ({nombre}): sin ⭐ en {grado_origen}, se omite", 'warn')
                continue

        # Borrar examen existente en el DTIE para este código
        n_borrados = dtie_conn.execute(
            "DELETE FROM examenes_finales WHERE asig_codigo = ?", (codigo,)
        ).rowcount
        total_borrados += n_borrados

        # Leer exámenes de la fuente para este código (sin filtrar subgrupo)
        # Las columnas opcionales se detectan dinámicamente
        cols_opcionales = [c for c in ('fecha', 'turno', 'aulas', 'periodo', 'observacion')
                           if c in src_ef_cols]
        if not cols_opcionales:
            continue

        src_examenes = src_conn.execute(
            f"SELECT {', '.join(cols_opcionales)} FROM examenes_finales WHERE asig_codigo = ?",
            (codigo,)
        ).fetchall()

        for examen in src_examenes:
            vals_src = dict(zip(cols_opcionales, examen))

            # Construir INSERT adaptado al esquema real del DTIE
            insert_cols = ['asig_codigo', 'asig_nombre', 'curso']
            insert_vals = [codigo, nombre, curso_dtie]

            for col in ('fecha', 'turno', 'aulas', 'periodo', 'observacion'):
                if col in vals_src and col in dtie_ef_cols:
                    insert_cols.append(col)
                    insert_vals.append(vals_src[col])

            # Campo auto/auto_generated (reinserción = no automática)
            if 'auto' in dtie_ef_cols:
                insert_cols.append('auto')
                insert_vals.append(0)
            elif 'auto_generated' in dtie_ef_cols:
                insert_cols.append('auto_generated')
                insert_vals.append(0)

            ph      = ', '.join(['?'] * len(insert_vals))
            col_str = ', '.join(insert_cols)

            if not dry_run:
                dtie_conn.execute(
                    f"INSERT INTO examenes_finales ({col_str}) VALUES ({ph})",
                    insert_vals
                )
            total_copiados += 1

    if not dry_run:
        dtie_conn.commit()

    log(f"Exámenes totales: {total_borrados} borrados, {total_copiados} copiados", 'ok')


# ─────────────────────────────────────────────────────────────────────────────
# Punto de entrada
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Sincroniza el horario y los exámenes finales de un grado DTIE '
                    'a partir de los grados de origen.'
    )
    parser.add_argument(
        'grado_dir',
        help='Carpeta del grado DTIE (ej. horarios/DTIE_GIDI_GIM)'
    )
    parser.add_argument(
        '--csv',
        help='Ruta al CSV de distribución (ej. config/fichas_DTIE_GIDI_GIM.csv). '
             'Si se omite, se busca automáticamente en config/ o en config.mapeo_csv.'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Simula la sincronización sin escribir nada en la BD.'
    )
    parser.add_argument(
        '--db',
        help='Ruta alternativa a la BD DTIE (anula la ruta del config.json). '
             'Útil cuando el launcher ya la ha copiado a /tmp/.',
        default=None
    )
    args = parser.parse_args()

    grado_dir = BASE_DIR / args.grado_dir
    if not grado_dir.exists():
        print(f"❌ No se encuentra la carpeta: {grado_dir}")
        sys.exit(1)

    # ── Cargar config.json ──────────────────────────────────────────────────
    cfg_path = grado_dir / 'config.json'
    if not cfg_path.exists():
        print(f"❌ No se encuentra config.json en {grado_dir}")
        sys.exit(1)

    with open(cfg_path, encoding='utf-8') as f:
        cfg = json.load(f)

    if not cfg.get('dtie'):
        print("❌ Este grado no es un DTIE (falta 'dtie: true' en config.json).")
        sys.exit(1)

    siglas = cfg.get('degree', {}).get('acronym', grado_dir.name)
    print(f"\n🔄  Sincronizando DTIE: {siglas}")
    if args.dry_run:
        print("    [DRY RUN — no se escribirá nada en la BD]")

    # ── Resolver ruta del CSV ───────────────────────────────────────────────
    csv_path = None
    if args.csv:
        csv_path = BASE_DIR / args.csv
    elif cfg.get('mapeo_csv'):
        csv_path = BASE_DIR / cfg['mapeo_csv']
    else:
        # Auto-detect: buscar config/fichas_DTIE_<SIGLAS>*.csv, luego cualquier fichas_DTIE_
        config_dir = BASE_DIR / 'config'
        candidates = sorted(config_dir.glob(f'fichas_DTIE_{siglas}*.csv'))
        if not candidates:
            candidates = sorted(config_dir.glob('fichas_DTIE_*.csv'))
        if candidates:
            csv_path = candidates[0]

    if csv_path is None or not csv_path.exists():
        print("❌ No se encuentra el CSV de distribución. "
              "Especifícalo con --csv <ruta> o añade 'mapeo_csv' al config.json del DTIE.")
        sys.exit(1)

    print(f"    CSV    : {csv_path.relative_to(BASE_DIR)}")

    # ── Leer CSV ────────────────────────────────────────────────────────────
    with open(csv_path, encoding='utf-8') as f:
        reader   = csv.DictReader(f)
        csv_rows = [r for r in reader if r.get('codigo', '').strip()]

    if not csv_rows:
        print("❌ El CSV está vacío o no tiene filas válidas.")
        sys.exit(1)

    print(f"    Asignaturas: {len(csv_rows)}")

    # ── Abrir BD DTIE ───────────────────────────────────────────────────────
    db_name      = cfg.get('server', {}).get('db_name', 'horarios.db')
    dtie_db_path = Path(args.db) if args.db else grado_dir / db_name
    if not dtie_db_path.exists():
        print(f"❌ No se encuentra la BD DTIE: {dtie_db_path}")
        sys.exit(1)

    dtie_conn, dtie_tmp = open_db_safe(dtie_db_path)
    dtie_conn.execute("PRAGMA journal_mode=WAL")
    try:
        dtie_db_display = dtie_db_path.relative_to(BASE_DIR)
    except ValueError:
        dtie_db_display = dtie_db_path
    print(f"    BD DTIE: {dtie_db_display}")

    # ── Abrir BDs de origen ─────────────────────────────────────────────────
    dtie_fuentes        = cfg.get('dtie_fuentes', [])
    src_conns_by_siglas = {}
    src_tmp_paths       = []   # temporales a limpiar al final

    for fuente in dtie_fuentes:
        db_path_str = fuente.get('db_path', '')
        if not db_path_str:
            continue
        db_path = BASE_DIR / db_path_str
        if not db_path.exists():
            log(f"BD fuente no encontrada: {db_path_str}", 'warn')
            continue
        grado_siglas          = db_path.parent.name.upper()
        src_conn, src_tmp     = open_db_safe(db_path, readonly=True)
        if src_tmp:
            src_tmp_paths.append(src_tmp)
        src_conns_by_siglas[grado_siglas] = src_conn
        print(f"    Fuente : {grado_siglas} → {db_path_str}")

    # ── Verificar que todas las fuentes del CSV están disponibles ───────────
    grados_csv = {r['grado_origen'].strip().upper() for r in csv_rows}
    missing    = grados_csv - set(src_conns_by_siglas.keys())
    if missing:
        print(f"❌ Grado(s) origen del CSV no disponibles en dtie_fuentes: {', '.join(sorted(missing))}")
        dtie_conn.close()
        for c in src_conns_by_siglas.values():
            c.close()
        sys.exit(1)

    # ── Sincronizar ─────────────────────────────────────────────────────────
    print()
    conflictos = []
    try:
        conflictos = sync_clases(
            csv_rows, src_conns_by_siglas, dtie_conn, dry_run=args.dry_run
        )
        print()
        sync_examenes_finales(
            csv_rows, src_conns_by_siglas, dtie_conn, dry_run=args.dry_run
        )
    except Exception as exc:
        print(f"\n❌ Error durante la sincronización: {exc}")
        raise
    finally:
        dtie_conn.close()
        for c in src_conns_by_siglas.values():
            c.close()
        # Limpiar ficheros temporales creados por open_db_safe
        for tmp in src_tmp_paths:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        if dtie_tmp:
            try:
                dtie_tmp.unlink(missing_ok=True)
            except OSError:
                pass

    # ── Resumen final ───────────────────────────────────────────────────────
    print()
    if args.dry_run:
        print("✅  Simulación completada sin errores.")
    elif conflictos:
        print(f"⚠️   Sincronización completada con {len(conflictos)} conflicto(s) de slot.")
        print("     Revisa los avisos anteriores para ver los detalles.")
    else:
        print("✅  Sincronización completada correctamente.")


if __name__ == '__main__':
    main()
