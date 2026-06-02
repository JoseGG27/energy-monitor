"""
Colector de datos de ESIOS (REE - Red Electrica de Espana).
Requiere token API - solicitar a consultasios@ree.es
"""
import requests
import pandas as pd
from datetime import date, timedelta
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import ESIOS_TOKEN, ESIOS_BASE_URL, ESIOS_INDICATOR_PVPC, ESIOS_INDICATOR_SPOT, DATA_RAW_DIR


def _check_token():
    if not ESIOS_TOKEN:
        raise EnvironmentError(
            "ESIOS_TOKEN no configurado. Anade tu token en el archivo .env\n"
            "Solicita acceso en: consultasios@ree.es"
        )


def get_esios_indicator(indicator_id: int, start: date, end: date) -> pd.DataFrame:
    """Descarga un indicador de ESIOS para un rango de fechas."""
    _check_token()
    headers = {
        "Accept":        "application/json; application/vnd.esios-api-v1+json",
        "Content-Type":  "application/json",
        "Host":          "api.esios.ree.es",
        "x-api-key":     ESIOS_TOKEN,
    }
    params = {
        "start_date": f"{start.isoformat()}T00:00:00",
        "end_date":   f"{end.isoformat()}T23:59:59",
    }
    url = f"{ESIOS_BASE_URL}/indicators/{indicator_id}"
    r = requests.get(url, headers=headers, params=params, timeout=30)
    r.raise_for_status()

    data = r.json()
    values = data.get("indicator", {}).get("values", [])
    if not values:
        return pd.DataFrame()

    df = pd.DataFrame(values)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.rename(columns={"value": "precio_eur_mwh"})
    df = df[["datetime", "precio_eur_mwh"]].sort_values("datetime")

    out_path = DATA_RAW_DIR / f"esios_{indicator_id}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"
    df.to_csv(out_path, index=False)
    print(f"[ESIOS] Indicador {indicator_id}: {len(df)} registros en {out_path}")
    return df


def get_pvpc(start: date, end: date) -> pd.DataFrame:
    """Precio PVPC (tarifa regulada para consumidores)."""
    return get_esios_indicator(ESIOS_INDICATOR_PVPC, start, end)


def get_spot_price(start: date, end: date) -> pd.DataFrame:
    """Precio spot del mercado diario."""
    return get_esios_indicator(ESIOS_INDICATOR_SPOT, start, end)


if __name__ == "__main__":
    today = date.today()
    try:
        df = get_spot_price(today - timedelta(days=7), today)
        print(df.head())
    except EnvironmentError as e:
        print(f"[INFO] {e}")
