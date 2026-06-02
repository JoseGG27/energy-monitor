"""
Modulo de analisis de precios electricos.
Calcula estadisticas, detecta anomalias y genera senales relevantes
para el negocio de carga EV (sites ABEI en ES/FR/DE).
"""
import json
import pandas as pd
import numpy as np
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import DATA_PROCESSED_DIR, ALERT_PRICE_HIGH_EUR_MWH, ALERT_PRICE_LOW_EUR_MWH


def load_omie_data(csv_path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, parse_dates=["fecha"])
    return df.sort_values("fecha")


def daily_stats(df: pd.DataFrame, price_col: str = "precio_es") -> pd.DataFrame:
    """Estadisticas diarias: media, min, max, volatilidad."""
    df["date"] = pd.to_datetime(df["fecha"]).dt.date
    stats = df.groupby("date")[price_col].agg(
        media="mean", minimo="min", maximo="max", volatilidad="std",
        p25=lambda x: x.quantile(0.25),
        p75=lambda x: x.quantile(0.75),
    ).reset_index()
    stats["spread"] = stats["maximo"] - stats["minimo"]
    return stats


def peak_valley_hours(df: pd.DataFrame, price_col: str = "precio_es") -> dict:
    """Identifica horas punta y valle. Util para optimizar carga EV."""
    hourly = df.groupby("hora")[price_col].mean().sort_values()
    return {
        "horas_valle":  hourly.head(6).index.tolist(),
        "horas_punta":  hourly.tail(6).index.tolist(),
        "precio_medio": hourly.mean(),
        "ahorro_potencial_pct": round(
            (hourly.tail(6).mean() - hourly.head(6).mean()) / hourly.mean() * 100, 1
        ),
    }


def detect_price_spikes(df: pd.DataFrame, price_col: str = "precio_es", z_threshold: float = 2.5) -> pd.DataFrame:
    """Detecta horas con precio anomalamente alto o bajo (Z-score)."""
    mean = df[price_col].mean()
    std  = df[price_col].std()
    df = df.copy()
    df["z_score"]  = (df[price_col] - mean) / std
    df["es_spike"] = df["z_score"].abs() > z_threshold
    df["tipo"]     = np.where(df["z_score"] > z_threshold, "pico_alto",
                     np.where(df["z_score"] < -z_threshold, "valle_extremo", "normal"))
    spikes = df[df["es_spike"]].copy()
    print(f"[Analisis] {len(spikes)} anomalias detectadas (umbral Z={z_threshold})")
    return spikes


def charging_cost_analysis(df: pd.DataFrame, kwh_per_session: float = 50.0, sessions_per_day: int = 20) -> pd.DataFrame:
    """Estima coste de energia por sesion de carga segun hora del dia."""
    hourly_avg = df.groupby("hora")["precio_es"].mean().reset_index()
    hourly_avg.columns = ["hora", "precio_eur_mwh"]
    hourly_avg["precio_eur_kwh"]      = hourly_avg["precio_eur_mwh"] / 1000
    hourly_avg["coste_sesion_eur"]    = hourly_avg["precio_eur_kwh"] * kwh_per_session
    hourly_avg["coste_diario_eur"]    = hourly_avg["coste_sesion_eur"] * sessions_per_day
    hourly_avg["ahorro_vs_punta_eur"] = (
        hourly_avg["coste_sesion_eur"].max() - hourly_avg["coste_sesion_eur"]
    )
    return hourly_avg.sort_values("hora")


def generate_summary_report(df: pd.DataFrame, output_name: str = "resumen") -> dict:
    """Genera un diccionario resumen exportable a JSON."""
    stats  = daily_stats(df)
    peaks  = peak_valley_hours(df)
    spikes = detect_price_spikes(df)
    costs  = charging_cost_analysis(df)

    report = {
        "periodo":               f"{df['fecha'].min()} - {df['fecha'].max()}",
        "precio_medio_eur_mwh":  round(df["precio_es"].mean(), 2),
        "precio_max_eur_mwh":    round(df["precio_es"].max(), 2),
        "precio_min_eur_mwh":    round(df["precio_es"].min(), 2),
        "anomalias_detectadas":  len(spikes),
        "horas_carga_optima":    peaks["horas_valle"],
        "ahorro_potencial_pct":  peaks["ahorro_potencial_pct"],
        "coste_sesion_optimo_eur": round(costs["coste_sesion_eur"].min(), 3),
        "coste_sesion_punta_eur":  round(costs["coste_sesion_eur"].max(), 3),
        "alertas": [],
    }
    if report["precio_max_eur_mwh"] > ALERT_PRICE_HIGH_EUR_MWH:
        report["alertas"].append(f"PRECIO ALTO: {report['precio_max_eur_mwh']} EUR/MWh")
    if report["precio_min_eur_mwh"] < ALERT_PRICE_LOW_EUR_MWH:
        report["alertas"].append(f"PRECIO BAJO: {report['precio_min_eur_mwh']} EUR/MWh")

    out_path = DATA_PROCESSED_DIR / f"{output_name}.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"[Analisis] Resumen guardado en {out_path}")
    return report
