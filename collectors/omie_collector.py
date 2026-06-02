"""
Colector de datos de OMIE (Operador del Mercado Ibérico de Energía).
Sin token necesario - datos publicos en TXT.
Descarga precios del mercado diario (SPOT) hora a hora.

Formato de URL real OMIE:
  INT_PBC_EV_H_1_{day}_{month}_{year}_{day}_{month}_{year}.TXT
Los precios vienen en una fila con 24 columnas (una por hora).
"""
import requests
import pandas as pd
from datetime import date, timedelta
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import DATA_RAW_DIR

OMIE_URL_TEMPLATE = (
    "https://www.omie.es/sites/default/files/dados/"
    "AGNO_{year}/MES_{month:02d}/TXT/"
    "INT_PBC_EV_H_1_{day:02d}_{month:02d}_{year}_{day:02d}_{month:02d}_{year}.TXT"
)


def download_omie_day(target_date: date) -> pd.DataFrame | None:
    """
    Descarga el precio marginal del mercado diario OMIE para una fecha.
    Devuelve DataFrame con columnas: fecha, hora, precio_es (EUR/MWh), precio_pt (EUR/MWh)
    """
    url = OMIE_URL_TEMPLATE.format(
        year=target_date.year,
        month=target_date.month,
        day=target_date.day,
    )
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
    except requests.HTTPError:
        print(f"[OMIE] Sin datos para {target_date} (archivo no disponible aun)")
        return None
    except requests.RequestException as e:
        print(f"[OMIE] Error de red: {e}")
        return None

    lines = r.text.splitlines()

    # Detectar formato: horario (1,2,...,24) o cuartohorario (H1Q1,H1Q2,...,H24Q4)
    header_row = next((l for l in lines if l.startswith(";")), None)
    cuartohorario = header_row and "H1Q1" in header_row

    precio_es_row = next((l for l in lines if "espa" in l.lower() and "EUR" in l), None)
    precio_pt_row = next((l for l in lines if "portugu" in l.lower() and "EUR" in l), None)

    if not precio_es_row:
        print(f"[OMIE] No se encontraron precios ES para {target_date}")
        return None

    def parse_all_values(row: str) -> list:
        """Extrae todos los valores numéricos de una fila OMIE."""
        values = []
        for p in row.split(";")[1:]:
            p = p.strip().replace(",", ".").replace("\xa0", "").replace(" ", "")
            if p:
                try:
                    values.append(float(p))
                except ValueError:
                    pass
        return values

    def agrupar_por_hora(valores: list) -> list:
        """Agrupa 96 cuartos de hora en 24 medias horarias."""
        horas = []
        for h in range(24):
            cuartos = valores[h * 4 : h * 4 + 4]
            horas.append(sum(cuartos) / len(cuartos) if cuartos else None)
        return horas

    raw_es = parse_all_values(precio_es_row)
    raw_pt = parse_all_values(precio_pt_row) if precio_pt_row else []

    if cuartohorario:
        precios_es = agrupar_por_hora(raw_es)
        precios_pt = agrupar_por_hora(raw_pt) if raw_pt else [None] * 24
        print(f"[OMIE] Formato cuartohorario detectado — 96 intervalos agrupados a 24h")
    else:
        precios_es = raw_es[:24]
        precios_pt = raw_pt[:24] if raw_pt else [None] * 24

    records = []
    for hora, (p_es, p_pt) in enumerate(zip(precios_es, precios_pt), start=1):
        hora_ts = hora if hora < 24 else 0
        fecha_ts = pd.Timestamp(target_date) + pd.Timedelta(days=1 if hora == 24 else 0)
        records.append({
            "fecha":     fecha_ts.replace(hour=hora_ts),
            "hora":      hora,
            "precio_es": p_es,
            "precio_pt": p_pt,
        })

    if not records:
        print(f"[OMIE] No se pudieron parsear datos para {target_date}")
        return None

    df = pd.DataFrame(records)
    out_path = DATA_RAW_DIR / f"omie_{target_date.strftime('%Y%m%d')}.csv"
    df.to_csv(out_path, index=False)
    print(f"[OMIE] {len(df)} registros guardados en {out_path}")
    return df


def download_omie_range(start: date, end: date) -> pd.DataFrame:
    """Descarga un rango de fechas y devuelve un DataFrame consolidado."""
    frames = []
    current = start
    while current <= end:
        df = download_omie_day(current)
        if df is not None:
            frames.append(df)
        current += timedelta(days=1)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    out_path = DATA_RAW_DIR / f"omie_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"
    combined.to_csv(out_path, index=False)
    print(f"[OMIE] Rango completo: {len(combined)} registros guardados en {out_path}")
    return combined


if __name__ == "__main__":
    today = date.today()
    week_ago = today - timedelta(days=7)
    print(f"Descargando OMIE del {week_ago} al {today - timedelta(days=1)}...")
    df = download_omie_range(week_ago, today - timedelta(days=1))
    if not df.empty:
        print(df.describe())
