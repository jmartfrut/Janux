#!/usr/bin/env python3
"""
tools/reload_fichas.py — Sincroniza las fichas docentes desde el CSV → BD
=========================================================================
Lee el CSV de fichas del grado (config/fichas_<SIGLAS>.csv) y actualiza la
tabla `fichas` de la BD SQLite, incluyendo el campo `cuatrimestre`.

Casos soportados:
  - cuatrimestre = '1C' / '2C' → ficha normal (valores completos)
  - cuatrimestre = 'A'          → asignatura anual; el frontend divide
                                   automáticamente los AFs por 2 al mostrar
                                   estadísticas para un cuatrimestre concreto.
  - cuatrimestre vacío / NULL   → se guarda como NULL (comportamiento legacy)

⚠️  Solo actualiza las fichas de asignaturas que ya existen en la BD.
    No crea asignaturas nuevas ni elimina las existentes.
    Si una asignatura del CSV no existe en la BD, se avisa y se omite.

Uso:
    python3 tools/reload_fichas.py horarios/GIM
    python3 tools/reload_fichas.py horarios/GIDI
    python3 tools/reload_fichas.py horarios/GIM --dry-run   # sin escribir
"""

import argparse
import csv
import io
import json
import sqlite3
import sys
from pathlib import Path

# Forzar UTF-8 en stdout/stderr para evitar errores con emojis en Windows (cp1252)
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR   = SCRIPT_DIR.parent


def load_config(grado_dir: Path) -> dict:
    cfg_path = grado_dir / "config.json"
    if not cfg_path.exists():
        sys.exit(f"ERROR: No existe {cfg_path}")
    with open(cfg_path, encoding="utf-8") as f:
        return json.load(f)


def find_fichas_csv(grado_dir: Path, cfg: dict) -> Path:
    """Busca el CSV de fichas: primero en config/, luego en grado/."""
    siglas = cfg["degree"]["acronym"]
    candidates = [
        ROOT_DIR / "config" / f"fichas_{siglas}.csv",
        grado_dir / f"fichas_{siglas}.csv",
        grado_dir / "fichas.csv",
    ]
    for p in candidates:
        if p.exists():
            return p
    sys.exit(
        f"ERROR: No se encontró el CSV de fichas para '{siglas}'.\n"
        f"Buscado en: {', '.join(str(p) for p in candidates)}"
    )


def parse_csv(csv_path: Path) -> list[dict]:
    """Parsea el CSV y devuelve lista de dicts normalizados."""
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):
            codigo = (row.get("codigo") or "").strip()
            if not codigo:
                continue  # sin código → ignorar (TFG, Prácticas, etc.)

            def _num(key, default=0):
                val = (row.get(key) or "").strip()
                try:
                    return int(float(val))
                except (ValueError, TypeError):
                    return default

            def _float(key, default=0.0):
                val = (row.get(key) or "").strip()
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return default

            cuat_raw = (row.get("cuatrimestre") or "").strip().upper()
            # Normalizar: acepta '1C', '2C', 'A', '1c', '2c', 'a', ''
            cuat = cuat_raw if cuat_raw in ("1C", "2C", "A") else None

            rows.append({
                "codigo":        codigo,
                "nombre":        (row.get("nombre") or "").strip(),
                "cuatrimestre":  cuat,
                "creditos":      _float("creditos"),
                "af1":           _num("af1"),
                "af2":           _num("af2"),
                "af3":           _num("af3"),
                "af4":           _num("af4"),
                "af5":           _num("af5"),
                "af6":           _num("af6"),
            })
    return rows


def reload_fichas(db_path: Path, fichas_csv: Path, dry_run: bool = False) -> None:
    rows = parse_csv(fichas_csv)
    print(f"  CSV leído: {fichas_csv}  ({len(rows)} asignaturas con código)")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Asegurar que la columna cuatrimestre existe (por si la migración v10
    # no se ha aplicado todavía; reload_fichas.py puede usarse standalone)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(fichas)").fetchall()}
    if "cuatrimestre" not in cols:
        if not dry_run:
            conn.execute("ALTER TABLE fichas ADD COLUMN cuatrimestre TEXT DEFAULT NULL")
            conn.commit()
            print("  ✅ Columna 'cuatrimestre' añadida a fichas (migración automática).")
        else:
            print("  [dry-run] Añadiría columna 'cuatrimestre' a fichas.")

    # Construir mapa codigo → asignatura_id desde la BD
    asig_map = {
        r["codigo"]: r["id"]
        for r in conn.execute("SELECT id, codigo FROM asignaturas").fetchall()
    }

    updated = 0
    skipped = 0
    for r in rows:
        asig_id = asig_map.get(r["codigo"])
        if asig_id is None:
            print(f"  ⚠️  Código '{r['codigo']}' ({r['nombre']}) no encontrado en BD — omitido.")
            skipped += 1
            continue

        if dry_run:
            print(
                f"  [dry-run] UPDATE fichas SET creditos={r['creditos']}, "
                f"af1={r['af1']}, af2={r['af2']}, af3={r['af3']}, af4={r['af4']}, "
                f"af5={r['af5']}, af6={r['af6']}, cuatrimestre={r['cuatrimestre']!r} "
                f"WHERE asignatura_id={asig_id}  ({r['codigo']} {r['nombre']})"
            )
        else:
            conn.execute("""
                UPDATE fichas
                SET creditos=?, af1=?, af2=?, af3=?, af4=?, af5=?, af6=?, cuatrimestre=?
                WHERE asignatura_id=?
            """, (
                r["creditos"], r["af1"], r["af2"], r["af3"],
                r["af4"], r["af5"], r["af6"], r["cuatrimestre"],
                asig_id
            ))
        updated += 1

    if not dry_run:
        conn.commit()
        print(f"  ✅ {updated} ficha(s) actualizadas, {skipped} omitida(s).")
    else:
        print(f"  [dry-run] {updated} ficha(s) se actualizarían, {skipped} omitida(s).")

    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Recarga fichas docentes desde CSV → BD SQLite del grado."
    )
    parser.add_argument(
        "grado_dir",
        help="Ruta a la carpeta del grado (ej: horarios/GIM)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Muestra lo que haría sin modificar la BD."
    )
    args = parser.parse_args()

    grado_dir = Path(args.grado_dir).resolve()
    if not grado_dir.is_dir():
        sys.exit(f"ERROR: No existe la carpeta '{grado_dir}'")

    cfg      = load_config(grado_dir)
    siglas   = cfg["degree"]["acronym"]
    db_name  = cfg.get("server", {}).get("db_name", "horarios.db")
    db_path  = grado_dir / db_name

    if not db_path.exists():
        sys.exit(f"ERROR: No existe la BD '{db_path}'")

    fichas_csv = find_fichas_csv(grado_dir, cfg)

    print(f"\n  Grado : {siglas}")
    print(f"  BD    : {db_path}")
    print(f"  CSV   : {fichas_csv}")
    if args.dry_run:
        print("  Modo  : DRY-RUN (sin cambios en la BD)\n")
    else:
        print()

    reload_fichas(db_path, fichas_csv, dry_run=args.dry_run)
    print()


if __name__ == "__main__":
    main()
