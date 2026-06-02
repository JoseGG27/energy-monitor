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

st.sidebar.markdown("---")
st.sidebar.markdown("**Costes del sistema (€/MWh)**")
st.sidebar.caption("Cargos regulados que se suman al precio spot")
peaje_acceso   = st.sidebar.number_input("Peaje de acceso",     value=25.0, step=1.0,
                                          help="Peajes de transporte y distribución (CNMC 2026)")
cargos_sistema = st.sidebar.number_input("Cargos del sistema",  value=18.0, step=1.0,
                                          help="Cargos regulados: renovables, extrapeninsular, etc.")
st.sidebar.markdown("**Impuestos**")
imp_electrico  = st.sidebar.number_input("Impuesto eléctrico (%)", value=5.11, step=0.1,
                                          help="Impuesto sobre la electricidad (Ley 38/1992)")
iva            = st.sidebar.number_input("IVA (%)", value=21.0, step=1.0,
                                          help="IVA aplicable a la factura eléctrica")

st.sidebar.markdown("---")
st.sidebar.markdown("**Sesión de carga EV**")
kwh_sesion = st.sidebar.number_input("kWh por sesión", value=50.0, step=5.0,
                                      help="Energía media por sesión de carga")

# ── Función de coste total ────────────────────────────────────────────────────
def coste_total_eur_mwh(spot: float) -> float:
    """Calcula el coste total €/MWh: spot + peajes + cargos + impuestos."""
    base   = max(spot, 0) + peaje_acceso + cargos_sistema   # precio negativo no reduce peajes
    con_ie = base * (1 + imp_electrico / 100)
    con_iva = con_ie * (1 + iva / 100)
    return con_iva

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

# Calcular columna de coste total para cada registro
df["coste_total_eur_mwh"] = df[price_col].apply(coste_total_eur_mwh)
df["coste_total_eur_kwh"] = df["coste_total_eur_mwh"] / 1000

# ── Título ───────────────────────────────────────────────────────────────────
st.title("⚡ Monitor de Precios Eléctricos — Mercado Ibérico")
st.caption(f"Fuente: OMIE  |  Período: {df['dia'].min()} → {df['dia'].max()}  |  {len(df)} registros")

# ── KPIs ─────────────────────────────────────────────────────────────────────
precio_medio      = df[price_col].mean()
precio_max        = df[price_col].max()
precio_min        = df[price_col].min()
coste_medio_total = df["coste_total_eur_mwh"].mean()
horas_negativas   = (df[price_col] < 0).sum()
horas_pico        = (df[price_col] > umbral_alto).sum()

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Precio spot medio",    f"{precio_medio:.1f} €/MWh")
col2.metric("Coste total medio",    f"{coste_medio_total:.1f} €/MWh",
            help="Spot + peajes + cargos + impuestos")
col3.metric("Precio spot máx.",     f"{precio_max:.1f} €/MWh")
col4.metric("Precio spot mín.",     f"{precio_min:.1f} €/MWh")
col5.metric("Horas precio < 0",     f"{horas_negativas}h")
col6.metric("Horas pico > umbral",  f"{horas_pico}h")

st.markdown("---")

# ── Gráfico precios hora a hora: spot vs coste total ─────────────────────────
st.subheader("📈 Precio spot vs Coste total (con peajes e impuestos)")
fig_line = go.Figure()

fig_line.add_hrect(y0=df[price_col].min() - 5, y1=umbral_bajo,
                   fillcolor="rgba(0,200,100,0.07)", line_width=0,
                   annotation_text="Zona valle", annotation_position="top left")
fig_line.add_hrect(y0=umbral_alto, y1=df["coste_total_eur_mwh"].max() + 5,
                   fillcolor="rgba(255,50,50,0.07)", line_width=0,
                   annotation_text="Zona pico", annotation_position="top left")

fig_line.add_trace(go.Scatter(
    x=df["fecha"], y=df[price_col],
    mode="lines", name="Precio spot (OMIE)",
    line=dict(color="#4fc3f7", width=1.5),
    hovertemplate="<b>%{x|%d %b %H:%M}</b><br>Spot: %{y:.1f} €/MWh<extra></extra>",
))
fig_line.add_trace(go.Scatter(
    x=df["fecha"], y=df["coste_total_eur_mwh"],
    mode="lines", name="Coste total (con peajes+IVA)",
    line=dict(color="#ffb74d", width=1.5, dash="dot"),
    hovertemplate="<b>%{x|%d %b %H:%M}</b><br>Total: %{y:.1f} €/MWh<extra></extra>",
))
fig_line.update_layout(
    height=380, margin=dict(l=0, r=0, t=10, b=0),
    xaxis_title=None, yaxis_title="EUR/MWh",
    hovermode="x unified", template="plotly_dark",
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
)
st.plotly_chart(fig_line, use_container_width=True)

# ── Desglose de costes ───────────────────────────────────────────────────────
with st.expander("📊 Ver desglose de costes del sistema", expanded=False):
    spot_rep   = precio_medio
    base_rep   = spot_rep + peaje_acceso + cargos_sistema
    con_ie_rep = base_rep * (1 + imp_electrico / 100)
    total_rep  = con_ie_rep * (1 + iva / 100)

    dc1, dc2, dc3, dc4, dc5 = st.columns(5)
    dc1.metric("Precio spot",        f"{spot_rep:.1f} €/MWh",   f"{spot_rep/total_rep*100:.0f}% del total")
    dc2.metric("Peaje de acceso",    f"{peaje_acceso:.1f} €/MWh", f"{peaje_acceso/total_rep*100:.0f}%")
    dc3.metric("Cargos del sistema", f"{cargos_sistema:.1f} €/MWh", f"{cargos_sistema/total_rep*100:.0f}%")
    dc4.metric("Imp. eléctrico",     f"{base_rep*(imp_electrico/100):.1f} €/MWh", f"{imp_electrico:.2f}%")
    dc5.metric("IVA",                f"{con_ie_rep*(iva/100):.1f} €/MWh",  f"{iva:.0f}%")

    st.markdown(f"**Coste total medio del período: `{total_rep:.1f} €/MWh` · `{total_rep/1000:.4f} €/kWh`**")
    st.caption("Nota: el impuesto eléctrico y el IVA se aplican sobre spot + peajes + cargos. "
               "Los precios negativos no reducen peajes ni cargos regulados.")

