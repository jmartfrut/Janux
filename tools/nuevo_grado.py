#!/usr/bin/env python3
"""
nuevo_grado.py — Wizard para crear un nuevo grado en el Gestor de Horarios.

Uso:
    python3 nuevo_grado.py
    → Abre http://localhost:8091 con el asistente completo.

El wizard recoge todos los datos necesarios (estructura, franjas, calendario,
actividades, asignaturas) y genera la carpeta grados/<SIGLAS>/ con:
    config.json, asignaturas_<SIGLAS>.csv, horarios.db, launchers
"""

import csv
import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT = 8092
BASE_DIR = Path(__file__).parent.parent  # raíz del proyecto (tools/../)

# ─────────────────────────────────────────────────────────────────────────────
# HTML WIZARD
# ─────────────────────────────────────────────────────────────────────────────

WIZARD_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nuevo Grado — Gestor de Horarios</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#f0f4f8;color:#1a2a3a;min-height:100vh}
/* HEADER */
.top-bar{background:#1a3a6b;color:#fff;padding:14px 32px;display:flex;align-items:center;gap:12px}
.top-bar h1{font-size:1.15rem;font-weight:600;letter-spacing:.3px}
.top-bar .sub{font-size:.82rem;opacity:.7;margin-top:1px}
/* STEPPER */
.stepper{display:flex;align-items:center;justify-content:center;gap:0;padding:20px 24px 0;flex-wrap:wrap;row-gap:8px}
.step{display:flex;align-items:center;gap:0}
.step-circle{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:.78rem;font-weight:700;border:2px solid #c8d4e0;background:#fff;color:#8a9ab0;transition:all .2s;flex-shrink:0}
.step-label{font-size:.72rem;color:#8a9ab0;margin:0 6px;white-space:nowrap;transition:color .2s}
.step-line{width:28px;height:2px;background:#c8d4e0;transition:background .2s;flex-shrink:0}
.step.active .step-circle{background:#1a3a6b;border-color:#1a3a6b;color:#fff}
.step.active .step-label{color:#1a3a6b;font-weight:600}
.step.done .step-circle{background:#22863a;border-color:#22863a;color:#fff}
.step.done .step-label{color:#22863a}
.step.done + .step-line,.step.active + .step-line{background:#1a3a6b}
/* CARD */
.card{background:#fff;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.07);max-width:820px;margin:20px auto 40px;padding:32px 36px}
.card h2{font-size:1.1rem;font-weight:700;color:#1a3a6b;margin-bottom:6px}
.card .desc{font-size:.83rem;color:#6a7a8a;margin-bottom:24px}
/* FORM ELEMENTS */
.field{margin-bottom:18px}
.field label{display:block;font-size:.8rem;font-weight:600;color:#3a4a5a;margin-bottom:5px;text-transform:uppercase;letter-spacing:.4px}
.field input[type=text],.field input[type=number],.field input[type=date],.field select,.field input[type=color]{width:100%;padding:8px 11px;border:1px solid #c8d4e0;border-radius:7px;font-size:.9rem;background:#fff;color:#1a2a3a;transition:border .15s}
.field input:focus,.field select:focus{outline:none;border-color:#1a3a6b;box-shadow:0 0 0 3px rgba(26,58,107,.1)}
.field input[type=color]{padding:4px;height:38px;cursor:pointer}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}
/* TABLES */
.tbl-wrap{overflow-x:auto;margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:.83rem}
th{background:#f0f4f8;color:#3a4a5a;font-weight:600;padding:7px 10px;text-align:left;border-bottom:2px solid #c8d4e0;white-space:nowrap}
td{padding:5px 6px;border-bottom:1px solid #e8eef4;vertical-align:middle}
td input[type=text],td input[type=number],td input[type=date],td select{width:100%;border:1px solid #dde5ee;border-radius:5px;padding:4px 7px;font-size:.82rem;background:#fff}
td input:focus,td select:focus{outline:none;border-color:#1a3a6b}
.td-btn{width:36px;text-align:center}
.btn-del{background:none;border:none;color:#c0392b;font-size:1rem;cursor:pointer;padding:2px 6px;border-radius:4px}
.btn-del:hover{background:#fdecea}
/* BUTTONS */
.actions{display:flex;align-items:center;justify-content:space-between;margin-top:28px;gap:12px}
.btn{padding:9px 22px;border-radius:8px;font-size:.88rem;font-weight:600;cursor:pointer;border:none;transition:all .15s}
.btn-primary{background:#1a3a6b;color:#fff}
.btn-primary:hover{background:#2855a0}
.btn-secondary{background:#e8eef4;color:#3a4a5a}
.btn-secondary:hover{background:#d0dae6}
.btn-outline{background:#fff;color:#1a3a6b;border:1.5px solid #1a3a6b}
.btn-outline:hover{background:#f0f4f8}
.btn-green{background:#22863a;color:#fff}
.btn-green:hover{background:#196b2e}
.btn:disabled{opacity:.5;cursor:not-allowed}
.btn-add{background:#eef4ff;color:#1a3a6b;border:1.5px dashed #7a9acb;font-size:.8rem;padding:5px 14px;border-radius:6px;cursor:pointer}
.btn-add:hover{background:#dce8f8}
/* SECTION TITLE */
.sec-title{font-size:.78rem;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#5a7aab;margin:22px 0 10px;padding-bottom:6px;border-bottom:1.5px solid #e0e8f4}
/* CONSOLE */
#console-wrap{margin-top:16px;display:none}
#console-out{background:#0d1117;color:#c9d1d9;font-family:'Consolas','Courier New',monospace;font-size:.78rem;padding:14px 16px;border-radius:8px;max-height:300px;overflow-y:auto;white-space:pre-wrap;line-height:1.5}
#console-out .ok{color:#56d364}
#console-out .err{color:#f85149}
#console-out .info{color:#58a6ff}
/* SUCCESS */
.success-box{background:#f0fff4;border:1.5px solid #56d364;border-radius:10px;padding:20px 24px;text-align:center;margin-top:20px;display:none}
.success-box h3{color:#22863a;font-size:1.1rem;margin-bottom:6px}
.success-box p{font-size:.85rem;color:#3a5a3a}
/* TAGS hint */
.hint{font-size:.75rem;color:#8a9ab0;margin-top:4px}
/* COLOR ROW */
.color-row{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:14px}
/* AF table */
.af-table{width:100%;border-collapse:collapse;font-size:.83rem;margin-top:6px}
.af-table th{background:#f0f4f8;padding:6px 10px;text-align:left;border-bottom:2px solid #c8d4e0;font-size:.78rem}
.af-table td{padding:6px 8px;border-bottom:1px solid #e8eef4;vertical-align:top}
.af-table td input{width:100%;border:1px solid #dde5ee;border-radius:5px;padding:4px 7px;font-size:.82rem}
/* IMPORT */
.import-bar{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.asig-count{font-size:.8rem;color:#6a7a8a;font-style:italic}
/* CALENDAR */
.cal-tabs{display:flex;gap:0;margin-bottom:18px;border-bottom:2px solid #e0e8f4}
.cal-tab{padding:9px 22px;border:none;background:none;font-size:.88rem;font-weight:600;color:#6a7a8a;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-2px;transition:all .15s}
.cal-tab.active{color:#1a3a6b;border-bottom-color:#1a3a6b}
.cal-grid{display:flex;flex-wrap:wrap;gap:24px;margin-top:4px}
.cal-month{min-width:210px}
.cal-month-title{font-size:.78rem;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#3a4a5a;margin-bottom:6px;text-align:center}
.cal-week-headers{display:grid;grid-template-columns:repeat(7,30px);margin-bottom:2px}
.cal-week-headers span{font-size:.65rem;text-align:center;color:#8a9ab0;font-weight:700;padding:2px 0}
.cal-days{display:grid;grid-template-columns:repeat(7,30px);gap:2px}
.cal-day{width:30px;height:28px;border-radius:5px;display:flex;align-items:center;justify-content:center;font-size:.76rem;cursor:pointer;border:1px solid transparent;transition:background .1s,border .1s;user-select:none}
.cal-day.in-range{border-color:#c8d4e0;background:#fff}
.cal-day.in-range:hover{border-color:#7a9acb;background:#eef4ff}
.cal-day.out-range{color:#d0d8e4;cursor:default;font-size:.7rem}
.cal-day.weekend.in-range{color:#8a9ab0}
.cal-day.no-lectivo{background:#f59e0b!important;color:#fff!important;border-color:#d97706!important}
.cal-day.festivo{background:#ef4444!important;color:#fff!important;border-color:#dc2626!important}
.cal-day.vacaciones{background:#a78bfa!important;color:#fff!important;border-color:#7c3aed!important}
.cal-legend{display:flex;gap:14px;margin-top:14px;flex-wrap:wrap;font-size:.76rem;color:#6a7a8a}
.leg-item{display:flex;align-items:center;gap:5px}
.leg-dot{width:13px;height:13px;border-radius:3px;flex-shrink:0;border:1px solid rgba(0,0,0,.1)}
.cal-hint{font-size:.75rem;color:#8a9ab0;margin-bottom:10px}
.cal-marked-list{margin-top:14px}
.cal-marked-title{font-size:.78rem;font-weight:600;color:#3a4a5a;margin-bottom:7px}
.cal-marked-item{display:flex;align-items:center;gap:8px;margin-bottom:5px}
.cal-marked-item .dot{width:10px;height:10px;border-radius:2px;flex-shrink:0}
.cal-marked-item .cal-date{font-size:.8rem;min-width:88px;color:#1a2a3a}
.cal-marked-item .cal-tipo{font-size:.74rem;min-width:72px;color:#6a7a8a}
.cal-marked-item input{border:1px solid #dde5ee;border-radius:5px;padding:3px 8px;font-size:.79rem;flex:1;max-width:240px}
.cal-marked-item input:focus{outline:none;border-color:#1a3a6b}
/* IMPORT STEP */
.mode-cards{display:flex;gap:14px;margin:16px 0 20px}
.mode-card{flex:1;border:2px solid #c8d4e0;border-radius:10px;padding:16px 18px;cursor:pointer;background:#fff;transition:border .2s,background .2s}
.mode-card.selected{border-color:#1a3a6b;background:#eef4ff}
.mode-card h4{font-size:.88rem;margin-bottom:5px;color:#1a2a3a;display:flex;align-items:center;gap:8px}
.mode-card p{font-size:.76rem;color:#6a7a8a;margin:0;line-height:1.4}
.excel-row{display:flex;align-items:center;gap:10px;margin-bottom:7px;padding:9px 13px;background:#f8fafd;border-radius:8px;border:1px solid #e0e8f4;flex-wrap:wrap}
.excel-row .curso-lbl{font-size:.85rem;font-weight:600;color:#3a4a5a;min-width:72px}
.excel-row .file-nm{font-size:.79rem;color:#6a7a8a;font-style:italic;flex:1;min-width:80px}
.excel-row .file-st{font-size:.79rem;min-width:90px;text-align:right}
.import-preview-box{background:#f8fafd;border:1.5px solid #c8d4e0;border-radius:9px;padding:14px 16px;margin-top:14px;font-size:.83rem;line-height:1.7}
/* responsive */
@media(max-width:600px){.row2,.row3,.color-row{grid-template-columns:1fr}.stepper{justify-content:flex-start;overflow-x:auto}.step-line{width:16px}.mode-cards{flex-direction:column}}
</style>
</head>
<body>

<div class="top-bar">
  <img src="/api/logo_svg" alt="Janux" style="height:64px;width:64px;border-radius:13px;flex-shrink:0;box-shadow:0 2px 8px rgba(0,0,0,0.3)"/>
  <div>
    <div class="h1" style="font-size:1.1rem;font-weight:700">Gestor de Horarios — Nuevo Grado</div>
    <div class="sub">Asistente de configuración inicial</div>
  </div>
</div>

<!-- STEPPER -->
<div class="stepper" id="stepper">
  <div class="step active" data-step="1"><div class="step-circle">1</div><div class="step-label">Básico</div></div>
  <div class="step-line"></div>
  <div class="step" data-step="2"><div class="step-circle">2</div><div class="step-label">Estructura</div></div>
  <div class="step-line"></div>
  <div class="step" data-step="3"><div class="step-circle">3</div><div class="step-label">Calendario</div></div>
  <div class="step-line"></div>
  <div class="step" data-step="4"><div class="step-circle">4</div><div class="step-label">Actividades</div></div>
  <div class="step-line"></div>
  <div class="step" data-step="5"><div class="step-circle">5</div><div class="step-label">Apariencia</div></div>
  <div class="step-line"></div>
  <div class="step" data-step="6"><div class="step-circle">6</div><div class="step-label">Asignaturas</div></div>
  <div class="step-line"></div>
  <div class="step" data-step="7"><div class="step-circle">7</div><div class="step-label">Importar</div></div>
  <div class="step-line"></div>
  <div class="step" data-step="8"><div class="step-circle">8</div><div class="step-label">Generar</div></div>
</div>

<!-- ══════ STEP 1: BÁSICO ══════ -->
<div class="card" id="step1">
  <h2>1 · Datos básicos</h2>
  <div class="desc">Identificación del grado, institución y servidor.</div>

  <div class="row2">
    <div class="field">
      <label>Escuela</label>
      <select id="b-escuela" onchange="onEscuelaChange()">
        <option value="">— Selecciona una escuela —</option>
      </select>
    </div>
    <div class="field">
      <label>Titulación</label>
      <select id="b-nombre" onchange="onTitulacionChange()" disabled>
        <option value="">— Selecciona primero una escuela —</option>
      </select>
    </div>
  </div>
  <input type="hidden" id="b-siglas">
  <div class="row2">
    <div class="field">
      <label>Nombre de la institución</label>
      <input type="text" id="b-inst" placeholder="Universidad Politécnica de Cartagena" value="Universidad Politécnica de Cartagena">
    </div>
    <div class="field">
      <label>Siglas de la institución</label>
      <input type="text" id="b-inst-siglas" placeholder="UPCT" value="UPCT" maxlength="10">
    </div>
  </div>
  <div class="row3">
    <div class="field">
      <label>Etiqueta de curso</label>
      <input type="text" id="b-curso-label" placeholder="2026-2027" value="2026-2027">
    </div>
    <div class="field">
      <label>Puerto del servidor</label>
      <input type="number" id="b-port" value="8080" min="1024" max="65535">
    </div>
  </div>

  <div class="actions">
    <span></span>
    <button class="btn btn-primary" onclick="goStep(2)">Siguiente →</button>
  </div>
</div>

<!-- ══════ STEP 2: ESTRUCTURA ══════ -->
<div class="card" id="step2" style="display:none">
  <h2>2 · Estructura del grado</h2>
  <div class="desc">Número de cursos, grupos por cuatrimestre y franjas horarias.</div>

  <div class="field" style="max-width:200px">
    <label>Número de cursos</label>
    <input type="number" id="e-num-cursos" value="4" min="1" max="8" oninput="renderCursoTable()">
  </div>

  <div class="sec-title">Grupos por curso</div>
  <div class="tbl-wrap">
    <table id="cursos-table">
      <thead><tr><th>Curso</th><th>Grupos 1er cuatrimestre</th><th>Grupos 2º cuatrimestre</th><th>Aulario</th></tr></thead>
      <tbody id="cursos-tbody"></tbody>
    </table>
  </div>

  <div class="sec-title">Franjas horarias</div>
  <div class="tbl-wrap">
    <table id="franjas-table">
      <thead><tr><th>#</th><th>Etiqueta (ej. 9:00 - 10:50)</th><th></th></tr></thead>
      <tbody id="franjas-tbody"></tbody>
    </table>
  </div>
  <button class="btn-add" onclick="addFranja()" style="margin-top:8px">+ Añadir franja</button>

  <div class="actions">
    <button class="btn btn-secondary" onclick="goStep(1)">← Anterior</button>
    <button class="btn btn-primary" onclick="goStep(3)">Siguiente →</button>
  </div>
</div>

<!-- ══════ STEP 3: CALENDARIO ACADÉMICO ══════ -->
<div class="card" id="step3" style="display:none">
  <h2>3 · Calendario académico</h2>
  <div class="desc">Define el inicio y fin de cada cuatrimestre. Haz clic en un día para marcarlo como <strong>no lectivo</strong> (naranja) o <strong>festivo</strong> (rojo). Segundo clic cambia el tipo, tercer clic lo borra.</div>

  <div class="cal-tabs">
    <button class="cal-tab active" id="tab-1C" onclick="switchCalTab('1C')">1er Cuatrimestre</button>
    <button class="cal-tab" id="tab-2C" onclick="switchCalTab('2C')">2º Cuatrimestre</button>
  </div>

  <!-- ── Panel 1C ── -->
  <div id="cal-panel-1C" class="cal-panel">
    <div class="row2" style="max-width:380px;margin-bottom:16px">
      <div class="field">
        <label>Inicio 1C</label>
        <input type="date" id="c1-inicio" oninput="renderCal('1C')">
      </div>
      <div class="field">
        <label>Fin 1C</label>
        <input type="date" id="c1-fin" oninput="renderCal('1C')">
      </div>
    </div>
    <div class="cal-hint">Clic → no lectivo &nbsp;|&nbsp; 2º clic → festivo &nbsp;|&nbsp; 3er clic → borrar</div>
    <div id="cal-grid-1C" class="cal-grid"></div>
    <div class="cal-legend">
      <span class="leg-item"><span class="leg-dot" style="background:#fff;border-color:#c8d4e0"></span>Lectivo</span>
      <span class="leg-item"><span class="leg-dot" style="background:#f59e0b"></span>No lectivo</span>
      <span class="leg-item"><span class="leg-dot" style="background:#ef4444"></span>Festivo</span>
    </div>
    <div id="cal-list-1C" class="cal-marked-list"></div>
  </div>

  <!-- ── Panel 2C ── -->
  <div id="cal-panel-2C" class="cal-panel" style="display:none">
    <div class="row2" style="max-width:380px;margin-bottom:16px">
      <div class="field">
        <label>Inicio 2C</label>
        <input type="date" id="c2-inicio" oninput="renderCal('2C')">
      </div>
      <div class="field">
        <label>Fin 2C</label>
        <input type="date" id="c2-fin" oninput="renderCal('2C')">
      </div>
    </div>
    <div class="cal-hint">Clic → no lectivo &nbsp;|&nbsp; 2º clic → festivo &nbsp;|&nbsp; 3er clic → borrar</div>
    <div id="cal-grid-2C" class="cal-grid"></div>
    <div class="cal-legend">
      <span class="leg-item"><span class="leg-dot" style="background:#fff;border-color:#c8d4e0"></span>Lectivo</span>
      <span class="leg-item"><span class="leg-dot" style="background:#f59e0b"></span>No lectivo</span>
      <span class="leg-item"><span class="leg-dot" style="background:#ef4444"></span>Festivo</span>
      <span class="leg-item"><span class="leg-dot" style="background:#a78bfa"></span>Vacaciones</span>
    </div>
    <div id="cal-list-2C" class="cal-marked-list"></div>

    <div class="sec-title" style="margin-top:22px">Periodos de vacaciones en 2C</div>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th>Inicio</th><th>Fin</th><th>Descripción</th><th></th></tr></thead>
        <tbody id="vacaciones-tbody"></tbody>
      </table>
    </div>
    <button class="btn-add" onclick="addVacaciones()" style="margin-top:7px">+ Añadir periodo</button>
  </div>

  <div class="actions">
    <button class="btn btn-secondary" onclick="goStep(2)">← Anterior</button>
    <button class="btn btn-primary" onclick="goStep(4)">Siguiente →</button>
  </div>
</div>

<!-- ══════ STEP 4: ACTIVIDADES ══════ -->
<div class="card" id="step4" style="display:none">
  <h2>4 · Tipos de Actividad Formativa</h2>
  <div class="desc">
    Cada clase tiene un campo <strong>Tipo</strong> seleccionable en la interfaz de horarios.
    El tipo determina cómo se contabiliza la actividad en las estadísticas.
    Todos los tipos tienen categoría AF fija y se contabilizan automáticamente.
  </div>

  <table class="af-table" style="margin-top:16px">
    <thead>
      <tr>
        <th style="width:80px">Código</th>
        <th>Descripción</th>
        <th style="width:160px;text-align:center">Contabiliza como</th>
      </tr>
    </thead>
    <tbody id="tipos-actividad-tbody">
      <tr><td colspan="3" style="color:#8a9ab0;text-align:center;padding:12px">Cargando tipos...</td></tr>
    </tbody>
  </table>
  <script>
  var _tiposActividadCache = null;
  (function(){
    fetch('/api/tipos_actividad')
      .then(r => r.json())
      .then(tipos => {
        _tiposActividadCache = tipos;
        const tbody = document.getElementById('tipos-actividad-tbody');
        if (!tipos.length) {
          tbody.innerHTML = '<tr><td colspan="3" style="color:#ef4444;text-align:center">No se encontró tipos_actividad.json</td></tr>';
          return;
        }
        tbody.innerHTML = tipos.map(t =>
          `<tr style="background:#eef4ff">
            <td><strong>${t.code}</strong></td>
            <td>${t.label}</td>
            <td style="text-align:center;font-weight:600;color:#1a3a6b">${t.af}</td>
          </tr>`
        ).join('');
      })
      .catch(() => {
        document.getElementById('tipos-actividad-tbody').innerHTML =
          '<tr><td colspan="3" style="color:#ef4444;text-align:center">Error al cargar tipos_actividad.json</td></tr>';
      });
  })();
  </script>
  <div class="hint" style="margin-top:10px">
    El tipo de cada clase se asigna manualmente en la interfaz de horarios.
    Para añadir o modificar tipos, edita el fichero <strong>tipos_actividad.json</strong> en la carpeta raíz del proyecto.
  </div>

  <!-- Campos ocultos para compatibilidad con config.json (AF1/AF2/AF4 base) -->
  <input type="hidden" id="af1-label" value="Teoría">
  <input type="hidden" id="af1-exact" value="">
  <input type="hidden" id="af1-starts" value="">
  <input type="hidden" id="af2-label" value="Laboratorio">
  <input type="hidden" id="af2-exact" value="LAB">
  <input type="hidden" id="af2-starts" value="">
  <input type="hidden" id="af4-label" value="Informática">
  <input type="hidden" id="af4-exact" value="INF">
  <input type="hidden" id="af4-starts" value="">

  <div class="actions">
    <button class="btn btn-secondary" onclick="goStep(3)">← Anterior</button>
    <button class="btn btn-primary" onclick="goStep(5)">Siguiente →</button>
  </div>
</div>

<!-- ══════ STEP 5: APARIENCIA ══════ -->
<div class="card" id="step5" style="display:none">
  <h2>5 · Apariencia</h2>
  <div class="desc">Paleta de colores del grado en la interfaz web.</div>

  <div class="color-row">
    <div class="field">
      <label>Color principal</label>
      <input type="color" id="ap-primary" value="#1a3a6b">
      <div class="hint">Cabecera, botones</div>
    </div>
    <div class="field">
      <label>Color principal claro</label>
      <input type="color" id="ap-primary-light" value="#2855a0">
      <div class="hint">Hover, bordes</div>
    </div>
    <div class="field">
      <label>Color de acento</label>
      <input type="color" id="ap-accent" value="#e8a020">
      <div class="hint">Badges, destacados</div>
    </div>
    <div class="field">
      <label>Color de fondo</label>
      <input type="color" id="ap-bg" value="#f0f4f8">
      <div class="hint">Fondo general</div>
    </div>
  </div>

  <div style="margin-top:20px;padding:16px 20px;border-radius:10px;display:flex;align-items:center;gap:14px" id="preview-bar">
    <span style="font-size:.85rem;font-weight:600">Vista previa:</span>
    <span id="prev-badge" style="padding:4px 12px;border-radius:20px;font-size:.8rem;font-weight:700;color:#fff">GIM</span>
    <span id="prev-btn" style="padding:6px 14px;border-radius:6px;font-size:.8rem;font-weight:600;color:#fff;cursor:default">Botón</span>
    <span id="prev-accent" style="padding:4px 10px;border-radius:5px;font-size:.78rem;font-weight:600">Acento</span>
  </div>

  <div class="actions">
    <button class="btn btn-secondary" onclick="goStep(4)">← Anterior</button>
    <button class="btn btn-primary" onclick="goStep(6)">Siguiente →</button>
  </div>
</div>

<!-- ══════ STEP 6: ASIGNATURAS ══════ -->
<div class="card" id="step6" style="display:none">
  <h2>6 · Asignaturas</h2>
  <div class="desc">Define todas las asignaturas del grado. Puedes importar un CSV o añadir filas manualmente.</div>

  <div class="import-bar">
    <label class="btn btn-outline" style="cursor:pointer;font-size:.82rem">
      📂 Importar CSV
      <input type="file" accept=".csv" style="display:none" onchange="importCSV(event)">
    </label>
    <button class="btn btn-outline" onclick="addAsigRow()" style="font-size:.82rem">+ Añadir fila</button>
    <button class="btn btn-outline" onclick="clearAsignaturas()" style="font-size:.82rem;color:#c0392b;border-color:#c0392b">🗑 Limpiar</button>
    <span class="asig-count" id="asig-count"></span>
  </div>

  <div class="hint" style="margin-bottom:8px">
    Formato CSV: <code>codigo,nombre,curso,cuatrimestre,creditos,af1,af2,af3,af4,af5,af6</code>
    (af3, af5 y af6 son opcionales, defecto 0)
  </div>

  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th>Código</th><th>Nombre</th><th>Curso</th><th>Cuat.</th>
          <th>Créd.</th><th>AF1</th><th>AF2</th><th>AF3</th><th>AF4</th><th>AF5</th><th>AF6</th><th></th>
        </tr>
      </thead>
      <tbody id="asig-tbody"></tbody>
    </table>
  </div>

  <div class="actions">
    <button class="btn btn-secondary" onclick="goStep(5)">← Anterior</button>
    <button class="btn btn-primary" onclick="goStep(7)">Siguiente →</button>
  </div>
</div>

<!-- ══════ STEP 7: IMPORTAR HORARIO ══════ -->
<div class="card" id="step7" style="display:none">
  <h2>7 · Importar horario de año anterior</h2>
  <div class="desc">Opcional. Puedes importar la distribución de clases desde los Excel del curso anterior para no empezar desde cero.</div>

  <div class="mode-cards">
    <div class="mode-card selected" id="mc-vacio" onclick="setImportMode('vacio')">
      <h4>📋 Horario vacío</h4>
      <p>La base de datos se generará sin clases asignadas. Las irás añadiendo manualmente desde la interfaz.</p>
    </div>
    <div class="mode-card" id="mc-importar" onclick="setImportMode('importar')">
      <h4>📂 Importar desde Excel anterior</h4>
      <p>Selecciona los archivos Excel del año pasado. Las clases se trasladarán al nuevo calendario respetando los festivos que hayas configurado.</p>
    </div>
  </div>

  <div id="import-excel-panel" style="display:none">
    <div class="sec-title">Archivos Excel por curso</div>
    <div class="hint" style="margin-bottom:12px">Un archivo por curso (contendrá los dos cuatrimestres). Ej: <code>25-26_GIDI 1C.xlsx</code></div>
    <div id="excel-upload-rows"></div>

    <div style="margin-top:14px;display:flex;align-items:center;gap:12px">
      <button class="btn btn-outline" onclick="analizarExcels()" id="btn-analizar">🔍 Analizar Excel</button>
      <span id="analizar-hint" style="font-size:.78rem;color:#8a9ab0">Selecciona al menos un archivo y pulsa Analizar.</span>
    </div>

    <div id="import-preview" style="display:none;margin-top:14px"></div>
  </div>

  <div class="actions">
    <button class="btn btn-secondary" onclick="goStep(6)">← Anterior</button>
    <button class="btn btn-primary" onclick="goStep(8)">Siguiente →</button>
  </div>
</div>

<!-- ══════ STEP 8: GENERAR ══════ -->
<div class="card" id="step8" style="display:none">
  <h2>8 · Generar proyecto</h2>
  <div class="desc">Revisa el resumen y pulsa "Generar" para crear la carpeta del grado con la base de datos.</div>

  <div id="summary-box" style="background:#f8fafd;border:1.5px solid #c8d4e0;border-radius:8px;padding:16px 20px;font-size:.85rem;line-height:1.9;margin-bottom:20px"></div>

  <button class="btn btn-green" id="btn-generate" onclick="generarGrado()" style="font-size:.95rem;padding:11px 28px">
    ⚡ Generar proyecto
  </button>

  <div id="console-wrap">
    <div style="font-size:.78rem;color:#6a7a8a;margin-bottom:4px">Salida del proceso:</div>
    <div id="console-out"></div>
  </div>

  <div class="success-box" id="success-box">
    <h3>✅ Proyecto creado correctamente</h3>
    <p id="success-path"></p>
    <p style="margin-top:8px">Abre la carpeta del grado y haz doble clic en el launcher para iniciar el servidor.</p>
  </div>

  <div class="actions" style="margin-top:20px">
    <button class="btn btn-secondary" onclick="goStep(7)">← Anterior</button>
    <button class="btn btn-outline" onclick="resetWizard()">🔄 Crear otro grado</button>
  </div>
</div>

<script>
// ─── STATE ───────────────────────────────────────────────────────────────────
let asignaturas = [];
let currentStep = 1;
let _titulacionesCache = [];
let _classroomsCache = [];   // aulas cargadas desde VAILLO/classrooms.json
let _escuelaActual = '';     // escuela seleccionada en paso 1

// Carga aulas desde classrooms.json al iniciar; si ya estamos en paso 2, re-renderiza la tabla
(function() {
  fetch('/api/classrooms')
    .then(r => r.json())
    .then(data => {
      _classroomsCache = data || [];
      if (currentStep === 2) renderCursoTable();
    })
    .catch(() => console.warn('No se pudo cargar classrooms.json'));
})();

// Carga titulaciones desde titulaciones.json al iniciar
(function() {
  fetch('/api/titulaciones')
    .then(r => r.json())
    .then(tits => {
      _titulacionesCache = tits;
      // Poblar escuelas con valores únicos manteniendo el orden de aparición
      const escuelas = [...new Set(tits.map(t => t.escuela))];
      const selEsc = document.getElementById('b-escuela');
      if (!selEsc) return;
      escuelas.forEach(e => {
        const opt = document.createElement('option');
        opt.value = e;
        opt.textContent = e;
        selEsc.appendChild(opt);
      });
      // Si solo hay una escuela, seleccionarla automáticamente y cargar titulaciones
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
  // Limpiar titulaciones y siglas
  selTit.innerHTML = '';
  document.getElementById('b-siglas').value = '';
  if (!escuela) {
    selTit.innerHTML = '<option value="">— Selecciona primero una escuela —</option>';
    selTit.disabled = true;
    return;
  }
  // Si ya estamos en el paso 2, re-renderizar la tabla de cursos con las nuevas aulas
  if (currentStep === 2) renderCursoTable();
  // Filtrar titulaciones por escuela seleccionada y excluir dobles grados
  const filtradas = _titulacionesCache.filter(t => t.escuela === escuela && !t.doble_grado);
  selTit.innerHTML = '<option value="">— Selecciona una titulación —</option>';
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

// ─── NAVIGATION ──────────────────────────────────────────────────────────────
function goStep(n) {
  if (n > currentStep && !validateStep(currentStep)) return;
  document.getElementById('step' + currentStep).style.display = 'none';
  currentStep = n;
  document.getElementById('step' + currentStep).style.display = 'block';
  updateStepper();
  if (n === 2) renderCursoTable();
  if (n === 7) initImportStep();
  if (n === 8) renderSummary();
  window.scrollTo({top: 0, behavior: 'smooth'});
}

function updateStepper() {
  document.querySelectorAll('.step').forEach(el => {
    const s = +el.dataset.step;
    el.classList.remove('active', 'done');
    if (s === currentStep) el.classList.add('active');
    else if (s < currentStep) el.classList.add('done');
  });
}

function validateStep(n) {
  if (n === 1) {
    const nombre = gv('b-nombre').trim();
    const siglas = gv('b-siglas').trim();
    if (!nombre) { alert('Selecciona una titulación.'); return false; }
    if (!siglas)  { alert('No se pudo obtener la clave del grado. Selecciona una titulación válida.'); return false; }
  }
  if (n === 2) {
    const rows = getFranjas();
    if (!rows.length) { alert('Añade al menos una franja horaria.'); return false; }
  }
  if (n === 6) {
    if (!asignaturas.length) {
      return confirm('La tabla de asignaturas está vacía. ¿Continuar de todas formas? (podrás añadirlas más tarde editando el CSV)');
    }
  }
  return true;
}

// ─── HELPERS ─────────────────────────────────────────────────────────────────
function gv(id) { return (document.getElementById(id)||{value:''}).value || ''; }
function sv(id, val) { const el = document.getElementById(id); if(el) el.value = val; }

// ─── STEP 2: CURSOS / FRANJAS ─────────────────────────────────────────────
function buildAularioOptions(selectedVal) {
  // Construye las <option> del desplegable de aula filtradas por escuela
  const escuela = _escuelaActual || document.getElementById('b-escuela').value;
  const aulas = _classroomsCache.filter(c => (!escuela || c.ESCUELA === escuela) && c.ClassroomCode);
  let html = '<option value="">— Sin aula por defecto —</option>';
  aulas.forEach(c => {
    const cap = c.ClassroomCapacity ? ` [${c.ClassroomCapacity}]` : '';
    const sel = (c.ClassroomCode === selectedVal) ? ' selected' : '';
    html += `<option value="${c.ClassroomCode}"${sel}>${c.ClassroomCode}${cap}</option>`;
  });
  // Si el valor guardado no está en la lista, añadirlo como opción extra
  if (selectedVal && !aulas.find(c => c.ClassroomCode === selectedVal)) {
    html += `<option value="${selectedVal}" selected>${selectedVal}</option>`;
  }
  return html;
}

function renderCursoTable() {
  const n = parseInt(gv('e-num-cursos')) || 4;
  const tbody = document.getElementById('cursos-tbody');
  const existing = [];
  tbody.querySelectorAll('tr').forEach(tr => {
    existing.push({
      g1c:     tr.querySelector('.g1c')     ? tr.querySelector('.g1c').value     : 2,
      g2c:     tr.querySelector('.g2c')     ? tr.querySelector('.g2c').value     : 2,
      aulario: tr.querySelector('.aulario') ? tr.querySelector('.aulario').value : ''
    });
  });
  tbody.innerHTML = '';
  for (let i = 0; i < n; i++) {
    const g1c     = existing[i] ? existing[i].g1c     : 2;
    const g2c     = existing[i] ? existing[i].g2c     : (i === n-1 ? 1 : 2);
    const aulario = existing[i] ? existing[i].aulario : '';
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><strong>${i+1}º</strong></td>
      <td><input type="number" class="g1c" value="${g1c}" min="1" max="10" style="width:80px"></td>
      <td><input type="number" class="g2c" value="${g2c}" min="1" max="10" style="width:80px"></td>
      <td><select class="aulario" style="min-width:160px">${buildAularioOptions(aulario)}</select></td>`;
    tbody.appendChild(tr);
  }
}

const DEFAULT_FRANJAS = [
  '9:00 - 10:50','11:10 - 13:00','13:10 - 15:00',
  '15:00 - 16:50','17:10 - 19:00','19:10 - 21:00'
];

function initFranjas() {
  const tbody = document.getElementById('franjas-tbody');
  if (tbody.children.length) return;
  DEFAULT_FRANJAS.forEach(f => addFranjaRow(f));
}

function addFranja() { addFranjaRow(''); }

function addFranjaRow(label) {
  const tbody = document.getElementById('franjas-tbody');
  const idx = tbody.children.length + 1;
  const tr = document.createElement('tr');
  tr.innerHTML = `<td style="width:30px;color:#8a9ab0;font-size:.8rem">${idx}</td>
    <td><input type="text" value="${label}" placeholder="ej. 9:00 - 10:50"></td>
    <td class="td-btn"><button class="btn-del" onclick="this.closest('tr').remove();renumberFranjas()">✕</button></td>`;
  tbody.appendChild(tr);
}

function renumberFranjas() {
  document.querySelectorAll('#franjas-tbody tr').forEach((tr, i) => {
    tr.cells[0].textContent = i + 1;
  });
}

function getFranjas() {
  const rows = [];
  document.querySelectorAll('#franjas-tbody tr').forEach(tr => {
    const label = tr.querySelector('input').value.trim();
    if (label) rows.push({ label });
  });
  return rows;
}

// ─── STEP 3: CALENDARIO ACADÉMICO ────────────────────────────────────────────
const MESES_ES = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                  'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
const DIAS_SHORT = ['L','M','X','J','V','S','D'];

// calDays['1C'] = { 'YYYY-MM-DD': { tipo: 'no_lectivo'|'festivo', desc: '' } }
const calDays = { '1C': {}, '2C': {} };

function switchCalTab(q) {
  ['1C','2C'].forEach(t => {
    document.getElementById('tab-' + t).classList.toggle('active', t === q);
    document.getElementById('cal-panel-' + t).style.display = t === q ? 'block' : 'none';
  });
}

function renderCal(q) {
  const idx = q === '1C' ? 1 : 2;
  const ini = gv('c' + idx + '-inicio');
  const fin = gv('c' + idx + '-fin');
  const grid = document.getElementById('cal-grid-' + q);
  if (!ini || !fin) {
    grid.innerHTML = '<div style="color:#8a9ab0;font-size:.82rem;padding:8px 0">Introduce las fechas de inicio y fin para ver el calendario.</div>';
    return;
  }
  const d0 = new Date(ini + 'T12:00:00');
  const d1 = new Date(fin + 'T12:00:00');
  if (d0 > d1) {
    grid.innerHTML = '<div style="color:#ef4444;font-size:.82rem">La fecha de inicio es posterior al fin.</div>';
    return;
  }
  const vacRanges = q === '2C' ? getVacRanges() : [];
  const months = [];
  const cur = new Date(d0.getFullYear(), d0.getMonth(), 1);
  const last = new Date(d1.getFullYear(), d1.getMonth(), 1);
  while (cur <= last) { months.push(new Date(cur)); cur.setMonth(cur.getMonth() + 1); }
  grid.innerHTML = months.map(m => renderMonth(q, m, d0, d1, vacRanges)).join('');
  renderMarkedList(q);
}

function renderMonth(q, monthDate, rangeStart, rangeEnd, vacRanges) {
  const yr = monthDate.getFullYear(), mo = monthDate.getMonth();
  const firstDow = (new Date(yr, mo, 1).getDay() + 6) % 7;
  const daysInMonth = new Date(yr, mo + 1, 0).getDate();
  const headers = DIAS_SHORT.map(d => `<span>${d}</span>`).join('');
  let cells = '';
  for (let i = 0; i < firstDow; i++) cells += '<div class="cal-day"></div>';
  for (let day = 1; day <= daysInMonth; day++) {
    const date = new Date(yr, mo, day);
    const ds = fmtDate(date);
    const dow = (date.getDay() + 6) % 7;
    const inRange = date >= rangeStart && date <= rangeEnd;
    if (!inRange) { cells += `<div class="cal-day out-range">${day}</div>`; continue; }
    const isVac = vacRanges.some(v => date >= v.s && date <= v.e);
    const sp = calDays[q][ds];
    let cls = 'cal-day in-range' + (dow >= 5 ? ' weekend' : '')
              + (isVac ? ' vacaciones' : '')
              + (sp ? ' ' + sp.tipo.replace('_','-') : '');
    cells += `<div class="${cls}" onclick="toggleCalDay('${q}','${ds}',this)" title="${ds}">${day}</div>`;
  }
  return `<div class="cal-month">
    <div class="cal-month-title">${MESES_ES[mo]} ${yr}</div>
    <div class="cal-week-headers">${headers}</div>
    <div class="cal-days">${cells}</div>
  </div>`;
}

function fmtDate(d) {
  return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
}

function toggleCalDay(q, ds, el) {
  const cur = calDays[q][ds];
  if (!cur)                          calDays[q][ds] = { tipo: 'no_lectivo', desc: '' };
  else if (cur.tipo === 'no_lectivo') calDays[q][ds] = { tipo: 'festivo', desc: cur.desc };
  else                               delete calDays[q][ds];
  // update cell class in-place (no full re-render)
  el.classList.remove('no-lectivo','festivo');
  const sp = calDays[q][ds];
  if (sp) el.classList.add(sp.tipo.replace('_','-'));
  renderMarkedList(q);
}

function renderMarkedList(q) {
  const list = document.getElementById('cal-list-' + q);
  const entries = Object.entries(calDays[q]).sort((a,b) => a[0].localeCompare(b[0]));
  if (!entries.length) { list.innerHTML = ''; return; }
  list.innerHTML = `<div class="cal-marked-title">Días marcados (${entries.length}):</div>` +
    entries.map(([ds, info]) => `
      <div class="cal-marked-item">
        <div class="dot" style="background:${info.tipo==='festivo'?'#ef4444':'#f59e0b'}"></div>
        <span class="cal-date">${ds}</span>
        <span class="cal-tipo">${info.tipo==='festivo'?'Festivo':'No lectivo'}</span>
        <input type="text" value="${(info.desc||'').replace(/"/g,'&quot;')}" placeholder="Descripción (opcional)"
               oninput="calDays['${q}']['${ds}'].desc=this.value">
        <button class="btn-del" onclick="removeCalDay('${q}','${ds}')">✕</button>
      </div>`).join('');
}

function removeCalDay(q, ds) {
  delete calDays[q][ds];
  renderCal(q);
}

function getVacRanges() {
  const out = [];
  document.querySelectorAll('#vacaciones-tbody tr').forEach(tr => {
    const s = tr.querySelector('.v-ini')?.value;
    const e = tr.querySelector('.v-fin')?.value;
    if (s && e) out.push({ s: new Date(s+'T12:00:00'), e: new Date(e+'T12:00:00') });
  });
  return out;
}

function addVacaciones() {
  const tbody = document.getElementById('vacaciones-tbody');
  const tr = document.createElement('tr');
  tr.innerHTML = `<td><input type="date" class="v-ini" oninput="renderCal('2C')"></td>
    <td><input type="date" class="v-fin" oninput="renderCal('2C')"></td>
    <td><input type="text" class="v-desc" placeholder="ej. Carnaval"></td>
    <td class="td-btn"><button class="btn-del" onclick="this.closest('tr').remove();renderCal('2C')">✕</button></td>`;
  tbody.appendChild(tr);
}

function getCalendario() {
  const cal = {};
  ['1C','2C'].forEach((q, i) => {
    const festivos = Object.entries(calDays[q]).map(([fecha, info]) => ({
      fecha, tipo: info.tipo, descripcion: info.desc || ''
    }));
    cal[q] = { inicio: gv('c'+(i+1)+'-inicio'), fin: gv('c'+(i+1)+'-fin'), festivos };
  });
  const vacs = [];
  document.querySelectorAll('#vacaciones-tbody tr').forEach(tr => {
    const ini = tr.querySelector('.v-ini')?.value;
    const fin = tr.querySelector('.v-fin')?.value;
    if (ini && fin) vacs.push({ inicio: ini, fin: fin, descripcion: tr.querySelector('.v-desc')?.value || '' });
  });
  if (vacs.length) cal['2C'].vacaciones = vacs;
  return cal;
}

// ─── STEP 5: PREVIEW ─────────────────────────────────────────────────────────
document.addEventListener('input', e => {
  if (['ap-primary','ap-primary-light','ap-accent','ap-bg'].includes(e.target.id)) updatePreview();
});

function updatePreview() {
  const primary = gv('ap-primary');
  const accent  = gv('ap-accent');
  const bg      = gv('ap-bg');
  const bar = document.getElementById('preview-bar');
  if (bar) bar.style.background = bg;
  const badge = document.getElementById('prev-badge');
  if (badge) { badge.style.background = primary; }
  const btn = document.getElementById('prev-btn');
  if (btn) { btn.style.background = primary; }
  const ac = document.getElementById('prev-accent');
  if (ac) { ac.style.background = accent + '33'; ac.style.color = accent; }
}

// ─── STEP 6: ASIGNATURAS ─────────────────────────────────────────────────────
function renderAsigTable() {
  const tbody = document.getElementById('asig-tbody');
  const count = document.getElementById('asig-count');
  if (count) count.textContent = asignaturas.length ? `(${asignaturas.length} filas)` : '';
  const nc = parseInt(gv('e-num-cursos')) || 4;
  const cuatOpts = `<option value="1C">1C</option><option value="2C">2C</option>`;
  const cursoOpts = Array.from({length:nc}, (_,i) =>
    `<option value="${i+1}">${i+1}º</option>`).join('');

  tbody.innerHTML = asignaturas.map((a, i) => `
    <tr>
      <td><input type="text" value="${esc(a.codigo)}" oninput="asignaturas[${i}].codigo=this.value"></td>
      <td><input type="text" value="${esc(a.nombre)}" oninput="asignaturas[${i}].nombre=this.value" style="min-width:140px"></td>
      <td><select onchange="asignaturas[${i}].curso=+this.value">${cursoOpts.replace(`value="${a.curso}"`,`value="${a.curso}" selected`)}</select></td>
      <td><select onchange="asignaturas[${i}].cuatrimestre=this.value">
        ${['1C','2C'].map(c=>`<option value="${c}" ${a.cuatrimestre===c?'selected':''}>${c}</option>`).join('')}
      </select></td>
      <td><input type="number" value="${a.creditos||6}" min="0" step="0.5" oninput="asignaturas[${i}].creditos=+this.value" style="width:55px"></td>
      <td><input type="number" value="${a.af1||0}" min="0" oninput="asignaturas[${i}].af1=+this.value" style="width:50px"></td>
      <td><input type="number" value="${a.af2||0}" min="0" oninput="asignaturas[${i}].af2=+this.value" style="width:50px"></td>
      <td><input type="number" value="${a.af3||0}" min="0" oninput="asignaturas[${i}].af3=+this.value" style="width:50px"></td>
      <td><input type="number" value="${a.af4||0}" min="0" oninput="asignaturas[${i}].af4=+this.value" style="width:50px"></td>
      <td><input type="number" value="${a.af5||0}" min="0" oninput="asignaturas[${i}].af5=+this.value" style="width:50px"></td>
      <td><input type="number" value="${a.af6||0}" min="0" oninput="asignaturas[${i}].af6=+this.value" style="width:50px"></td>
      <td class="td-btn"><button class="btn-del" onclick="removeAsig(${i})">✕</button></td>
    </tr>`).join('');
}

function esc(s) { return String(s||'').replace(/"/g,'&quot;').replace(/</g,'&lt;'); }

function addAsigRow() {
  const nc = parseInt(gv('e-num-cursos')) || 4;
  asignaturas.push({codigo:'',nombre:'',curso:1,cuatrimestre:'1C',creditos:6,af1:45,af2:0,af3:0,af4:0,af5:0,af6:0});
  renderAsigTable();
}

function removeAsig(i) {
  asignaturas.splice(i, 1);
  renderAsigTable();
}

function clearAsignaturas() {
  if (!asignaturas.length || confirm('¿Eliminar todas las filas?')) {
    asignaturas = [];
    renderAsigTable();
  }
}

function importCSV(e) {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = ev => {
    const text = ev.target.result;
    parseCSV(text);
  };
  reader.readAsText(file, 'utf-8');
  e.target.value = '';
}

function parseCSV(text) {
  const lines = text.split(/\r?\n/).filter(l => l.trim());
  if (!lines.length) return;
  // Detect header
  const firstLower = lines[0].toLowerCase();
  let dataLines = firstLower.includes('codigo') || firstLower.includes('nombre') ? lines.slice(1) : lines;
  const imported = [];
  dataLines.forEach(line => {
    const cols = line.split(',').map(c => c.trim().replace(/^"|"$/g,''));
    if (cols.length < 4) return;
    imported.push({
      codigo:       cols[0] || '',
      nombre:       cols[1] || '',
      curso:        parseInt(cols[2]) || 1,
      cuatrimestre: cols[3] || '1C',
      creditos:     parseFloat(cols[4]) || 6,
      af1:          parseFloat(cols[5]) || 0,
      af2:          parseFloat(cols[6]) || 0,
      af3:          parseFloat(cols[7]) || 0,
      af4:          parseFloat(cols[8]) || 0,
      af5:          parseFloat(cols[9]) || 0,
      af6:          parseFloat(cols[10]) || 0
    });
  });
  if (imported.length) {
    asignaturas = imported;
    renderAsigTable();
    alert(`Importadas ${imported.length} asignaturas.`);
  } else {
    alert('No se encontraron filas válidas en el CSV.');
  }
}

// ─── STEP 7: SUMMARY + GENERATE ──────────────────────────────────────────────
function renderSummary() {
  const b = getBasico();
  const e = getEstructura();
  const cal = getCalendario();
  const f1 = cal['1C'].festivos || [];
  const f2 = cal['2C'].festivos || [];
  const vac = cal['2C'].vacaciones || [];

  const box = document.getElementById('summary-box');
  box.innerHTML = `
    <b>Grado:</b> ${b.nombre} (${b.siglas})<br>
    <b>Institución:</b> ${b.institucion} (${b.siglas_inst})<br>
    <b>Curso:</b> ${b.curso_label} · Puerto: ${b.puerto}<br>
    <b>Estructura:</b> ${e.cursos.length} cursos, ${e.franjas.length} franjas horarias<br>
    <b>Calendario 1C:</b> ${cal['1C'].inicio||'—'} → ${cal['1C'].fin||'—'} · ${f1.length} festivos<br>
    <b>Calendario 2C:</b> ${cal['2C'].inicio||'—'} → ${cal['2C'].fin||'—'} · ${f2.length} festivos · ${vac.length} periodos vacaciones<br>
    <b>Asignaturas:</b> ${asignaturas.length} filas<br>
    <b>Importar horario:</b> ${importMode === 'importar' ? `Sí — ${importedClases.length} clases desde Excel` : 'No (horario vacío)'}<br>
    <b>Carpeta destino:</b> grados/${b.siglas}/
  `;
}

function getBasico() {
  return {
    nombre: gv('b-nombre'),
    siglas: gv('b-siglas'),
    institucion: gv('b-inst'),
    siglas_inst: gv('b-inst-siglas'),
    curso_label: gv('b-curso-label'),
    puerto: gv('b-port') || '8080',
    badge: ''
  };
}

function getEstructura() {
  const cursos = [];
  document.querySelectorAll('#cursos-tbody tr').forEach(tr => {
    cursos.push({
      g1c:     parseInt(tr.querySelector('.g1c').value) || 2,
      g2c:     parseInt(tr.querySelector('.g2c').value) || 2,
      aulario: tr.querySelector('.aulario') ? tr.querySelector('.aulario').value.trim() : ''
    });
  });
  return { cursos, franjas: getFranjas() };
}

function getActividades() {
  // tipoToAf se construye a partir de tipos_actividad.json vía API.
  // Se usa _tiposActividadCache, poblada al cargar el paso 4.
  const tipoToAf = {};
  (_tiposActividadCache || []).forEach(t => {
    if (t.af && t.af !== '-') tipoToAf[t.code] = t.af;
  });
  return {
    AF1: { label: gv('af1-label'), aula_exact: gv('af1-exact'), aula_startswith: gv('af1-starts') },
    AF2: { label: gv('af2-label'), aula_exact: gv('af2-exact'), aula_startswith: gv('af2-starts') },
    AF4: { label: gv('af4-label'), aula_exact: gv('af4-exact'), aula_startswith: gv('af4-starts') },
    tipo_to_af: tipoToAf
  };
}

function getApariencia() {
  return {
    primary:       gv('ap-primary'),
    primary_light: gv('ap-primary-light'),
    accent:        gv('ap-accent'),
    bg:            gv('ap-bg')
  };
}

async function generarGrado() {
  const btn = document.getElementById('btn-generate');
  btn.disabled = true; btn.textContent = '⏳ Generando…';
  document.getElementById('console-wrap').style.display = 'block';
  document.getElementById('console-out').innerHTML = '';
  document.getElementById('success-box').style.display = 'none';

  consoleLog('Enviando datos al servidor…', 'info');

  const payload = {
    basico:             getBasico(),
    estructura:         getEstructura(),
    calendario:         getCalendario(),
    actividades:        getActividades(),
    apariencia:         getApariencia(),
    asignaturas,
    clases_importadas:  importMode === 'importar' ? importedClases : []
  };

  try {
    const r = await fetch('/api/crear', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const res = await r.json();
    if (res.output) {
      res.output.split('\n').forEach(l =>
        consoleLog(l, l.includes('✅') ? 'ok' : l.includes('ERROR') || l.includes('Error') ? 'err' : ''));
    }
    if (res.error) {
      res.error.split('\n').filter(Boolean).forEach(l => consoleLog(l, 'err'));
    }
    if (res.traceback) {
      res.traceback.split('\n').forEach(l => consoleLog(l, 'err'));
    }
    if (res.ok) {
      consoleLog('\n✅ Proyecto creado correctamente.', 'ok');
      const sb = document.getElementById('success-box');
      sb.style.display = 'block';
      document.getElementById('success-path').textContent = 'Carpeta: ' + (res.grado_dir || 'grados/' + getBasico().siglas);
    } else {
      consoleLog('\n❌ Se produjeron errores. Revisa la salida.', 'err');
    }
  } catch(e) {
    consoleLog('Error de conexión: ' + e.message, 'err');
  } finally {
    btn.disabled = false; btn.textContent = '⚡ Generar proyecto';
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

function resetWizard() {
  if (!confirm('¿Crear un nuevo grado? Se perderán los datos actuales.')) return;
  location.reload();
}

// ─── STEP 7: IMPORTAR HORARIO ─────────────────────────────────────────────────
let importMode    = 'vacio';
let importedClases = [];
let excelFiles    = {};   // curso_num (int) → File

function setImportMode(mode) {
  importMode = mode;
  document.getElementById('mc-vacio').classList.toggle('selected',    mode === 'vacio');
  document.getElementById('mc-importar').classList.toggle('selected', mode === 'importar');
  const panel = document.getElementById('import-excel-panel');
  panel.style.display = mode === 'importar' ? 'block' : 'none';
  if (mode === 'importar') renderExcelUploadRows();
}

function initImportStep() {
  if (importMode === 'importar') renderExcelUploadRows();
}

function renderExcelUploadRows() {
  const n = parseInt(gv('e-num-cursos')) || 4;
  const container = document.getElementById('excel-upload-rows');
  // Preserve existing file selections
  const prevFiles = { ...excelFiles };
  container.innerHTML = '';
  excelFiles = {};
  for (let i = 1; i <= n; i++) {
    const div = document.createElement('div');
    div.className = 'excel-row';
    const fname = prevFiles[i] ? prevFiles[i].name : 'No seleccionado';
    div.innerHTML = `
      <span class="curso-lbl">${i}º Curso</span>
      <label class="btn btn-outline" style="cursor:pointer;font-size:.82rem;margin:0;padding:6px 14px">
        📂 Seleccionar
        <input type="file" accept=".xlsx,.xls" style="display:none"
               onchange="excelFileSelected(${i}, event)">
      </label>
      <span class="file-nm" id="excel-nm-${i}">${fname}</span>
      <span class="file-st" id="excel-st-${i}"></span>`;
    container.appendChild(div);
    if (prevFiles[i]) excelFiles[i] = prevFiles[i];
  }
}

function excelFileSelected(curso, event) {
  const file = event.target.files[0];
  if (!file) return;
  excelFiles[curso] = file;
  const nm = document.getElementById(`excel-nm-${curso}`);
  if (nm) nm.textContent = file.name;
  const st = document.getElementById(`excel-st-${curso}`);
  if (st) st.innerHTML = '';
  event.target.value = '';
  // Reset preview
  const p = document.getElementById('import-preview');
  if (p) { p.style.display = 'none'; p.innerHTML = ''; }
  importedClases = [];
}

async function analizarExcels() {
  const btn = document.getElementById('btn-analizar');
  const hint = document.getElementById('analizar-hint');
  const preview = document.getElementById('import-preview');

  if (!Object.keys(excelFiles).length) {
    alert('Selecciona al menos un archivo Excel antes de analizar.');
    return;
  }

  btn.disabled = true;
  btn.textContent = '⏳ Analizando…';
  hint.textContent = '';
  preview.style.display = 'block';
  preview.innerHTML = '<div style="color:#6a7a8a;font-size:.83rem">Analizando archivos… esto puede tardar unos segundos.</div>';
  importedClases = [];

  const resumen = [];
  let hasError  = false;

  for (const [cursoStr, file] of Object.entries(excelFiles)) {
    const curso = parseInt(cursoStr);
    try {
      const b64 = await fileToBase64(file);
      const r   = await fetch('/api/parse_excel', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ file_b64: b64, curso })
      });
      const res = await r.json();
      if (!res.ok) {
        resumen.push(`<div style="color:#c0392b">❌ ${curso}º Curso: ${res.error||'Error desconocido'}</div>`);
        hasError = true;
      } else {
        const clases = res.clases || [];
        importedClases = importedClases.concat(clases);
        const c1 = clases.filter(c => c.cuatrimestre === '1C').length;
        const c2 = clases.filter(c => c.cuatrimestre === '2C').length;
        const nasig = (res.asignaturas || []).length;
        resumen.push(`<div style="color:#22863a">✅ ${curso}º Curso: ${clases.length} clases (1C: ${c1} · 2C: ${c2}) · ${nasig} asignaturas</div>`);
        const st = document.getElementById(`excel-st-${curso}`);
        if (st) st.innerHTML = `<span style="color:#22863a">✅ ${clases.length}</span>`;
      }
    } catch(e) {
      resumen.push(`<div style="color:#c0392b">❌ ${curso}º Curso: ${e.message}</div>`);
      hasError = true;
    }
  }

  const total = importedClases.length;
  preview.innerHTML = `
    <div class="import-preview-box">
      <div style="font-weight:700;font-size:.9rem;color:${hasError?'#c0392b':'#22863a'};margin-bottom:10px">
        ${hasError ? '⚠️' : '✅'} Total: <strong>${total} clases</strong> listas para importar
      </div>
      ${resumen.join('')}
      ${total > 0 ? `<div style="margin-top:10px;font-size:.76rem;color:#6a7a8a">
        Las clases se trasladarán semana a semana al nuevo calendario.<br>
        Los días festivos o no-lectivos que hayas configurado en el paso 3 se respetarán automáticamente.
      </div>` : ''}
    </div>`;

  btn.disabled = false;
  btn.textContent = '🔍 Analizar Excel';
  hint.textContent = total > 0 ? 'Pulsa "Siguiente →" para continuar.' : 'No se encontraron clases.';
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = e => resolve(e.target.result.split(',')[1]);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

// ─── INIT ─────────────────────────────────────────────────────────────────────
renderCursoTable();
initFranjas();
updatePreview();
</script>
</body>
</html>
"""

# ─────────────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────────────

def build_config(data):
    b   = data['basico']
    e   = data['estructura']
    c   = data['calendario']
    act = data['actividades']
    ap  = data['apariencia']

    siglas = b['siglas'].upper().strip()

    grupos_por_curso  = {}
    aulario_por_curso = {}
    for i, curso in enumerate(e['cursos']):
        grupos_por_curso[str(i + 1)] = {
            '1C': int(curso.get('g1c', 2)),
            '2C': int(curso.get('g2c', 2))
        }
        aulario = curso.get('aulario', '').strip()
        if aulario:
            aulario_por_curso[str(i + 1)] = aulario

    franjas = [{'label': f['label'], 'orden': i + 1}
               for i, f in enumerate(e.get('franjas', []))]

    def parse_list(s):
        return [x.strip() for x in str(s).split(',') if x.strip()]

    activity_types = {}
    for key in ['AF1', 'AF2', 'AF4']:
        a = act.get(key, {})
        entry = {'label': a.get('label', key)}
        exact  = parse_list(a.get('aula_exact', ''))
        starts = parse_list(a.get('aula_startswith', ''))
        # AF1 special case: empty string means teoría (no aula)
        if key == 'AF1' and not exact:
            exact = ['']
        entry['aula_exact']      = exact
        entry['aula_startswith'] = starts
        activity_types[key] = entry
    activity_types['AF5'] = {'fichas_only': True}
    activity_types['AF6'] = {'fichas_only': True}

    tipo_to_af = {k: v for k, v in act.get('tipo_to_af', {}).items() if v}

    cfg = {
        '_comment': f"Configuración del Gestor de Horarios — {siglas}",
        'institution': {
            'name':     b.get('institucion', ''),
            'acronym':  b.get('siglas_inst', ''),
            'logo_png': 'docs/logo_upct.png',
            'logo_pdf': 'docs/logo.pdf'
        },
        'degree': {
            'name':    b.get('nombre', ''),
            'acronym': siglas
        },
        'server': {
            'port':        int(b.get('puerto', 8080)),
            'db_name':     'horarios.db',
            'curso_label': b.get('curso_label', '')
        },
        'degree_structure': {
            'num_cursos':        len(e['cursos']),
            'num_semanas':       16,
            'grupos_por_curso':  grupos_por_curso,
            'aulario_por_curso': aulario_por_curso,
            'franjas':           franjas
        },
        'calendario': c,
        'branding': {
            'primary':       ap.get('primary', '#1a3a6b'),
            'primary_light': ap.get('primary_light', '#2855a0'),
            'accent':        ap.get('accent', '#e8a020'),
            'bg':            ap.get('bg', '#f0f4f8')
        },
        'activity_types': activity_types,
        'tipo_to_af': tipo_to_af,
        'ui': {
            'destacadas_badge': "DTIE",
            'export_prefix':    siglas
        }
    }
    return cfg


def write_csv(asignaturas, path):
    fields = ['codigo', 'nombre', 'curso', 'cuatrimestre',
              'creditos', 'af1', 'af2', 'af3', 'af4', 'af5', 'af6']
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for a in asignaturas:
            w.writerow({k: a.get(k, 0) for k in fields})


def generar_launchers(grado_dir: Path, siglas: str, cfg: dict):
    port        = cfg['server']['port']
    db_name     = cfg['server']['db_name']
    curso_label = cfg['server']['curso_label']
    db_stem     = db_name.replace('.db', '')

    # Los launchers viven DENTRO de grados/<SIGLAS>/
    # El servidor y la BD están dos niveles arriba: ../../
    root_rel  = '../..'          # raíz del proyecto desde grados/SIGLAS/
    db_rel    = db_name          # la BD está en la misma carpeta que el launcher

    # ── macOS .command ──────────────────────────────────────────────────────
    command_content = f"""#!/bin/bash
# Launcher — {siglas} ({curso_label})
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/{root_rel}" && pwd)"
DB_SRC="$DIR/{db_rel}"
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
  --grado "grados/{siglas}" &
SERVER_PID=$!

sleep 1.5 && open "http://localhost:{port}"
wait "$SERVER_PID"
"""
    command_path = grado_dir / f'Iniciar {siglas}.command'
    command_path.write_text(command_content, encoding='utf-8')
    command_path.chmod(0o755)
    subprocess.run(['chmod', '+x', str(command_path)], check=False)

    # ── Windows .bat ────────────────────────────────────────────────────────
    bat_content = f"""@echo off
REM Launcher — {siglas} ({curso_label})
set DIR=%~dp0
set ROOT=%DIR%..\\..
set DB_SRC=%DIR%{db_name}
set DB_TMP=%TEMP%\\{db_stem}_{siglas}.db

copy /Y "%DB_SRC%" "%DB_TMP%" >nul 2>&1

set DB_PATH_OVERRIDE=%DB_TMP%
set CURSO_LABEL={curso_label}
set CONFIG_PATH_OVERRIDE=%DIR%
start "" "http://localhost:{port}"
python "%ROOT%\\servidor_horarios.py" --grado "grados/{siglas}"

copy /Y "%DB_TMP%" "%DB_SRC%" >nul 2>&1
echo Base de datos guardada.
pause
"""
    bat_path = grado_dir / f'Iniciar {siglas}.bat'
    bat_path.write_text(bat_content, encoding='utf-8')

    # ── Linux .sh ────────────────────────────────────────────────────────────
    sh_content = f"""#!/bin/bash
# Launcher — {siglas} ({curso_label})
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/{root_rel}" && pwd)"
DB_SRC="$DIR/{db_rel}"
DB_TMP="/tmp/{db_stem}_{siglas}.db"

cp "$DB_SRC" "$DB_TMP" 2>/dev/null || true

cleanup() {{
  kill "$SERVER_PID" 2>/dev/null
  wait "$SERVER_PID" 2>/dev/null
  [ -f "$DB_TMP" ] && cp "$DB_TMP" "$DB_SRC" && echo "BD guardada."
}}
trap cleanup EXIT INT TERM HUP

DB_PATH_OVERRIDE="$DB_TMP" CURSO_LABEL="{curso_label}" CONFIG_PATH_OVERRIDE="$DIR" \\
  python3 "$ROOT/servidor_horarios.py" --grado "grados/{siglas}" &
SERVER_PID=$!

sleep 1.5 && (xdg-open "http://localhost:{port}" 2>/dev/null || true)
wait "$SERVER_PID"
"""
    sh_path = grado_dir / f'iniciar_{siglas.lower()}.sh'
    sh_path.write_text(sh_content, encoding='utf-8')
    sh_path.chmod(0o755)
    subprocess.run(['chmod', '+x', str(sh_path)], check=False)


def api_parse_excel(data):
    """
    Parsea un archivo Excel de horarios (recibido en base64) y devuelve
    la lista de clases de ambos cuatrimestres.
    """
    try:
        import base64
        from importar_horarios import parse_excel_all_cuats

        file_b64 = data.get('file_b64', '')
        curso    = int(data.get('curso', 1))

        if not file_b64:
            return {'ok': False, 'error': 'No se recibió ningún archivo.'}

        file_bytes = base64.b64decode(file_b64)
        result     = parse_excel_all_cuats(file_bytes, curso)

        if result.get('error'):
            return {'ok': False, 'error': result['error']}

        clases = result.get('1C', []) + result.get('2C', [])
        return {
            'ok':          True,
            'clases':      clases,
            'asignaturas': result.get('asignaturas', []),
        }
    except Exception:
        return {'ok': False, 'error': traceback.format_exc()}


def api_crear(data):
    try:
        siglas = data['basico']['siglas'].upper().strip()
        if not siglas:
            return {'ok': False, 'error': 'Las siglas no pueden estar vacías.'}

        grado_dir = BASE_DIR / 'grados' / siglas
        grado_dir.mkdir(parents=True, exist_ok=True)

        # config.json
        cfg = build_config(data)
        config_path = grado_dir / 'config.json'
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

        # CSV de asignaturas
        csv_path = grado_dir / f'asignaturas_{siglas}.csv'
        write_csv(data.get('asignaturas', []), csv_path)

        # Ejecutar setup_grado.py
        setup_script = BASE_DIR / 'tools' / 'setup_grado.py'
        if not setup_script.exists():
            return {'ok': False, 'error': f'No se encuentra setup_grado.py en {BASE_DIR / "tools"}'}

        cmd = [sys.executable, str(setup_script),
               str(grado_dir), str(csv_path), '--force']
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(BASE_DIR))
        output = result.stdout + result.stderr

        # Launchers en la raíz del proyecto
        generar_launchers(grado_dir, siglas, cfg)

        # ── Importar clases desde Excel (si se proporcionaron) ────────────────
        import_log = ''
        clases_importadas = data.get('clases_importadas', [])
        if clases_importadas and result.returncode == 0:
            try:
                import sqlite3 as _sqlite3
                from setup_grado import import_clases_desde_excel
                db_file = grado_dir / cfg['server']['db_name']
                if db_file.exists():
                    conn2 = _sqlite3.connect(str(db_file))
                    conn2.execute("PRAGMA foreign_keys = ON")
                    import_clases_desde_excel(conn2, clases_importadas)
                    conn2.close()
                    import_log = f'\n✅ {len(clases_importadas)} clases importadas desde Excel.'
                else:
                    import_log = '\n⚠️ No se encontró la BD para importar clases.'
            except Exception:
                import_log = f'\n⚠️ Error al importar clases:\n{traceback.format_exc()}'

        return {
            'ok':        result.returncode == 0,
            'output':    output + import_log,
            'grado_dir': str(grado_dir)
        }

    except Exception:
        return {'ok': False, 'error': traceback.format_exc()}


# ─────────────────────────────────────────────────────────────────────────────
# DTIE — importar funciones desde nuevo_dtie.py
# ─────────────────────────────────────────────────────────────────────────────

try:
    from nuevo_dtie import (
        WIZARD_HTML as DTIE_HTML,
        api_grados            as dtie_api_grados,
        api_leer_dtie         as dtie_api_leer_dtie,
        api_crear_dtie        as dtie_api_crear_dtie,
        api_csvs_dtie         as dtie_api_csvs_dtie,
        api_resolver_csv_dtie as dtie_api_resolver_csv_dtie,
    )
    _DTIE_AVAILABLE = True
except ImportError:
    _DTIE_AVAILABLE = False
    DTIE_HTML = '<h1>nuevo_dtie.py no encontrado</h1>'

# ─────────────────────────────────────────────────────────────────────────────
# LANDING PAGE
# ─────────────────────────────────────────────────────────────────────────────

LANDING_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Janux — Gestor de Horarios</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#f0f4f8;color:#1a2a3a;
     min-height:100vh;display:flex;flex-direction:column}
.top-bar{background:#1a3a6b;color:#fff;padding:18px 40px;display:flex;align-items:center;gap:16px}
.top-bar img{height:72px;width:72px;border-radius:14px;box-shadow:0 2px 10px rgba(0,0,0,.35);flex-shrink:0}
.top-bar-text h1{font-size:1.4rem;font-weight:700;letter-spacing:.2px}
.top-bar-text p{font-size:.88rem;opacity:.7;margin-top:3px}
.main{flex:1;display:flex;align-items:center;justify-content:center;padding:40px 24px}
.cards{display:flex;gap:28px;flex-wrap:wrap;justify-content:center;max-width:780px;width:100%}
.card{background:#fff;border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,.09);
      padding:36px 32px;flex:1;min-width:280px;max-width:340px;
      display:flex;flex-direction:column;align-items:center;text-align:center;
      border:2.5px solid transparent;transition:all .2s;cursor:pointer;text-decoration:none;color:inherit}
.card:hover{transform:translateY(-4px);box-shadow:0 8px 30px rgba(0,0,0,.13)}
.card-grado:hover{border-color:#1a3a6b}
.card-dtie:hover{border-color:#6b1a3a}
.card-icon{font-size:3rem;margin-bottom:16px;line-height:1}
.card h2{font-size:1.15rem;font-weight:700;margin-bottom:8px}
.card p{font-size:.84rem;color:#6a7a8a;line-height:1.55;margin-bottom:20px;flex:1}
.card-btn{padding:10px 28px;border-radius:9px;font-size:.9rem;font-weight:700;
          border:none;cursor:pointer;transition:background .15s;width:100%}
.card-grado .card-btn{background:#1a3a6b;color:#fff}
.card-grado .card-btn:hover{background:#2855a0}
.card-dtie .card-btn{background:#6b1a3a;color:#fff}
.card-dtie .card-btn:hover{background:#8b2a52}
.footer{text-align:center;padding:16px;font-size:.76rem;color:#a0aab4}
@media(max-width:560px){.cards{flex-direction:column;align-items:center}.card{max-width:100%}}
</style>
</head>
<body>

<div class="top-bar">
  <img src="/api/logo_svg" alt="Janux">
  <div class="top-bar-text">
    <h1>Janux — Gestor de Horarios</h1>
    <p>Asistente de configuración · UPCT</p>
  </div>
</div>

<div class="main">
  <div class="cards">

    <a class="card card-grado" href="/nuevo">
      <div class="card-icon">🎓</div>
      <h2>Configurar Grado</h2>
      <p>Crea un nuevo grado desde cero: estructura de cursos, franjas horarias, calendario académico, asignaturas e importación de Excel.</p>
      <button class="card-btn" onclick="event.preventDefault();location.href='/nuevo'">Nuevo Grado →</button>
    </a>

    <a class="card card-dtie" href="/dtie">
      <div class="card-icon">⭐</div>
      <h2>Configurar Doble Grado</h2>
      <p>Genera un Programa de Estudios Conjunto (DTIE) combinando asignaturas marcadas con ⭐ en dos grados ya existentes.</p>
      <button class="card-btn" onclick="event.preventDefault();location.href='/dtie'">Nuevo Doble Grado →</button>
    </a>

  </div>
</div>

<div class="footer">Janux · Gestor de Horarios UPCT</div>

</body>
</html>
"""

# ─────────────────────────────────────────────────────────────────────────────
# HTTP SERVER
# ─────────────────────────────────────────────────────────────────────────────

class WizardHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == '/':
            self._html(LANDING_HTML)
        elif self.path == '/nuevo':
            self._html(WIZARD_HTML)
        elif self.path == '/dtie':
            self._html(DTIE_HTML)
        elif self.path == '/api/ping':
            self._json({'ok': True})
        elif self.path == '/api/logo_svg':
            self._svg(BASE_DIR / 'docs' / 'logo_janux.svg')
        elif self.path == '/api/grados':
            self._json(dtie_api_grados() if _DTIE_AVAILABLE else {'grados': []})
        elif self.path == '/api/csvs_dtie':
            self._json(dtie_api_csvs_dtie() if _DTIE_AVAILABLE else {'csvs': []})
        elif self.path == '/api/tipos_actividad':
            tipos_path = BASE_DIR / 'config' / 'tipos_actividad.json'
            if tipos_path.exists():
                with open(tipos_path, encoding='utf-8') as f:
                    self._json(json.load(f))
            else:
                self._json([])
        elif self.path == '/api/titulaciones':
            tit_path = BASE_DIR / 'config' / 'titulaciones.json'
            if tit_path.exists():
                with open(tit_path, encoding='utf-8') as f:
                    self._json(json.load(f))
            else:
                self._json([])
        elif self.path == '/api/classrooms':
            classrooms_path = BASE_DIR / 'config' / 'classrooms.json'
            if classrooms_path.exists():
                with open(classrooms_path, encoding='utf-8') as f:
                    self._json(json.load(f))
            else:
                self._json([])
        else:
            self._404()

    def do_POST(self):
        if self.path == '/api/crear':
            data = self._read_json()
            self._json(api_crear(data))
        elif self.path == '/api/parse_excel':
            data = self._read_json()
            self._json(api_parse_excel(data))
        elif self.path == '/api/leer_dtie' and _DTIE_AVAILABLE:
            data = self._read_json()
            self._json(dtie_api_leer_dtie(data))
        elif self.path == '/api/crear_dtie' and _DTIE_AVAILABLE:
            data = self._read_json()
            self._json(dtie_api_crear_dtie(data))
        elif self.path == '/api/resolver_csv_dtie' and _DTIE_AVAILABLE:
            data = self._read_json()
            self._json(dtie_api_resolver_csv_dtie(data))
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

    def _svg(self, path):
        try:
            data = Path(path).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'image/svg+xml')
            self.send_header('Content-Length', len(data))
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self._404()

    def _404(self):
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # silenciar logs de consola


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def _wait_and_open(url, timeout=10):
    """Espera a que el servidor responda al ping y luego abre el navegador."""
    ping = f'http://127.0.0.1:{PORT}/api/ping'
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(ping, timeout=1)
            print(f'  ✓ Servidor listo — abriendo navegador...')
            result = subprocess.call(['open', url])
            print(f'  open retornó: {result}')
            return
        except Exception as e:
            print(f'  ping fallido: {e}')
            time.sleep(0.1)
    print(f'  Timeout — abriendo navegador de todas formas...')
    result = subprocess.call(['open', url])
    print(f'  open retornó: {result}')


def main():
    browser_url = f'http://localhost:{PORT}'
    url = f'http://127.0.0.1:{PORT}'
    print(f'')
    print(f'  ╔══════════════════════════════════════════╗')
    print(f'  ║   Janux — Gestor de Horarios UPCT        ║')
    print(f'  ║   {browser_url:<40} ║')
    print(f'  ╚══════════════════════════════════════════╝')
    print(f'')
    print(f'  Abre el navegador en {browser_url}')
    print(f'  Pulsa Ctrl+C para detener.')
    print(f'')
    class DualStackServer(HTTPServer):
        address_family = socket.AF_INET6
        def server_bind(self):
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            super().server_bind()

    DualStackServer.allow_reuse_address = True
    server = DualStackServer(('::', PORT), WizardHandler)
    threading.Thread(target=_wait_and_open, args=(browser_url,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nServidor detenido.')


if __name__ == '__main__':
    main()
