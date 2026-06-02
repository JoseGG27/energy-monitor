"""
Dashboard público de precios eléctricos — energy-monitor
Ejecutar localmente:  streamlit run dashboard/app.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import json
from datetime import date, timedelta
from collectors.omie_collector import download_omie_range

# ── Configuración de página ──────────────────────────────────────────────────
st.set_page_config(
    page_title="Monitor Precios Eléctricos",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar ──────────────────────────────────────────────────────────────────
st.sidebar.title("⚡ Energy Monitor")
st.sidebar.markdown("Precios mercado ibérico (OMIE)")

days = st.sidebar.slider("Días a mostrar", min_value=1, max_value=30, value=7)
country = st.sidebar.radio("País", ["España (ES)", "Portugal (PT)"], index=0)
price_col = "precio_es" if "España" in country else "precio_pt"

st.sidebar.markdown("---")
st.sidebar.markdown("**Umbrales de alerta**")
umbral_alto = st.sidebar.number_input("Precio alto (EUR/MWh)", value=150.0, step=5.0)
umbral_bajo = st.sidebar.number_input("Precio bajo (EUR/MWh)", value=20.0, step=5.0)

# ── Carga de datos ───────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_data(days: int) -> pd.DataFrame:
    today = date.today()
    start = today - timedelta(days=days)
    end   = today - timedelta(days=1)
    raw_dir = Path(__file__).parent.parent / "data" / "raw"
    frames = []
    for d in pd.date_range(start, end):
        p = raw_dir / f"omie_{d.strftime('%Y%m%d')}.csv"
        if p.exists():
            frames.append(pd.read_csv(p, parse_dates=["fecha"]))
    if frames:
        return pd.concat(frames, ignore_index=True).sort_values("fecha")
    return download_omie_range(start, end)

with st.spinner("Cargando datos de OMIE..."):
    df = load_data(days)

if df.empty:
    st.error("No hay datos disponibles para el período seleccionado.")
    st.stop()

df["fecha"]    = pd.to_datetime(df["fecha"])
df["dia"]      = df["fecha"].dt.date
df["hora_num"] = df["hora"].astype(int)

# ── Título ───────────────────────────────────────────────────────────────────
st.title("⚡ Monitor de Precios Eléctricos — Mercado Ibérico")
st.caption(f"Fuente: OMIE  |  Período: {df['dia'].min()} → {df['dia'].max()}  |  {len(df)} registros")

# ── KPIs ─────────────────────────────────────────────────────────────────────
precio_medio     = df[price_col].mean()
precio_max       = df[price_col].max()
precio_min       = df[price_col].min()
horas_negativas  = (df[price_col] < 0).sum()
horas_pico       = (df[price_col] > umbral_alto).sum()

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Precio medio",        f"{precio_medio:.1f} €/MWh")
col2.metric("Precio máximo",       f"{precio_max:.1f} €/MWh")
col3.metric("Precio mínimo",       f"{precio_min:.1f} €/MWh")
col4.metric("Horas precio < 0",    f"{horas_negativas}h")
col5.metric("Horas pico > umbral", f"{horas_pico}h")

st.markdown("---")

# ── Gráfico precios hora a hora ───────────────────────────────────────────────
st.subheader("📈 Precio hora a hora")
fig_line = go.Figure()
fig_line.add_hrect(y0=df[price_col].min() - 5, y1=umbral_bajo,
                   fillcolor="rgba(0,200,100,0.07)", line_width=0,
                   annotation_text="Zona valle", annotation_position="top left")
fig_line.add_hrect(y0=umbral_alto, y1=df[price_col].max() + 5,
                   fillcolor="rgba(255,50,50,0.07)", line_width=0,
                   annotation_text="Zona pico", annotation_position="top left")
fig_line.add_trace(go.Scatter(
    x=df["fecha"], y=df[price_col],
    mode="lines", name="Precio",
    line=dict(color="#4fc3f7", width=1.5),
    hovertemplate="<b>%{x|%d %b %H:%M}</b><br>%{y:.1f} EUR/MWh<extra></extra>",
))
fig_line.update_layout(
    height=380, margin=dict(l=0, r=0, t=10, b=0),
    xaxis_title=None, yaxis_title="EUR/MWh",
    hovermode="x unified", template="plotly_dark",
)
st.plotly_chart(fig_line, use_container_width=True)

# ── Heatmap ──────────────────────────────────────────────────────────────────
st.subheader("🗓️ Heatmap: precio por hora y día")
pivot = df.pivot_table(index="hora_num", columns="dia", values=price_col, aggfunc="mean")
fig_heat = px.imshow(
    pivot,
    labels=dict(x="Día", y="Hora", color="EUR/MWh"),
    color_continuous_scale="RdYlGn_r",
    aspect="auto", template="plotly_dark",
)
fig_heat.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0))
fig_heat.update_xaxes(tickformat="%d %b")
st.plotly_chart(fig_heat, use_container_width=True)

# ── Perfil horario + análisis EV ─────────────────────────────────────────────
col_a, col_b = st.columns(2)

with col_a:
    st.subheader("🕐 Perfil horario medio")
    hourly = df.groupby("hora_num")[price_col].mean().reset_index()
    hourly.columns = ["Hora", "Precio medio (EUR/MWh)"]
    colors = ["#ef5350" if p > umbral_alto else "#66bb6a" if p < umbral_bajo else "#4fc3f7"
              for p in hourly["Precio medio (EUR/MWh)"]]
    fig_bar = go.Figure(go.Bar(
        x=hourly["Hora"], y=hourly["Precio medio (EUR/MWh)"],
        marker_color=colors,
        hovertemplate="Hora %{x}h: %{y:.1f} EUR/MWh<extra></extra>",
    ))
    fig_bar.update_layout(height=320, template="plotly_dark",
                          margin=dict(l=0, r=0, t=10, b=0),
                          xaxis_title="Hora del día", yaxis_title="EUR/MWh")
    st.plotly_chart(fig_bar, use_container_width=True)

with col_b:
    st.subheader("🔋 Optimización carga EV (50 kWh/sesión)")
    hourly["Coste sesión (EUR)"] = hourly["Precio medio (EUR/MWh)"] / 1000 * 50
    hourly_sorted = hourly.sort_values("Precio medio (EUR/MWh)")
    mejores = hourly_sorted.head(6)
    peores  = hourly_sorted.tail(6)
    ahorro      = mejores["Coste sesión (EUR)"].mean()
    coste_punta = peores["Coste sesión (EUR)"].mean()

    m1, m2, m3 = st.columns(3)
    m1.metric("Coste en valle",    f"{ahorro:.2f} €")
    m2.metric("Coste en punta",    f"{coste_punta:.2f} €")
    m3.metric("Ahorro potencial",  f"{((coste_punta - ahorro) / coste_punta * 100):.0f}%")

    st.markdown("**Mejores horas para cargar:**")
    st.success("⚡ " + ", ".join([f"{int(h)}h" for h in mejores["Hora"].tolist()]))
    st.markdown("**Horas a evitar:**")
    st.error("⛔ " + ", ".join([f"{int(h)}h" for h in peores["Hora"].tolist()]))
    st.dataframe(
        hourly[["Hora", "Precio medio (EUR/MWh)", "Coste sesión (EUR)"]].sort_values("Hora"),
        use_container_width=True, hide_index=True, height=180,
    )

# ── Alertas ──────────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("🚨 Alertas del período")
alerts_path = Path(__file__).parent.parent / "data" / "processed" / "alerts_log.json"
if alerts_path.exists():
    with open(alerts_path) as f:
        alerts = json.load(f)
    if alerts:
        df_alerts = pd.DataFrame(alerts)
        df_alerts["timestamp"] = pd.to_datetime(df_alerts["timestamp"]).dt.strftime("%d/%m %H:%M")
        altas = df_alerts[df_alerts["nivel"] == "high"]
        opps  = df_alerts[df_alerts["nivel"] == "opportunity"]
        tab1, tab2 = st.tabs([f"Criticas ({len(altas)})", f"Oportunidades ({len(opps)})"])
        with tab1:
            st.dataframe(altas[["timestamp", "tipo", "mensaje"]].rename(
                columns={"timestamp": "Hora", "tipo": "Tipo", "mensaje": "Detalle"}),
                use_container_width=True, hide_index=True)
        with tab2:
            st.dataframe(opps[["timestamp", "tipo", "mensaje"]].rename(
                columns={"timestamp": "Hora", "tipo": "Tipo", "mensaje": "Detalle"}),
                use_container_width=True, hide_index=True)
    else:
        st.info("Sin alertas en el período.")
else:
    st.info("Ejecuta primero `python main.py --mode omie` para generar alertas.")

st.markdown("---")
st.caption("Datos: OMIE (mercado ibérico) · Actualización: cada hora · Desarrollado con Streamlit + Plotly")
