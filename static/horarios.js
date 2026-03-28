let DB = null;
let currentCurso = '1', currentCuat = '1C', currentGroup = '1', currentWeekIdx = 0, currentView = 'semana';
let editCtx = null;
let _classroomsAll = [];   // aulas cargadas desde /api/classrooms
const DAYS = ['LUNES','MARTES','MIÉRCOLES','JUEVES','VIERNES'];
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

async function saveDB() {
  const btn = document.getElementById('btnSaveDB');
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '&#9203; Guardando...';
  try {
    const res = await api('/api/db/checkpoint', {});
    if (res.ok) {
      btn.innerHTML = '&#10003; Guardado';
      btn.style.background = 'rgba(39,174,96,.4)';
      showToast('Base de datos guardada correctamente');
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

async function backupDB() {
  const btn = document.getElementById('btnBackupDB');
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '&#9203; Preparando...';
  try {
    // Descargar la BD desde el servidor (ya hace checkpoint internamente)
    const response = await fetch('/api/db/download');
    if (!response.ok) throw new Error('Error al obtener la base de datos del servidor');
    const blob = await response.blob();

    // Obtener el nombre sugerido del header Content-Disposition
    const disposition = response.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="?([^"]+)"?/);
    const suggestedName = match ? match[1] : 'horarios_copia.db';

    // Usar File System Access API para que el usuario elija dónde guardar
    if (window.showSaveFilePicker) {
      const fileHandle = await window.showSaveFilePicker({
        suggestedName,
        types: [{ description: 'Base de datos SQLite', accept: { 'application/octet-stream': ['.db'] } }]
      });
      const writable = await fileHandle.createWritable();
      await writable.write(blob);
      await writable.close();
      btn.innerHTML = '&#10003; Guardado';
      btn.style.background = 'rgba(39,174,96,.25)';
      showToast('Copia guardada correctamente');
    } else {
      // Fallback: descarga directa al directorio de descargas
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = suggestedName;
      a.click();
      URL.revokeObjectURL(url);
      btn.innerHTML = '&#10003; Descargado';
      btn.style.background = 'rgba(39,174,96,.25)';
      showToast('Copia descargada: ' + suggestedName);
    }
    setTimeout(() => { btn.innerHTML = orig; btn.style.background = ''; btn.disabled = false; }, 3000);
  } catch(e) {
    if (e.name === 'AbortError') {
      // El usuario canceló el diálogo — no es un error
      btn.innerHTML = orig;
      btn.style.background = '';
      btn.disabled = false;
    } else {
      btn.innerHTML = '&#10007; Error';
      btn.style.background = 'rgba(231,76,60,.25)';
      showToast('Error al guardar: ' + e.message, true);
      setTimeout(() => { btn.innerHTML = orig; btn.style.background = ''; btn.disabled = false; }, 3000);
    }
  }
}

function importDBFileSelected(input) {
  if (!input.files || !input.files[0]) return;
  const file = input.files[0];
  input.value = ''; // reset para poder volver a seleccionar el mismo fichero
  if (!confirm('¿Seguro que deseas sustituir la base de datos actual por "' + file.name + '"?\n\nSe creará una copia de seguridad automática antes de continuar.')) return;
  importDB(file);
}

async function importDB(file) {
  const btn = document.getElementById('btnImportDB');
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '&#9203; Importando...';
  try {
    const arrayBuffer = await file.arrayBuffer();
    const res = await fetch('/api/db/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: arrayBuffer
    });
    const data = await res.json();
    if (data.ok) {
      btn.innerHTML = '&#9203; Guardando...';
      btn.style.background = 'rgba(39,174,96,.2)';
      await api('/api/db/checkpoint', {});
      btn.innerHTML = '&#10003; Importado';
      btn.style.background = 'rgba(39,174,96,.4)';
      showToast('Base de datos importada y guardada correctamente. Recargando datos...');
      setTimeout(async () => {
        btn.innerHTML = orig; btn.style.background = ''; btn.disabled = false;
        DB = await api('/api/schedule');
        DB._overrideSet = new Set(DB.fichas_override || []);
        render();
      }, 2000);
    } else {
      throw new Error(data.error || 'Error desconocido');
    }
  } catch(e) {
    btn.innerHTML = '&#10007; Error';
    btn.style.background = 'rgba(231,76,60,.25)';
    showToast('Error al importar: ' + e.message, true);
    setTimeout(() => { btn.innerHTML = orig; btn.style.background = ''; btn.disabled = false; }, 3000);
  }
}

// ─── VERSIÓN ─────────────────────────────────────────────────────────────────

let _versionDetailVisible = false;

async function loadVersionBadge() {
  const badge = document.getElementById('versionBadge');
  if (!badge) return;
  try {
    const info = await fetch('/api/db/info').then(r => r.json());
    const upToDate = info.db_up_to_date;
    badge.className = 'version-badge ' + (upToDate ? 'ok' : 'warn');
    badge.innerHTML = upToDate
      ? `&#10003; v${info.app_version}`
      : `&#9888; v${info.app_version} · BD v${info.db_version}&#8594;v${info.schema_latest}`;
    badge.title = upToDate
      ? `Código v${info.app_version} · Esquema BD v${info.db_version} — Al día. Haz clic para más detalle.`
      : `Hay migraciones pendientes (BD v${info.db_version} → v${info.schema_latest}). Reinicia el servidor para actualizar.`;
    badge._info = info;
  } catch(e) {
    badge.style.display = 'none';
  }
}

