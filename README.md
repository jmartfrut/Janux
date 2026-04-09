
<p align="center">
  <a href="docs/presentacion.pdf">
    <img src="docs/img/slide_01.jpg" alt="Janux — Ver presentación" width="100%"/>
  </a>
</p>

> 💡 **Haz clic en la imagen** para abrir la presentación en el navegador.

---

Herramienta para visualizar, editar y verificar horarios de titulaciones universitarias. Desarrollada originalmente para la **UPCT** (Universidad Politécnica de Cartagena), soporta múltiples grados —incluidos dobles grados (DTIE)— y múltiples cursos académicos de forma independiente.

Arquitectura mínima: servidor Python local + base de datos SQLite + frontend HTML/JS en un solo fichero. Sin dependencias de framework, sin instalación compleja.

---

## Características

- **6 vistas**: Semana, Todas las semanas, Estadísticas, Parciales, Finales y Festivos
- **Edición en línea**: crear, modificar, mover e intercambiar clases directamente desde el navegador
- **Verificación automática**: horas reales vs. fichas docentes (AF1/AF2/AF4) con badges verde/rojo
- **Detección de conflictos**: solapamientos de turno entre cursos consecutivos en Parciales y Finales
- **Exámenes finales**: tres períodos (enero/junio/julio), distribución automática, exportación PDF oficial
- **Dobles grados (DTIE)**: marcar asignaturas como destacadas (⭐) y generar el DTIE desde el asistente Janux
- **Exportación PDF**: semana individual o curso completo (multipágina), sin diálogo de impresión
- **Multi-grado**: cada titulación tiene su propia carpeta, BD y configuración independiente
- **Calendario configurable**: gestión de festivos y días no lectivos por cuatrimestre desde la propia interfaz
- **Gestión de BD**: backup con timestamp, descarga y restauración desde el navegador
- **Compatible con Dropbox/OneDrive**: los launchers copian la BD a `/tmp` (macOS) o `%TEMP%` (Windows) antes de arrancar
- **Multiplataforma**: launchers `.command` para macOS, `.sh` para Linux y `.bat` para Windows
- **Despliegue Docker** opcional para entornos de servidor

---

## Estructura del repositorio

```
Janux/
├── servidor_horarios.py        # Servidor único, multi-grado
├── requirements.txt
├── launchers/
│   ├── Janux.command           # macOS — asistente nuevo grado / DTIE
│   ├── Janux.sh                # Linux
│   └── Janux.bat               # Windows
├── horarios/
│   ├── GIM/
│   │   ├── config.json         # Configuración completa del grado
│   │   ├── horarios_2627.db    # BD del curso 2026-2027
│   │   └── Iniciar Horarios GIM 2627.command
│   └── GIDI/
│       ├── config.json
│       ├── horarios.db
│       └── Iniciar GIDI.command
├── config/
│   ├── classrooms.json         # Catálogo de aulas (datalist)
│   ├── fichas_GIM.csv          # Fichas docentes GIM
│   ├── fichas_GIDI.csv         # Fichas docentes GIDI
│   ├── tipos_actividad.json    # Tipos de actividad estándar
│   └── titulaciones.json       # Catálogo de titulaciones UPCT
├── tools/
│   ├── nuevo_grado.py          # Wizard web nuevo grado (puerto 8092)
│   ├── nuevo_dtie.py           # Wizard web doble grado DTIE (puerto 8092)
│   ├── setup_grado.py          # Inicializa BD desde config.json + CSV
│   ├── importar_horarios.py    # Parser de Excel de horarios UPCT
│   ├── exportar_excel.py       # Exporta BD → Excel plantilla UPCT
│   └── exportar_finales_pdf.py # Genera PDF oficial de exámenes finales
├── static/
│   ├── horarios.js             # Frontend JS completo
│   └── horarios.css
├── templates/
│   └── index.html
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── docs/                       # Logos, presentación, documentación
└── backups/                    # Copias de seguridad (.db con timestamp)
```

> La carpeta `horarios/` no está versionada — se genera localmente por cada instalación.

---

## Arrancar el servidor

### macOS — forma recomendada

Doble clic en el fichero `.command` del grado correspondiente:

