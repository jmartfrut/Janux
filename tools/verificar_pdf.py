#!/usr/bin/env python3
"""
verificar_pdf.py — Verifica que un PDF institucional (horarios.upct.es)
coincide con los datos de la base de datos del Gestor de Horarios Janux.

Uso como librería:
    from tools.verificar_pdf import verificar_pdf
    resultado = verificar_pdf(pdf_path, grupo_id, db_conn)

Uso como script:
    python3 tools/verificar_pdf.py <pdf_path> <grupo_id> <db_path>
"""

import re
import sqlite3
import sys
import os
from collections import defaultdict

# ── Constantes de franjas ─────────────────────────────────────────────────────
FRANJA_HORA_TO_ID = {'09:00': 1, '11:10': 2, '13:10': 3}
FRANJA_ID_TO_LABEL = {1: '9:00 - 10:50', 2: '11:10 - 13:00', 3: '13:10 - 15:00'}

DIA_NORM = {
    'Lunes':     'LUNES',
    'Martes':    'MARTES',
    'Miércoles': 'MIÉRCOLES',
    'Jueves':    'JUEVES',
    'Viernes':   'VIERNES',
}
DIAS_ABREV = {
    'LUNES': 'Lun', 'MARTES': 'Mar', 'MIÉRCOLES': 'Mié',
    'JUEVES': 'Jue', 'VIERNES': 'Vie',
}


def _build_col_bounds(day_order):
    """Devuelve [(dia_norm, x_left, x_right), ...] para asignar palabras a columnas.

    Se añaden 2 px al límite derecho de cada columna (excepto la última) para
    absorber pequeñas diferencias de subpíxel en la posición x de las palabras:
    por ejemplo, 'Fabricación' puede caer a x0=502.3 cuando el límite teórico
    es 502.25, y sin la tolerancia quedaría asignada a la columna siguiente.
    """
    bounds = []
    xs = [dx for _, dx in day_order]
    for i, (dia, dx) in enumerate(day_order):
        left  = xs[i-1] + (dx - xs[i-1]) / 2 if i > 0 else 0
        right = xs[i+1] - (xs[i+1] - dx) / 2 + 2 if i + 1 < len(day_order) else 9999
        bounds.append((DIA_NORM.get(dia, dia), left, right))
    return bounds


def _assign_col(x0, col_bounds):
    for dia, xl, xr in col_bounds:
        if xl <= x0 < xr:
            return dia
    return None


def _detect_asig(cell_text, asig_tokens):
    """
    Devuelve el nombre de la asignatura si todos sus tokens están en cell_text.

    Incluye un fallback de prefijo para cubrir tokens fusionados por renderizado
    superpuesto en desdobles múltiples: el PDF puede renderizar el nombre N veces
    sobre la misma posición y pdfplumber entrelaza los caracteres produciendo un
    token como "MatemáticaMsatemáticaMsatemáticas" que no contiene "Matemáticas"
    como subcadena exacta pero SÍ empieza por "Matemátic" (= token[:-1]).
    Solo se activa el fallback para tokens largos (≥5 chars) para evitar falsos
    positivos.
    """
    words = cell_text.split()
    for asig, tokens in asig_tokens.items():
        if not tokens:
            continue
        match = True
        for t in tokens:
            if t in cell_text:
                continue  # coincidencia exacta
            # Fallback 1: token fusionado por renderizado superpuesto
            # (ej. "MatemáticaMsatemáticas" startswith "Matemátic")
            if len(t) >= 5 and any(w.startswith(t[:-1]) for w in words):
                continue
            # Fallback 2: inicialismo con varios puntos (C.I., E.T.S., ...)
            # El PDF muestra el nombre expandido; saltar este token
            # — los demás tokens (ej. "Materiales") son suficientes.
            if t.count('.') >= 2:
                continue
            match = False
            break
        if match:
            return asig
    return None