function toggleVersionDetail() {
  const badge = document.getElementById('versionBadge');
  const existing = document.getElementById('versionDetail');
  if (existing) { existing.remove(); _versionDetailVisible = false; return; }
  if (!badge || !badge._info) return;
  const info = badge._info;

  const div = document.createElement('div');
  div.id = 'versionDetail';
  div.className = 'version-detail';
  const rows = [
    ['Código (servidor)',  `v${info.app_version}`],
    ['Esquema BD actual',  `v${info.db_version}`],
    ['Esquema disponible', `v${info.schema_latest}`],
    ['Estado',            info.db_up_to_date ? '✅ Al día' : '⚠️ Pendiente — reinicia el servidor'],
  ];
  div.innerHTML = `<table>${rows.map(([k,v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('')}</table>`;

  // Colocar como hijo de body con posición fixed para evitar recorte del header
  document.body.appendChild(div);
  const rect = badge.getBoundingClientRect();
  div.style.position = 'fixed';
  div.style.top  = (rect.bottom + 6) + 'px';
  div.style.right = (window.innerWidth - rect.right) + 'px';
  div.style.left  = 'auto';

  _versionDetailVisible = true;
  const close = (e) => {
    if (!badge.contains(e.target) && !div.contains(e.target)) {
      div.remove();
      _versionDetailVisible = false;
      document.removeEventListener('click', close);
    }
  };
  setTimeout(() => document.addEventListener('click', close), 0);
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
  return cls.tipo === 'EXP' || cls.tipo === 'EXF';
}

function isDestacada(cls) {
  if (!DB || !DB._destacadasSet || !cls.asig_codigo) return false;
  const actType = getActType(cls);
  const sg = cls.subgrupo || '';
  return DB._destacadasSet.has(cls.asig_codigo + '::' + currentGroup + '::' + actType + '::' + sg);
}