```
horarios/GIM/Iniciar Horarios GIM 2627.command   → GIM 2026-2027
horarios/GIDI/Iniciar GIDI.command               → GIDI 2026-2027
```

El launcher copia la BD a `/tmp/` (evita errores de I/O en Dropbox/OneDrive), arranca el servidor y abre el navegador. Al cerrar la ventana del terminal, los cambios se guardan automáticamente en el `.db` del grado.

### Linux (Ubuntu / Debian)

```bash
bash "horarios/GIM/Iniciar Horarios GIM 2627.sh"
```

Requiere `lsof` y `curl` instalados (`sudo apt install lsof curl`). El navegador se abre automáticamente con `xdg-open`.

### Windows

Doble clic en el fichero `.bat` del grado correspondiente.

**Prerequisito — Python 3.9 o superior:**
1. Descarga el instalador desde [python.org/downloads](https://www.python.org/downloads/)
2. Durante la instalación, marca **"Add Python to PATH"** (imprescindible)
3. Completa la instalación y haz doble clic en el `.bat`

> ⚠️ Para que los cambios se guarden correctamente en Windows, cierra el servidor **pulsando cualquier tecla** en la ventana de comandos, no con el botón X.

### Manual (cualquier plataforma)

```bash
# Grado GIM (2026-2027)
CONFIG_PATH_OVERRIDE="horarios/GIM" python3 servidor_horarios.py

# Grado GIDI
CONFIG_PATH_OVERRIDE="horarios/GIDI" python3 servidor_horarios.py
```

Abre el navegador en `http://localhost:<puerto>` (el puerto se define en `config.json` de cada grado).

---

## Crear un grado nuevo o DTIE

Doble clic en `launchers/Janux.command` (macOS) o equivalente para tu plataforma. Se abre el asistente Janux en `http://localhost:8092` con dos opciones:

- **Grado nuevo**: wizard de varios pasos. Genera `horarios/<SIGLAS>/config.json`, el CSV de asignaturas y la BD.
- **Doble Grado (DTIE)**: combina asignaturas marcadas como destacadas (⭐) de dos grados origen. Lee las BDs de origen y genera la carpeta del DTIE.

### Herramientas de línea de comandos

```bash
# Inicializar BD desde cero (config.json + CSV de asignaturas):
python3 tools/setup_grado.py horarios/GIDI asignaturas_GIDI.csv --force

# Importar horarios desde Excel (formato semanal UPCT):
python3 tools/importar_horarios.py <fichero.xlsx> horarios/<SIGLAS>/

# Exportar horarios a Excel (plantilla UPCT):
python3 tools/exportar_excel.py [ruta_salida.xlsx]
```

> ⚠️ `setup_grado.py --force` **elimina todos los ajustes manuales** de la BD.

---

## Vistas

### Semana
Grilla lunes-viernes × 6 franjas horarias (9:00–21:00, bloques de 2 horas). Panel lateral con horas acumuladas por asignatura. Navegación por curso, cuatrimestre, grupo y semana. Exportación PDF directa.

### Todas
Scroll vertical de todas las semanas del cuatrimestre. Exportación PDF multipágina.

### Estadísticas
Tabla de horas reales impartidas vs. horas declaradas en fichas docentes (AF1, AF2, AF4). Badge verde si coinciden, rojo si hay desviación. Desglose por subgrupo para laboratorio e informática. Posibilidad de excluir asignaturas del cómputo de un grupo concreto.

### Parciales
Calendario global de exámenes parciales. Detección automática de conflictos de turno entre cursos consecutivos (1º-2º, 2º-3º, 3º-4º).

### Finales
Calendario de exámenes finales con tres períodos (enero, junio, julio). Distribución automática sin solapamientos, respetando los ya asignados manualmente. Exportación a PDF oficial (tabla + calendario semanal). Checklist para excluir asignaturas.

### Festivos
Gestión de festivos y días no lectivos del calendario del grado. Los días marcados bloquean la columna correspondiente en la vista de semana.

---

## Base de datos

SQLite independiente por grado. Tablas persistentes: `asignaturas`, `grupos`, `semanas`, `clases`, `fichas`, `franjas`. Tablas dinámicas (creadas automáticamente si no existen): `fichas_override`, `festivos_calendario`, `examenes_finales`, `finales_excluidas`, `asignaturas_destacadas`.

El tipo de actividad se codifica en el campo `aula` de `clases`:

| Valor de `aula` | Tipo |
|-----------------|------|
| `""` (vacío) | AF1 — Teoría |
| `"LAB"` | AF2 — Laboratorio |
| `"INFO"` / `"Aula:…"` | AF4 — Informática |
| Otro texto | PS — Puesto singular |

Los días con `es_no_lectivo=1` bloquean la columna entera en la vista de semana.

---

## Configuración (`config.json`)

Cada grado se define completamente en su `horarios/<SIGLAS>/config.json`. Secciones principales:

- **`institution`** / **`degree`** — nombre, siglas y logos
- **`server`** — puerto, nombre del `.db` y etiqueta del curso (`curso_label`)
- **`degree_structure`** — cursos, semanas, grupos por cuatrimestre y franjas horarias
- **`calendario`** — fechas de inicio/fin por cuatrimestre, festivos y vacaciones
- **`branding`** — colores corporativos CSS (`primary`, `accent`, `bg`)
- **`activity_types`** — definición de AF1/AF2/AF4 (patrones del campo `aula`)
- **`tipo_to_af`** — mapeo tipo de actividad Excel → AF (ej. `INF→AF4`, `LAB→AF2`)
- **`ui`** — badge de asignaturas destacadas (ej. `"DTIE"`) y prefijo de exportación PDF

---

## API

Principales endpoints del servidor:

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET` | `/api/schedule` | Datos completos del grado (franjas, asignaturas, grupos, fichas, config) |
| `POST` | `/api/clase/update` | Editar campos de una clase existente |
| `POST` | `/api/clase/create` | Crear una clase nueva |
| `POST` | `/api/clase/delete` | Eliminar una clase |
| `POST` | `/api/clase/move` | Mover o intercambiar (swap) una clase a otro día/franja |
| `POST` | `/api/asignatura` | Crear, renombrar o eliminar asignatura |
| `POST` | `/api/ficha-override` | Excluir/incluir asignatura del cómputo de un grupo |
| `POST` | `/api/destacada/toggle` | Marcar/desmarcar clase como destacada ⭐ (DTIE) |
| `GET` | `/api/festivos` | Listar festivos y días no lectivos |
| `POST` | `/api/festivos/set` | Añadir, modificar o eliminar un festivo |
| `GET` | `/api/finales` | Listar exámenes finales |
| `POST` | `/api/finales/set` | Añadir, actualizar o eliminar un examen final |
| `POST` | `/api/finales/batch-set` | Insertar múltiples exámenes en una transacción |
| `POST` | `/api/finales/reset-auto` | Eliminar exámenes auto-generados de un período |
| `GET` | `/api/finales/checklist` | Asignaturas excluidas del calendario de finales |
| `POST` | `/api/finales/checklist/toggle` | Marcar/desmarcar asignatura como excluida |
| `GET` | `/api/finales/export-pdf` | Generar PDF oficial de los 3 períodos de finales |
| `GET` | `/api/exportar_excel` | Exportar horarios a Excel (plantilla UPCT) |
| `POST` | `/api/db/backup` | Crear copia de seguridad con timestamp en `backups/` |
| `GET` | `/api/db/download` | Descargar el `.db` activo |
| `POST` | `/api/db/import` | Sustituir la BD activa por un fichero subido |
| `GET` | `/api/classrooms` | Lista de aulas disponibles |
| `GET` | `/api/logo` | Logo de la institución en PNG |

---

## Dependencias

**Python** (≥ 3.9):
```bash
pip install -r requirements.txt
# openpyxl>=3.1   — importar/exportar Excel
# pdfplumber      — compatibilidad con instalaciones anteriores
# reportlab       — exportación PDF de finales (instalar aparte si se necesita)
```

**JavaScript** (cargadas desde CDN, sin instalación):
- [html2canvas 1.4.1](https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js)
- [jsPDF 2.5.1](https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js)

---

## Despliegue Docker

```bash
cd docker/
HOST_PORT=8765 DB_PATH=/app/data/horarios.db docker-compose up -d
```

La BD se monta como volumen en `/app/data/`. El servidor la localiza mediante la variable `DB_PATH`.

---

## Licencia

MIT © 2026 Jesús Martínez
