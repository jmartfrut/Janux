"""
exportar_finales_pdf.py — Genera el PDF de exámenes finales en el formato oficial GIM-UPCT.

Estructura del PDF (igual que el original Feb-26):
  - Página 1 (portrait A4): tabla con Código | Asignatura | Curso | Turno | Fecha | Aulas
  - Página 2 (landscape A4): calendario semanal (Lun-Sáb × semanas × cursos)

Uso:
    from exportar_finales_pdf import generar_pdf_finales
    pdf_bytes = generar_pdf_finales(exams, periodo_label, curso_label, periodo_key)
"""

# ── Compatibilidad con OpenSSL antiguo (macOS + Python < 3.11 sin soporte FIPS) ──
# reportlab llama hashlib.md5(usedforsecurity=False) que falla en ciertos builds.
import hashlib as _hl
try:
    _hl.md5(usedforsecurity=False)
except TypeError:
    _orig_md5 = _hl.md5
    def _safe_md5(*args, **kwargs):
        kwargs.pop('usedforsecurity', None)
        return _orig_md5(*args, **kwargs)
    _hl.md5 = _safe_md5

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame,
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
    NextPageTemplate,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus.flowables import Flowable
from datetime import date, timedelta
import io, os as _os, subprocess as _sp

# ── Logo UPCT/GIM ─────────────────────────────────────────────────────────────
_SCRIPT_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # raíz del proyecto
_LOGO_PDF   = _os.path.join(_SCRIPT_DIR, 'docs', 'logo.pdf')
_LOGO_PNG   = _os.path.join(_SCRIPT_DIR, 'docs', 'logo_upct.png')
_LOGO_RATIO = 1528.08 / 181.707   # ancho:alto del PDF original

def _ensure_logo():
    """Convierte logo.pdf → logo_upct.png (una sola vez) usando pdftoppm."""
    if _os.path.exists(_LOGO_PNG):
        return True
    if not _os.path.exists(_LOGO_PDF):
        return False
    try:
        prefix = _LOGO_PNG[:-4]   # sin .png
        _sp.run(['pdftoppm', '-r', '150', '-png', '-singlefile', _LOGO_PDF, prefix],
                capture_output=True, timeout=15)
        return _os.path.exists(_LOGO_PNG)
    except Exception:
        return False

_LOGO_OK = _ensure_logo()

# ── Paleta de colores (del PDF original) ────────────────────────────────────
C_TITLE_BG   = colors.HexColor('#1e3a5f')   # azul marino encabezado
C_TITLE_FG   = colors.white
C_HEAD_BG    = colors.HexColor('#2d5faa')   # azul medio columnas
C_HEAD_FG    = colors.white
C_ROW_ALT    = colors.HexColor('#eef3fb')   # fila alternada
C_ROW_NORM   = colors.white
C_BORDER     = colors.HexColor('#9bb3d4')
C_WEEK_BG    = colors.HexColor('#d6e4f7')   # fondo semana/fecha
C_WEEK_FG    = colors.HexColor('#1e3a5f')
C_COURSE_BG  = colors.HexColor('#e8f0fb')   # fondo columna curso
C_EXAM_BG    = colors.white
C_EXAM_M     = colors.HexColor('#1e40af')   # azul mañana
C_EXAM_T     = colors.HexColor('#7c3aed')   # morado tarde
C_SIDE_BG    = colors.HexColor('#1e3a5f')   # lateral rotado
C_EMPTY      = colors.HexColor('#f8fafd')

DIAS_ES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']
MESES   = ['', 'ene.', 'feb.', 'mar.', 'abr.', 'may.', 'jun.',
           'jul.', 'ago.', 'sep.', 'oct.', 'nov.', 'dic.']


def _iso_to_date(iso_str):
    y, m, d = map(int, iso_str.split('-'))
    return date(y, m, d)


def _fmt_date_short(d):
    """Formato '8-ene.' para una fecha."""
    return f"{d.day}-{MESES[d.month]}"


def _get_weeks(start_iso, end_iso):
    """Devuelve lista de semanas (cada semana = lista de 6 fechas Lun-Sáb)."""
    start = _iso_to_date(start_iso)
    end   = _iso_to_date(end_iso)
    # Primer lunes de la semana que contiene start
    dow = start.weekday()  # 0=Lun
    ws  = start - timedelta(days=dow)
    weeks = []
    while ws <= end:
        week = [ws + timedelta(days=i) for i in range(6)]
        if any(start <= d <= end for d in week):
            weeks.append(week)
        ws += timedelta(days=7)
    return weeks


