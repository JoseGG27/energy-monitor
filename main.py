"""
Punto de entrada principal del Monitor de Precios y Regulacion Energetica.
Uso: python main.py [--mode omie|full] [--days 7]
"""
import argparse
from datetime import date, timedelta


def run_omie_only(days: int):
    """Modo sin tokens: solo OMIE (datos publicos)."""
    from collectors.omie_collector import download_omie_range
    from analysis.price_analysis import load_omie_data, generate_summary_report
    from alerts.alert_engine import AlertEngine

    today = date.today()
    start = today - timedelta(days=days)
    end   = today - timedelta(days=1)

    print(f"\n=== Descargando OMIE ({start} -> {end}) ===")
    df = download_omie_range(start, end)

    if df.empty:
        print("Sin datos disponibles.")
        return

    print(f"\n=== Analizando precios ===")
    report = generate_summary_report(df, "resumen_omie")

    print(f"\n=== Procesando alertas ===")
    engine = AlertEngine()
    engine.process_dataframe(df)
    summary = engine.save_and_report()
    print(summary)

    print(f"\n=== Resumen ejecutivo ===")
    print(f"Periodo:            {report['periodo']}")
    print(f"Precio medio:       {report['precio_medio_eur_mwh']} EUR/MWh")
    print(f"Precio maximo:      {report['precio_max_eur_mwh']} EUR/MWh")
    print(f"Anomalias:          {report['anomalias_detectadas']}")
    print(f"Horas carga optima: {report['horas_carga_optima']}")
    print(f"Ahorro potencial:   {report['ahorro_potencial_pct']}% cargando en horas valle vs punta")
    print(f"Coste sesion optimo:{report['coste_sesion_optimo_eur']} EUR (50 kWh)")


def run_full(days: int):
    """Modo completo: OMIE + ESIOS + ENTSO-E (requiere tokens)."""
    from collectors.esios_collector import get_spot_price
    from collectors.entsoe_collector import get_iberian_comparison

    today = date.today()
    start = today - timedelta(days=days)
    end   = today - timedelta(days=1)

    run_omie_only(days)

    print(f"\n=== Descargando ESIOS ===")
    try:
        df_esios = get_spot_price(start, end)
        if not df_esios.empty:
            print(f"ESIOS: {len(df_esios)} registros")
    except EnvironmentError as e:
        print(f"[ESIOS] {e}")

    print(f"\n=== Descargando ENTSO-E (ES/FR/DE) ===")
    try:
        df_entsoe = get_iberian_comparison(start, end)
        if not df_entsoe.empty:
            print(df_entsoe.groupby("country")["precio_eur_mwh"].mean())
    except EnvironmentError as e:
        print(f"[ENTSO-E] {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monitor de Precios Energeticos")
    parser.add_argument("--mode", choices=["omie", "full"], default="omie")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    if args.mode == "omie":
        run_omie_only(args.days)
    else:
        run_full(args.days)
