"""
Motor de alertas: detecta condiciones relevantes y genera notificaciones.
"""
import json
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import ALERT_PRICE_HIGH_EUR_MWH, ALERT_PRICE_LOW_EUR_MWH, DATA_PROCESSED_DIR


class AlertEngine:
    def __init__(self):
        self.alerts_log = DATA_PROCESSED_DIR / "alerts_log.json"
        self.alerts = []

    def check_price_threshold(self, precio: float, hora: int, fecha: str):
        if precio > ALERT_PRICE_HIGH_EUR_MWH:
            self._add_alert("PRECIO_ALTO", f"Precio {precio:.1f} EUR/MWh en hora {hora} del {fecha}", "high")
        elif precio < ALERT_PRICE_LOW_EUR_MWH:
            self._add_alert("PRECIO_BAJO", f"Precio {precio:.1f} EUR/MWh en hora {hora} del {fecha} - OPORTUNIDAD", "opportunity")

    def check_daily_anomaly(self, pct_change: float, fecha: str):
        if abs(pct_change) > 30:
            direction = "subida" if pct_change > 0 else "bajada"
            self._add_alert("ANOMALIA_DIARIA", f"{direction.upper()} del {abs(pct_change):.1f}% respecto ayer ({fecha})", "high")

    def _add_alert(self, tipo: str, mensaje: str, nivel: str):
        alert = {
            "timestamp": datetime.now().isoformat(),
            "tipo":      tipo,
            "nivel":     nivel,
            "mensaje":   mensaje,
        }
        self.alerts.append(alert)
        tag = {"high": "[!!]", "opportunity": "[OK]", "info": "[--]"}.get(nivel, "[  ]")
        print(f"[ALERTA] {tag} {tipo}: {mensaje}")

    def process_dataframe(self, df):
        """Procesa un DataFrame OMIE completo y genera alertas automaticamente."""
        df_sorted = df.sort_values("fecha")
        daily_avg = df_sorted.groupby(df_sorted["fecha"].dt.date)["precio_es"].mean()

        for i, (fecha, precio_medio) in enumerate(daily_avg.items()):
            if i > 0:
                prev_precio = daily_avg.iloc[i - 1]
                pct_change = (precio_medio - prev_precio) / prev_precio * 100
                self.check_daily_anomaly(pct_change, str(fecha))

        for _, row in df.iterrows():
            self.check_price_threshold(row["precio_es"], row.get("hora", 0), str(row["fecha"]))

        return self.alerts

    def save_and_report(self) -> str:
        """Guarda el log y devuelve un resumen de texto."""
        with open(self.alerts_log, "w") as f:
            json.dump(self.alerts, f, indent=2)

        if not self.alerts:
            return "Sin alertas en el periodo analizado."

        high  = [a for a in self.alerts if a["nivel"] == "high"]
        opps  = [a for a in self.alerts if a["nivel"] == "opportunity"]
        infos = [a for a in self.alerts if a["nivel"] == "info"]

        lines = [
            f"=== MONITOR ENERGETICO - {datetime.now().strftime('%d/%m/%Y')} ===",
            f"Total alertas: {len(self.alerts)}",
            f"  Criticas: {len(high)}",
            f"  Oportunidades: {len(opps)}",
            f"  Informativas: {len(infos)}",
            "",
        ]
        for a in self.alerts[:10]:
            lines.append(f"[{a['nivel'].upper()}] {a['tipo']}: {a['mensaje']}")

        return "\n".join(lines)