def _build_exam_index(exams):
    """Devuelve dict[iso][curso] = (asig_nombre, turno)."""
    idx = {}
    for e in exams:
        iso  = e['fecha']
        c    = str(e['curso'])
        nom  = e.get('asig_nombre', '')
        turno = e.get('turno', 'mañana')
        if iso not in idx:
            idx[iso] = {}
        idx[iso][c] = (nom, turno)
    return idx


# ── Flowable para texto vertical (rotado 90°) ───────────────────────────────
class VerticalText(Flowable):
    """Dibuja texto rotado -90° (de abajo a arriba) centrado en su caja."""
    def __init__(self, text, width, height, font='Helvetica-Bold',
                 fontsize=8, fg=colors.white, bg=None):
        self._text = text
        self._w = width
        self._h = height
        self._font = font
        self._fs = fontsize
        self._fg = fg
        self._bg = bg
        Flowable.__init__(self)

    def wrap(self, *args):
        return self._w, self._h

    def draw(self):
        c = self.canv
        if self._bg:
            c.setFillColor(self._bg)
            c.rect(0, 0, self._w, self._h, fill=1, stroke=0)
        c.saveState()
        c.setFillColor(self._fg)
        c.setFont(self._font, self._fs)
        c.translate(self._w / 2, self._h / 2)
        c.rotate(90)
        c.drawCentredString(0, -self._fs * 0.35, self._text)
        c.restoreState()