# ── Heatmap ──────────────────────────────────────────────────────────────────
tab_heat1, tab_heat2 = st.tabs(["🗓️ Heatmap precio spot", "🗓️ Heatmap coste total"])
with tab_heat1:
    pivot = df.pivot_table(index="hora_num", columns="dia", values=price_col, aggfunc="mean")
    fig_h = px.imshow(pivot, labels=dict(x="Día", y="Hora", color="€/MWh"),
                      color_continuous_scale="RdYlGn_r", aspect="auto", template="plotly_dark")
    fig_h.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
    fig_h.update_xaxes(tickformat="%d %b")
    st.plotly_chart(fig_h, use_container_width=True)
with tab_heat2:
    pivot2 = df.pivot_table(index="hora_num", columns="dia", values="coste_total_eur_mwh", aggfunc="mean")
    fig_h2 = px.imshow(pivot2, labels=dict(x="Día", y="Hora", color="€/MWh"),
                       color_continuous_scale="RdYlGn_r", aspect="auto", template="plotly_dark")
    fig_h2.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
    fig_h2.update_xaxes(tickformat="%d %b")
    st.plotly_chart(fig_h2, use_container_width=True)

# ── Perfil horario + análisis EV ─────────────────────────────────────────────
st.markdown("---")
col_a, col_b = st.columns(2)

with col_a:
    st.subheader("🕐 Perfil horario medio")
    hourly = df.groupby("hora_num").agg(
        spot     = (price_col, "mean"),
        total    = ("coste_total_eur_mwh", "mean"),
    ).reset_index().rename(columns={"hora_num": "Hora"})

    fig_bar = go.Figure()
    colors_spot = ["#ef5350" if p > umbral_alto else "#66bb6a" if p < umbral_bajo else "#4fc3f7"
                   for p in hourly["spot"]]
    fig_bar.add_trace(go.Bar(
        x=hourly["Hora"], y=hourly["spot"],
        name="Precio spot", marker_color=colors_spot,
        hovertemplate="Hora %{x}h — Spot: %{y:.1f} €/MWh<extra></extra>",
    ))
    fig_bar.add_trace(go.Scatter(
        x=hourly["Hora"], y=hourly["total"],
        name="Coste total", mode="lines+markers",
        line=dict(color="#ffb74d", width=2),
        hovertemplate="Hora %{x}h — Total: %{y:.1f} €/MWh<extra></extra>",
    ))
    fig_bar.update_layout(
        height=340, template="plotly_dark",
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis_title="Hora del día", yaxis_title="EUR/MWh",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        barmode="overlay",
    )
    st.plotly_chart(fig_bar, use_container_width=True)

with col_b:
    st.subheader(f"🔋 Optimización carga EV ({kwh_sesion:.0f} kWh/sesión)")

    hourly["coste_sesion_spot_eur"]  = hourly["spot"].apply(lambda x: max(x, 0)) / 1000 * kwh_sesion
    hourly["coste_sesion_total_eur"] = hourly["total"] / 1000 * kwh_sesion

    hourly_sorted = hourly.sort_values("total")
    mejores = hourly_sorted.head(6)
    peores  = hourly_sorted.tail(6)

    coste_valle_total = mejores["coste_sesion_total_eur"].mean()
    coste_punta_total = peores["coste_sesion_total_eur"].mean()
    ahorro_pct = (coste_punta_total - coste_valle_total) / coste_punta_total * 100 if coste_punta_total > 0 else 0

    m1, m2, m3 = st.columns(3)
    m1.metric("Coste sesión valle",  f"{coste_valle_total:.2f} €", help="Coste total en horas baratas")
    m2.metric("Coste sesión punta",  f"{coste_punta_total:.2f} €", help="Coste total en horas caras")
    m3.metric("Ahorro potencial",    f"{ahorro_pct:.0f}%")

    st.markdown("**Mejores horas para cargar:**")
    st.success("⚡ " + ", ".join([f"{int(h)}h" for h in mejores["Hora"].tolist()]))
    st.markdown("**Horas a evitar:**")
    st.error("⛔ " + ", ".join([f"{int(h)}h" for h in peores["Hora"].tolist()]))

    tabla = hourly[["Hora", "spot", "total", "coste_sesion_total_eur"]].sort_values("Hora").copy()
    tabla.columns = ["Hora", "Spot (€/MWh)", "Coste total (€/MWh)", f"Sesión {kwh_sesion:.0f}kWh (€)"]
    tabla = tabla.round(2)
    st.dataframe(tabla, use_container_width=True, hide_index=True, height=210)

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
        tab1, tab2 = st.tabs([f"Críticas ({len(altas)})", f"Oportunidades ({len(opps)})"])
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
st.caption("Datos: OMIE (mercado ibérico) · Peajes y cargos: CNMC 2026 (ajustables en sidebar) · "
           "Desarrollado con Streamlit + Plotly")
