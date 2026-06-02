"""
Colector ENTSO-E - datos de precios europeos (Espana, Francia, Alemania).
Requiere token API - solicitar a transparency@entsoe.eu
"""
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import (
    ENTSOE_TOKEN, ENTSOE_BASE_URL,
    ENTSOE_AREA_ES, ENTSOE_AREA_FR, ENTSOE_AREA_DE,
    DATA_RAW_DIR
)

AREAS = {
    "ES": ENTSOE_AREA_ES,
    "FR": ENTSOE_AREA_FR,
    "DE": ENTSOE_AREA_DE,
}


def _check_token():
    if not ENTSOE_TOKEN:
        raise EnvironmentError(
            "ENTSOE_TOKEN no configurado. Anade tu token en .env\n"
            "Registro en: https://transparency.entsoe.eu\n"
            "Solicita acceso REST a: transparency@entsoe.eu"
        )


def get_day_ahead_prices(country: str, start: date, end: date) -> pd.DataFrame:
    """Descarga precios day-ahead para un pais (ES, FR, DE)."""
    _check_token()
    if country not in AREAS:
        raise ValueError(f"Pais no soportado: {country}. Usa: {list(AREAS.keys())}")

    params = {
        "securityToken":  ENTSOE_TOKEN,
        "documentType":   "A44",
        "in_Domain":      AREAS[country],
        "out_Domain":     AREAS[country],
        "periodStart":    start.strftime("%Y%m%d0000"),
        "periodEnd":      end.strftime("%Y%m%d2300"),
    }
    r = requests.get(ENTSOE_BASE_URL, params=params, timeout=30)
    r.raise_for_status()

    ns = {"ns": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"}
    root = ET.fromstring(r.text)

    records = []
    for ts in root.findall(".//ns:TimeSeries", ns):
        period = ts.find("ns:Period", ns)
        if period is None:
            continue
        start_str = period.find("ns:timeInterval/ns:start", ns)
        if start_str is None:
            continue
        t_start = pd.to_datetime(start_str.text)
        for pt in period.findall("ns:Point", ns):
            pos   = int(pt.find("ns:position", ns).text)
            price = float(pt.find("ns:price.amount", ns).text)
            records.append({
                "datetime":       t_start + pd.Timedelta(hours=pos - 1),
                "country":        country,
                "precio_eur_mwh": price,
            })

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    # Normalizar timezone UTC → local y eliminar duplicados (ENTSO-E devuelve múltiples TimeSeries)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_convert("Europe/Madrid").dt.tz_localize(None)
    df = df.sort_values("datetime")
    # Quedarse con el último precio publicado por hora (el más actualizado)
    df = df.drop_duplicates(subset=["datetime", "country"], keep="last").reset_index(drop=True)

    out_path = DATA_RAW_DIR / f"entsoe_{country}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"
    df.to_csv(out_path, index=False)
    print(f"[ENTSO-E] {country}: {len(df)} registros guardados")
    return df


def get_iberian_comparison(start: date, end: date) -> pd.DataFrame:
    """Descarga ES + FR + DE y devuelve un DataFrame comparativo."""
    frames = []
    for country in ["ES", "FR", "DE"]:
        try:
            df = get_day_ahead_prices(country, start, end)
            if not df.empty:
                frames.append(df)
        except Exception as e:
            print(f"[ENTSO-E] Error en {country}: {e}")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


if __name__ == "__main__":
    today = date.today()
    try:
        df = get_iberian_comparison(today - timedelta(days=7), today)
        if not df.empty:
            print(df.groupby("country")["precio_eur_mwh"].describe())
    except EnvironmentError as e:
        print(f"[INFO] {e}")