def parse_pdf(pdf_path, asignaturas_nombres):
    """
    Parsea el PDF institucional y extrae las clases con coordenadas.

    Retorna lista de dicts:
        {sem_num, dia, franja_id, asignatura, tipo, subgrupo, fecha_inicio}
    """
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError(
            "pdfplumber no está instalado. Ejecuta: pip install pdfplumber"
        )

    # Tokenización por asignatura (solo tokens >2 chars para evitar falsos positivos)
    asig_tokens = {
        a: [t for t in a.split() if len(t) > 2]
        for a in asignaturas_nombres
    }

    clases = []
    # {sem_num: set(dias_completamente_vacios_en_PDF_pero_con_cabecera)}
    dias_vacios_pdf = {}

    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            if page_idx == 0:
                continue  # primera página suele ser vacía o portada

            sem_num = page_idx  # page 1 → semana 1, page 2 → semana 2, ...

            words = page.extract_words()

            # ── Fecha de la semana (para mostrar en el informe) ──────────────
            fecha_inicio = None
            for w in words:
                m = re.search(r'(\d{2}/\d{2}/\d{4})', w['text'])
                if m and w['top'] < 60:
                    fecha_inicio = m.group(1)
                    break
            # Línea completa de semana
            text_top = ' '.join(w['text'] for w in words if w['top'] < 60)
            m_fecha = re.search(r'(\d{2}/\d{2}/\d{4})\s*[–—-]\s*(\d{2}/\d{2}/\d{4})', text_top)
            if m_fecha:
                fecha_inicio = m_fecha.group(1)

            # ── Posiciones X de los días ──────────────────────────────────────
            day_cols = [
                (w['text'], w['x0'])
                for w in words
                if w['text'] in DIA_NORM and w['top'] < 85
            ]
            day_order = sorted(day_cols, key=lambda x: x[1])
            if not day_order:
                continue
            col_bounds = _build_col_bounds(day_order)

            # ── Palabras de contenido (sin leyenda ni col. horas izq.) ────────
            cw = [w for w in words if 85 <= w['top'] <= 495 and w['x0'] > 35]

            # ── Marcadores de sesión "HH:MM–HH:MM" ───────────────────────────
            markers = []
            for w in cw:
                m = re.match(r'(\d{2}:\d{2})[–—\-]\d{2}:\d{2}$', w['text'])
                if m:
                    h = m.group(1)
                    fid = FRANJA_HORA_TO_ID.get(h)
                    if not fid:
                        continue
                    dia = _assign_col(w['x0'], col_bounds)
                    if dia:
                        markers.append({
                            'x0': w['x0'], 'top': w['top'],
                            'fid': fid, 'dia': dia,
                        })

            # ── Reasignar marcadores desbordados de columna adyacente ────────
            # En desdobles triples (o N) la última sub-celda puede sobrepasar
            # el límite de la columna y quedar asignada al día siguiente.
            # Si un marcador solitario en día_D está a ≤65 px del marcador más
            # a la derecha del grupo adyacente izquierdo (mismo fid, top ±2 px),
            # se reasigna al día izquierdo ANTES de construir marker_groups y de
            # calcular días vacíos.
            day_order_norm = [DIA_NORM.get(d, d) for d, _ in day_order]
            for _fid in list({mk['fid'] for mk in markers}):
                for _di in range(1, len(day_order_norm)):
                    _right_dia = day_order_norm[_di]
                    _left_dia  = day_order_norm[_di - 1]
                    _right_mks = [mk for mk in markers
                                  if mk['dia'] == _right_dia and mk['fid'] == _fid]
                    _left_mks  = [mk for mk in markers
                                  if mk['dia'] == _left_dia  and mk['fid'] == _fid]
                    if not _left_mks:
                        continue
                    for _rmk in list(_right_mks):
                        _same_top = [lmk for lmk in _left_mks
                                     if abs(lmk['top'] - _rmk['top']) <= 2]
                        if not _same_top:
                            continue
                        _nearest_x = max(lmk['x0'] for lmk in _same_top)
                        if _rmk['x0'] - _nearest_x <= 65:
                            _rmk['dia'] = _left_dia   # reasignar

            # Detectar días vacíos: aparecen en la cabecera pero sin sesiones
            dias_en_cabecera = {
                DIA_NORM.get(d, d)
                for d, _ in day_order
                if d not in ('Sábado', 'Domingo')
            }
            dias_con_sesion = {mk['dia'] for mk in markers}
            dias_vacios_pdf[sem_num] = dias_en_cabecera - dias_con_sesion

            # ── Calcular límites X por celda (manejo de desdobles) ───────────
            # Un desdoble es cuando hay ≥2 marcadores en el mismo día+franja.
            # En ese caso el PDF pone sub-celdas lado a lado dentro de la columna.
            # Calculamos límites xl/xr individuales para cada marcador.

            def _subcell_bounds(mk, group_markers, col_xl, col_xr):
                """
                Devuelve (xl, xr) para un marcador dentro de su grupo de desdoble.

                - Marcador único → usa los límites completos de la columna.
                - Desdoble (n≥2 marcadores):
                    · xl = límite izq. de col  (primer marcador) o
                           punto medio con el marcador anterior
                    · xr = (siguiente marcador x0) - 1  (si hay siguiente) o
                           col_xr + 50  (último: ampliar para capturar dígitos
                           de subgrupo que pueden caer ligeramente fuera)
                """
                if len(group_markers) == 1:
                    return col_xl, col_xr

                xs = sorted(m['x0'] for m in group_markers)
                i  = xs.index(mk['x0'])

                xl = col_xl if i == 0 else (xs[i - 1] + xs[i]) / 2
                xr = (xs[i + 1] - 1) if i < len(xs) - 1 else (col_xr + 50)
                return xl, xr

            # Agrupar marcadores por (dia, franja) — ya con reasignación aplicada
            from collections import defaultdict as _ddict
            marker_groups = _ddict(list)
            for mk in markers:
                marker_groups[(mk['dia'], mk['fid'])].append(mk)

            # ── Extraer celda para cada marcador ─────────────────────────────
            # Comportamiento base: detección de asig por sub-celda individual
            # (preserva desdobles heterogéneos donde cada sub-celda tiene su
            # propia asignatura).
            # Fallback de grupo: si la detección per-celda falla (texto
            # superpuesto en desdobles homogéneos como el triple desdoble de
            # la misma asignatura), se busca la asig en el rango completo del
            # grupo y se reutiliza para esa sub-celda.

            for mk in markers:
                mt, mx = mk['top'], mk['x0']

                # Columna del día
                col_info = next(
                    ((xl, xr) for d, xl, xr in col_bounds if d == mk['dia']),
                    None
                )
                if not col_info:
                    continue
                col_xl, col_xr = col_info

                # Límite vertical
                same_col_tops = [
                    m['top'] for m in markers
                    if abs(m['x0'] - mx) < 15 and m['top'] > mt
                ]
                if same_col_tops:
                    top_limit = min(same_col_tops) - 2
                else:
                    next_franja_tops = [
                        m['top'] for m in markers
                        if m['dia'] == mk['dia'] and m['fid'] > mk['fid']
                    ]
                    top_limit = (min(next_franja_tops) - 2
                                 if next_franja_tops else mt + 100)

                # Límites X ajustados por desdoble
                group = marker_groups[(mk['dia'], mk['fid'])]
                xl, xr = _subcell_bounds(mk, group, col_xl, col_xr)

                # Palabras de la sub-celda
                cell_ws = [
                    w for w in cw
                    if xl <= w['x0'] < xr and mt < w['top'] <= top_limit
                ]
                cell_text = ' '.join(w['text'] for w in cell_ws)

                # Detección de asig por sub-celda individual.
                asig = _detect_asig(cell_text, asig_tokens)

                if not asig and len(group) > 1:
                    # Fallback para desdobles HOMOGÉNEOS con texto superpuesto:
                    # en un triple desdoble de la misma asignatura, el nombre
                    # fusionado puede aparecer solo en la primera sub-celda;
                    # las restantes quedan sin nombre pero sí tienen contenido
                    # (tipo, subgrupo).  Aquí comprobamos qué asig detectan las
                    # otras sub-celdas del grupo y, solo si todas coinciden en
                    # la misma, la propagamos a esta sub-celda.
                    # De este modo NO se activa en desdobles heterogéneos
                    # (cada sub-celda con distinta asig), evitando los falsos
                    # positivos que producía el fallback anterior.
                    cell_tokens = cell_text.split()
                    has_content = (
                        'INF' in cell_tokens or 'LAB' in cell_tokens
                        or re.search(r'Subgrupo:', cell_text)
                    )
                    if has_content:
                        other_asigs = []
                        for other_mk in group:
                            if other_mk is mk:
                                continue
                            o_xl, o_xr = _subcell_bounds(
                                other_mk, group, col_xl, col_xr)
                            o_same = [m['top'] for m in markers
                                      if abs(m['x0'] - other_mk['x0']) < 15
                                      and m['top'] > other_mk['top']]
                            if o_same:
                                o_top = min(o_same) - 2
                            else:
                                o_nxt = [m['top'] for m in markers
                                         if m['dia'] == other_mk['dia']
                                         and m['fid'] > other_mk['fid']]
                                o_top = (min(o_nxt) - 2 if o_nxt
                                         else other_mk['top'] + 100)
                            o_ws = [w for w in cw
                                    if o_xl <= w['x0'] < o_xr
                                    and other_mk['top'] < w['top'] <= o_top]
                            o_text = ' '.join(w['text'] for w in o_ws)
                            o_asig = _detect_asig(o_text, asig_tokens)
                            if o_asig:
                                other_asigs.append(o_asig)
                        unique = set(other_asigs)
                        if len(unique) == 1:
                            asig = list(unique)[0]

                if not asig:
                    continue

                # Tipo (INF / LAB / vacío = teoría)
                tokens = cell_text.split()
                tipo = ''
                if 'INF' in tokens:
                    tipo = 'INF'
                elif 'LAB' in tokens:
                    tipo = 'LAB'

                # Subgrupo: buscar "Subgrupo: N" en el texto de la celda
                subgrupo = ''
                m_sg = re.search(r'Subgrupo:\s*(\d)', cell_text)
                if m_sg:
                    subgrupo = m_sg.group(1)
                elif 'Subgrupo:' in tokens:
                    idx = tokens.index('Subgrupo:')
                    if idx + 1 < len(tokens) and tokens[idx + 1].isdigit():
                        subgrupo = tokens[idx + 1]

                clases.append({
                    'sem_num':      sem_num,
                    'dia':          mk['dia'],
                    'franja_id':    mk['fid'],
                    'asignatura':   asig,
                    'tipo':         tipo,
                    'subgrupo':     subgrupo,
                    'fecha_inicio': fecha_inicio or '',
                })

    return clases, dias_vacios_pdf