function buildSubjectCard(cls, color, search, interactive) {
  const parcial = isParcial(cls);
  const destacada = !parcial && isDestacada(cls);
  const cardColor = parcial ? 'color-parcial' : (destacada ? 'color-destacada' : color);
  const match = search && cls.asig_nombre && cls.asig_nombre.toLowerCase().includes(search);
  const onclick = interactive ? ` onclick="openEdit(${cls.id})"` : '';
  const _actType = getActType(cls);
  const _sg = cls.subgrupo || '';
  const dtieBtnHtml = (!parcial && interactive && cls.asig_codigo) ? `<button class="dtie-btn${destacada?' active':''}" onclick="event.stopPropagation();toggleDtie('${cls.asig_codigo}',currentGroup,'${_actType}','${_sg}')" title="${destacada?'Quitar DTIE':'Marcar como DTIE'}">&#11088;</button>` : '';
  const dragAttrs = interactive ? ` draggable="true" ondragstart="startDrag(event,${cls.id})" ondragend="endDrag(event)"` : '';
  return `<div class="subject-card ${cardColor}${match?' search-highlight':''}"${onclick}${dragAttrs} style="cursor:${interactive?'grab':'default'}">
    ${dtieBtnHtml}
    ${parcial ? `<span class="parcial-badge">&#128221; ${cls.tipo === 'EXF' ? 'EXAMEN FINAL' : 'EXAMEN PARCIAL'}${cls.observacion ? ' &middot; '+cls.observacion : ''}</span>` : ''}
    ${destacada ? `<span class="parcial-badge" style="color:#ffffff;background:rgba(255,255,255,.15);font-size:.6rem">&#11088; ${DESTACADAS_BADGE}</span>` : ''}
    <div class="subject-name">${cls.asig_nombre||cls.contenido||''}</div>
    ${cls.asig_codigo?`<div class="subject-code">[${cls.asig_codigo}]</div>`:''}
    <div class="subject-tags">
      ${cls.tipo?`<span class="tag tag-tipo">${cls.tipo}</span>`:''}
      ${cls.aula?`<span class="tag">&#127979; ${cls.aula}</span>`:''}
      ${cls.subgrupo?`<span class="tag">&#128101; Sg.${cls.subgrupo}</span>`:''}
    </div>
  </div>`;
}

async function toggleDtie(codigo, grupo_num, act_type, subgrupo) {
  const res = await api('/api/destacada/toggle', {codigo, grupo_num, act_type, subgrupo});
  if (res.ok) {
    const key = codigo + '::' + grupo_num + '::' + act_type + '::' + subgrupo;
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
      // Atributos drag-drop para celdas destino (solo en modo interactivo)
      const dropAttrs = interactive
        ? ` ondragover="dragOverCell(event,${arr.length>0&&!arr[0].es_no_lectivo?'true':'false'})" ondragleave="dragLeaveCell(event)" ondrop="dropClase(event,'${day}',${f.id})"`
        : '';
      if (!arr.length) {
        // Celda vacía
        html += interactive
          ? `<td class="sch-cell sch-empty"${dropAttrs} onclick="openAdd(${week.semana_id},'${day}',${f.id})"><span class="empty-label">+ Anadir</span></td>`
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
        html += `<td class="sch-cell${destacadaCls} ${match?'search-highlight':''}"${onclick}${dropAttrs}>
          ${buildSubjectCard(cls, color, search, interactive)}
          ${addDesdobleBtn}
        </td>`;
      } else {
        // Celda DIVIDIDA — desdoble (no es destino de swap, sí de move si se arrastra desde fuera)
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
    a.counts.teoria > 0 || a.counts.af3 > 0 || a.counts.ps > 0 || a.counts.parcial > 0 ||
    Object.keys(a.infoBySubgrupo).length > 0 || Object.keys(a.labBySubgrupo).length > 0
  );
  if (!asigs.length) return '';

  const ACT_META = {
    teoria:  { label: '&#128218; Teor&iacute;a',     thCls: 'act-teoria-th', tdCls: 'act-teoria-td' },
    af3:     { label: '&#128203; Aula Espec. <small style="font-size:.7em">AF3</small>', thCls: 'act-ps-th', tdCls: 'act-ps-td' },
    info:    { label: '&#128187; Inform&aacute;t.',   thCls: 'act-info-th',   tdCls: 'act-info-td'   },
    lab:     { label: '&#128300; Lab.',               thCls: 'act-lab-th',    tdCls: 'act-lab-td'    },
    ps:      { label: '&#127981; Aula Esp.',          thCls: 'act-ps-th',     tdCls: 'act-ps-td'     },
    parcial: { label: '&#128221; Parcial',            thCls: 'act-parcial-th',tdCls: 'act-parcial-td'},
  };

  const hasTeoria  = asigs.some(a => a.counts.teoria  > 0);
  const hasAf3     = asigs.some(a => a.counts.af3     > 0);
  const hasInfo    = asigs.some(a => Object.keys(a.infoBySubgrupo).length > 0);
  const hasLab     = asigs.some(a => Object.keys(a.labBySubgrupo).length  > 0);
  const hasPs      = asigs.some(a => a.counts.ps      > 0);
  const hasParcial = asigs.some(a => a.counts.parcial > 0);

  const cols = [];
  if (hasTeoria)  cols.push('teoria');
  if (hasAf3)     cols.push('af3');
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
    grandTotal += (a.counts.teoria + a.counts.af3 + a.counts.ps + maxInfo + maxLab) * 2;
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
    const acumH = (a.counts.teoria + a.counts.af3 + a.counts.ps + maxInfo + maxLab) * 2;
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
  renderComentarioSection();
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
  const t = (cls.tipo || '').trim().toUpperCase();
  // Tipos con categoría AF fija
  if (t === 'LAB') return 'lab';
  if (t === 'INF') return 'info';
  if (t === 'EXF') return 'parcial6';                        // Examen final → siempre AF6
  if (t === 'EXP') return cls.af_cat === 'AF6' ? 'parcial6' : 'parcial5'; // según marca de la clase
  if (t === 'CPA') return 'teoria';
  if (t === 'SEM') return 'af3';
  // Tipos editables: usar TIPO_TO_AF inyectado desde config.json del grado
  if (t && typeof TIPO_TO_AF !== 'undefined' && TIPO_TO_AF[t]) {
    const af = TIPO_TO_AF[t];
    if (af === 'AF2') return 'lab';
    if (af === 'AF4') return 'info';
    if (af === 'AF5' || af === 'AF6') return 'parcial';
    if (af === 'AF1') return 'teoria';
    if (af === 'AF3') return 'af3';
  }
  // Sin tipo o sin mapeo configurado: usar comportamiento legacy (AE/AEO/EPyOAE → parcial, resto → teoría)
  // Esto mantiene compatibilidad con grados existentes sin tipo_to_af en config.json
  if (['AE','AEO','EPYOAE'].includes(t)) return 'parcial';
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
      if (!tipo) return; // tipo no asignado a ninguna categoría AF → no cuenta

      if (!asigData[c.asig_codigo]) {
        asigData[c.asig_codigo] = {
          nombre: c.asig_nombre, codigo: c.asig_codigo,
          counts: { teoria:0, af3:0, ps:0, parcial:0, parcial5:0, parcial6:0 },
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

function buildActTable(allAsigs, groupKey, opts = {}) {
  // DEBUG: verificar fichas
  const conFichas = allAsigs.filter(a => a.fichas !== null).length;
  const dbFichasCount = DB && DB.fichas ? Object.keys(DB.fichas).length : 0;
  console.log('[buildActTable] asigs:', allAsigs.length, '| con fichas:', conFichas, '| DB.fichas keys:', dbFichasCount);
  if (allAsigs.length > 0) {
    const a0 = allAsigs[0];
    console.log('[buildActTable] Primer asig:', a0.nombre, '| fichas:', JSON.stringify(a0.fichas), '| counts:', JSON.stringify(a0.counts));
  }

  const ACT_META = {
    teoria:   { label: '&#128218; Teor&iacute;a <small class="af-code">AF1</small>',         thCls: 'act-teoria-th',  tdCls: 'act-teoria-td'  },
    af3:      { label: '&#128203; Aula Espec. <small class="af-code">AF3</small>',            thCls: 'act-ps-th',      tdCls: 'act-ps-td'      },
    info:     { label: '&#128187; Inform&aacute;tica <small class="af-code">AF4</small>',     thCls: 'act-info-th',    tdCls: 'act-info-td'    },
    lab:      { label: '&#128300; Laboratorio <small class="af-code">AF2</small>',            thCls: 'act-lab-th',     tdCls: 'act-lab-td'     },
    ps:       { label: '&#127981; Aula Espec&iacute;f.',                                      thCls: 'act-ps-th',      tdCls: 'act-ps-td'      },
    parcial:  { label: '&#128221; Examen Parcial',                                            thCls: 'act-parcial-th', tdCls: 'act-parcial-td' },
    parcial5: { label: '&#128221; <small class="af-code">AF5</small> &middot; Eval. cont. in',  thCls: 'act-parcial-th', tdCls: 'act-parcial-td' },
    parcial6: { label: '&#127891; <small class="af-code">AF6</small> &middot; Eval. cont. out', thCls: 'act-parcial-th', tdCls: 'act-parcial-td' },
  };

  const hasInfo     = allAsigs.some(a => Object.keys(a.infoBySubgrupo).length > 0);
  const hasLab      = allAsigs.some(a => Object.keys(a.labBySubgrupo).length > 0);
  const hasTeoria   = allAsigs.some(a => a.counts.teoria   > 0);
  const hasAf3      = allAsigs.some(a => a.counts.af3      > 0 || (a.fichas && (a.fichas.af3 || 0) > 0));
  const hasPs       = allAsigs.some(a => a.counts.ps       > 0);
  const hasParcial  = allAsigs.some(a => a.counts.parcial  > 0);
  // opts.hasParcial5 / opts.hasParcial6: flags globales calculadas en renderStats para que
  // todos los grupos del cuatrimestre muestren las mismas columnas AF5/AF6.
  const hasParcial5 = opts.hasParcial5 !== undefined
    ? opts.hasParcial5
    : allAsigs.some(a => a.counts.parcial5 > 0 || (a.fichas && a.fichas.af5 > 0));
  const hasParcial6 = opts.hasParcial6 !== undefined
    ? opts.hasParcial6
    : allAsigs.some(a => a.counts.parcial6 > 0 || (a.fichas && a.fichas.af6 > 0));

  const cols = [];
  if (hasTeoria)   cols.push('teoria');   // AF1
  if (hasLab)      cols.push('lab');      // AF2
  if (hasAf3)      cols.push('af3');      // AF3
  if (hasInfo)     cols.push('info');     // AF4
  if (hasParcial5) cols.push('parcial5'); // AF5
  if (hasParcial6) cols.push('parcial6'); // AF6
  if (hasPs)       cols.push('ps');
  if (hasParcial)  cols.push('parcial');

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

  // ── Celda para parcial5 / parcial6: sesiones × 2h vs valor de ficha
  function parcialAfCell(n, espH, tdCls) {
    const h = n * 2;
    if (!n && !espH) return `<td class="${tdCls}">&mdash;</td>`;
    const ok = (espH === null || espH === undefined || h === espH);
    const style = ok ? '' : 'background:#fee2e2;border-left:3px solid #dc2626';
    const badge = (espH !== null && espH !== undefined)
      ? `<div class="ficha-badge ${ok?'ok':'err'}">${ok?'&#10003;':'&#9888;'} Ficha:&nbsp;${espH}h</div>` : '';
    return `<td class="${tdCls}" style="${style}">${h ? `<strong>${h}h</strong><small>${n}&nbsp;ex.</small>` : '&mdash;'}${badge}</td>`;
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
    const espAf3  = f ? (f.af3 || 0) : null;
    const espAf4  = f ? f.af4  : null;
    const espAf5  = f ? f.af5  : null;
    const espAf6  = f ? f.af6  : null;
    // Total real presencial (sesiones × 2h): AF1+AF2+AF3+AF4+AF5 (sin AF6 — examen final no suma al total)
    const maxInfo = Object.values(a.infoBySubgrupo).length ? Math.max(...Object.values(a.infoBySubgrupo)) : 0;
    const maxLab  = Object.values(a.labBySubgrupo).length  ? Math.max(...Object.values(a.labBySubgrupo))  : 0;
    const totalReal = (a.counts.teoria + a.counts.af3 + a.counts.ps + maxInfo + maxLab + a.counts.parcial5) * 2;

    // ── Chequeos fichas ──────────────────────────────────────────────────
    // Teoría (AF1): sesiones × 2h vs ficha
    const teorReal = a.counts.teoria * 2;
    const teorOk   = (espAf1 === null) || (teorReal === espAf1);

    // Aula Específica (AF3): sesiones × 2h vs ficha
    const af3Real = a.counts.af3 * 2;
    const af3Ok   = (espAf3 === null || espAf3 === 0) ? (af3Real === 0) : (af3Real === espAf3);

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

    // AF5 (EXP→parcial5): sesiones × 2h vs ficha
    const p5Real = a.counts.parcial5 * 2;
    const p5Ok   = (espAf5 === null) || (p5Real === espAf5);

    // AF6 (EXF + EXP→parcial6): sesiones × 2h vs ficha
    const p6Real = a.counts.parcial6 * 2;
    const p6Ok   = (espAf6 === null) || (p6Real === espAf6);

    // Total: todos los bloques presenciales (incluyendo AF5+AF6 ahora contabilizados)
    const presReal = totalReal;
    const presEsp  = f ? (f.af1 + f.af2 + (f.af3 || 0) + f.af4 + f.af5) : null;  // AF1+AF2+AF3+AF4+AF5 (AF6 excluido del total)
    const totalOk  = (presEsp === null) || (presReal === presEsp);

    // ¿Algún error en la asignatura? (con soporte de override manual por grupo)
    const rawErr = !teorOk || !af3Ok || !infoOk || !labOk || !p5Ok || !p6Ok || !totalOk;
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
      if (t === 'af3') {
        const h = a.counts.af3 * 2, n = a.counts.af3;
        const showBadge = espAf3 !== null && (espAf3 > 0 || h > 0);
        const espBadge = showBadge
          ? `<div class="ficha-badge ${af3Ok?'ok':'err'}">${af3Ok?'&#10003;':'&#9888;'} Ficha: ${espAf3}h</div>` : '';
        const cellStyle = af3Ok ? '' : 'background:#fee2e2;border-left:3px solid #dc2626';
        return `<td class="${ACT_META.af3.tdCls}" style="${cellStyle}">${h ? `<strong>${h}h</strong><small>${n}&nbsp;ses.</small>` : '&mdash;'}${espBadge}</td>`;
      }
      if (t === 'parcial5') return parcialAfCell(a.counts.parcial5, espAf5, ACT_META.parcial5.tdCls);
      if (t === 'parcial6') return parcialAfCell(a.counts.parcial6, espAf6, ACT_META.parcial6.tdCls);
      // ps
      const h = a.counts[t] * 2, n = a.counts[t];
      return `<td class="${ACT_META[t].tdCls}">${h ? `<strong>${h}h</strong><small>${n}&nbsp;ses.</small>` : '&mdash;'}</td>`;
    }).join('');

    // Columna total — horas reales (AF1+AF2+AF3+AF4+AF5) vs ficha — AF6 excluido
    const totalBadge = (presEsp !== null)
      ? `<small style="display:block;color:${totalOk?'#166534':'#dc2626'};font-weight:700">${totalOk?'&#10003;':('&#9888; ficha:'+presEsp+'h')}</small>` : '';
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
        if (!cls.tipo || !['EXP','EXF'].includes(cls.tipo)) continue;
        const sNum = semana.numero;
        if (!byWeek[sNum]) byWeek[sNum] = {};
        if (!byWeek[sNum][curso]) byWeek[sNum][curso] = {};
        if (!byWeek[sNum][curso][cls.dia]) byWeek[sNum][curso][cls.dia] = new Map();
        const key = (cls.asig_nombre || '') + '|||' + cls.tipo + (cls.observacion ? '|' + cls.observacion : '');
        const ex = byWeek[sNum][curso][cls.dia].get(key);
        if (ex) {
          if (!ex.grupos.includes(grupo.grupo)) ex.grupos.push(grupo.grupo);
          // conservar la franja de menor orden (más temprana del día)
          if (cls.franja_orden < ex.franjaOrden) { ex.franjaOrden = cls.franja_orden; ex.franja = cls.franja_label; }
        } else {
          byWeek[sNum][curso][cls.dia].set(key, {
            nombre: cls.asig_nombre || '—',
            obs: (cls.tipo === 'EXF' ? 'Examen final' : 'Examen parcial') + (cls.observacion ? ' · ' + cls.observacion : ''),
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
    a.download = `Finales_${EXPORT_PREFIX}_${CURSO_STR.replace('-','_')}_${shortLabel}.pdf`;
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
        Se verifica AF1 (Teor&iacute;a) + AF2 (Lab) + AF3 (Aula Espec.) + AF4 (Info) + AF5 (Eval. cont. en horario lectivo) contra el horario.
        AF6 (eval. final/continua fuera de horario) se muestra en columna propia cuando hay actividades EXF/EXP-AF6 registradas o la ficha lo indica.
        Las filas <span style="background:#fde8e8;padding:1px 6px;border-radius:3px;border:1px solid #dc2626">rojas</span> no cumplen AF1+AF2+AF3+AF4+AF5 de la ficha.
       </div>`
    : `<div style="background:#fee2e2;border:1px solid #dc2626;border-radius:8px;padding:8px 16px;margin-bottom:12px;font-size:.82rem;color:#991b1b">
        &#9888; <strong>Sin datos de fichas en BD</strong> — ejecuta <code>rebuild_fichas.py</code> para cargarlos.
       </div>`;

  // Pre-calcular stats de todos los grupos para obtener flags de columnas consistentes:
  // si CUALQUIER grupo (o ficha) tiene EXP/AF5 o EXP/AF6, todos los grupos muestran esa columna.
  const allGroupStats = groupKeys.map(gKey => ({
    gKey,
    g: DB.grupos[gKey],
    asigs: computeGroupStats(DB.grupos[gKey].semanas)
  }));
  const globalHasParcial5 = allGroupStats.some(s =>
    s.asigs.some(a => a.counts.parcial5 > 0 || (a.fichas && a.fichas.af5 > 0))
  );
  const globalHasParcial6 = allGroupStats.some(s =>
    s.asigs.some(a => a.counts.parcial6 > 0 || (a.fichas && a.fichas.af6 > 0))
  );

  let sectionsHtml = fichasBanner;
  allGroupStats.forEach(({ gKey, g, asigs }) => {
    const weeks  = g.semanas;
    let totalH = 0, totalParciales = 0;
    asigs.forEach(a => {
      const maxInfo = Object.values(a.infoBySubgrupo).length ? Math.max(...Object.values(a.infoBySubgrupo)) : 0;
      const maxLab  = Object.values(a.labBySubgrupo).length  ? Math.max(...Object.values(a.labBySubgrupo))  : 0;
      totalH         += (a.counts.teoria + a.counts.af3 + a.counts.ps + maxInfo + maxLab) * 2;
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
      const af3Real  = a.counts.af3 * 2;
      const maxInfo = Object.values(a.infoBySubgrupo).length ? Math.max(...Object.values(a.infoBySubgrupo)) : 0;
      const maxLab  = Object.values(a.labBySubgrupo).length  ? Math.max(...Object.values(a.labBySubgrupo))  : 0;
      const presReal = (a.counts.teoria + a.counts.af3 + a.counts.ps + maxInfo + maxLab + a.counts.parcial5) * 2;
      const presEsp  = f.af1 + f.af2 + (f.af3 || 0) + f.af4 + f.af5;
      const infoE = Object.entries(a.infoBySubgrupo);
      const labE  = Object.entries(a.labBySubgrupo);
      const espAf3r = f.af3 || 0;
      const teorOk  = (teorReal === f.af1);
      const af3Ok   = espAf3r === 0 ? (af3Real === 0) : (af3Real === espAf3r);
      const infoOk  = infoE.length === 0 ? f.af4 === 0 : infoE.every(([,n]) => n*2 === f.af4);
      const labOk   = labE.length  === 0 ? f.af2 === 0 : labE.every(([,n]) => n*2 === f.af2);
      const totOk   = presReal === presEsp;
      if (!teorOk || !af3Ok || !infoOk || !labOk || !totOk) fichasErrCount++;
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
        ${buildActTable(asigs, gKey, { hasParcial5: globalHasParcial5, hasParcial6: globalHasParcial6 })}
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

function updateAulaSelect(preserveVal) {
  const sel = document.getElementById('fAula');
  if (!sel) return;
  const currentVal = (preserveVal !== undefined) ? preserveVal : sel.value;
  // Preferir AULAS_POR_CURSO[curso] si está configurado; si no, usar classrooms.json completo
  const aulasCurso = AULAS_POR_CURSO[String(currentCurso)] || [];
  let items = [];
  if (aulasCurso.length > 0) {
    items = aulasCurso.map(a => ({ value: a, label: a }));
  } else {
    items = _classroomsAll
      .filter(c => c.ClassroomCode)
      .map(c => ({
        value: c.ClassroomCode,
        label: c.ClassroomCode
      }));
  }
  sel.innerHTML = '<option value="">— Sin aula (Teoría) —</option>' +
    items.map(i => `<option value="${i.value}">${i.label}</option>`).join('');
  // Si el valor guardado no está en la lista (aula legacy), añadirlo como opción
  if (currentVal && !items.find(i => i.value === currentVal)) {
    sel.insertAdjacentHTML('beforeend', `<option value="${currentVal}">${currentVal}</option>`);
  }
  sel.value = currentVal;
}
// Alias para compatibilidad con llamadas antiguas
function updateAulaDatalist() { updateAulaSelect(); }
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
  const aula = (g && g.aula) ? ' · Aula: ' + formatAula(g.aula) : '';
  document.getElementById('headerSubtitle').textContent = ordinals[currentCurso] + ' Curso · ' + DEGREE_ACRONYM + ' · ' + INSTITUTION_ACRONYM + aula;
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
  ['fAsignatura','fAula','fTipo','fSubgrupo','fObs'].forEach(id => document.getElementById(id).disabled = no);
  ['fAfCatAF5','fAfCatAF6'].forEach(id => { const el = document.getElementById(id); if (el) el.disabled = no; });
  if (no) document.getElementById('rowAfCat').style.display = 'none';
}
function onAsignaturaSelect() {}

function onTipoChange() {
  const tipo = document.getElementById('fTipo').value;
  const row = document.getElementById('rowAfCat');
  if (tipo === 'EXP') {
    row.style.display = 'block';
    // Default AF5 if nothing selected
    const checked = document.querySelector('input[name="fAfCat"]:checked');
    if (!checked) document.getElementById('fAfCatAF5').checked = true;
  } else {
    row.style.display = 'none';
  }
}

// ─── DRAG & DROP ───
let _dragClaseId = null;

function startDrag(event, claseId) {
  _dragClaseId = claseId;
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', String(claseId));
  // Marcar la card como "dragging" tras el siguiente frame para que se vea el ghost
  const card = event.currentTarget;
  setTimeout(() => card.classList.add('dragging'), 0);
  event.stopPropagation();
}

function endDrag(event) {
  event.currentTarget.classList.remove('dragging');
  // Limpiar todos los resaltados
  document.querySelectorAll('.drag-over-move, .drag-over-swap').forEach(el => {
    el.classList.remove('drag-over-move', 'drag-over-swap');
  });
}

function dragOverCell(event, hasClase) {
  if (_dragClaseId === null) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = 'move';
  const td = event.currentTarget;
  // Quitar clases previas de todos los tds
  document.querySelectorAll('.drag-over-move, .drag-over-swap').forEach(el => {
    if (el !== td) { el.classList.remove('drag-over-move', 'drag-over-swap'); }
  });
  td.classList.toggle('drag-over-move', !hasClase);
  td.classList.toggle('drag-over-swap',  hasClase);
}

function dragLeaveCell(event) {
  // Solo quitar la clase si realmente salimos del td (no a un hijo)
  if (!event.currentTarget.contains(event.relatedTarget)) {
    event.currentTarget.classList.remove('drag-over-move', 'drag-over-swap');
  }
}

async function dropClase(event, dia, franjaId) {
  event.preventDefault();
  event.currentTarget.classList.remove('drag-over-move', 'drag-over-swap');
  const claseId = _dragClaseId;
  _dragClaseId = null;
  if (!claseId) return;

  // Verificar que no es el mismo slot (mismo dia+franja de la clase origen)
  const week = getCurrentWeek();
  const origen = week.clases.find(c => c.id === claseId);
  if (origen && origen.dia === dia && origen.franja_id === franjaId) return;

  const res = await api('/api/clase/move', { id: claseId, dia, franja_id: franjaId });
  if (res.error) {
    showToast('No se pudo mover: ' + res.error, true);
    return;
  }
  if (res.swap) showToast('↕ Clases intercambiadas');
  else          showToast('→ Clase movida');
  await loadData();
}

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
  updateAulaSelect(cls.aula || '');
  document.getElementById('fTipo').value = cls.tipo || '';
  document.getElementById('fSubgrupo').value = cls.subgrupo || '';
  document.getElementById('fObs').value = cls.observacion || '';
  document.getElementById('fNoLectivo').checked = !!cls.es_no_lectivo;
  // AF5/AF6 radio for EXP classes
  const rowAfCat = document.getElementById('rowAfCat');
  if (cls.tipo === 'EXP') {
    rowAfCat.style.display = 'block';
    const afCat = cls.af_cat || 'AF5';
    document.getElementById('fAfCatAF5').checked = (afCat === 'AF5');
    document.getElementById('fAfCatAF6').checked = (afCat === 'AF6');
  } else {
    rowAfCat.style.display = 'none';
    document.getElementById('fAfCatAF5').checked = false;
    document.getElementById('fAfCatAF6').checked = false;
  }
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
  document.getElementById('fTipo').value = '';
  document.getElementById('fSubgrupo').value = '';
  document.getElementById('fObs').value = '';
  document.getElementById('fNoLectivo').checked = false;
  document.getElementById('fDia').value = dia;
  if (franja) document.getElementById('fHora').value = franjaId;
  // Reset AF5/AF6 row
  document.getElementById('rowAfCat').style.display = 'none';
  document.getElementById('fAfCatAF5').checked = false;
  document.getElementById('fAfCatAF6').checked = false;
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

  const tipoVal = document.getElementById('fTipo').value.trim();
  const afCatChecked = document.querySelector('input[name="fAfCat"]:checked');
  const afCat = (tipoVal === 'EXP' && afCatChecked) ? afCatChecked.value : null;
  console.log('[saveSlot] tipo:', tipoVal, '| af_cat a enviar:', afCat);

  const payload = {
    aula: document.getElementById('fAula').value.trim(),
    tipo: tipoVal,
    subgrupo: document.getElementById('fSubgrupo').value.trim(),
    observacion: document.getElementById('fObs').value.trim(),
    es_no_lectivo: noLec,
    af_cat: afCat,
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
  const grupoLabel  = currentGroup === 'unico' ? 'Grupo Unico' : 'Grupo ' + currentGroup;
  const cuatLabel   = currentCuat === '1C' ? '1er Cuatrimestre' : '2o Cuatrimestre';
  const aulaLabel   = g && g.aula ? ' — ' + formatAula(g.aula) : '';
  const aulario     = AULARIO_POR_CURSO[String(currentCurso)];
  const aularioStr  = aulario ? ' (' + aulario + ')' : '';
  return ordinals[currentCurso] + ' Curso' + aularioStr + ' ' + DEGREE_ACRONYM + ' · ' + cuatLabel + ' · ' + grupoLabel + aulaLabel;
}

// ─── PDF GENERATION (html2canvas + jsPDF, sin diálogo de impresora) ───

// Carga el logo UPCT como data-URL (sin caché para reflejar cambios al instante)
let _logoDataUrl = null;
async function _loadLogo() {
  if (_logoDataUrl !== null) return _logoDataUrl;
  try {
    const resp = await fetch('/api/logo?t=' + Date.now());
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

async function exportarInstitucional() {
  const btn = document.getElementById('btnExportInstitucional');
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '&#9203; Generando…';
  try {
    const resp = await fetch('/api/exportar_institucional');
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
    a.download = match ? match[1] : `Horarios_Institucional_${EXPORT_PREFIX}.xlsx`;
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
    pdf.text('Horarios ' + DEGREE_ACRONYM + ' — Curso ' + CURSO_STR + ' — ' + info, 8, 7);
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
    // Comentario al pie (si existe)
    const _gk1 = _comentarioKey();
    if (_comentarioCache[_gk1] === undefined) await loadComentario(_gk1);
    const _com1 = (_comentarioCache[_gk1] || '').trim();
    if (_com1) {
      const _pw1 = pdf.internal.pageSize.getWidth() - 16;
      const _yc  = 16 + ih + 5;
      // Línea separadora
      pdf.setDrawColor(180, 180, 180);
      pdf.setLineWidth(0.4);
      pdf.line(8, _yc, 8 + _pw1, _yc);
      // Etiqueta "Observaciones:"
      pdf.setFontSize(9); pdf.setTextColor(100, 100, 100);
      pdf.setFont(undefined, 'bold');
      pdf.text('Observaciones:', 8, _yc + 5);
      // Texto del comentario
      pdf.setFontSize(12); pdf.setTextColor(30, 30, 30);
      pdf.setFont(undefined, 'normal');
      const _lines = pdf.splitTextToSize(_com1, _pw1);
      pdf.text(_lines, 8, _yc + 11);
    }
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
      pdf.text('Horarios ' + DEGREE_ACRONYM + ' — Curso ' + CURSO_STR + ' — ' + info, 8, 6);
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
      // Comentario al pie de cada página (si existe)
      const _gkA = _comentarioKey();
      if (_comentarioCache[_gkA] === undefined) await loadComentario(_gkA);
      const _comA = (_comentarioCache[_gkA] || '').trim();
      if (_comA) {
        const _pwA = pdf.internal.pageSize.getWidth() - 16;
        const _ycA = 14 + ih + 4;
        // Línea separadora
        pdf.setDrawColor(180, 180, 180);
        pdf.setLineWidth(0.4);
        pdf.line(8, _ycA, 8 + _pwA, _ycA);
        // Etiqueta "Observaciones:"
        pdf.setFontSize(9); pdf.setTextColor(100, 100, 100);
        pdf.setFont(undefined, 'bold');
        pdf.text('Observaciones:', 8, _ycA + 5);
        // Texto del comentario
        pdf.setFontSize(12); pdf.setTextColor(30, 30, 30);
        pdf.setFont(undefined, 'normal');
        const _linesA = pdf.splitTextToSize(_comA, _pwA);
        pdf.text(_linesA, 8, _ycA + 11);
      }
    }
    document.body.removeChild(cap);
    setPdfProgress(97, 'Guardando archivo…');
    const fname = `horarios_${EXPORT_PREFIX}_${currentCurso}curso_${currentCuat}_grupo${currentGroup}_todas.pdf`;
    pdf.save(fname);
    setPdfProgress(100, '¡Listo!');
    setTimeout(hidePdfOverlay, 700);
  } catch(e) {
    hidePdfOverlay();
    console.error(e);
    alert('Error al generar PDF: ' + e.message + '\n\nComprueba la conexión a internet (necesaria la primera vez).');
  }
}

// ─── COMENTARIOS ───
let _comentarioCache = {};   // grupo_key → texto

function _comentarioKey() {
  return currentCurso + '_' + currentCuat + '_grupo_' + currentGroup;
}

async function loadComentario(grupoKey) {
  if (_comentarioCache[grupoKey] !== undefined) return _comentarioCache[grupoKey];
  try {
    const r = await fetch('/api/comentario?grupo_key=' + encodeURIComponent(grupoKey));
    const d = await r.json();
    _comentarioCache[grupoKey] = d.ok ? (d.comentario || '') : '';
  } catch (e) {
    _comentarioCache[grupoKey] = '';
  }
  return _comentarioCache[grupoKey];
}

async function saveComentario() {
  const grupoKey = _comentarioKey();
  const ta = document.getElementById('comentarioText');
  const text = ta ? ta.value : '';
  _comentarioCache[grupoKey] = text;
  try {
    const r = await fetch('/api/comentario/set', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ grupo_key: grupoKey, comentario: text })
    });
    const d = await r.json();
    if (d.ok) showToast('Comentario guardado ✓');
    else showToast('Error al guardar: ' + (d.error || ''));
  } catch (e) {
    showToast('Error de conexión al guardar comentario');
  }
}

async function renderComentarioSection() {
  const sec = document.getElementById('comentarioSection');
  if (!sec) return;
  const grupoKey = _comentarioKey();
  const text = await loadComentario(grupoKey);
  const groupLabel = currentGroup === 'unico' ? 'Grupo Único' : 'Grupo ' + currentGroup;
  sec.innerHTML = `
    <details class="comentario-details" id="comentarioDetails">
      <summary class="comentario-summary">
        <span>&#128172; Comentarios — ${groupLabel} &nbsp;·&nbsp; ${currentCurso}º ${currentCuat}</span>
        <span class="comentario-hint">Se incluirán al pie de los PDFs exportados</span>
      </summary>
      <div class="comentario-body">
        <textarea id="comentarioText" class="comentario-textarea" rows="4"
          placeholder="Escribe aquí observaciones o notas para este grupo. Se imprimirán al pie de los PDFs."
        >${_escHtml(text)}</textarea>
        <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:8px">
          <button class="btn btn-outline btn-sm" onclick="
            document.getElementById('comentarioText').value='';
            _comentarioCache['${grupoKey}']='';
            saveComentario();
          ">&#128465; Borrar</button>
          <button class="btn btn-primary btn-sm" onclick="saveComentario()">&#128190; Guardar comentario</button>
        </div>
      </div>
    </details>`;
}

function _escHtml(s) {
  return String(s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
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

// ─── INIT ───
(async function() {
  // Cargar aulas antes del loadData para que el select esté poblado desde el primer render
  try {
    _classroomsAll = await fetch('/api/classrooms').then(r => r.json());
  } catch(e) { _classroomsAll = []; }
  loadVersionBadge();   // sin await — se carga en paralelo, no bloquea la UI
  await loadData();
  const rows = await api('/api/festivos');
  FESTIVOS_MAP = {};
  for (const r of rows) FESTIVOS_MAP[r.fecha] = { tipo: r.tipo, descripcion: r.descripcion };
  buildSemanaDateMap();
})();
