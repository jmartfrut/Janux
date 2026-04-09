#!/usr/bin/env python3
"""
nuevo_dtie.py — Wizard para crear un grado DTIE combinando asignaturas destacadas
                (marcadas con ⭐) de dos grados de origen existentes.

Uso:
    python3 nuevo_dtie.py
    → Abre http://localhost:8092 con el asistente completo.

Genera horarios/<SIGLAS>/ con config.json, horarios.db y launchers.
Las clases se copian semana a semana de las BDs de origen.
"""

import io
import json
import sqlite3
import subprocess
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Forzar UTF-8 en stdout/stderr para evitar errores con emojis en Windows (cp1252)
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

PORT     = 8092
BASE_DIR = Path(__file__).parent.parent  # raíz del proyecto (tools/../)

# ─────────────────────────────────────────────────────────────────────────────
# HTML WIZARD
# ─────────────────────────────────────────────────────────────────────────────

WIZARD_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nuevo Doble Grado — Gestor de Horarios</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#f0f4f8;color:#1a2a3a;min-height:100vh}
.top-bar{background:#6b1a3a;color:#fff;padding:14px 32px;display:flex;align-items:center;gap:12px}
.top-bar h1{font-size:1.15rem;font-weight:600;letter-spacing:.3px}
.top-bar .sub{font-size:.82rem;opacity:.7;margin-top:1px}
.stepper{display:flex;align-items:center;justify-content:center;gap:0;padding:20px 24px 0;flex-wrap:wrap;row-gap:8px}
.step{display:flex;align-items:center;gap:0}
.step-circle{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:.78rem;font-weight:700;border:2px solid #c8d4e0;background:#fff;color:#8a9ab0;transition:all .2s;flex-shrink:0}
.step-label{font-size:.72rem;color:#8a9ab0;margin:0 6px;white-space:nowrap;transition:color .2s}
.step-line{width:28px;height:2px;background:#c8d4e0;transition:background .2s;flex-shrink:0}
.step.active .step-circle{background:#6b1a3a;border-color:#6b1a3a;color:#fff}
.step.active .step-label{color:#6b1a3a;font-weight:600}
.step.done .step-circle{background:#22863a;border-color:#22863a;color:#fff}
.step.done .step-label{color:#22863a}
.step.done + .step-line,.step.active + .step-line{background:#6b1a3a}
.card{background:#fff;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.07);max-width:900px;margin:20px auto 40px;padding:32px 36px}
.card h2{font-size:1.1rem;font-weight:700;color:#6b1a3a;margin-bottom:6px}
.card .desc{font-size:.83rem;color:#6a7a8a;margin-bottom:24px}
.field{margin-bottom:18px}
.field label{display:block;font-size:.8rem;font-weight:600;color:#3a4a5a;margin-bottom:5px;text-transform:uppercase;letter-spacing:.4px}
.field input[type=text],.field input[type=number],.field select{width:100%;padding:8px 11px;border:1px solid #c8d4e0;border-radius:7px;font-size:.9rem;background:#fff;color:#1a2a3a;transition:border .15s}
.field input[type=color]{padding:4px;height:38px;cursor:pointer;width:100%;border:1px solid #c8d4e0;border-radius:7px}
.field input:focus,.field select:focus{outline:none;border-color:#6b1a3a;box-shadow:0 0 0 3px rgba(107,26,58,.1)}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}
.row4{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:14px}
.hint{font-size:.75rem;color:#8a9ab0;margin-top:4px}
.sec-title{font-size:.78rem;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#9a3a6a;margin:22px 0 10px;padding-bottom:6px;border-bottom:1.5px solid #f0e0e8}
.actions{display:flex;align-items:center;justify-content:space-between;margin-top:28px;gap:12px}
.btn{padding:9px 22px;border-radius:8px;font-size:.88rem;font-weight:600;cursor:pointer;border:none;transition:all .15s}
.btn-primary{background:#6b1a3a;color:#fff}
.btn-primary:hover{background:#8b2a52}
.btn-secondary{background:#e8eef4;color:#3a4a5a}
.btn-secondary:hover{background:#d0dae6}
.btn-green{background:#22863a;color:#fff}
.btn-green:hover{background:#196b2e}
.btn-outline{background:#fff;color:#6b1a3a;border:1.5px solid #6b1a3a}
.btn-outline:hover{background:#fdf0f4}
.btn:disabled{opacity:.5;cursor:not-allowed}
/* Source cards */
.source-card{border:2px solid #e0d0d8;border-radius:10px;padding:18px 20px;margin-bottom:16px;background:#fdf8fa}
.source-card.loaded{border-color:#22863a;background:#f0fff4}
.source-card h3{font-size:.9rem;font-weight:700;color:#6b1a3a;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.source-badge{font-size:.7rem;background:#6b1a3a;color:#fff;padding:2px 8px;border-radius:10px}
.source-badge.b{background:#1a3a6b}
/* Table */
.tbl-wrap{overflow-x:auto;margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:.82rem}
th{background:#f7f0f4;color:#5a3a4a;font-weight:600;padding:7px 10px;text-align:left;border-bottom:2px solid #e0d0d8;white-space:nowrap}
td{padding:5px 7px;border-bottom:1px solid #f0e8ec;vertical-align:middle}
td select,td input[type=number],td input[type=text]{width:100%;border:1px solid #dde5ee;border-radius:5px;padding:4px 7px;font-size:.82rem;background:#fff}
td select:focus,td input:focus{outline:none;border-color:#6b1a3a}
tr.conflict-row td{background:#fff3f5}
.conflict-icon{color:#dc2626;font-size:.8rem;font-weight:700}
.ok-icon{color:#22863a;font-size:.8rem}
.src-tag{font-size:.68rem;font-weight:700;padding:2px 6px;border-radius:4px;display:inline-block}
.src-tag-a{background:#fdf0f4;color:#6b1a3a;border:1px solid #e0b0c0}
.src-tag-b{background:#f0f4fd;color:#1a3a6b;border:1px solid #b0c0e0}
/* Console */
#console-wrap{margin-top:16px;display:none}
#console-out{background:#0d1117;color:#c9d1d9;font-family:'Consolas','Courier New',monospace;font-size:.78rem;padding:14px 16px;border-radius:8px;max-height:320px;overflow-y:auto;white-space:pre-wrap;line-height:1.5}
#console-out .ok{color:#56d364}
#console-out .err{color:#f85149}
#console-out .info{color:#58a6ff}
#console-out .warn{color:#f5a623}
.success-box{background:#f0fff4;border:1.5px solid #56d364;border-radius:10px;padding:20px 24px;text-align:center;margin-top:20px;display:none}
.success-box h3{color:#22863a;font-size:1.1rem;margin-bottom:6px}
.success-box p{font-size:.85rem;color:#3a5a3a}
.conflict-banner{background:#fff3f5;border:1.5px solid #f5c0c8;border-radius:8px;padding:10px 14px;margin-top:12px;font-size:.82rem;color:#7a1a2a;display:none}
.conflict-banner strong{display:block;margin-bottom:4px}
.conflict-popup{position:fixed;background:#fff;border:1.5px solid #f5c0c8;border-radius:9px;
  box-shadow:0 6px 24px rgba(0,0,0,.16);padding:14px 16px;z-index:9999;
  max-width:380px;min-width:230px;font-size:.8rem;line-height:1.5}
.conflict-popup-title{font-weight:700;color:#7a1a2a;font-size:.82rem;margin-bottom:10px;
  display:flex;justify-content:space-between;align-items:center;gap:8px}
.conflict-popup-close{cursor:pointer;color:#8a9ab0;font-size:1.1rem;line-height:1;flex-shrink:0}
.conflict-popup-close:hover{color:#3a4a5a}
.conf-pop-item{margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid #f0e8ec}
.conf-pop-item:last-child{border-bottom:none;margin-bottom:0;padding-bottom:0}
.conf-pop-asig{font-weight:600;color:#3a4a5a;font-size:.79rem}
.conf-pop-slots{margin-top:3px;color:#6a7a8a;font-size:.76rem;padding-left:8px}
.conf-pop-slot{display:block}
.conflict-icon.clickable{cursor:pointer}
.summary-box{background:#fdf8fa;border:1.5px solid #e0d0d8;border-radius:9px;padding:14px 18px;font-size:.84rem;line-height:1.8;margin-bottom:16px}
@media(max-width:600px){.row2,.row3,.row4{grid-template-columns:1fr}.stepper{justify-content:flex-start;overflow-x:auto}.step-line{width:16px}}
</style>
</head>
<body>

<div class="top-bar">
  <img src="/api/logo_svg" alt="Janux" style="height:64px;width:64px;border-radius:13px;flex-shrink:0;box-shadow:0 2px 8px rgba(0,0,0,0.3)"/>
  <div>
    <div style="font-size:1.1rem;font-weight:700">Gestor de Horarios — Nuevo Doble Grado</div>
    <div class="sub">Programa de Estudios Conjunto — asistente de configuración</div>
  </div>
</div>

<!-- STEPPER -->
<div class="stepper" id="stepper">
  <div class="step active" data-step="1"><div class="step-circle">1</div><div class="step-label">Básico</div></div>
  <div class="step-line"></div>
  <div class="step" data-step="2"><div class="step-circle">2</div><div class="step-label">Grados origen</div></div>
  <div class="step-line"></div>
  <div class="step" data-step="3"><div class="step-circle">3</div><div class="step-label">Estructura</div></div>
  <div class="step-line"></div>
  <div class="step" data-step="4"><div class="step-circle">4</div><div class="step-label">Distribución</div></div>
  <div class="step-line"></div>
  <div class="step" data-step="5"><div class="step-circle">5</div><div class="step-label">Generar</div></div>
</div>

<!-- ══════ STEP 1: BÁSICO ══════ -->
<div class="card" id="step1">
  <h2>1 · Datos básicos del DTIE</h2>
  <div class="desc">Identificación del nuevo grado conjunto y configuración del servidor.</div>

  <div class="row2">
    <div class="field">
      <label>Escuela</label>
      <select id="b-escuela" onchange="onEscuelaChange()">
        <option value="">— Selecciona una escuela —</option>
      </select>
    </div>
    <div class="field">
      <label>Titulación DTIE</label>
      <select id="b-nombre" onchange="onTitulacionChange()" disabled>
        <option value="">— Selecciona primero una escuela —</option>
      </select>
      <div class="hint">Solo se muestran los dobles grados disponibles</div>
    </div>
  </div>
  <input type="hidden" id="b-siglas">
  <div class="row2">
    <div class="field">
      <label>Institución</label>
      <input type="text" id="b-inst" placeholder="Universidad Politécnica de Cartagena" value="Universidad Politécnica de Cartagena">
    </div>
    <div class="field">
      <label>Siglas institución</label>
      <input type="text" id="b-inst-siglas" placeholder="UPCT" value="UPCT" maxlength="10">
    </div>
  </div>
  <div class="row2">
    <div class="field">
      <label>Etiqueta de curso</label>
      <input type="text" id="b-curso-label" placeholder="2026-2027" value="2026-2027">
    </div>
    <div class="field">
      <label>Puerto del servidor</label>
      <input type="number" id="b-port" value="8082" min="1024" max="65535">
    </div>
  </div>

  <div class="actions">
    <span></span>
    <button class="btn btn-primary" onclick="goStep(2)">Siguiente →</button>
  </div>
</div>

<!-- ══════ STEP 2: GRADOS ORIGEN ══════ -->
<div class="card" id="step2" style="display:none">
  <h2>2 · Grados de origen</h2>
  <div class="desc">Selecciona los dos grados cuyas asignaturas marcadas con ⭐ formarán el DTIE. Pulsa <strong>Cargar</strong> para leer las asignaturas destacadas de cada BD.</div>

  <!-- Selector grado principal -->
  <div style="background:#fef9ec;border:1.5px solid #e8c840;border-radius:9px;padding:12px 16px;margin-bottom:16px;font-size:.84rem;color:#5a4a10">
    <strong>Grado principal:</strong> el grado principal hereda las franjas horarias y los tipos de actividad para el DTIE.
    <div style="margin-top:10px;display:flex;gap:24px">
      <label style="display:flex;align-items:center;gap:7px;cursor:pointer;font-weight:600">
        <input type="radio" name="grado-principal" id="principal-a" value="a" checked
               onchange="updatePrincipalCards()" style="accent-color:#6b1a3a;width:16px;height:16px">
        <span class="source-badge" style="font-size:.75rem">A</span> Grado A es el principal
      </label>
      <label style="display:flex;align-items:center;gap:7px;cursor:pointer;font-weight:600">
        <input type="radio" name="grado-principal" id="principal-b" value="b"
               onchange="updatePrincipalCards()" style="accent-color:#1a3a6b;width:16px;height:16px">
        <span class="source-badge b" style="font-size:.75rem">B</span> Grado B es el principal
      </label>
    </div>
  </div>

  <!-- Grado A -->
  <div class="source-card" id="card-a">
    <h3>⭐ Grado A &nbsp;<span class="source-badge">origen A</span>&nbsp;<span id="badge-principal-a" style="font-size:.68rem;background:#e8c840;color:#5a4a10;padding:2px 8px;border-radius:10px;font-weight:700">★ Principal</span></h3>
    <div class="row2">
      <div class="field">
        <label>Seleccionar grado disponible</label>
        <select id="sel-a" onchange="fillDbPath('a')">
          <option value="">— seleccionar —</option>
        </select>
      </div>
      <div class="field">
        <label>Ruta a la base de datos</label>
        <input type="text" id="db-a" placeholder="horarios/GIM/horarios.db">
        <div class="hint">Relativa a la carpeta del proyecto</div>
      </div>
    </div>
    <button class="btn btn-outline" style="margin-top:4px" onclick="cargarFuente('a')">🔍 Cargar grado A</button>
    <div id="preview-a" style="margin-top:10px;font-size:.82rem;color:#6a7a8a"></div>
  </div>

  <!-- Grado B -->
  <div class="source-card" id="card-b">
    <h3>⭐ Grado B &nbsp;<span class="source-badge b">origen B</span>&nbsp;<span id="badge-principal-b" style="font-size:.68rem;background:#e8c840;color:#5a4a10;padding:2px 8px;border-radius:10px;font-weight:700;display:none">★ Principal</span></h3>
    <div class="row2">
      <div class="field">
        <label>Seleccionar grado disponible</label>
        <select id="sel-b" onchange="fillDbPath('b')">
          <option value="">— seleccionar —</option>
        </select>
      </div>
      <div class="field">
        <label>Ruta a la base de datos</label>
        <input type="text" id="db-b" placeholder="horarios/GIDI/horarios.db">
        <div class="hint">Relativa a la carpeta del proyecto</div>
      </div>
    </div>
    <button class="btn btn-outline" style="margin-top:4px" onclick="cargarFuente('b')">🔍 Cargar grado B</button>
    <div id="preview-b" style="margin-top:10px;font-size:.82rem;color:#6a7a8a"></div>
  </div>

  <div class="actions">
    <button class="btn btn-secondary" onclick="goStep(1)">← Anterior</button>
    <button class="btn btn-primary" onclick="validateFuentes()">Siguiente →</button>
  </div>
</div>

<!-- ══════ STEP 3: ESTRUCTURA ══════ -->
<div class="card" id="step3" style="display:none">
  <h2>3 · Estructura del DTIE</h2>
  <div class="desc">Define el número de cursos, grupos por cuatrimestre y aulas del nuevo grado conjunto. Se precargan los datos del grado principal; ajústalos si es necesario.</div>

  <div class="field" style="max-width:220px">
    <label>Número de cursos</label>
    <input type="number" id="e-num-cursos" value="5" min="1" max="8" oninput="renderEstructuraTable()">
  </div>

  <div class="sec-title">Grupos por curso</div>
  <div class="tbl-wrap">
    <table id="e-cursos-table">
      <thead>
        <tr>
          <th>Curso</th>
          <th>Grupos 1er cuatrimestre</th>
          <th>Grupos 2º cuatrimestre</th>
        </tr>
      </thead>
      <tbody id="e-cursos-tbody"></tbody>
    </table>
  </div>
  <div class="hint" style="margin-top:8px">El número de grupos determina cuántos horarios paralelos se crean; cada grupo tendrá las mismas clases copiadas de los grados de origen.</div>

  <div class="actions">
    <button class="btn btn-secondary" onclick="goStep(2)">← Anterior</button>
    <button class="btn btn-primary" onclick="goStep(4)">Siguiente →</button>
  </div>
</div>

<!-- ══════ STEP 4: DISTRIBUCIÓN ══════ -->
<div class="card" id="step4" style="display:none">
  <h2>4 · Distribución de asignaturas por curso</h2>
  <div class="desc">Asigna a cada asignatura DTIE el curso y cuatrimestre en el nuevo grado. Mismo formato que el CSV de grado convencional. Las filas con ⚠️ indican solapamiento horario.</div>

  <div id="destacadas-banner" style="display:none;background:#fff8ed;border:1.5px solid #f5c070;border-radius:8px;padding:10px 14px;margin-bottom:8px;font-size:.82rem;color:#7a4a00;line-height:1.5"></div>
  <div id="conflict-banner" class="conflict-banner"></div>

  <!-- Barra de importación CSV -->
  <div style="display:flex;align-items:center;gap:10px;margin:14px 0;padding:12px 16px;background:#f0f4f8;border-radius:8px;border:1.5px solid #c8d4e0;flex-wrap:wrap">
    <input type="file" id="csv-dtie-input" accept=".csv" style="display:none" onchange="importarCsvDtie(this.files[0])">
    <button class="btn btn-outline" style="font-size:.82rem;padding:7px 14px" onclick="document.getElementById('csv-dtie-input').click()">📂 Importar CSV</button>
    <button class="btn btn-secondary" style="font-size:.82rem;padding:7px 14px" onclick="cargarCsvDeConfig()">📋 Desde config/</button>
    <select id="csv-config-sel" style="display:none;border:1px solid #c8d4e0;border-radius:7px;padding:6px 10px;font-size:.82rem;background:#fff" onchange="cargarCsvSeleccionado(this.value)">
      <option value="">— seleccionar CSV —</option>
    </select>
    <div id="csv-import-status" style="font-size:.82rem;color:#6a7a8a;flex:1;min-width:180px">
      Importa un CSV tipo <code style="background:#e8eef4;padding:1px 5px;border-radius:3px">fichas_DTIE_GIDI_GIM.csv</code> para precargar la distribución.
    </div>
    <button class="btn btn-secondary" id="btn-clear-csv" onclick="clearCsvDtie()" style="display:none;font-size:.8rem;padding:6px 14px">✕ Limpiar</button>
  </div>

  <div class="tbl-wrap" style="margin-top:4px">
    <table id="dist-table">
      <thead>
        <tr>
          <th>Origen</th>
          <th>Código</th>
          <th>Nombre asignatura</th>
          <th>Curso origen</th>
          <th>Cuat. origen</th>
          <th style="min-width:90px">Curso DTIE ↓</th>
          <th style="min-width:90px">Cuat. DTIE ↓</th>
          <th style="min-width:80px">Grupo origen</th>
          <th style="width:30px"></th>
        </tr>
      </thead>
      <tbody id="dist-tbody"></tbody>
    </table>
  </div>
  <div style="margin-top:8px;font-size:.76rem;color:#8a9ab0">
    Los créditos y valores AF se heredan automáticamente de las BDs de origen y no son editables.
    El campo <strong>Grupo origen</strong> permite seleccionar qué subgrupo se copia cuando hay más de uno en el grado de origen (dejar vacío para usar el grupo con más clases).
  </div>

  <div class="actions">
    <button class="btn btn-secondary" onclick="goStep(3)">← Anterior</button>
    <button class="btn btn-primary" onclick="validarYSiguientePaso4()">Siguiente →</button>
  </div>
</div>

<!-- ══════ STEP 5: APARIENCIA + GENERAR ══════ -->
<div class="card" id="step5" style="display:none">
  <h2>5 · Apariencia y generación</h2>
  <div class="desc">Personaliza los colores del grado DTIE y genera el proyecto.</div>

  <div class="sec-title">Colores de la interfaz</div>
  <div class="row4">
    <div class="field">
      <label>Color primario</label>
      <input type="color" id="ap-primary" value="#6b1a3a">
    </div>
    <div class="field">
      <label>Primario hover</label>
      <input type="color" id="ap-primary-light" value="#8b2a52">
    </div>
    <div class="field">
      <label>Acento</label>
      <input type="color" id="ap-accent" value="#e8a020">
    </div>
    <div class="field">
      <label>Fondo</label>
      <input type="color" id="ap-bg" value="#f0f4f8">
    </div>
  </div>

  <div class="sec-title">Resumen</div>
  <div class="summary-box" id="summary-box">—</div>

  <div id="console-wrap">
    <div style="font-size:.78rem;font-weight:600;color:#5a6a7a;margin-bottom:6px">Salida del proceso:</div>
    <div id="console-out"></div>
  </div>

  <div class="success-box" id="success-box">
    <h3>✅ DTIE creado correctamente</h3>
    <p id="success-path"></p>
    <p style="margin-top:6px">Usa el launcher generado para arrancar el servidor.</p>
  </div>

  <div class="actions">
    <button class="btn btn-secondary" onclick="goStep(4)">← Anterior</button>
    <button class="btn btn-green" id="btn-generate" onclick="generarDtie()">⚡ Generar DTIE</button>
  </div>
</div>

<script>
// ─── STATE ───────────────────────────────────────────────────────────────────
let fuenteData = { a: null, b: null };  // {asignaturas: [...], grado_nombre, db_path}
let gradosDisponibles = [];
let _titulacionesCache = [];
let _escuelaActual = '';
let _csvData = null;   // filas enriquecidas desde CSV; null = usar asignaturas destacadas
let _conflictDetailMap = {};  // codigo → {otherCodigo → {nombre, slots:[{sem,dia,fl}]}}
let _activeConflictPopup = null;

// ─── STEPS ───────────────────────────────────────────────────────────────────
function goStep(n) {
  document.querySelectorAll('.card').forEach(c => c.style.display = 'none');
  document.getElementById('step' + n).style.display = '';
  document.querySelectorAll('.step').forEach(s => {
    const sn = parseInt(s.dataset.step);
    s.classList.toggle('active', sn === n);
    s.classList.toggle('done', sn < n);
  });
  if (n === 3) buildEstructuraTable();
  if (n === 4) buildDistTable();
  if (n === 5) buildSummary();
}

// ─── VALIDACIÓN PASO 4 → 5 ───────────────────────────────────────────────────
function validarYSiguientePaso4() {
  if (!_csvData) {
    // Resaltar la barra de importación e informar al usuario
    const bar = document.querySelector('#step4 > div[style*="background:#f0f4f8"]');
    const status = document.getElementById('csv-import-status');
    if (bar) {
      bar.style.borderColor = '#c0392b';
      bar.style.background  = '#fff0f0';
      setTimeout(() => {
        bar.style.borderColor = '#c8d4e0';
        bar.style.background  = '#f0f4f8';
      }, 3000);
    }
    if (status) {
      status.innerHTML = '<span style="color:#c0392b;font-weight:600">⚠️ Debes importar el CSV de distribución antes de continuar.</span>';
      setTimeout(() => {
        status.innerHTML = 'Importa un CSV tipo <code style="background:#e8eef4;padding:1px 5px;border-radius:3px">fichas_DTIE_GIDI_GIM.csv</code> para precargar la distribución.';
      }, 4000);
    }
    return;
  }
  goStep(5);
}

// ─── CARGAR GRADOS DISPONIBLES ───────────────────────────────────────────────
async function loadGrados() {
  try {
    const r = await fetch('/api/grados');
    const res = await r.json();
    gradosDisponibles = res.grados || [];
    ['a', 'b'].forEach(k => {
      const sel = document.getElementById('sel-' + k);
      gradosDisponibles.forEach(g => {
        const opt = document.createElement('option');
        opt.value = g.db_path;
        opt.textContent = `${g.siglas} — ${g.nombre} (${g.db_path})`;
        sel.appendChild(opt);
      });
    });
  } catch(e) { console.warn('No se pudo cargar lista de grados:', e); }
}

function fillDbPath(k) {
  const sel = document.getElementById('sel-' + k);
  const db  = document.getElementById('db-' + k);
  if (sel.value) db.value = sel.value;
}

// ─── CARGAR FUENTE ────────────────────────────────────────────────────────────
async function cargarFuente(k) {
  const db_path = document.getElementById('db-' + k).value.trim();
  if (!db_path) { alert('Introduce la ruta de la base de datos.'); return; }
  const prev = document.getElementById('preview-' + k);
  prev.innerHTML = '<em>Cargando…</em>';
  try {
    const r = await fetch('/api/leer_dtie', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({db_path})
    });
    const res = await r.json();
    if (!res.ok) {
      prev.innerHTML = `<span style="color:#c0392b">❌ ${res.error}</span>`;
      return;
    }
    fuenteData[k] = {db_path, ...res};
    const n = (res.asignaturas || []).length;
    prev.innerHTML = `<span style="color:#22863a">✅ ${res.grado_nombre || db_path} — <strong>${n} asignatura${n!==1?'s':''} DTIE</strong></span>`;
    document.getElementById('card-' + k).classList.add('loaded');
  } catch(e) {
    prev.innerHTML = `<span style="color:#c0392b">❌ Error: ${e.message}</span>`;
  }
}

function validateFuentes() {
  if (!fuenteData.a) { alert('Carga el Grado A antes de continuar.'); return; }
  if (!fuenteData.b) { alert('Carga el Grado B antes de continuar.'); return; }
  if (!fuenteData.a.asignaturas?.length && !fuenteData.b.asignaturas?.length) {
    if (!confirm('No se encontraron asignaturas DTIE en ninguna fuente. ¿Continuar igualmente?')) return;
  }
  goStep(3);
}

// ─── STEP 3: ESTRUCTURA ──────────────────────────────────────────────────────
function buildEstructuraTable() {
  // Pre-poblar desde degree_structure del grado principal (si está disponible)
  const principal = document.querySelector('input[name="grado-principal"]:checked')?.value || 'a';
  const src = fuenteData[principal];
  const ds = src?.degree_structure || {};
  const gpc = ds.grupos_por_curso || {};

  // Determinar nCursos: del select, o inferido del grado principal, o por defecto 5
  const numCursosEl = document.getElementById('e-num-cursos');
  const nFromSrc = Object.keys(gpc).length;
  if (numCursosEl && !numCursosEl._userEdited && nFromSrc > 0) {
    numCursosEl.value = Math.max(nFromSrc, 5);  // DTIE: mínimo 5 cursos
    numCursosEl._userEdited = false;
  }

  renderEstructuraTable(gpc);
}

function renderEstructuraTable(gpcHint) {
  const nCursos = parseInt(document.getElementById('e-num-cursos').value) || 5;
  const tbody = document.getElementById('e-cursos-tbody');

  // Preserve existing edits
  const existing = {};
  tbody.querySelectorAll('tr').forEach(tr => {
    const c = tr.dataset.curso;
    if (c) existing[c] = {
      g1c: tr.querySelector('.e-g1c')?.value,
      g2c: tr.querySelector('.e-g2c')?.value,
    };
  });

  tbody.innerHTML = '';
  const gpc = gpcHint || {};
  for (let i = 1; i <= nCursos; i++) {
    const cs = String(i);
    const prev = existing[cs] || {};
    const defG1c = prev.g1c ?? (gpc[cs]?.['1C'] ?? 1);
    const defG2c = prev.g2c ?? (gpc[cs]?.['2C'] ?? 1);

    const tr = document.createElement('tr');
    tr.dataset.curso = cs;
    tr.innerHTML = `
      <td style="font-weight:600;color:#6b1a3a;text-align:center">${i}º</td>
      <td><input type="number" class="e-g1c" value="${defG1c}" min="0" max="20" style="width:70px"></td>
      <td><input type="number" class="e-g2c" value="${defG2c}" min="0" max="20" style="width:70px"></td>`;
    tbody.appendChild(tr);
  }
}

function getEstructura() {
  const cursos = [];
  document.querySelectorAll('#e-cursos-tbody tr').forEach(tr => {
    cursos.push({
      g1c: parseInt(tr.querySelector('.e-g1c')?.value) || 1,
      g2c: parseInt(tr.querySelector('.e-g2c')?.value) || 1,
    });
  });
  return { cursos };
}

// ─── TABLA DE DISTRIBUCIÓN ───────────────────────────────────────────────────
function buildDistTable() {
  const tbody = document.getElementById('dist-tbody');
  // Preserve existing edits
  const existing = {};
  tbody.querySelectorAll('tr').forEach(tr => {
    const cod = tr.dataset.codigo;
    if (cod) existing[cod] = {
      curso:      tr.querySelector('.curso-dtie')?.value,
      cuat:       tr.querySelector('.cuat-dtie')?.value,
      grupo_orig: tr.querySelector('.grupo-orig-v')?.value,
    };
  });

  // Fuente de filas: CSV importado o asignaturas destacadas
  let rows;
  if (_csvData) {
    rows = _csvData;
  } else {
    rows = [];
    (fuenteData.a?.asignaturas || []).forEach(a => rows.push({...a, fuente:'a', fuente_label:'A'}));
    (fuenteData.b?.asignaturas || []).forEach(a => rows.push({...a, fuente:'b', fuente_label:'B'}));
  }

  tbody.innerHTML = '';
  rows.forEach(a => {
    const prev = existing[a.codigo] || {};
    // En modo CSV: defCurso/defCuat vienen del CSV; en modo destacadas: del grupo origen
    const defCurso     = prev.curso       || (_csvData ? String(a.curso_dtie||'1') : String(a.curso_origen||'1'));
    const defCuat      = prev.cuat        || (_csvData ? (a.cuatrimestre||'1C')    : (a.cuatrimestre_origen||'1C'));
    const defGrupoOrig = prev.grupo_orig  || a.grupo_num || '';
    // Opciones de cuatrimestre: base 1C/2C + añadir si defCuat es otro valor (A, I, etc.)
    const cuatBase = ['1C', '2C'];
    if (!cuatBase.includes(defCuat)) cuatBase.push(defCuat);
    const cuatHtml = cuatBase.map(o => `<option value="${o}"${defCuat===o?' selected':''}>${o}</option>`).join('');
    // Indicador visual para códigos no encontrados en BD o no marcados con ⭐
    const notFound      = a.found === false;
    const notDestacada  = a.found !== false && a.destacada === false;
    const warnIcon = notFound
      ? '<span class="conflict-icon" title="Código no encontrado en la BD de origen"> ⚠</span>'
      : (notDestacada
          ? '<span style="color:#e67e00;font-weight:700;cursor:default" title="Esta asignatura existe en la BD pero NO está marcada con ⭐ — no se copiará al horario DTIE">⭐❌</span>'
          : '');
    const tr = document.createElement('tr');
    if (notFound)     tr.style.background = '#fff3f5';
    if (notDestacada) tr.style.background = '#fff8ed';
    tr.dataset.codigo    = a.codigo;
    tr.dataset.fuente    = a.fuente;
    tr.dataset.grupo_num = a.grupo_num || '';
    // Almacenar valores AF/créditos como data-attributes (solo lectura, heredados de la BD)
    tr.dataset.creditos  = a.creditos ?? 6;
    tr.dataset.af1       = a.af1 ?? 0;
    tr.dataset.af2       = a.af2 ?? 0;
    tr.dataset.af4       = a.af4 ?? 0;
    tr.dataset.af5       = a.af5 ?? 0;
    tr.dataset.af6       = a.af6 ?? 0;
    tr.innerHTML = `
      <td><span class="src-tag src-tag-${a.fuente}">${esc(a.fuente_label||a.fuente.toUpperCase())}</span>${warnIcon}</td>
      <td style="font-family:monospace;font-size:.78rem">${esc(a.codigo)}</td>
      <td>${esc(a.nombre)}</td>
      <td style="text-align:center">${a.curso_origen||'?'}</td>
      <td style="text-align:center">${a.cuatrimestre_origen||'?'}</td>
      <td><select class="curso-dtie" onchange="checkConflicts()">
        ${[1,2,3,4,5,6].map(n=>`<option value="${n}"${defCurso==n?' selected':''}>${n}º</option>`).join('')}
      </select></td>
      <td><select class="cuat-dtie" onchange="checkConflicts()">${cuatHtml}</select></td>
      <td><input type="text" class="grupo-orig-v" value="${esc(defGrupoOrig)}" placeholder="vacío=auto"
           title="Número de grupo origen a copiar (vacío=grupo con más clases)" style="width:72px"></td>
      <td class="conf-cell"></td>`;
    tbody.appendChild(tr);
  });
  checkConflicts();
  checkDestacadasWarning();
}

function checkDestacadasWarning() {
  const banner = document.getElementById('destacadas-banner');
  if (!banner) return;

  // Solo aplica cuando hay CSV cargado
  if (!_csvData) { banner.innerHTML = ''; banner.style.display = 'none'; return; }

  const noDestacadas  = _csvData.filter(a => a.found !== false && a.destacada === false);
  const noEncontradas = _csvData.filter(a => a.found === false);

  const partes = [];
  if (noDestacadas.length > 0) {
    const nombres = noDestacadas.map(a => `<strong>${esc(a.codigo)}</strong> (${esc(a.nombre||'')})`).join(', ');
    partes.push(
      `⭐❌ <strong>${noDestacadas.length} asignatura${noDestacadas.length>1?'s':''} del CSV no está${noDestacadas.length>1?'n':''} marcada${noDestacadas.length>1?'s':''} con ⭐ en el grado de origen — <u>no se copiarán al horario DTIE</u>.</strong><br>${nombres}`
    );
  }
  if (noEncontradas.length > 0) {
    const nombres = noEncontradas.map(a => `<strong>${esc(a.codigo)}</strong>`).join(', ');
    partes.push(
      `⚠️ <strong>${noEncontradas.length} código${noEncontradas.length>1?'s':''} no encontrado${noEncontradas.length>1?'s':''} en la BD de origen.</strong><br>${nombres}`
    );
  }

  if (partes.length > 0) {
    banner.innerHTML = partes.join('<hr style="border:none;border-top:1px solid #f5c6a0;margin:6px 0">');
    banner.style.display = '';
  } else {
    banner.innerHTML = '';
    banner.style.display = 'none';
  }
}

function getDistribucion() {
  const rows = [];
  document.querySelectorAll('#dist-tbody tr').forEach(tr => {
    rows.push({
      codigo:       tr.dataset.codigo,
      fuente:       tr.dataset.fuente,
      // grupo_origen editable prevalece sobre el grupo_num original del CSV
      grupo_num:    tr.querySelector('.grupo-orig-v')?.value?.trim() || tr.dataset.grupo_num || '',
      nombre:       tr.querySelector('td:nth-child(3)').textContent,
      curso_dtie:   parseInt(tr.querySelector('.curso-dtie').value),
      cuatrimestre: tr.querySelector('.cuat-dtie').value,
      // Créditos y AF son de solo lectura, heredados de la BD de origen
      creditos:     parseFloat(tr.dataset.creditos)||0,
      af1:          parseInt(tr.dataset.af1)||0,
      af2:          parseInt(tr.dataset.af2)||0,
      af4:          parseInt(tr.dataset.af4)||0,
      af5:          parseInt(tr.dataset.af5)||0,
      af6:          parseInt(tr.dataset.af6)||0,
    });
  });
  return rows;
}

// ─── DETECCIÓN DE CONFLICTOS (cliente) ────────────────────────────────────────
function checkConflicts() {
  const dist = getDistribucion();
  const conflictCodigos = new Set();
  // slotMap: "curso_cuat" → {slot_key → [{codigo, nombre, sem, dia, fl}]}
  const slotMap = {};
  dist.forEach(d => {
    const key = `${d.curso_dtie}_${d.cuatrimestre}`;
    if (!slotMap[key]) slotMap[key] = {};
    getSchedule(d.codigo, d.fuente).forEach(s => {
      const sk = `${s.sem}_${s.dia}_${s.fr}`;
      if (!slotMap[key][sk]) slotMap[key][sk] = [];
      // Deduplicar por codigo: evita falsos conflictos si el mismo código
      // aparece dos veces en la tabla (p.ej. marcado con distintos grupo_num)
      if (!slotMap[key][sk].some(e => e.codigo === d.codigo)) {
        slotMap[key][sk].push({codigo: d.codigo, nombre: d.nombre, sem: s.sem, dia: s.dia, fl: s.fl || ''});
      }
    });
  });

  // Construir mapa detallado: codigo → {otherCodigo → {nombre, slots[]}}
  _conflictDetailMap = {};
  Object.values(slotMap).forEach(slots => {
    Object.values(slots).forEach(entries => {
      if (entries.length < 2) return;
      entries.forEach(e => {
        conflictCodigos.add(e.codigo);
        if (!_conflictDetailMap[e.codigo]) _conflictDetailMap[e.codigo] = {};
        entries.forEach(other => {
          if (other.codigo === e.codigo) return;
          if (!_conflictDetailMap[e.codigo][other.codigo])
            _conflictDetailMap[e.codigo][other.codigo] = {nombre: other.nombre, slots: []};
          _conflictDetailMap[e.codigo][other.codigo].slots.push(
            {sem: e.sem, dia: e.dia, fl: e.fl}
          );
        });
      });
    });
  });

  let nConflicts = 0;
  document.querySelectorAll('#dist-tbody tr').forEach(tr => {
    const cod = tr.dataset.codigo;
    const hasConflict = conflictCodigos.has(cod);
    tr.classList.toggle('conflict-row', hasConflict);
    const cell = tr.querySelector('.conf-cell');
    if (hasConflict) {
      cell.innerHTML = '<span class="conflict-icon clickable" title="Pulsa para ver los solapamientos">⚠️</span>';
      cell.querySelector('.conflict-icon').addEventListener('click', ev => {
        ev.stopPropagation();
        showConflictPopup(ev.currentTarget, cod);
      });
      nConflicts++;
    } else {
      cell.innerHTML = '<span class="ok-icon">✓</span>';
    }
  });

  const banner = document.getElementById('conflict-banner');
  if (nConflicts > 0) {
    banner.style.display = '';
    banner.innerHTML = `<strong>⚠️ ${nConflicts} asignatura${nConflicts!==1?'s':''} con solapamiento horario</strong>
      Las filas marcadas en rojo comparten alguna franja con otra asignatura del mismo curso/cuatrimestre DTIE.
      Pulsa ⚠️ para ver el detalle. El grado se generará igualmente.`;
  } else {
    banner.style.display = 'none';
  }
}

// ─── POPUP DE DETALLE DE SOLAPAMIENTOS ───────────────────────────────────────
function showConflictPopup(anchor, codigo) {
  // Cerrar popup anterior si existe
  if (_activeConflictPopup) { _activeConflictPopup.remove(); _activeConflictPopup = null; }

  const details = _conflictDetailMap[codigo] || {};
  const entries = Object.entries(details);
  if (!entries.length) return;

  const popup = document.createElement('div');
  popup.className = 'conflict-popup';

  let html = `<div class="conflict-popup-title">
    <span>⚠️ Solapamientos en mismo curso DTIE</span>
    <span class="conflict-popup-close" title="Cerrar">✕</span>
  </div>`;

  entries.forEach(([otherCod, info]) => {
    // Deduplicar slots y ordenar por semana
    const seen = new Set();
    const uniqueSlots = info.slots
      .filter(s => { const k = `${s.sem}_${s.dia}_${s.fl}`; if (seen.has(k)) return false; seen.add(k); return true; })
      .sort((a, b) => a.sem - b.sem);
    const slotLines = uniqueSlots.slice(0, 8)
      .map(s => `<span class="conf-pop-slot">Sem ${String(s.sem).padStart(2,' ')} · ${s.dia}${s.fl ? ' · ' + s.fl : ''}</span>`)
      .join('');
    const extra = uniqueSlots.length > 8 ? `<span class="conf-pop-slot" style="color:#aaa">… y ${uniqueSlots.length - 8} más</span>` : '';
    html += `<div class="conf-pop-item">
      <div class="conf-pop-asig">[${esc(otherCod)}] ${esc(info.nombre)}</div>
      <div class="conf-pop-slots">${slotLines}${extra}</div>
    </div>`;
  });

  popup.innerHTML = html;
  document.body.appendChild(popup);
  _activeConflictPopup = popup;

  // Posicionar junto al ancla
  const rect = anchor.getBoundingClientRect();
  const pw = popup.offsetWidth;
  const ph = popup.offsetHeight;
  const left = Math.min(rect.right + 6, window.innerWidth - pw - 8);
  const top  = Math.min(rect.top, window.innerHeight - ph - 8);
  popup.style.left = Math.max(8, left) + 'px';
  popup.style.top  = Math.max(8, top)  + 'px';

  // Botón cerrar
  popup.querySelector('.conflict-popup-close').addEventListener('click', () => {
    popup.remove(); _activeConflictPopup = null;
  });
  // Cerrar al hacer clic fuera
  setTimeout(() => {
    document.addEventListener('click', function handler(e) {
      if (_activeConflictPopup && !_activeConflictPopup.contains(e.target)) {
        _activeConflictPopup.remove(); _activeConflictPopup = null;
        document.removeEventListener('click', handler);
      }
    });
  }, 50);
}

function getSchedule(codigo, fuente) {
  const data = fuenteData[fuente];
  if (!data?.schedules) return [];
  return data.schedules[codigo] || [];
}

// ─── RESUMEN ─────────────────────────────────────────────────────────────────
function buildSummary() {
  const b = getBasico();
  const dist = getDistribucion();
  const est = getEstructura();
  const nA = dist.filter(d => d.fuente === 'a').length;
  const nB = dist.filter(d => d.fuente === 'b').length;
  const cursos = [...new Set(dist.map(d => d.curso_dtie))].sort();
  const estResumen = est.cursos.map((c, i) =>
    `${i+1}º: ${c.g1c} gr.1C / ${c.g2c} gr.2C`
  ).join('<br>  ');
  document.getElementById('summary-box').innerHTML = `
    <b>Grado DTIE:</b> ${b.nombre} (${b.siglas})<br>
    <b>Institución:</b> ${b.institucion} (${b.siglas_inst})<br>
    <b>Curso:</b> ${b.curso_label} · Puerto: ${b.puerto}<br>
    <b>Fuente A:</b> ${fuenteData.a?.grado_nombre||'—'} — ${nA} asignaturas<br>
    <b>Fuente B:</b> ${fuenteData.b?.grado_nombre||'—'} — ${nB} asignaturas<br>
    <b>Total asignaturas:</b> ${dist.length} · Cursos DTIE: ${cursos.join(', ')||'—'}<br>
    <b>Estructura:</b><br>  ${estResumen||'—'}<br>
    <b>Carpeta destino:</b> horarios/${b.siglas}/
  `;
}

// ─── GETTERS ─────────────────────────────────────────────────────────────────
function getBasico() {
  return {
    nombre:      document.getElementById('b-nombre').value,
    siglas:      document.getElementById('b-siglas').value.toUpperCase(),
    institucion: document.getElementById('b-inst').value,
    siglas_inst: document.getElementById('b-inst-siglas').value,
    curso_label: document.getElementById('b-curso-label').value,
    puerto:      document.getElementById('b-port').value || '8082',
  };
}

function getApariencia() {
  return {
    primary:       document.getElementById('ap-primary').value,
    primary_light: document.getElementById('ap-primary-light').value,
    accent:        document.getElementById('ap-accent').value,
    bg:            document.getElementById('ap-bg').value,
  };
}

// ─── GENERAR ─────────────────────────────────────────────────────────────────
async function generarDtie() {
  const btn = document.getElementById('btn-generate');
  btn.disabled = true; btn.textContent = '⏳ Generando…';
  document.getElementById('console-wrap').style.display = 'block';
  document.getElementById('console-out').innerHTML = '';
  document.getElementById('success-box').style.display = 'none';

  consoleLog('Enviando datos al servidor…', 'info');

  const principal = document.querySelector('input[name="grado-principal"]:checked')?.value || 'a';
  const payload = {
    basico:          getBasico(),
    apariencia:      getApariencia(),
    estructura:      getEstructura(),
    grado_principal: principal,
    fuentes:      [
      {db_path: fuenteData.a.db_path, grado_nombre: fuenteData.a.grado_nombre || 'A'},
      {db_path: fuenteData.b.db_path, grado_nombre: fuenteData.b.grado_nombre || 'B'},
    ],
    distribucion: getDistribucion(),
  };

  try {
    const r = await fetch('/api/crear_dtie', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const res = await r.json();
    if (res.output) {
      res.output.split('\n').forEach(l =>
        consoleLog(l, l.includes('✅')?'ok': l.includes('ERROR')||l.includes('Error')?'err':
                      l.includes('⚠️')?'warn':''));
    }
    if (res.error) res.error.split('\n').filter(Boolean).forEach(l => consoleLog(l, 'err'));
    if (res.traceback) res.traceback.split('\n').forEach(l => consoleLog(l, 'err'));
    if (res.ok) {
      consoleLog('\n✅ DTIE creado correctamente.', 'ok');
      const sb = document.getElementById('success-box');
      sb.style.display = 'block';
      document.getElementById('success-path').textContent = 'Carpeta: ' + (res.grado_dir || 'horarios/' + getBasico().siglas);
    } else {
      consoleLog('\n❌ Se produjeron errores. Revisa la salida.', 'err');
    }
  } catch(e) {
    consoleLog('Error de conexión: ' + e.message, 'err');
  } finally {
    btn.disabled = false; btn.textContent = '⚡ Generar DTIE';
  }
}

function consoleLog(text, cls) {
  const box = document.getElementById('console-out');
  const span = document.createElement('span');
  if (cls) span.className = cls;
  span.textContent = text + '\n';
  box.appendChild(span);
  box.scrollTop = box.scrollHeight;
}

function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ─── CSV IMPORT ──────────────────────────────────────────────────────────────
function parseCsvLine(line) {
  const result = [];
  let cur = '', inQuote = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuote && line[i+1] === '"') { cur += '"'; i++; }
      else inQuote = !inQuote;
    } else if (ch === ',' && !inQuote) {
      result.push(cur); cur = '';
    } else { cur += ch; }
  }
  result.push(cur);
  return result;
}

function parseCSV(text) {
  // Eliminar BOM (UTF-8 con BOM) si existe
  const clean = text.replace(/^\uFEFF/, '');
  const lines = clean.replace(/\r\n?/g, '\n').trim().split('\n');
  const headers = parseCsvLine(lines[0]).map(h => h.trim());
  const nCols = headers.length;
  return lines.slice(1).filter(l => l.trim()).map(line => {
    const vals = parseCsvLine(line);
    // Si hay más valores que cabeceras, el exceso pertenece al campo 'nombre' (índice 1)
    // porque el CSV DTIE tiene estructura fija: codigo,nombre,grado_origen,curso_dtie,cuatrimestre,grupo_origen
    const nExtra = vals.length - nCols;
    const norm = nExtra > 0
      ? [vals[0], vals.slice(1, 2 + nExtra).join(','), ...vals.slice(2 + nExtra)]
      : vals;
    const obj = {};
    headers.forEach((h, i) => obj[h] = (norm[i] || '').trim());
    return obj;
  });
}

async function _resolverCSV(payload) {
  const status = document.getElementById('csv-import-status');
  const r = await fetch('/api/resolver_csv_dtie', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  const res = await r.json();
  if (!res.ok) { status.innerHTML = `<span style="color:#c0392b">❌ ${res.error}</span>`; return null; }
  // Merge schedules en fuenteData para que checkConflicts() los vea
  if (res.schedules?.a && fuenteData.a) Object.assign(fuenteData.a.schedules, res.schedules.a);
  if (res.schedules?.b && fuenteData.b) Object.assign(fuenteData.b.schedules, res.schedules.b);
  _csvData = res.rows;
  buildDistTable();
  const nOk  = res.rows.filter(r => r.found !== false).length;
  const nErr = res.rows.filter(r => r.found === false).length;
  const warn = res.warnings?.length ? `<br><span style="color:#e8a020">⚠️ ${res.warnings.length} aviso(s) — ver consola del navegador</span>` : '';
  status.innerHTML = `<span style="color:#22863a">✅ ${nOk} asignaturas cargadas${nErr ? ` · <strong style="color:#c0392b">${nErr} no encontradas</strong>` : ''}</span>${warn}`;
  document.getElementById('btn-clear-csv').style.display = '';
  if (res.warnings?.length) console.warn('CSV DTIE warnings:', res.warnings);
  return res;
}

async function importarCsvDtie(file) {
  if (!file) return;
  if (!fuenteData.a || !fuenteData.b) {
    alert('Carga ambos grados en el paso 2 antes de importar el CSV.'); return;
  }
  const status = document.getElementById('csv-import-status');
  status.innerHTML = '<em>Leyendo fichero…</em>';
  try {
    const text = await file.text();
    const rows = parseCSV(text);
    if (!rows.length) { status.innerHTML = '<span style="color:#c0392b">CSV vacío o sin filas.</span>'; return; }
    status.innerHTML = `<em>Resolviendo ${rows.length} filas contra las BDs de origen…</em>`;
    await _resolverCSV({
      csv_rows: rows,
      fuentes: [{db_path: fuenteData.a.db_path}, {db_path: fuenteData.b.db_path}]
    });
  } catch(e) {
    document.getElementById('csv-import-status').innerHTML = `<span style="color:#c0392b">❌ ${e.message}</span>`;
  }
  document.getElementById('csv-dtie-input').value = '';  // reset para permitir reimportar
}

async function cargarCsvDeConfig() {
  try {
    const r = await fetch('/api/csvs_dtie');
    const res = await r.json();
    const sel = document.getElementById('csv-config-sel');
    sel.innerHTML = '<option value="">— seleccionar CSV —</option>';
    (res.csvs || []).forEach(c => {
      const opt = document.createElement('option');
      opt.value = c.path; opt.textContent = c.name;
      sel.appendChild(opt);
    });
    sel.style.display = '';
    if (!res.csvs?.length) {
      alert('No hay ficheros fichas_DTIE_*.csv en config/');
      sel.style.display = 'none';
    }
  } catch(e) { alert('Error al listar CSVs: ' + e.message); }
}

async function cargarCsvSeleccionado(path) {
  if (!path) return;
  if (!fuenteData.a || !fuenteData.b) {
    alert('Carga ambos grados en el paso 2 primero.'); return;
  }
  const status = document.getElementById('csv-import-status');
  status.innerHTML = `<em>Cargando ${path.split('/').pop()}…</em>`;
  try {
    await _resolverCSV({
      csv_path: path,
      fuentes: [{db_path: fuenteData.a.db_path}, {db_path: fuenteData.b.db_path}]
    });
  } catch(e) {
    status.innerHTML = `<span style="color:#c0392b">❌ ${e.message}</span>`;
  }
}

function clearCsvDtie() {
  _csvData = null;
  document.getElementById('csv-import-status').innerHTML =
    'Importa un CSV tipo <code style="background:#e8eef4;padding:1px 5px;border-radius:3px">fichas_DTIE_GIDI_GIM.csv</code> para precargar la distribución.';
  document.getElementById('btn-clear-csv').style.display = 'none';
  document.getElementById('csv-config-sel').style.display = 'none';
  buildDistTable();
}

// ─── TITULACIONES DTIE ────────────────────────────────────────────────────────
(function() {
  fetch('/api/titulaciones')
    .then(r => r.json())
    .then(tits => {
      _titulacionesCache = tits;
      // Solo escuelas con dobles grados
      const escuelas = [...new Set(tits.filter(t => t.doble_grado).map(t => t.escuela))];
      const selEsc = document.getElementById('b-escuela');
      if (!selEsc) return;
      escuelas.forEach(e => {
        const opt = document.createElement('option');
        opt.value = e; opt.textContent = e;
        selEsc.appendChild(opt);
      });
      // Si solo hay una escuela, seleccionarla automáticamente
      if (escuelas.length === 1) {
        selEsc.value = escuelas[0];
        onEscuelaChange();
      }
    })
    .catch(() => console.warn('No se pudo cargar titulaciones.json'));
})();

function onEscuelaChange() {
  const escuela = document.getElementById('b-escuela').value;
  _escuelaActual = escuela;
  const selTit = document.getElementById('b-nombre');
  selTit.innerHTML = '';
  document.getElementById('b-siglas').value = '';
  if (!escuela) {
    selTit.innerHTML = '<option value="">— Selecciona primero una escuela —</option>';
    selTit.disabled = true;
    return;
  }
  // Filtrar SOLO dobles grados de esa escuela
  const filtradas = _titulacionesCache.filter(t => t.escuela === escuela && t.doble_grado);
  selTit.innerHTML = '<option value="">— Selecciona una titulación DTIE —</option>';
  filtradas.forEach(t => {
    const opt = document.createElement('option');
    opt.value = t.titulacion;
    opt.dataset.code = t.code;
    opt.textContent = t.code + ' · ' + t.titulacion;
    selTit.appendChild(opt);
  });
  selTit.disabled = false;
}

function onTitulacionChange() {
  const sel = document.getElementById('b-nombre');
  const opt = sel && sel.options[sel.selectedIndex];
  document.getElementById('b-siglas').value = (opt && opt.dataset.code) ? opt.dataset.code : '';
}

function updatePrincipalCards() {
  const principal = document.querySelector('input[name="grado-principal"]:checked')?.value || 'a';
  document.getElementById('badge-principal-a').style.display = principal === 'a' ? '' : 'none';
  document.getElementById('badge-principal-b').style.display = principal === 'b' ? '' : 'none';
}

// ─── INIT ─────────────────────────────────────────────────────────────────────
loadGrados();
</script>
</body>
</html>
"""

# ─────────────────────────────────────────────────────────────────────────────
# BACKEND — FUNCIONES DE DATOS
# ─────────────────────────────────────────────────────────────────────────────

def resolve_db_path(db_path_str):
    """Convierte una ruta relativa o absoluta a Path absoluta."""
    p = Path(db_path_str)
    if not p.is_absolute():
        p = BASE_DIR / p
    return p


def api_grados(_=None):
    """Lista los grados disponibles en horarios/."""
    grados_dir = BASE_DIR / 'horarios'
    result = []
    if not grados_dir.exists():
        return {'grados': []}
    for subdir in sorted(grados_dir.iterdir()):
        if not subdir.is_dir():
            continue
        cfg_path = subdir / 'config.json'
        if not cfg_path.exists():
            continue
        try:
            with open(cfg_path, encoding='utf-8') as f:
                cfg = json.load(f)
            db_name = cfg.get('server', {}).get('db_name', 'horarios.db')
            db_path = subdir / db_name
            if db_path.exists():
                result.append({
                    'siglas':    cfg.get('degree', {}).get('acronym', subdir.name),
                    'nombre':    cfg.get('degree', {}).get('name', subdir.name),
                    'db_path':   str(db_path.relative_to(BASE_DIR)),
                    'curso':     cfg.get('server', {}).get('curso_label', ''),
                })
        except Exception:
            pass
    return {'grados': result}


def api_leer_dtie(data):
    """
    Lee las asignaturas marcadas como DTIE (asignaturas_destacadas) de una BD.
    Devuelve también el schedule comprimido de cada asignatura para conflict detection.
    """
    db_path_str = data.get('db_path', '')
    if not db_path_str:
        return {'ok': False, 'error': 'db_path vacío.'}

    db_path = resolve_db_path(db_path_str)
    if not db_path.exists():
        return {'ok': False, 'error': f'No se encuentra: {db_path}'}

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Verificar que existe la tabla
        has_dest = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='asignaturas_destacadas'"
        ).fetchone()
        if not has_dest:
            conn.close()
            return {'ok': False, 'error': 'La BD no tiene tabla asignaturas_destacadas. '
                    'Abre el grado y marca asignaturas con ⭐ primero.'}

        # Detectar si asignaturas tiene columnas curso/cuatrimestre (rebuild_db no las tiene)
        asig_cols = [r[1] for r in conn.execute("PRAGMA table_info(asignaturas)").fetchall()]
        has_curso_col = 'curso' in asig_cols

        if has_curso_col:
            curso_select = "a.curso AS curso_origen, a.cuatrimestre AS cuatrimestre_origen,"
            order_by = "ORDER BY a.curso, a.cuatrimestre, a.nombre"
        else:
            # Inferir curso/cuatrimestre desde el grupo_num (clave del grupo)
            # La clave tiene formato "N_XC_grupo_..." donde N=curso, XC=cuatrimestre
            curso_select = "NULL AS curso_origen, NULL AS cuatrimestre_origen,"
            order_by = "ORDER BY a.nombre"

        rows = conn.execute(f"""
            SELECT DISTINCT a.codigo, a.nombre,
                   {curso_select}
                   d.grupo_num,
                   COALESCE(f.creditos, 6.0) AS creditos,
                   COALESCE(f.af1, 0) AS af1,
                   COALESCE(f.af2, 0) AS af2,
                   COALESCE(f.af4, 0) AS af4,
                   COALESCE(f.af5, 0) AS af5,
                   COALESCE(f.af6, 0) AS af6
            FROM asignaturas_destacadas d
            JOIN asignaturas a ON a.codigo = d.codigo
            LEFT JOIN fichas f ON f.asignatura_id = a.id
            {order_by}
        """).fetchall()

        asignaturas_raw = [dict(r) for r in rows]

        # Deduplicar por codigo: la misma asignatura puede estar marcada con
        # distintos grupo_num/act_type en asignaturas_destacadas, lo que generaría
        # filas duplicadas que rompen la detección de solapamientos en el cliente.
        _seen_codigos: dict = {}
        for _a in asignaturas_raw:
            if _a['codigo'] not in _seen_codigos:
                _seen_codigos[_a['codigo']] = _a
        asignaturas = list(_seen_codigos.values())

        # Para cada asignatura: inferir curso/cuatrimestre y grupo desde las clases reales
        # (más robusto que depender del valor grupo_num almacenado, que puede ser solo un número)
        def find_main_grupo(codigo_asig):
            """Devuelve (grupo_id, curso, cuatrimestre) del grupo con más clases para esta asig."""
            r = conn.execute("""
                SELECT g.id, g.curso, g.cuatrimestre, COUNT(*) AS cnt
                FROM clases c
                JOIN asignaturas a ON a.id = c.asignatura_id
                JOIN semanas s ON s.id = c.semana_id
                JOIN grupos g ON g.id = s.grupo_id
                WHERE a.codigo = ? AND c.es_no_lectivo = 0
                GROUP BY g.id ORDER BY cnt DESC LIMIT 1
            """, (codigo_asig,)).fetchone()
            return r  # (grupo_id, curso, cuatrimestre, cnt) or None

        if not has_curso_col:
            for asig in asignaturas:
                g = find_main_grupo(asig['codigo'])
                if g:
                    asig['curso_origen']        = g[1]
                    asig['cuatrimestre_origen']  = g[2]
                    asig['_grupo_id_origen']     = g[0]
                else:
                    asig['curso_origen']        = None
                    asig['cuatrimestre_origen']  = None
                    asig['_grupo_id_origen']     = None
        else:
            for asig in asignaturas:
                g = find_main_grupo(asig['codigo'])
                asig['_grupo_id_origen'] = g[0] if g else None

        # Leer schedules comprimidos para conflict detection en el cliente
        schedules = {}
        for asig in asignaturas:
            codigo   = asig['codigo']
            grupo_id = asig.get('_grupo_id_origen')
            if not grupo_id:
                schedules[codigo] = []
                continue
            clases = conn.execute("""
                SELECT s.numero AS sem, c.dia, c.franja_id AS fr, f.label AS fl
                FROM clases c
                JOIN semanas s ON s.id = c.semana_id
                JOIN asignaturas a ON a.id = c.asignatura_id
                JOIN franjas f ON f.id = c.franja_id
                WHERE s.grupo_id = ? AND a.codigo = ? AND c.es_no_lectivo = 0
            """, (grupo_id, codigo)).fetchall()
            schedules[codigo] = [{'sem': r[0], 'dia': r[1], 'fr': r[2], 'fl': r[3]} for r in clases]

        # Nombre del grado (para mostrar en preview)
        grado_nombre = db_path_str  # fallback
        cfg_path = db_path.parent / 'config.json'
        if cfg_path.exists():
            try:
                with open(cfg_path, encoding='utf-8') as f:
                    cfg = json.load(f)
                grado_nombre = cfg.get('degree', {}).get('name', db_path_str)
            except Exception:
                pass

        # Leer degree_structure del config para pre-poblar el paso Estructura
        degree_structure = {}
        if cfg_path.exists():
            try:
                with open(cfg_path, encoding='utf-8') as f:
                    cfg = json.load(f)
                degree_structure = cfg.get('degree_structure', {})
            except Exception:
                pass

        conn.close()
        return {
            'ok':               True,
            'asignaturas':      asignaturas,
            'schedules':        schedules,
            'grado_nombre':     grado_nombre,
            'degree_structure': degree_structure,
        }

    except Exception:
        return {'ok': False, 'error': traceback.format_exc()}


# ─────────────────────────────────────────────────────────────────────────────
# GENERACIÓN DE LA BD DTIE
# ─────────────────────────────────────────────────────────────────────────────

def create_tables_dtie(conn):
    """Crea el esquema completo al último nivel de migrate_db.py.
    Mantener sincronizado con setup_grado.py::create_tables y
    con las migraciones de tools/migrate_db.py."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS asignaturas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL, nombre TEXT NOT NULL,
            curso INTEGER DEFAULT NULL, cuatrimestre TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS grupos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            curso INTEGER, cuatrimestre TEXT, grupo TEXT,
            aula TEXT DEFAULT '', clave TEXT
        );
        CREATE TABLE IF NOT EXISTS franjas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT, orden INTEGER
        );
        CREATE TABLE IF NOT EXISTS semanas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grupo_id INTEGER REFERENCES grupos(id),
            numero INTEGER, descripcion TEXT
        );
        CREATE TABLE IF NOT EXISTS clases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semana_id INTEGER REFERENCES semanas(id),
            dia TEXT, franja_id INTEGER REFERENCES franjas(id),
            asignatura_id INTEGER REFERENCES asignaturas(id),
            aula TEXT DEFAULT '', tipo TEXT DEFAULT '',
            subgrupo TEXT DEFAULT '', af_cat TEXT DEFAULT NULL,
            observacion TEXT DEFAULT '', es_no_lectivo INTEGER DEFAULT 0,
            contenido TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS fichas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asignatura_id INTEGER NOT NULL UNIQUE REFERENCES asignaturas(id) ON DELETE CASCADE,
            creditos REAL DEFAULT 0, af1 INTEGER DEFAULT 0, af2 INTEGER DEFAULT 0,
            af3 INTEGER DEFAULT 0, af4 INTEGER DEFAULT 0,
            af5 INTEGER DEFAULT 0, af6 INTEGER DEFAULT 0,
            cuatrimestre  TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS festivos_calendario (
            fecha TEXT PRIMARY KEY, tipo TEXT DEFAULT 'no_lectivo', descripcion TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS fichas_override (
            codigo TEXT NOT NULL, grupo_key TEXT NOT NULL DEFAULT '',
            motivo TEXT DEFAULT '', ts TEXT DEFAULT '',
            PRIMARY KEY (codigo, grupo_key)
        );
        CREATE TABLE IF NOT EXISTS finales_excluidas (
            periodo TEXT NOT NULL, curso TEXT NOT NULL, asig_codigo TEXT NOT NULL,
            asig_nombre TEXT DEFAULT '',
            PRIMARY KEY (periodo, curso, asig_codigo)
        );
        CREATE TABLE IF NOT EXISTS examenes_finales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL, curso TEXT NOT NULL, asig_nombre TEXT DEFAULT '',
            asig_codigo TEXT DEFAULT '', turno TEXT DEFAULT 'mañana',
            observacion TEXT DEFAULT '', auto_generated INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS asignaturas_destacadas (
            codigo TEXT NOT NULL, grupo_num TEXT NOT NULL DEFAULT '',
            act_type TEXT NOT NULL DEFAULT '', subgrupo TEXT NOT NULL DEFAULT '',
            modo INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (codigo, grupo_num, act_type, subgrupo)
        );
        CREATE TABLE IF NOT EXISTS comentarios_horario (
            grupo_key TEXT NOT NULL,
            comentario TEXT DEFAULT '',
            ts TEXT DEFAULT '',
            PRIMARY KEY (grupo_key)
        );
    """)
    conn.commit()


def generar_dtie_db(dtie_conn, src_conns, distribucion, estructura, log):
    """
    Genera la BD DTIE copiando clases de las BDs de origen.
    src_conns: [conn_a, conn_b]
    distribucion: [{codigo, fuente ('a'/'b'), grupo_num, nombre, curso_dtie,
                    cuatrimestre, creditos, af1, af2, af4}, ...]
    estructura: {cursos: [{g1c, g2c, aula}, ...]}  — de la UI del paso Estructura
    log: función log(msg, tipo)
    Devuelve lista de conflictos detectados.
    """
    fuente_idx = {'a': 0, 'b': 1}
    est_cursos = estructura.get('cursos', [])

    # Helper: número de grupos para (curso, cuat) según la estructura configurada
    def n_grupos_para(curso, cuat):
        idx = int(curso) - 1
        if idx < 0 or idx >= len(est_cursos):
            return 1  # fallback
        c = est_cursos[idx]
        n = int(c.get('g1c' if cuat == '1C' else 'g2c', 1))
        return max(1, n)  # al menos 1 grupo

    # 1. Franjas (de la fuente A)
    src_franjas = src_conns[0].execute(
        "SELECT label, orden FROM franjas ORDER BY orden"
    ).fetchall()
    for label, orden in src_franjas:
        dtie_conn.execute(
            "INSERT INTO franjas (label, orden) VALUES (?,?)", (label, orden)
        )
    dtie_conn.commit()
    log(f'  ✅ {len(src_franjas)} franjas copiadas de la fuente A', 'ok')

    # Mapa orden→id en la nueva BD
    new_franjas = dtie_conn.execute("SELECT id, orden FROM franjas").fetchall()
    orden_to_new_id = {orden: fid for fid, orden in new_franjas}

    # Mapa franja_id_src→new_franja_id para cada fuente
    franja_maps = []
    for i, src_conn in enumerate(src_conns):
        sf = src_conn.execute("SELECT id, orden FROM franjas").fetchall()
        franja_maps.append({sid: orden_to_new_id.get(orden, sid) for sid, orden in sf})

    # 2. Determinar (curso, cuatrimestre) únicos del DTIE
    cuats_por_curso = {}
    for d in distribucion:
        c = int(d['curso_dtie'])
        q = d['cuatrimestre']
        cuats_por_curso.setdefault(c, set()).add(q)

    # 3. Crear grupos: N por (curso, cuatrimestre) según estructura configurada
    #    grupo_id_map: (curso, cuat, grupo_num) → dtie_grupo_id
    #    también mantenemos (curso, cuat) → [lista de grupo_ids] para copiar clases a todos
    grupo_id_map = {}    # (curso, cuat, grupo_num_str) → dtie_grupo_id
    grupos_por_cc = {}   # (curso, cuat) → [dtie_grupo_id, ...]
    total_grupos = 0
    for curso in sorted(cuats_por_curso.keys()):
        for cuat in sorted(cuats_por_curso[curso]):
            n = n_grupos_para(curso, cuat)
            ids_este_cc = []
            for g in range(1, n + 1):
                clave = f"{curso}_{cuat}_grupo_{g}"
                cur = dtie_conn.execute(
                    "INSERT INTO grupos (curso, cuatrimestre, grupo, aula, clave) VALUES (?,?,?,?,?)",
                    (curso, cuat, str(g), '', clave)
                )
                gid = cur.lastrowid
                grupo_id_map[(curso, cuat, str(g))] = gid
                ids_este_cc.append(gid)
                total_grupos += 1
            grupos_por_cc[(curso, cuat)] = ids_este_cc
    dtie_conn.commit()
    log(f'  ✅ {total_grupos} grupos DTIE creados', 'ok')

    # 4. Copiar semanas desde la primera asignatura disponible de cada (curso, cuat)
    #    Las mismas semanas se replican en TODOS los grupos del (curso, cuat)
    semana_map = {}  # (dtie_grupo_id, semana_num) → dtie_semana_id
    for (curso, cuat), dtie_grupo_ids in grupos_por_cc.items():
        # Encontrar fuente para este (curso, cuat)
        src_conn = None
        src_grupo_clave = None
        for d in distribucion:
            if int(d['curso_dtie']) == curso and d['cuatrimestre'] == cuat:
                src_conn = src_conns[fuente_idx[d['fuente']]]
                src_grupo_clave = d.get('grupo_num', '')
                break

        if src_conn is None:
            continue

        # Buscar el grupo fuente con más clases del cuatrimestre indicado
        src_grupo = None
        if src_grupo_clave:
            src_grupo = src_conn.execute(
                "SELECT id FROM grupos WHERE clave = ?", (src_grupo_clave,)
            ).fetchone()
        if not src_grupo:
            src_grupo = src_conn.execute("""
                SELECT g.id FROM grupos g
                JOIN semanas s ON s.grupo_id = g.id
                JOIN clases c ON c.semana_id = s.id
                WHERE g.cuatrimestre = ?
                GROUP BY g.id ORDER BY COUNT(*) DESC LIMIT 1
            """, (cuat,)).fetchone()
        if not src_grupo:
            log(f'  ⚠️ No se encontró grupo para curso {curso} {cuat} en fuente', 'warn')
            continue

        src_grupo_id = src_grupo[0]
        semanas = src_conn.execute(
            "SELECT numero, descripcion FROM semanas WHERE grupo_id = ? ORDER BY numero",
            (src_grupo_id,)
        ).fetchall()

        # Replicar las mismas semanas en cada grupo DTIE de este (curso, cuat)
        for dtie_grupo_id in dtie_grupo_ids:
            for sem_num, sem_desc in semanas:
                cur = dtie_conn.execute(
                    "INSERT INTO semanas (grupo_id, numero, descripcion) VALUES (?,?,?)",
                    (dtie_grupo_id, sem_num, sem_desc)
                )
                semana_map[(dtie_grupo_id, sem_num)] = cur.lastrowid

        log(f'  ✅ {len(semanas)} semanas × {len(dtie_grupo_ids)} grupo(s) para curso {curso} {cuat}', 'ok')

    dtie_conn.commit()

    # 5. Copiar festivos del calendario de fuente A
    try:
        fest = src_conns[0].execute(
            "SELECT fecha, tipo, descripcion FROM festivos_calendario"
        ).fetchall()
        for row in fest:
            dtie_conn.execute(
                "INSERT OR IGNORE INTO festivos_calendario (fecha, tipo, descripcion) VALUES (?,?,?)",
                row
            )
        dtie_conn.commit()
        if fest:
            log(f'  ✅ {len(fest)} festivos de calendario copiados', 'ok')
    except Exception:
        pass  # tabla puede no existir en fuente

    # 6. Insertar asignaturas y fichas
    asig_id_map = {}  # codigo → new asig_id
    for d in distribucion:
        codigo    = d['codigo']
        curso_dtie = int(d['curso_dtie'])
        cuat      = d['cuatrimestre']
        cur = dtie_conn.execute(
            "INSERT INTO asignaturas (codigo, nombre, curso, cuatrimestre) VALUES (?,?,?,?)",
            (codigo, d['nombre'], curso_dtie, cuat)
        )
        asig_id = cur.lastrowid
        asig_id_map[codigo] = asig_id

        dtie_conn.execute(
            "INSERT OR REPLACE INTO fichas (asignatura_id, creditos, af1, af2, af4, af5, af6) "
            "VALUES (?,?,?,?,?,?,?)",
            (asig_id,
             float(d.get('creditos') or 0),
             int(d.get('af1') or 0),
             int(d.get('af2') or 0),
             int(d.get('af4') or 0),
             int(d.get('af5') or 0),
             int(d.get('af6') or 0))
        )
        # Marcar como destacada en todos los grupos DTIE del (curso, cuat)
        for gid_this in grupos_por_cc.get((curso_dtie, cuat), []):
            # Obtener clave del grupo
            g_row = dtie_conn.execute(
                "SELECT clave FROM grupos WHERE id = ?", (gid_this,)
            ).fetchone()
            if g_row:
                dtie_conn.execute(
                    "INSERT OR IGNORE INTO asignaturas_destacadas (codigo, grupo_num) VALUES (?,?)",
                    (codigo, g_row[0])
                )

    dtie_conn.commit()
    log(f'  ✅ {len(distribucion)} asignaturas insertadas', 'ok')

    # 7. Copiar clases — se replican en TODOS los grupos del (curso, cuat)
    conflicts = []
    slot_map  = {}   # (dtie_grupo_id, sem_num, dia, new_franja_id) → codigo
    total_clases = 0

    for d in distribucion:
        codigo     = d['codigo']
        fidx       = fuente_idx[d['fuente']]
        curso_dtie = int(d['curso_dtie'])
        cuat       = d['cuatrimestre']

        src_conn        = src_conns[fidx]
        dtie_grupo_ids  = grupos_por_cc.get((curso_dtie, cuat), [])
        new_asig_id     = asig_id_map.get(codigo)

        if not dtie_grupo_ids or new_asig_id is None:
            log(f'  ⚠️ Sin grupo/asig DTIE para {codigo}, se omite', 'warn')
            continue

        # Buscar asignatura en fuente
        src_asig = src_conn.execute(
            "SELECT id FROM asignaturas WHERE codigo = ?", (codigo,)
        ).fetchone()
        if not src_asig:
            log(f'  ⚠️ Asignatura {codigo} no encontrada en fuente {d["fuente"].upper()}', 'warn')
            continue

        src_asig_id = src_asig[0]

        # Buscar el grupo fuente: primero por grupo_num indicado, luego por más clases
        grupo_num_str = str(d.get('grupo_num', '')).strip()
        src_grupo_id = None
        if grupo_num_str:
            # Intento 1: clave exacta (por si el usuario escribió la clave completa)
            row = src_conn.execute(
                "SELECT g.id FROM grupos g "
                "JOIN semanas s ON s.grupo_id = g.id "
                "JOIN clases c ON c.semana_id = s.id "
                "WHERE c.asignatura_id = ? AND g.clave = ? "
                "GROUP BY g.id LIMIT 1",
                (src_asig_id, grupo_num_str)
            ).fetchone()
            if row:
                src_grupo_id = row[0]
            else:
                # Intento 2: clave que termina en _grupo_{N}
                row = src_conn.execute(
                    "SELECT g.id FROM grupos g "
                    "JOIN semanas s ON s.grupo_id = g.id "
                    "JOIN clases c ON c.semana_id = s.id "
                    "WHERE c.asignatura_id = ? AND g.clave LIKE ? "
                    "GROUP BY g.id LIMIT 1",
                    (src_asig_id, f'%_grupo_{grupo_num_str}')
                ).fetchone()
                if row:
                    src_grupo_id = row[0]

        if src_grupo_id is None:
            # Fallback: grupo con más clases de esta asignatura
            best = src_conn.execute("""
                SELECT g.id, COUNT(*) AS cnt
                FROM clases c
                JOIN semanas s ON s.id = c.semana_id
                JOIN grupos g ON g.id = s.grupo_id
                WHERE c.asignatura_id = ? AND c.es_no_lectivo = 0
                GROUP BY g.id ORDER BY cnt DESC LIMIT 1
            """, (src_asig_id,)).fetchone()
            if not best:
                log(f'  ⚠️ Sin clases para {codigo} en fuente {d["fuente"].upper()}, se omite', 'warn')
                continue
            src_grupo_id = best[0]
        franja_map   = franja_maps[fidx]

        clases = src_conn.execute("""
            SELECT c.dia, c.franja_id, c.aula, c.subgrupo, c.observacion,
                   c.es_no_lectivo, c.contenido, s.numero
            FROM clases c
            JOIN semanas s ON s.id = c.semana_id
            WHERE s.grupo_id = ? AND c.asignatura_id = ?
        """, (src_grupo_id, src_asig_id)).fetchall()

        # Filtrar subgrupos: copiar solo los subgrupos marcados como destacados
        # en la BD origen para este (codigo, grupo_num). Esto evita que se
        # copien todos los subgrupos de prácticas cuando el usuario solo marcó uno.
        if grupo_num_str:
            starred_rows = src_conn.execute(
                "SELECT DISTINCT subgrupo FROM asignaturas_destacadas "
                "WHERE codigo = ? AND grupo_num = ?",
                (codigo, grupo_num_str)
            ).fetchall()
            starred_subgrupos = {r[0] for r in starred_rows}
            if starred_subgrupos:
                # c[3] = subgrupo en el SELECT anterior
                clases = [c for c in clases if c[3] in starred_subgrupos]

        # Insertar clases en CADA grupo DTIE del (curso, cuat)
        n_copied = 0
        for dtie_grupo_id in dtie_grupo_ids:
            for dia, src_franja_id, aula, subgrupo, observacion, es_no_lectivo, contenido, sem_num in clases:
                dtie_semana_id = semana_map.get((dtie_grupo_id, sem_num))
                if dtie_semana_id is None:
                    continue

                new_franja_id = franja_map.get(src_franja_id, src_franja_id)

                # Conflict detection (solo en el primer grupo, para no duplicar alertas)
                if not es_no_lectivo and dtie_grupo_id == dtie_grupo_ids[0]:
                    slot_key = (dtie_grupo_id, sem_num, dia, new_franja_id)
                    if slot_key in slot_map:
                        prev = slot_map[slot_key]
                        if prev != codigo:
                            conf_key = tuple(sorted([prev, codigo])) + (sem_num, dia, new_franja_id)
                            if conf_key not in {tuple(sorted([c['asig1'], c['asig2']])) +
                                                (c['semana'], c['dia'], new_franja_id) for c in conflicts}:
                                conflicts.append({
                                    'semana': sem_num, 'dia': dia,
                                    'asig1': prev, 'asig2': codigo
                                })
                    else:
                        slot_map[slot_key] = codigo

                dtie_conn.execute("""
                    INSERT INTO clases
                        (semana_id, dia, franja_id, asignatura_id, aula, subgrupo,
                         observacion, es_no_lectivo, contenido)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (dtie_semana_id, dia, new_franja_id, new_asig_id,
                      aula or '', subgrupo or '', observacion or '',
                      es_no_lectivo or 0, contenido or ''))
                n_copied += 1

        total_clases += n_copied

    dtie_conn.commit()
    log(f'  ✅ {total_clases} clases copiadas en total', 'ok')

    return conflicts


def api_csvs_dtie(_=None):
    """Lista los ficheros fichas_DTIE_*.csv disponibles en config/."""
    config_dir = BASE_DIR / 'config'
    result = []
    if config_dir.exists():
        for f in sorted(config_dir.glob('fichas_DTIE_*.csv')):
            result.append({'name': f.name, 'path': str(f.relative_to(BASE_DIR))})
    return {'csvs': result}


def api_resolver_csv_dtie(data):
    """
    Enriquece filas CSV de distribución DTIE con fichas y schedules
    leídos desde las BDs de los grados de origen.

    Acepta:
      csv_rows: [{"codigo","nombre","grado_origen","curso_dtie","cuatrimestre","grupo_origen"}, ...]
      csv_path: ruta relativa a un CSV en el servidor (alternativa a csv_rows)
      fuentes:  [{"db_path": "horarios/GIM/horarios.db"}, {"db_path": "horarios/GIDI/horarios.db"}]
    """
    import csv as _csv

    try:
      return _api_resolver_csv_dtie_impl(data)
    except Exception:
      return {'ok': False, 'error': traceback.format_exc()}


def _api_resolver_csv_dtie_impl(data):
    import csv as _csv

    fuentes = data.get('fuentes', [{}, {}])

    # ── Leer filas del CSV ────────────────────────────────────────────────────
    # Campos fijos del CSV DTIE — 'nombre' en índice 1 puede contener comas sin escapar
    _FIELDNAMES = ['codigo', 'nombre', 'grado_origen', 'curso_dtie', 'cuatrimestre', 'grupo_origen']
    _N_COLS = len(_FIELDNAMES)

    def _parse_dtie_row(raw_values):
        """Reconstruye una fila aunque 'nombre' tenga comas sin escapar."""
        n_extra = len(raw_values) - _N_COLS
        if n_extra > 0:
            raw_values = [raw_values[0],
                          ','.join(raw_values[1:2 + n_extra]),
                          *raw_values[2 + n_extra:]]
        return dict(zip(_FIELDNAMES, raw_values))

    csv_path_str = data.get('csv_path')
    if csv_path_str:
        csv_file = BASE_DIR / csv_path_str
        if not csv_file.exists():
            return {'ok': False, 'error': f'No se encuentra {csv_path_str}'}
        with open(csv_file, encoding='utf-8-sig', newline='') as f:
            reader = _csv.reader(f)
            header = next(reader, None)   # descartar cabecera
            if header is None:
                return {'ok': False, 'error': 'CSV vacío.'}
            csv_rows = [_parse_dtie_row(row) for row in reader if any(row)]
    else:
        csv_rows = data.get('csv_rows', [])

    if not csv_rows:
        return {'ok': False, 'error': 'No hay filas en el CSV.'}

    # ── Conectar a las BDs fuente y mapear siglas → clave (a/b) ──────────────
    fuente_map    = {}   # siglas_upper → 'a' | 'b'
    conns         = {}   # 'a' | 'b'  → sqlite3.Connection
    asig_col_sets = {}   # 'a' | 'b'  → set of column names in asignaturas

    for key, f in zip(['a', 'b'], fuentes):
        db_path_str = f.get('db_path', '')
        if not db_path_str:
            continue
        db_path = resolve_db_path(db_path_str)
        if not db_path.exists():
            continue
        # Siglas desde config.json o nombre de carpeta
        cfg_path = db_path.parent / 'config.json'
        try:
            with open(cfg_path, encoding='utf-8') as fp:
                cfg = json.load(fp)
            siglas = cfg.get('degree', {}).get('acronym', db_path.parent.name)
        except Exception:
            siglas = db_path.parent.name
        fuente_map[siglas.upper()]              = key
        fuente_map[db_path.parent.name.upper()] = key  # fallback por carpeta
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            conns[key] = conn
            # Detectar columnas disponibles en asignaturas (varía según BD)
            asig_col_sets[key] = {
                r[1] for r in conn.execute("PRAGMA table_info(asignaturas)").fetchall()
            }
        except Exception:
            pass

    # Normalización de cuatrimestre: C1→1C, C2→2C; el resto pasa tal cual (A, I…)
    _CUAT_MAP = {'C1': '1C', 'C2': '2C', 'c1': '1C', 'c2': '2C',
                 '1C': '1C', '2C': '2C'}

    rows_out  = []
    schedules = {'a': {}, 'b': {}}
    warnings  = []

    for row in csv_rows:
        codigo     = str(row.get('codigo', '')).strip()
        nombre_csv = str(row.get('nombre', '')).strip()
        grado_orig = str(row.get('grado_origen', '')).strip().upper()
        try:
            curso_dtie = int(row.get('curso_dtie', 1) or 1)
        except (ValueError, TypeError):
            curso_dtie = 1
        cuat_raw     = str(row.get('cuatrimestre', '1C')).strip()
        cuatrimestre = _CUAT_MAP.get(cuat_raw, cuat_raw)
        grupo_orig   = str(row.get('grupo_origen', '')).strip()

        fuente = fuente_map.get(grado_orig)

        base_row = {
            'codigo': codigo, 'nombre': nombre_csv, 'grado_origen': grado_orig,
            'fuente': fuente or 'a', 'fuente_label': (fuente or 'a').upper(),
            'curso_dtie': curso_dtie, 'cuatrimestre': cuatrimestre,
            'grupo_num': grupo_orig,
            'curso_origen': None, 'cuatrimestre_origen': None,
            'creditos': 6, 'af1': 0, 'af2': 0, 'af4': 0, 'af5': 0, 'af6': 0,
        }

        if fuente not in conns:
            warnings.append(f'Grado "{grado_orig}" no cargado — {codigo} sin enriquecer.')
            rows_out.append({**base_row, 'found': False})
            continue

        conn = conns[fuente]
        a_cols = asig_col_sets.get(fuente, set())

        # Buscar asignatura por código — adaptar SELECT a columnas disponibles
        extra_cols = ', '.join(
            c for c in ('curso', 'cuatrimestre') if c in a_cols
        )
        select_asig = f"SELECT id, nombre{', ' + extra_cols if extra_cols else ''} FROM asignaturas WHERE codigo = ?"
        asig = conn.execute(select_asig, (codigo,)).fetchone()

        if not asig:
            warnings.append(f'Código {codigo} no encontrado en {grado_orig}.')
            rows_out.append({**base_row, 'found': False})
            continue

        asig_id      = asig['id']
        curso_origen = asig['curso']        if 'curso'        in a_cols else None
        cuat_origen  = asig['cuatrimestre'] if 'cuatrimestre' in a_cols else None

        # Comprobar si está marcada como destacada (⭐) en la BD de origen
        has_dest_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='asignaturas_destacadas'"
        ).fetchone()
        if has_dest_table:
            es_destacada = conn.execute(
                "SELECT 1 FROM asignaturas_destacadas WHERE codigo = ? LIMIT 1", (codigo,)
            ).fetchone() is not None
        else:
            es_destacada = False

        # Fichas docentes
        ficha = conn.execute(
            "SELECT creditos, af1, af2, af4, af5, af6 FROM fichas WHERE asignatura_id = ?",
            (asig_id,)
        ).fetchone()

        # Grupo para el schedule: primero por grupo_origen, luego el de más clases
        grupo_id = None
        if grupo_orig:
            g = conn.execute("""
                SELECT g.id, g.curso, g.cuatrimestre FROM grupos g
                JOIN semanas s ON s.grupo_id = g.id
                JOIN clases c  ON c.semana_id = s.id
                JOIN asignaturas a ON a.id = c.asignatura_id
                WHERE a.codigo = ? AND g.grupo = ? AND c.es_no_lectivo = 0
                GROUP BY g.id ORDER BY COUNT(*) DESC LIMIT 1
            """, (codigo, grupo_orig)).fetchone()
            if g:
                grupo_id = g[0]
                if curso_origen is None: curso_origen = g[1]
                if cuat_origen  is None: cuat_origen  = g[2]
        if not grupo_id:
            g = conn.execute("""
                SELECT g.id, g.curso, g.cuatrimestre FROM grupos g
                JOIN semanas s ON s.grupo_id = g.id
                JOIN clases c  ON c.semana_id = s.id
                JOIN asignaturas a ON a.id = c.asignatura_id
                WHERE a.codigo = ? AND c.es_no_lectivo = 0
                GROUP BY g.id ORDER BY COUNT(*) DESC LIMIT 1
            """, (codigo,)).fetchone()
            if g:
                grupo_id = g[0]
                if curso_origen is None: curso_origen = g[1]
                if cuat_origen  is None: cuat_origen  = g[2]

        # Schedule comprimido para conflict detection
        sched = []
        if grupo_id:
            clases = conn.execute("""
                SELECT s.numero AS sem, c.dia, c.franja_id AS fr, f.label AS fl
                FROM clases c
                JOIN semanas s ON s.id = c.semana_id
                JOIN asignaturas a ON a.id = c.asignatura_id
                JOIN franjas f ON f.id = c.franja_id
                WHERE s.grupo_id = ? AND a.codigo = ? AND c.es_no_lectivo = 0
            """, (grupo_id, codigo)).fetchall()
            sched = [{'sem': r['sem'], 'dia': r['dia'], 'fr': r['fr'], 'fl': r['fl']} for r in clases]
        schedules[fuente][codigo] = sched

        rows_out.append({
            **base_row,
            'nombre':             asig['nombre'] or nombre_csv,
            'curso_origen':       curso_origen,
            'cuatrimestre_origen': cuat_origen,
            'creditos': ficha['creditos'] if ficha else 6,
            'af1':      ficha['af1']      if ficha else 0,
            'af2':      ficha['af2']      if ficha else 0,
            'af4':      ficha['af4']      if ficha else 0,
            'af5':      ficha['af5']      if ficha else 0,
            'af6':      ficha['af6']      if ficha else 0,
            'found':      True,
            'destacada':  es_destacada,
        })

    for conn in conns.values():
        try:
            conn.close()
        except Exception:
            pass

    return {'ok': True, 'rows': rows_out, 'schedules': schedules, 'warnings': warnings}


def build_config_dtie(data, src_configs):
    """Genera config.json para el grado DTIE."""
    b  = data['basico']
    ap = data.get('apariencia', {})
    siglas = b['siglas'].upper().strip()

    # ── Estructura desde el payload (paso 3) ────────────────────────────────
    estructura = data.get('estructura', {})
    est_cursos = estructura.get('cursos', [])

    # Si no hay estructura definida, derivarla de la distribución (compatibilidad)
    dist = data['distribucion']
    if est_cursos:
        grupos_por_curso = {}
        for i, c in enumerate(est_cursos, start=1):
            cs = str(i)
            grupos_por_curso[cs] = {
                '1C': max(0, int(c.get('g1c', 1))),
                '2C': max(0, int(c.get('g2c', 1))),
            }
        num_cursos = len(est_cursos)
    else:
        # Fallback: un grupo por (curso, cuatrimestre) existente en la distribución
        cuats_por_curso = {}
        for d in dist:
            c = str(int(d['curso_dtie']))
            q = d['cuatrimestre']
            cuats_por_curso.setdefault(c, set()).add(q)
        grupos_por_curso = {}
        for c, cuats in cuats_por_curso.items():
            grupos_por_curso[c] = {
                '1C': 1 if '1C' in cuats else 0,
                '2C': 1 if '2C' in cuats else 0,
            }
        num_cursos = len(cuats_por_curso)

    # Índice del grado principal (A=0, B=1)
    principal_idx = 1 if data.get('grado_principal', 'a') == 'b' else 0

    # Franjas del grado principal (si disponible)
    franjas = []
    if src_configs and len(src_configs) > principal_idx and src_configs[principal_idx]:
        franjas = src_configs[principal_idx].get('degree_structure', {}).get('franjas', [])

    # Activity types heredados del grado principal
    activity_types = {}
    if src_configs and len(src_configs) > principal_idx and src_configs[principal_idx]:
        activity_types = src_configs[principal_idx].get('activity_types', {})
    if not activity_types:
        activity_types = {
            'AF1': {'label': 'Teoría', 'aula_exact': [''], 'aula_startswith': []},
            'AF2': {'label': 'Laboratorio', 'aula_exact': ['LAB'], 'aula_startswith': []},
            'AF4': {'label': 'Informática', 'aula_exact': [], 'aula_startswith': ['INFO', 'Aula:']},
            'AF5': {'fichas_only': True},
            'AF6': {'fichas_only': True},
        }

    fuentes_info = []
    for i, f in enumerate(data.get('fuentes', [])):
        fuentes_info.append({'db_path': f['db_path'], 'grado_nombre': f.get('grado_nombre', '')})

    degree_structure = {
        'num_cursos':        num_cursos,
        'num_semanas':       16,
        'grupos_por_curso':  grupos_por_curso,
        'franjas':           franjas,
    }

    return {
        '_comment': f'Configuración DTIE — {siglas} (generado por nuevo_dtie.py)',
        'dtie': True,
        'dtie_grado_principal': data.get('grado_principal', 'a'),
        'dtie_fuentes': fuentes_info,
        'institution': {
            'name':     b.get('institucion', ''),
            'acronym':  b.get('siglas_inst', ''),
            'logo_png': 'docs/logo_upct.png',
            'logo_pdf': 'docs/logo.pdf',
        },
        'degree': {'name': b.get('nombre', ''), 'acronym': siglas},
        'server': {
            'port':        int(b.get('puerto', 8082)),
            'db_name':     'horarios.db',
            'curso_label': b.get('curso_label', ''),
        },
        'degree_structure': degree_structure,
        'branding': {
            'primary':       ap.get('primary', '#6b1a3a'),
            'primary_light': ap.get('primary_light', '#8b2a52'),
            'accent':        ap.get('accent', '#e8a020'),
            'bg':            ap.get('bg', '#f0f4f8'),
        },
        'activity_types': activity_types,
        'ui': {
            'destacadas_badge': b.get('badge', 'DTIE'),
            'export_prefix':    siglas,
        },
        'calendario': {},  # no se usa (semanas copiadas de origen)
    }


def generar_launchers_dtie(grado_dir: Path, siglas: str, cfg: dict):
    """Genera launchers .command/.bat/.sh para el grado DTIE."""
    port        = cfg['server']['port']
    db_name     = cfg['server']['db_name']
    curso_label = cfg['server']['curso_label']
    db_stem     = db_name.replace('.db', '')

    command_content = f"""#!/bin/bash
# Launcher DTIE — {siglas} ({curso_label})
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
DB_SRC="$DIR/{db_name}"
DB_TMP="/tmp/{db_stem}_{siglas}.db"

cp "$DB_SRC" "$DB_TMP" 2>/dev/null || true

cleanup() {{
  kill "$SERVER_PID" 2>/dev/null
  wait "$SERVER_PID" 2>/dev/null
  if [ -f "$DB_TMP" ]; then
    cp "$DB_TMP" "$DB_SRC"
    echo "Base de datos guardada."
  fi
}}
trap cleanup EXIT INT TERM HUP

DB_PATH_OVERRIDE="$DB_TMP" CURSO_LABEL="{curso_label}" CONFIG_PATH_OVERRIDE="$DIR" \\
  python3 "$ROOT/servidor_horarios.py" \\
  --grado "horarios/{siglas}" &
SERVER_PID=$!

sleep 1.5 && open "http://localhost:{port}"
wait "$SERVER_PID"
"""
    cmd_path = grado_dir / f'Iniciar {siglas}.command'
    cmd_path.write_text(command_content, encoding='utf-8')
    cmd_path.chmod(0o755)

    bat_content = f"""@echo off
REM Launcher DTIE — {siglas} ({curso_label})
set DIR=%~dp0
set ROOT=%DIR%..\\..
set DB_SRC=%DIR%{db_name}
set DB_TMP=%TEMP%\\{db_stem}_{siglas}.db
copy /Y "%DB_SRC%" "%DB_TMP%" >nul 2>&1
set DB_PATH_OVERRIDE=%DB_TMP%
set CURSO_LABEL={curso_label}
set CONFIG_PATH_OVERRIDE=%DIR%
start "" "http://localhost:{port}"
python "%ROOT%\\servidor_horarios.py" --grado "horarios/{siglas}"
copy /Y "%DB_TMP%" "%DB_SRC%" >nul 2>&1
echo Base de datos guardada.
pause
"""
    (grado_dir / f'Iniciar {siglas}.bat').write_text(bat_content, encoding='utf-8')

    sh_content = f"""#!/bin/bash
# Launcher DTIE — {siglas} ({curso_label})
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
DB_SRC="$DIR/{db_name}"
DB_TMP="/tmp/{db_stem}_{siglas}.db"

cp "$DB_SRC" "$DB_TMP" 2>/dev/null || true

cleanup() {{
  kill "$SERVER_PID" 2>/dev/null
  wait "$SERVER_PID" 2>/dev/null
  [ -f "$DB_TMP" ] && cp "$DB_TMP" "$DB_SRC" && echo "BD guardada."
}}
trap cleanup EXIT INT TERM HUP

DB_PATH_OVERRIDE="$DB_TMP" CURSO_LABEL="{curso_label}" CONFIG_PATH_OVERRIDE="$DIR" \\
  python3 "$ROOT/servidor_horarios.py" --grado "horarios/{siglas}" &
SERVER_PID=$!

sleep 1.5 && (xdg-open "http://localhost:{port}" 2>/dev/null || true)
wait "$SERVER_PID"
"""
    sh_path = grado_dir / f'iniciar_{siglas.lower()}.sh'
    sh_path.write_text(sh_content, encoding='utf-8')
    sh_path.chmod(0o755)


def api_crear_dtie(data):
    """Endpoint principal: crea la carpeta y BD del DTIE."""
    output_lines = []

    def log(msg, tipo=''):
        output_lines.append(msg)
        print(msg)

    try:
        siglas = data['basico']['siglas'].upper().strip()
        if not siglas:
            return {'ok': False, 'error': 'Las siglas no pueden estar vacías.'}

        distribucion = data.get('distribucion', [])
        if not distribucion:
            return {'ok': False, 'error': 'La distribución está vacía.'}

        fuentes   = data.get('fuentes', [{}, {}])
        db_path_a = resolve_db_path(fuentes[0].get('db_path', ''))
        db_path_b = resolve_db_path(fuentes[1].get('db_path', ''))

        for label, p in [('Fuente A', db_path_a), ('Fuente B', db_path_b)]:
            if not p or not p.exists():
                return {'ok': False, 'error': f'{label}: no se encuentra {p}'}

        log(f'Abriendo BDs de origen…', 'info')
        conn_a = sqlite3.connect(str(db_path_a))
        conn_b = sqlite3.connect(str(db_path_b))
        src_conns = [conn_a, conn_b]

        # Leer configs de origen
        src_configs = []
        for p in [db_path_a, db_path_b]:
            cfg_p = p.parent / 'config.json'
            try:
                with open(cfg_p, encoding='utf-8') as f:
                    src_configs.append(json.load(f))
            except Exception:
                src_configs.append(None)

        # Crear carpeta
        grado_dir = BASE_DIR / 'horarios' / siglas
        grado_dir.mkdir(parents=True, exist_ok=True)
        log(f'Carpeta destino: {grado_dir}', 'info')

        # Generar config.json
        cfg = build_config_dtie(data, src_configs)
        cfg_path = grado_dir / 'config.json'
        with open(cfg_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        log('  ✅ config.json generado', 'ok')

        # Generar CSV de asignaturas (mismo formato que grado convencional)
        import csv as _csv
        csv_path = grado_dir / f'asignaturas_{siglas}.csv'
        fields = ['codigo', 'nombre', 'curso', 'cuatrimestre', 'creditos', 'af1', 'af2', 'af4', 'af5', 'af6']
        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            w = _csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for d in distribucion:
                w.writerow({
                    'codigo':       d['codigo'],
                    'nombre':       d['nombre'],
                    'curso':        int(d['curso_dtie']),
                    'cuatrimestre': d['cuatrimestre'],
                    'creditos':     float(d.get('creditos') or 0),
                    'af1':          int(d.get('af1') or 0),
                    'af2':          int(d.get('af2') or 0),
                    'af4':          int(d.get('af4') or 0),
                    'af5':          int(d.get('af5') or 0),
                    'af6':          int(d.get('af6') or 0),
                })
        log(f'  ✅ {csv_path.name} generado ({len(distribucion)} asignaturas)', 'ok')

        # Crear BD DTIE
        db_path = grado_dir / 'horarios.db'
        if db_path.exists():
            db_path.unlink()
        dtie_conn = sqlite3.connect(str(db_path))
        dtie_conn.execute("PRAGMA foreign_keys = ON")

        log('Creando tablas…', 'info')
        create_tables_dtie(dtie_conn)

        log('Copiando datos de origen…', 'info')
        estructura = data.get('estructura', {})
        conflicts = generar_dtie_db(dtie_conn, src_conns, distribucion, estructura, log)

        dtie_conn.close()
        conn_a.close()
        conn_b.close()

        # Marcar la BD DTIE como actualizada al esquema más reciente
        try:
            from migrate_db import stamp as _stamp_db
            _stamp_db(str(db_path))
        except ImportError:
            pass  # el servidor aplicará migraciones al arrancar

        # Reportar conflictos
        if conflicts:
            log(f'\n⚠️ Se detectaron {len(conflicts)} solapamientos horarios:', 'warn')
            for c in conflicts[:20]:  # máximo 20 en consola
                log(f'   Sem {c["semana"]} {c["dia"]}: {c["asig1"]} ↔ {c["asig2"]}', 'warn')
            if len(conflicts) > 20:
                log(f'   … y {len(conflicts)-20} más.', 'warn')
        else:
            log('\n✅ Sin solapamientos horarios detectados.', 'ok')

        # Launchers
        generar_launchers_dtie(grado_dir, siglas, cfg)
        log('  ✅ Launchers generados (.command / .bat / .sh)', 'ok')

        log(f'\n✅ Grado DTIE "{siglas}" creado en {grado_dir}', 'ok')

        return {
            'ok':        True,
            'output':    '\n'.join(output_lines),
            'grado_dir': str(grado_dir),
            'conflicts': conflicts,
        }

    except Exception:
        tb = traceback.format_exc()
        return {
            'ok':       False,
            'output':   '\n'.join(output_lines),
            'error':    str(tb).split('\n')[-2],
            'traceback': tb,
        }


# ─────────────────────────────────────────────────────────────────────────────
# HTTP SERVER
# ─────────────────────────────────────────────────────────────────────────────

class DtieHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path in ('/', '/nuevo'):
            self._html(WIZARD_HTML)
        elif self.path == '/api/ping':
            self._json({'ok': True})
        elif self.path == '/api/grados':
            self._json(api_grados())
        elif self.path == '/api/titulaciones':
            tit_path = BASE_DIR / 'config' / 'titulaciones.json'
            if tit_path.exists():
                self._json(json.loads(tit_path.read_text('utf-8')))
            else:
                self._json([])
        elif self.path == '/api/csvs_dtie':
            self._json(api_csvs_dtie())
        elif self.path == '/api/classrooms':
            cl_path = BASE_DIR / 'config' / 'classrooms.json'
            if cl_path.exists():
                self._json(json.loads(cl_path.read_text('utf-8')))
            else:
                self._json([])
        elif self.path == '/api/logo_svg':
            self._serve_file(BASE_DIR / 'docs' / 'logo_janux.svg', 'image/svg+xml')
        else:
            self._404()

    def do_POST(self):
        data = self._read_json()
        if self.path == '/api/leer_dtie':
            self._json(api_leer_dtie(data))
        elif self.path == '/api/crear_dtie':
            self._json(api_crear_dtie(data))
        elif self.path == '/api/resolver_csv_dtie':
            self._json(api_resolver_csv_dtie(data))
        else:
            self._404()

    def _read_json(self):
        n = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(n))

    def _html(self, content):
        b = content.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(b))
        self.end_headers()
        self.wfile.write(b)

    def _json(self, obj):
        b = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(b))
        self.end_headers()
        self.wfile.write(b)

    def _serve_file(self, path, ctype):
        try:
            data = Path(path).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', len(data))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self._404()

    def _404(self):
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # silenciar logs HTTP


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    server = HTTPServer(('localhost', PORT), DtieHandler)
    url    = f'http://localhost:{PORT}'

    def open_browser():
        import time
        time.sleep(0.8)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()

    print(f'')
    print(f'  ╔══════════════════════════════════════════╗')
    print(f'  ║   Wizard DTIE — Gestor de Horarios       ║')
    print(f'  ║   {url:<40} ║')
    print(f'  ╚══════════════════════════════════════════╝')
    print(f'')
    print(f'  Abre el navegador en {url}')
    print(f'  Pulsa Ctrl+C para detener.')
    print(f'')

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nServidor detenido.')


if __name__ == '__main__':
    main()