def _get_db_clases(db_conn, grupo_id, sem_max=None):
    """
    Devuelve las clases de la BD para el grupo dado (sin EXP/EXF).
    """
    db_conn.row_factory = sqlite3.Row
    cur = db_conn.cursor()

    sql = """
        SELECT s.numero     AS sem_num,
               s.descripcion AS sem_desc,
               c.dia,
               f.orden      AS franja_id,
               f.label      AS franja_label,
               a.nombre     AS asignatura,
               a.codigo,
               COALESCE(c.tipo,'')     AS tipo,
               COALESCE(c.subgrupo,'') AS subgrupo
        FROM clases c
        JOIN semanas     s ON c.semana_id     = s.id
        JOIN franjas     f ON c.franja_id     = f.id
        LEFT JOIN asignaturas a ON c.asignatura_id = a.id
        WHERE s.grupo_id = ?
          AND (c.es_no_lectivo IS NULL OR c.es_no_lectivo = 0)
          AND a.nombre IS NOT NULL
          AND (c.tipo IS NULL OR c.tipo NOT IN ('EXP','EXF'))
    """
    params = [grupo_id]
    if sem_max is not None:
        sql += " AND s.numero <= ?"
        params.append(sem_max)

    rows = cur.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _get_asignaturas_grupo(db_conn, grupo_id):
    """Devuelve los nombres de asignaturas presentes en el grupo."""
    db_conn.row_factory = sqlite3.Row
    cur = db_conn.cursor()
    rows = cur.execute("""
        SELECT DISTINCT a.nombre
        FROM clases c
        JOIN semanas s     ON c.semana_id     = s.id
        JOIN asignaturas a ON c.asignatura_id = a.id
        WHERE s.grupo_id = ? AND a.nombre IS NOT NULL
    """, (grupo_id,)).fetchall()
    return [r['nombre'] for r in rows]