# ── Página 1: tabla lista ────────────────────────────────────────────────────
def _portrait_table(exams, titulo, subtitulo):
    """Construye los elementos de la página portrait (lista de exámenes)."""
    styles = getSampleStyleSheet()

    sTitle = ParagraphStyle('sTitle', parent=styles['Normal'],
                            fontSize=13, fontName='Helvetica-Bold',
                            textColor=C_TITLE_FG, alignment=1,
                            spaceAfter=0)
    sSub   = ParagraphStyle('sSub', parent=styles['Normal'],
                            fontSize=13, fontName='Helvetica-Bold',
                            textColor=C_TITLE_FG, alignment=1)
    sHead  = ParagraphStyle('sHead', parent=styles['Normal'],
                            fontSize=8.5, fontName='Helvetica-Bold',
                            textColor=C_HEAD_FG, alignment=1)
    sCell  = ParagraphStyle('sCell', parent=styles['Normal'],
                            fontSize=7.5, fontName='Helvetica',
                            alignment=0, leading=10)
    sCellC = ParagraphStyle('sCellC', parent=sCell, alignment=1)
    sCellM = ParagraphStyle('sCellM', parent=sCell,
                            textColor=C_EXAM_M, alignment=1)
    sCellT = ParagraphStyle('sCellT', parent=sCell,
                            textColor=C_EXAM_T, alignment=1)

    # Cabecera institucional con logo
    from reportlab.platypus import Image as _RLImage
    TOTAL_W = 170*mm

    if _LOGO_OK:
        logo_h_pt  = 14*mm                           # altura logo en cabecera
        logo_w_pt  = min(logo_h_pt * _LOGO_RATIO, 95*mm)
        logo_h_pt  = logo_w_pt / _LOGO_RATIO
        logo_cell  = _RLImage(_LOGO_PNG, width=logo_w_pt, height=logo_h_pt)
        title_w    = TOTAL_W - logo_w_pt - 4*mm
        header_table = Table([[Paragraph(titulo, sTitle), logo_cell]],
                              colWidths=[title_w, logo_w_pt + 4*mm])
        header_table.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), C_TITLE_BG),
            ('TOPPADDING',    (0,0), (-1,-1), 7),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING',   (0,0), (0,-1),  10),
            ('LEFTPADDING',   (1,0), (1,-1),  4),
            ('RIGHTPADDING',  (1,0), (1,-1),  8),
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN',         (1,0), (1,-1),  'RIGHT'),
        ]))
    else:
        header_table = Table([[Paragraph(titulo, sTitle)]], colWidths=[TOTAL_W])
        header_table.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), C_TITLE_BG),
            ('TOPPADDING',    (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('LEFTPADDING',   (0,0), (-1,-1), 10),
        ]))

    sub_table = Table([[Paragraph(subtitulo, sSub)]], colWidths=[TOTAL_W])
    sub_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), C_TITLE_BG),
        ('TOPPADDING',    (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING',   (0,0), (-1,-1), 10),
    ]))

    # Ordenar exámenes: por curso, luego fecha
    def sort_key(e):
        return (str(e.get('curso', '9')), e['fecha'])
    sorted_exams = sorted(exams, key=sort_key)

    # Detectar si los exámenes incluyen información de grupo (parciales)
    has_grupo = any(e.get('grupo') for e in sorted_exams)

    # Columnas: Código | Asignatura | Curso | Turno | Fecha | [Grupo] | Aulas/Obs
    if has_grupo:
        # 7 columnas: redistribuir 170mm incluyendo Grupo (16mm); Asignatura reducida
        col_w = [22*mm, 69*mm, 13*mm, 13*mm, 18*mm, 16*mm, 19*mm]
        head_row = [
            Paragraph('Código',      sHead),
            Paragraph('Asignatura',  sHead),
            Paragraph('Curso',       sHead),
            Paragraph('Turno',       sHead),
            Paragraph('Fecha',       sHead),
            Paragraph('Grupo',       sHead),
            Paragraph('Observación', sHead),
        ]
    else:
        col_w = [22*mm, 85*mm, 13*mm, 13*mm, 20*mm, 17*mm]
        head_row = [
            Paragraph('Código',      sHead),
            Paragraph('Asignatura',  sHead),
            Paragraph('Curso',       sHead),
            Paragraph('Turno',       sHead),
            Paragraph('Fecha',       sHead),
            Paragraph('Aulas',       sHead),
        ]
    rows = [head_row]
    course_change_rows = []   # índices de fila (en la tabla) donde cambia el curso
    prev_curso = None
    for i, e in enumerate(sorted_exams):
        fecha_d = _iso_to_date(e['fecha'])
        turno   = e.get('turno', 'mañana')
        turno_s = 'M' if turno == 'mañana' else 'T'
        sT = sCellM if turno == 'mañana' else sCellT
        curso = str(e.get('curso', ''))
        # Fila 0 = cabecera, fila i+1 = dato i
        if prev_curso is not None and curso != prev_curso:
            course_change_rows.append(i + 1)   # primera fila del nuevo curso
        prev_curso = curso
        if has_grupo:
            rows.append([
                Paragraph(str(e.get('asig_codigo', '')), sCellC),
                Paragraph(str(e.get('asig_nombre', '')), sCell),
                Paragraph(curso,                          sCellC),
                Paragraph(turno_s,                        sT),
                Paragraph(_fmt_date_short(fecha_d),       sCellC),
                Paragraph(str(e.get('grupo', '')),        sCellC),
                Paragraph(str(e.get('observacion', '')),  sCellC),
            ])
        else:
            rows.append([
                Paragraph(str(e.get('asig_codigo', '')), sCellC),
                Paragraph(str(e.get('asig_nombre', '')), sCell),
                Paragraph(curso,                          sCellC),
                Paragraph(turno_s,                        sT),
                Paragraph(_fmt_date_short(fecha_d),       sCellC),
                Paragraph(str(e.get('observacion', '')),  sCellC),
            ])

    data_table = Table(rows, colWidths=col_w, repeatRows=1)
    ts = [
        ('BACKGROUND',    (0,0), (-1,0),  C_HEAD_BG),
        ('TEXTCOLOR',     (0,0), (-1,0),  C_HEAD_FG),
        ('GRID',          (0,0), (-1,-1), 0.4, C_BORDER),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [C_ROW_NORM, C_ROW_ALT]),
        ('TOPPADDING',    (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING',   (0,0), (-1,-1), 4),
        ('RIGHTPADDING',  (0,0), (-1,-1), 4),
        ('FONTNAME',      (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE',      (0,1), (-1,-1), 7.5),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
    ]
    # Línea gruesa (2 pt, azul marino) encima de cada fila que inicia un nuevo curso
    for r in course_change_rows:
        ts.append(('LINEABOVE', (0, r), (-1, r), 2.0, C_TITLE_BG))
    data_table.setStyle(TableStyle(ts))

    return [header_table, sub_table, Spacer(1, 6*mm), data_table]


# ── Callback portrait (sin logo: ya está embebido en el header del story) ────
def _on_portrait_page(canv, doc):
    pass   # logo incluido directamente en header_table de _portrait_table


# ── Página 2: calendario landscape ──────────────────────────────────────────
def _landscape_calendar_canvas(c, exam_idx, weeks, titulo_lateral, page_w, page_h,
                                start_date=None, end_date=None):
    """
    Dibuja directamente en el canvas el calendario landscape.
    Layout (igual al PDF original):
      [lateral rotado | semana | curso | Lun | Mar | Mié | Jue | Vie | Sáb]
    start_date / end_date: date objects; días fuera de este rango se muestran en gris.
    """
    C_OUT_OF_PERIOD = colors.HexColor('#e8e8e8')  # gris para días fuera del período
    M = 8   # margen exterior (pt)
    LW = 18 # ancho columna lateral rotada
    SW = 18 # ancho columna semana
    CW = 14 # ancho columna curso
    # Ancho disponible para los 6 días
    avail_w = page_w - 2*M - LW - SW - CW
    DW = avail_w / 6  # ancho de cada día

    CURSOS = ['1', '2', '3', '4']
    N_WEEKS = len(weeks)
    DAY_H = 14  # altura fila de fechas
    COURSE_H = 14  # altura fila de curso

    LEGEND_H = 16   # pt reservados para leyenda en la parte inferior
    LEGEND_GAP = 4  # pt entre calendario y leyenda

    x0 = M  # start x (necesario antes del logo)

    # Logo grande y centrado sobre el calendario
    content_x  = x0 + LW          # inicio del área de contenido (tras lateral)
    content_w  = page_w - M - content_x   # ancho del área de contenido
    logo_reserve = 0
    if _LOGO_OK:
        lw_logo = content_w * 0.55                    # 55% del ancho de contenido
        lh_logo = lw_logo / _LOGO_RATIO
        logo_x  = content_x + (content_w - lw_logo) / 2   # centrado
        logo_y  = page_h - M - lh_logo
        c.drawImage(_LOGO_PNG, logo_x, logo_y, lw_logo, lh_logo,
                    preserveAspectRatio=True, mask='auto')
        logo_reserve = lh_logo + 4   # espacio que el logo ocupa (+ gap)

    # Altura total disponible (respetando logo arriba y leyenda abajo)
    avail_h = page_h - 2*M - logo_reserve - LEGEND_H - LEGEND_GAP
    # Filas: 1 header días + N_WEEKS * (1 fecha + 4 cursos)
    n_data_rows = N_WEEKS * (1 + len(CURSOS))
    total_rows = 1 + n_data_rows
    row_h = avail_h / total_rows

    # Ajustar para que sea razonable
    row_h = min(row_h, 22)
    total_h_needed = total_rows * row_h
    # Situar el calendario justo debajo del logo (o del margen superior)
    y_top = page_h - M - logo_reserve
    # Si hay espacio sobrante, centrar dentro del área disponible
    spare = avail_h - total_h_needed
    if spare > 0:
        y_top -= spare / 2

    # ── Dibujar fondo del lateral ──
    c.setFillColor(C_SIDE_BG)
    c.rect(x0, M + LEGEND_H + LEGEND_GAP, LW, y_top - M - LEGEND_H - LEGEND_GAP,
           fill=1, stroke=0)

    # Texto lateral rotado
    c.saveState()
    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 7)
    lateral_mid = (M + LEGEND_H + LEGEND_GAP + y_top) / 2
    c.translate(x0 + LW/2, lateral_mid)
    c.rotate(90)
    c.drawCentredString(0, -2.5, titulo_lateral)
    c.restoreState()

    # ── Header de días (Lunes...Sábado) ──
    y = y_top
    header_h = row_h * 1.1

    # Fondo header
    c.setFillColor(C_TITLE_BG)
    c.rect(x0 + LW, y - header_h, page_w - 2*M - LW, header_h, fill=1, stroke=0)

    # Celdas de días
    c.setFillColor(C_TITLE_FG)
    c.setFont('Helvetica-Bold', 7.5)
    for di, nombre in enumerate(DIAS_ES):
        dx = x0 + LW + SW + CW + di * DW
        c.drawCentredString(dx + DW/2, y - header_h + 4, nombre)

    # Bordes header
    c.setStrokeColor(C_BORDER)
    c.setLineWidth(0.4)
    c.rect(x0 + LW, y - header_h, page_w - 2*M - LW, header_h, fill=0, stroke=1)

    y -= header_h

    EXAM_FS = 7.0  # tamaño de fuente para nombres de examen

    # ── Semanas ──
    for wi, week in enumerate(weeks):
        # Fila de fechas (sin texto en la columna SW — irá el SEMANA X rotado abajo)
        fecha_h = row_h
        c.setFillColor(C_WEEK_BG)
        # Fondo fila de fechas: solo a partir de SW+CW (el SW se pintará después con SEMANA)
        c.rect(x0 + LW + SW, y - fecha_h, page_w - 2*M - LW - SW, fecha_h, fill=1, stroke=0)

        # Fechas en cada día (gris si está fuera del período)
        c.setFont('Helvetica-Bold', 6.5)
        for di, day in enumerate(week):
            in_period = (start_date is None or day >= start_date) and \
                        (end_date   is None or day <= end_date)
            dx = x0 + LW + SW + CW + di * DW
            if not in_period:
                c.setFillColor(C_OUT_OF_PERIOD)
                c.rect(dx, y - fecha_h, DW, fecha_h, fill=1, stroke=0)
            c.setFillColor(C_WEEK_FG if in_period else colors.HexColor('#aaaaaa'))
            c.drawCentredString(dx + DW/2, y - fecha_h/2 - 2.5, _fmt_date_short(day))

        c.setStrokeColor(C_BORDER)
        c.rect(x0 + LW + SW, y - fecha_h, page_w - 2*M - LW - SW, fecha_h, fill=0, stroke=1)
        y -= fecha_h

        y_courses_top = y  # tope del bloque de filas de curso (para pintar SEMANA después)

        # Filas de cursos
        for ci, curso in enumerate(CURSOS):
            course_h = row_h
            bg = C_ROW_ALT if ci % 2 == 0 else C_ROW_NORM
            # Fondo fila (sin columna SW)
            c.setFillColor(bg)
            c.rect(x0 + LW + SW, y - course_h, page_w - 2*M - LW - SW, course_h,
                   fill=1, stroke=0)

            # Cubrir con gris los días fuera del período en esta fila de curso
            for di, day in enumerate(week):
                in_period = (start_date is None or day >= start_date) and \
                            (end_date   is None or day <= end_date)
                if not in_period:
                    dx = x0 + LW + SW + CW + di * DW
                    c.setFillColor(C_OUT_OF_PERIOD)
                    c.rect(dx, y - course_h, DW, course_h, fill=1, stroke=0)

            # Fondo columna curso
            c.setFillColor(C_COURSE_BG)
            c.rect(x0 + LW + SW, y - course_h, CW, course_h, fill=1, stroke=0)

            # Texto curso (centrado vertical)
            c.setFillColor(C_TITLE_BG)
            c.setFont('Helvetica-Bold', 7)
            c.drawCentredString(x0 + LW + SW + CW/2, y - course_h/2 - 2.5, f'{curso}º')

            # Exámenes de cada día (solo en días dentro del período)
            for di, day in enumerate(week):
                in_period = (start_date is None or day >= start_date) and \
                            (end_date   is None or day <= end_date)
                iso_str = day.strftime('%Y-%m-%d')
                cell_info = exam_idx.get(iso_str, {}).get(curso)
                if cell_info and in_period:
                    nom, turno = cell_info
                    dx = x0 + LW + SW + CW + di * DW
                    fg = C_EXAM_M if turno == 'mañana' else C_EXAM_T

                    # Partir en líneas ajustándose al ancho de la celda
                    max_w = DW - 4
                    c.setFont('Helvetica', EXAM_FS)
                    words = nom.split()
                    lines = []
                    cur = ''
                    for w in words:
                        test = (cur + ' ' + w).strip()
                        if c.stringWidth(test, 'Helvetica', EXAM_FS) < max_w:
                            cur = test
                        else:
                            if cur: lines.append(cur)
                            cur = w
                    if cur: lines.append(cur)
                    lines = lines[:2]

                    c.setFillColor(fg)
                    line_gap = EXAM_FS * 1.2
                    if len(lines) == 1:
                        c.drawCentredString(dx + DW/2, y - course_h/2 - EXAM_FS*0.35, lines[0])
                    else:
                        c.drawCentredString(dx + DW/2, y - course_h/2 + line_gap*0.4, lines[0])
                        c.drawCentredString(dx + DW/2, y - course_h/2 - line_gap*0.8, lines[1])

            # Bordes fila curso (sin SW)
            c.setStrokeColor(C_BORDER)
            c.setLineWidth(0.3)
            c.rect(x0 + LW + SW, y - course_h, page_w - 2*M - LW - SW,
                   course_h, fill=0, stroke=1)
            for di in range(1, 7):
                lx = x0 + LW + SW + CW + di * DW
                c.line(lx, y - course_h, lx, y)

            y -= course_h

        # ── "SEMANA X" rotado en la columna SW, abarcando las 4 filas de curso ──
        week_span_h = y_courses_top - y
        c.setFillColor(C_WEEK_BG)
        c.rect(x0 + LW, y, SW, week_span_h + fecha_h, fill=1, stroke=0)  # también fila fechas
        c.saveState()
        c.setFillColor(C_WEEK_FG)
        c.setFont('Helvetica-Bold', 7)
        c.translate(x0 + LW + SW/2, y + week_span_h/2)
        c.rotate(90)
        c.drawCentredString(0, -2.5, f'SEMANA {wi + 1}')
        c.restoreState()
        # Borde del bloque SW (fechas + cursos)
        c.setStrokeColor(C_BORDER)
        c.setLineWidth(0.4)
        c.rect(x0 + LW, y, SW, week_span_h + fecha_h, fill=0, stroke=1)

    # Borde exterior del lateral (hasta el fondo del calendario)
    c.setStrokeColor(C_BORDER)
    c.setLineWidth(0.8)
    c.rect(x0, y, LW, y_top - y, fill=0, stroke=1)

    # Borde exterior general
    c.rect(x0, y, page_w - 2*M - x0 + M, y_top - y, fill=0, stroke=1)

    # ── Leyenda de colores debajo del calendario ─────────────────────────────
    LEG_FS  = 8.0                             # tamaño de fuente leyenda
    sw_s    = LEG_FS + 2                      # cuadrito de color (pt)
    leg_y   = y - LEGEND_GAP - (LEGEND_H - LEG_FS) / 2 - 1   # línea de base

    def _leg_entry(cx, color, letter, label):
        """Dibuja un bloque de leyenda y devuelve la x final."""
        # Cuadrito de color
        c.setFillColor(color)
        c.rect(cx, leg_y - 1, sw_s, sw_s, fill=1, stroke=0)
        cx += sw_s + 4
        # Letra en negrita
        c.setFillColor(C_WEEK_FG)
        c.setFont('Helvetica-Bold', LEG_FS)
        c.drawString(cx, leg_y, letter)
        cx += c.stringWidth(letter, 'Helvetica-Bold', LEG_FS) + 3
        # Texto normal
        c.setFont('Helvetica', LEG_FS)
        c.drawString(cx, leg_y, label)
        cx += c.stringWidth(label, 'Helvetica', LEG_FS)
        return cx

    x_leg = content_x + 4    # alineado con el inicio del área de contenido
    x_leg = _leg_entry(x_leg, C_EXAM_M, 'M', ' — Examen de mañana')
    x_leg += 18               # separación entre bloques
    _leg_entry(x_leg, C_EXAM_T, 'T', ' — Examen de tarde')


# ── Función principal ────────────────────────────────────────────────────────
def generar_pdf_finales(exams, periodo_label_plain, curso_label, start_iso, end_iso):
    """
    exams            : lista de dicts (fecha, asig_nombre, asig_codigo, curso, turno, observacion)
    periodo_label_plain : str, ej. 'Enero - 1er Cuatrimestre'
    curso_label      : str, ej. '2025-2026'
    start_iso / end_iso: rango del período

    Genera 2 páginas (portrait lista + landscape calendario) para UN período.
    Para un PDF con los 3 períodos usa generar_pdf_finales_all().
    """
    return generar_pdf_finales_all(
        [{'label': periodo_label_plain, 'start': start_iso,
          'end': end_iso, 'exams': exams}],
        curso_label,
    )


def generar_pdf_finales_all(periods_data, curso_label, degree_name="Grado en Ingeniería Mecánica", degree_acronym="GIM"):
    """
    periods_data : lista de dicts con claves:
        label  — str, ej. 'Enero - 1er Cuatrimestre'
        start  — str ISO, inicio del período
        end    — str ISO, fin del período
        exams  — lista de dicts de exámenes
    curso_label  : str, ej. '2025-2026'

    Genera un PDF con 2 páginas por período (portrait + landscape),
    todo en un único canvas sin dependencias externas.
    """
    subtitulo = degree_name
    pw_l, ph_l = landscape(A4)
    pw_p, ph_p = A4
    buf = io.BytesIO()

    # ── PageTemplates reutilizables ──
    portrait_frame = Frame(
        15*mm, 10*mm, pw_p - 30*mm, ph_p - 20*mm,
        id='portrait', leftPadding=0, bottomPadding=0,
        rightPadding=0, topPadding=0,
    )
    landscape_frame = Frame(
        0, 0, pw_l, ph_l,
        id='landscape', leftPadding=0, bottomPadding=0,
        rightPadding=0, topPadding=0,
    )
    portrait_tpl  = PageTemplate(id='portrait',  frames=[portrait_frame],
                                  pagesize=A4, onPage=_on_portrait_page)
    landscape_tpl = PageTemplate(id='landscape', frames=[landscape_frame],
                                  pagesize=landscape(A4))

    first_titulo = (f"Fechas Exámenes Finales - {periods_data[0]['label']} "
                    f"- Curso {curso_label}") if periods_data else "Exámenes Finales"
    doc = BaseDocTemplate(
        buf,
        pageTemplates=[portrait_tpl, landscape_tpl],
        title=first_titulo,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=10*mm,  bottomMargin=10*mm,
    )

    def _make_landscape_flowable(ei, wk, lt, sd, ed):
        """Cierra sobre exam_idx, weeks, lat_title y fechas límite del período concreto."""
        class _Cal(Flowable):
            def wrap(self, aw, ah): return aw, ah
            def draw(self):
                _landscape_calendar_canvas(self.canv, ei, wk, lt, pw_l, ph_l,
                                           start_date=sd, end_date=ed)
        return _Cal()

    story = []
    for i, p in enumerate(periods_data):
        titulo    = f"Fechas Exámenes Finales - {p['label']} - Curso {curso_label}"
        lat_title = f"EXÁMENES FINALES - {p['label'].upper()} - {degree_acronym} - {curso_label}"
        exam_idx  = _build_exam_index(p['exams'])
        weeks     = _get_weeks(p['start'], p['end'])
        sd        = _iso_to_date(p['start'])
        ed        = _iso_to_date(p['end'])

        if i > 0:
            story.append(NextPageTemplate('portrait'))
            story.append(PageBreak())
        story += _portrait_table(p['exams'], titulo, subtitulo)
        story.append(NextPageTemplate('landscape'))
        story.append(PageBreak())
        story.append(_make_landscape_flowable(exam_idx, weeks, lat_title, sd, ed))

    doc.build(story)
    return buf.getvalue()


# ── CLI para testing ─────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sqlite3, sys, os

    db_path = os.environ.get('DB_PATH_OVERRIDE') or os.path.join(
        os.path.dirname(os.path.dirname(__file__)), 'horarios.db')
    periodo = sys.argv[1] if len(sys.argv) > 1 else '1'
    curso_label = os.environ.get('CURSO_LABEL', '2025-2026')

    yEnd = int(curso_label.split('-')[1]) if '-' in curso_label else 2026
    PERIODS = {
        '1': ('Enero — 1er Cuatrimestre',   f'{yEnd}-01-07', f'{yEnd}-01-31'),
        '2': ('Junio — 2º Cuatrimestre',    f'{yEnd}-05-31', f'{yEnd}-06-22'),
        '3': ('Extraordinaria (Jun-Jul)',    f'{yEnd}-06-24', f'{yEnd}-07-17'),
    }
    label, start, end = PERIODS.get(periodo, PERIODS['1'])

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM examenes_finales WHERE fecha >= ? AND fecha <= ? ORDER BY fecha, curso",
        (start, end)
    ).fetchall()
    conn.close()
    exams = [dict(r) for r in rows]

    print(f"Generando PDF: {len(exams)} exámenes del período '{label}'")
    pdf_bytes = generar_pdf_finales(exams, label, curso_label, start, end)

    import tempfile, pathlib
    out = str(pathlib.Path(tempfile.gettempdir()) / f'finales_test_{periodo}.pdf')
    with open(out, 'wb') as f:
        f.write(pdf_bytes)
    print(f"PDF guardado en {out} ({len(pdf_bytes)//1024} KB)")
