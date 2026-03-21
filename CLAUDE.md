# Gestor de Horarios GIM — UPCT

Aplicación web para visualizar y gestionar los horarios del Grado en Ingeniería Mecánica (4 cursos, 2 cuatrimestres).

## Arrancar

**Doble clic en el `.command` correspondiente** (siempre usar esto, no el terminal):

- `Iniciar Horarios GIM.command` → curso 2025-2026
- `Iniciar Horarios GIM 2627.command` → curso 2026-2027

Los cambios se guardan automáticamente al cerrar la ventana del terminal.

## Vistas disponibles

- **Semana** — horario semanal por grupo, exportable a PDF
- **Todas** — todas las semanas de un vistazo, exportable a PDF
- **Estadísticas** — horas reales frente a las previstas por asignatura
- **Parciales** — calendario de exámenes y detección de solapamientos entre cursos

## Añadir un nuevo grado

Desde la propia aplicación, mediante la interfaz gráfica.

## Reconstruir datos desde cero

Solo necesario si se actualizan los ficheros Excel o el PDF de fichas. ⚠️ Se perderán los ajustes manuales.

```bash
# Si cambian los Excel de horarios:
python3 rebuild_db.py && python3 rebuild_fichas.py && python3 update_calendario.py

# Si solo cambia el PDF de fichas:
python3 rebuild_fichas.py && python3 update_calendario.py

# Si solo cambia el calendario 2026-2027 (editar fechas en update_calendario.py):
python3 update_calendario.py
```

## Advertencias

- **No modificar `horarios.db` directamente** — es la base de datos principal.
- Si Dropbox sobreescribe la base de datos, reconstruir con: `python3 rebuild_db.py && python3 rebuild_fichas.py`
- `update_calendario.py` nunca toca `horarios.db`; genera `horarios_2627.db` por separado.

## Detalle técnico

Ver `TECHNICAL.md` para el esquema de la base de datos, la API, el histórico de sesiones y otros detalles de implementación.