def _get_grupo_info(db_conn, grupo_id):
    """Devuelve info del grupo (curso, cuatrimestre, grupo, clave)."""
    db_conn.row_factory = sqlite3.Row
    row = db_conn.execute(
        "SELECT * FROM grupos WHERE id = ?", (grupo_id,)
    ).fetchone()
    return dict(row) if row else {}


def _get_semanas_grupo(db_conn, grupo_id):
    """Devuelve {numero: descripcion} para el grupo."""
    db_conn.row_factory = sqlite3.Row
    rows = db_conn.execute(
        "SELECT numero, descripcion FROM semanas WHERE grupo_id = ? ORDER BY numero",
        (grupo_id,)
    ).fetchall()
    return {r['numero']: r['descripcion'] for r in rows}


def verificar_pdf(pdf_path, grupo_id, db_conn):
    """
    Función principal. Parsea el PDF y lo compara con la BD.

    Retorna dict:
    {
        "grupo": {...},
        "stats": {
            "total_db": int, "total_pdf": int,
            "coincidencias": int, "solo_pdf": int, "solo_db": int,
            "tasa_pdf": float,   # % de clases PDF que coinciden
            "tasa_db":  float,   # % de clases BD que aparecen en PDF
        },
        "semanas": [
            {
                "numero": int, "descripcion": str, "fecha_inicio_pdf": str,
                "coincidencias": [...], "solo_pdf": [...], "solo_db": [...],
            },
            ...
        ],
        "discrepancias": [...]   # lista plana de todas las diferencias
    }
    """
    # 1. Metadatos del grupo
    grupo_info   = _get_grupo_info(db_conn, grupo_id)
    asignaturas  = _get_asignaturas_grupo(db_conn, grupo_id)
    semanas_desc = _get_semanas_grupo(db_conn, grupo_id)
    sem_max      = max(semanas_desc.keys()) if semanas_desc else 20

    # 2. Parsear PDF
    pdf_clases, dias_vacios_pdf = parse_pdf(pdf_path, asignaturas)

    # Descartar páginas PDF más allá del rango de semanas de la BD.
    # El PDF institucional puede tener páginas adicionales (ej. un segundo
    # cuatrimestre, páginas de reserva) que no corresponden a ninguna semana
    # definida; incluirlas generaría falsos positivos en solo_pdf.
    pdf_clases      = [c for c in pdf_clases      if c['sem_num'] <= sem_max]
    dias_vacios_pdf = {k: v for k, v in dias_vacios_pdf.items() if k <= sem_max}

    # 3. Clases de la BD (hasta sem_max para no comparar semanas vacías)
    db_clases = _get_db_clases(db_conn, grupo_id, sem_max)

    # 4. Construir conjuntos de tuplas clave
    def _key(c):
        return (c['sem_num'], c['dia'], c['franja_id'],
                c['asignatura'], c['tipo'], c['subgrupo'])

    pdf_set = set(_key(c) for c in pdf_clases)
    db_set  = set(_key(c) for c in db_clases)

    only_pdf = pdf_set - db_set
    only_db  = db_set  - pdf_set
    in_both  = pdf_set & db_set

    # 4b. Detectar días posiblemente no-lectivos:
    #     días que aparecen en la cabecera del PDF pero sin ninguna clase
    #     y que sin embargo tienen clases en la BD.
    posibles_no_lectivos = []
    nolectivo_keys = set()   # claves a excluir de only_db
    for sem_num, dias_vacios in dias_vacios_pdf.items():
        for dia in sorted(dias_vacios):
            clases_en_dia = [k for k in only_db if k[0] == sem_num and k[1] == dia]
            if clases_en_dia:
                posibles_no_lectivos.append({
                    'sem_num':     sem_num,
                    'dia':         dia,
                    'dia_abrev':   DIAS_ABREV.get(dia, dia),
                    'descripcion': semanas_desc.get(sem_num, f'Semana {sem_num}'),
                    'clases':      [_fmt_disc(k, 'solo_db') for k in sorted(clases_en_dia)],
                })
                nolectivo_keys.update(clases_en_dia)

    # Retirar de only_db las entradas ya clasificadas como posible no-lectivo
    only_db = only_db - nolectivo_keys

    # 5. Fecha inicio por semana (del PDF)
    fecha_por_sem = {}
    for c in pdf_clases:
        if c['fecha_inicio'] and c['sem_num'] not in fecha_por_sem:
            fecha_por_sem[c['sem_num']] = c['fecha_inicio']

    # 6. Construir resultado por semana
    semanas_result = []
    for num in sorted(semanas_desc.keys()):
        desc = semanas_desc[num]
        sem_pdf  = {k for k in pdf_set if k[0] == num}
        sem_db   = {k for k in db_set  if k[0] == num}
        sem_both = sem_pdf & sem_db

        def _fmt(k):
            return {
                'sem_num':    k[0],
                'dia':        k[1],
                'dia_abrev':  DIAS_ABREV.get(k[1], k[1]),
                'franja_id':  k[2],
                'franja':     FRANJA_ID_TO_LABEL.get(k[2], ''),
                'asignatura': k[3],
                'tipo':       k[4] or '—',
                'subgrupo':   k[5] or '—',
            }

        sem_only_db_real = (sem_db - sem_pdf) - nolectivo_keys
        semanas_result.append({
            'numero':           num,
            'descripcion':      desc,
            'fecha_inicio_pdf': fecha_por_sem.get(num, ''),
            'total_db':         len(sem_db),
            'total_pdf':        len(sem_pdf),
            'coincidencias':    [_fmt(k) for k in sorted(sem_both)],
            'solo_pdf':         [_fmt(k) for k in sorted(sem_pdf - sem_db)],
            'solo_db':          [_fmt(k) for k in sorted(sem_only_db_real)],
            'ok':               len(sem_pdf - sem_db) == 0 and len(sem_only_db_real) == 0,
        })

    total_db  = len(db_set)
    total_pdf = len(pdf_set)
    coincid   = len(in_both)

    discrepancias = []
    for k in sorted(only_pdf):
        d = _fmt_disc(k, 'solo_pdf')
        discrepancias.append(d)
    for k in sorted(only_db):
        d = _fmt_disc(k, 'solo_db')
        discrepancias.append(d)
    discrepancias.sort(key=lambda d: (d['sem_num'], d['dia'], d['franja_id']))

    return {
        'grupo': grupo_info,
        'stats': {
            'total_db':     total_db,
            'total_pdf':    total_pdf,
            'coincidencias': coincid,
            'solo_pdf':     len(only_pdf),
            'solo_db':      len(only_db),
            'tasa_pdf':     round(100 * coincid / max(total_pdf, 1), 1),
            'tasa_db':      round(100 * coincid / max(total_db,  1), 1),
        },
        'semanas':              semanas_result,
        'discrepancias':        discrepancias,
        'posibles_no_lectivos': posibles_no_lectivos,
    }


