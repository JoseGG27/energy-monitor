"""
Script de refresco de datos - ejecutar localmente con tus tokens.

Descarga los ultimos N dias de ESIOS y ENTSO-E, guarda los CSVs
en data/raw/ y los sube automaticamente a GitHub para que
Streamlit Cloud los sirva sin llamar a las APIs directamente.

Uso:
    python refresh_data.py          # ultimos 7 dias
    python refresh_data.py --days 30
    python refresh_data.py --dry-run  # descarga pero no sube a GitHub
"""
import argparse
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def run(cmd: str) -> int:
    """Ejecuta un comando de shell y devuelve el codigo de salida."""
    print(f"\n$ {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=BASE_DIR)
    return result.returncode


def download_esios(start: date, end: date):
    from collectors.esios_collector import get_spot_price, get_pvpc
    from config.settings import ESIOS_TOKEN

    if not ESIOS_TOKEN:
        print("[ESIOS] Token no configurado - omitiendo.")
        return

    print(f"\n=== ESIOS ({start} -> {end}) ===")
    try:
        df = get_spot_price(start, end)
        print(f"  Precio spot: {len(df)} registros")
    except Exception as e:
        print(f"  [ERROR spot] {e}")

    try:
        df = get_pvpc(start, end)
        print(f"  PVPC:        {len(df)} registros")
    except Exception as e:
        print(f"  [ERROR PVPC] {e}")


def download_entsoe(start: date, end: date):
    from collectors.entsoe_collector import get_iberian_comparison
    from config.settings import ENTSOE_TOKEN

    if not ENTSOE_TOKEN:
        print("[ENTSO-E] Token no configurado - omitiendo.")
        return

    print(f"\n=== ENTSO-E ES/FR/DE ({start} -> {end}) ===")
    try:
        df = get_iberian_comparison(start, end)
        if not df.empty:
            resumen = df.groupby("country")["precio_eur_mwh"].agg(["mean", "min", "max"]).round(1)
            print(resumen.to_string())
        else:
            print("  Sin datos disponibles.")
    except Exception as e:
        print(f"  [ERROR] {e}")


def push_to_github(days: int):
    """Hace commit y push de los CSVs nuevos/actualizados."""
    hoy = date.today().strftime("%Y-%m-%d")

    # Verificar que hay cambios
    result = subprocess.run("git status --porcelain data/raw/",
                            shell=True, capture_output=True, text=True, cwd=BASE_DIR)
    if not result.stdout.strip():
        print("\n[OK] No hay cambios nuevos en data/raw/ - nada que subir.")
        return

    cmds = [
        "git add data/raw/esios_*.csv data/raw/entsoe_*.csv",
        f'git commit -m "data: refresco automatico {hoy} (ultimos {days} dias)"',
        "git push",
    ]
    for cmd in cmds:
        code = run(cmd)
        if code != 0:
            print(f"\n[ERROR] Fallo: {cmd}")
            sys.exit(code)

    print(f"\n[OK] Datos subidos a GitHub - Streamlit Cloud se actualizara en ~1 min.")


def main():
    parser = argparse.ArgumentParser(description="Refresco de datos ESIOS + ENTSO-E")
    parser.add_argument("--days",    type=int, default=7,    help="Dias hacia atras a descargar")
    parser.add_argument("--dry-run", action="store_true",    help="Descarga pero no sube a GitHub")
    args = parser.parse_args()

    today = date.today()
    start = today - timedelta(days=args.days)
    end   = today - timedelta(days=1)

    print(f"{'='*55}")
    print(f"  REFRESCO DE DATOS - {today}")
    print(f"  Periodo: {start} -> {end}  ({args.days} dias)")
    print(f"{'='*55}")

    download_esios(start, end)
    download_entsoe(start, end)

    if args.dry_run:
        print("\n[dry-run] Descarga completada. No se sube a GitHub.")
    else:
        push_to_github(args.days)


if __name__ == "__main__":
    main()