def _fmt_disc(k, origen):
    return {
        'sem_num':    k[0],
        'dia':        k[1],
        'dia_abrev':  DIAS_ABREV.get(k[1], k[1]),
        'franja_id':  k[2],
        'franja':     FRANJA_ID_TO_LABEL.get(k[2], ''),
        'asignatura': k[3],
        'tipo':       k[4] or '—',
        'subgrupo':   k[5] or '—',
        'origen':     origen,   # 'solo_pdf' | 'solo_db'
    }


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    if len(sys.argv) < 4:
        print("Uso: python3 tools/verificar_pdf.py <pdf_path> <grupo_id> <db_path>")
        sys.exit(1)

    pdf_path  = sys.argv[1]
    grupo_id  = int(sys.argv[2])
    db_path   = sys.argv[3]

    conn = sqlite3.connect(db_path)
    resultado = verificar_pdf(pdf_path, grupo_id, conn)
    conn.close()

    s = resultado['stats']
    g = resultado['grupo']
    print(f"\n{'='*65}")
    print(f"  Verificación PDF — Curso {g.get('curso','?')} · {g.get('cuatrimestre','?')} · Grupo {g.get('grupo','?')}")
    print(f"{'='*65}")
    print(f"  Clases en BD              : {s['total_db']}")
    print(f"  Clases detectadas en PDF  : {s['total_pdf']}")
    print(f"  Coincidencias exactas     : {s['coincidencias']}")
    print(f"  Solo en PDF               : {s['solo_pdf']}")
    print(f"  Solo en BD                : {s['solo_db']}")
    print(f"  Cobertura BD→PDF          : {s['tasa_db']}%")
    print(f"{'='*65}")

    if resultado['discrepancias']:
        print("\nDISCREPANCIAS:")
        for d in resultado['discrepancias']:
            origen_txt = '⚠ Solo en PDF' if d['origen'] == 'solo_pdf' else '⚠ Solo en BD '
            print(f"  Sem{d['sem_num']:02d} {d['dia_abrev']} {d['franja']:13} | "
                  f"{d['asignatura']:<25} tipo={d['tipo']:3} subg={d['subgrupo']} | {origen_txt}")
    else:
        print("\n✅ Sin discrepancias detectadas.")
