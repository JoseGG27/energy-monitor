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
from collectors.entsoe_collector import get_iberian_comparison

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

# ── Carga ESIOS (CSVs locales subidos por refresh_data.py) ───────────────────
@st.cache_data(ttl=3600)
def load_esios(days: int):
    raw_dir = Path(__file__).parent.parent / "data" / "raw"
    today   = date.today()
    start   = today - timedelta(days=days)

    def _load_indicator(prefix: str) -> pd.DataFrame:
        files = sorted(raw_dir.glob(f"{prefix}_*.csv"))
        if not files:
            return pd.DataFrame()
        df = pd.read_csv(files[-1])   # el más reciente
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_convert("Europe/Madrid").dt.tz_localize(None)
        df = df[df["datetime"] >= pd.Timestamp(start)]
        # Agregar múltiples registros por hora -> media horaria
        df["hora"] = df["datetime"].dt.floor("h")
        df = df.groupby("hora")["precio_eur_mwh"].mean().reset_index()
        df.columns = ["datetime", "precio_eur_mwh"]
        return df.sort_values("datetime")

    spot = _load_indicator("esios_600")
    pvpc = _load_indicator("esios_1001")
    return spot, pvpc

df_esios_spot, df_esios_pvpc = load_esios(days)
tiene_esios = not df_esios_spot.empty or not df_esios_pvpc.empty

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
    mode="lines", name="Spot OMIE",
    line=dict(color="#4fc3f7", width=1.5),
    hovertemplate="<b>%{x|%d %b %H:%M}</b><br>OMIE: %{y:.1f} €/MWh<extra></extra>",
))
if not df_esios_spot.empty:
    fig_line.add_trace(go.Scatter(
        x=df_esios_spot["datetime"], y=df_esios_spot["precio_eur_mwh"],
        mode="lines", name="Spot ESIOS (REE)",
        line=dict(color="#ce93d8", width=1.5, dash="dash"),
        hovertemplate="<b>%{x|%d %b %H:%M}</b><br>ESIOS: %{y:.1f} €/MWh<extra></extra>",
    ))
if not df_esios_pvpc.empty:
    fig_line.add_trace(go.Scatter(
        x=df_esios_pvpc["datetime"], y=df_esios_pvpc["precio_eur_mwh"],
        mode="lines", name="PVPC (tarifa regulada)",
        line=dict(color="#a5d6a7", width=1.5, dash="dot"),
        hovertemplate="<b>%{x|%d %b %H:%M}</b><br>PVPC: %{y:.1f} €/MWh<extra></extra>",
    ))
fig_line.add_trace(go.Scatter(
    x=df["fecha"], y=df["coste_total_eur_mwh"],
    mode="lines", name="Coste total (spot+peajes+IVA)",
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


# ── Sección ESIOS: Spot REE + PVPC ───────────────────────────────────────────
st.markdown("---")
st.subheader("🔌 ESIOS (REE) — Precio Spot y PVPC")

if not tiene_esios:
    st.info("Sin datos ESIOS. Ejecuta `python refresh_data.py` para descargarlos.")
else:
    # KPIs ESIOS
    kpi_cols = st.columns(4)
    if not df_esios_spot.empty:
        kpi_cols[0].metric("Spot ESIOS medio", f"{df_esios_spot['precio_eur_mwh'].mean():.1f} €/MWh")
        kpi_cols[1].metric("Spot ESIOS máx.",  f"{df_esios_spot['precio_eur_mwh'].max():.1f} €/MWh")
    if not df_esios_pvpc.empty:
        kpi_cols[2].metric("PVPC medio",       f"{df_esios_pvpc['precio_eur_mwh'].mean():.1f} €/MWh")
        kpi_cols[3].metric("PVPC máx.",        f"{df_esios_pvpc['precio_eur_mwh'].max():.1f} €/MWh")

    # Gráfico PVPC vs Spot OMIE vs Spot ESIOS
    fig_esios = go.Figure()
    fig_esios.add_trace(go.Scatter(
        x=df["fecha"], y=df[price_col],
        mode="lines", name="Spot OMIE",
        line=dict(color="#4fc3f7", width=1.5),
        hovertemplate="OMIE %{x|%d %b %H:%M}: %{y:.1f} €/MWh<extra></extra>",
    ))
    if not df_esios_spot.empty:
        fig_esios.add_trace(go.Scatter(
            x=df_esios_spot["datetime"], y=df_esios_spot["precio_eur_mwh"],
            mode="lines", name="Spot ESIOS (REE)",
            line=dict(color="#ce93d8", width=1.5, dash="dash"),
            hovertemplate="ESIOS %{x|%d %b %H:%M}: %{y:.1f} €/MWh<extra></extra>",
        ))
    if not df_esios_pvpc.empty:
        fig_esios.add_trace(go.Scatter(
            x=df_esios_pvpc["datetime"], y=df_esios_pvpc["precio_eur_mwh"],
            mode="lines", name="PVPC (tarifa regulada)",
            line=dict(color="#a5d6a7", width=2),
            hovertemplate="PVPC %{x|%d %b %H:%M}: %{y:.1f} €/MWh<extra></extra>",
        ))
    fig_esios.update_layout(
        height=360, margin=dict(l=0, r=0, t=10, b=0),
        xaxis_title=None, yaxis_title="EUR/MWh",
        hovermode="x unified", template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig_esios, use_container_width=True)

    # Tabla comparativa horaria PVPC vs Spot OMIE
    if not df_esios_pvpc.empty:
        st.markdown("**Comparativa horaria: PVPC vs Spot OMIE**")
        df_esios_pvpc_h = df_esios_pvpc.copy()
        df_esios_pvpc_h["hora"] = df_esios_pvpc_h["datetime"].dt.hour
        pvpc_horario = df_esios_pvpc_h.groupby("hora")["precio_eur_mwh"].mean().reset_index()
        pvpc_horario.columns = ["Hora", "PVPC medio (€/MWh)"]

        omie_horario = df.groupby("hora_num")[price_col].mean().reset_index()
        omie_horario.columns = ["Hora", "Spot OMIE (€/MWh)"]

        tabla_comp = pvpc_horario.merge(omie_horario, on="Hora")
        tabla_comp["Diferencia PVPC-OMIE"] = (tabla_comp["PVPC medio (€/MWh)"] - tabla_comp["Spot OMIE (€/MWh)"]).round(2)
        tabla_comp["PVPC medio (€/MWh)"]  = tabla_comp["PVPC medio (€/MWh)"].round(2)
        tabla_comp["Spot OMIE (€/MWh)"]   = tabla_comp["Spot OMIE (€/MWh)"].round(2)

        col_t1, col_t2 = st.columns([2, 1])
        with col_t1:
            st.dataframe(tabla_comp, use_container_width=True, hide_index=True, height=280)
        with col_t2:
            diff_media = tabla_comp["Diferencia PVPC-OMIE"].mean()
            st.metric("Diferencia media PVPC vs Spot",
                      f"{diff_media:+.1f} €/MWh",
                      help="Positivo = PVPC más caro que el spot de mercado")
            pvpc_kwh = df_esios_pvpc["precio_eur_mwh"].mean() / 1000
            st.metric("PVPC medio en €/kWh", f"{pvpc_kwh:.4f} €/kWh")
            coste_pvpc_sesion = pvpc_kwh * kwh_sesion
            st.metric(f"Coste sesión EV ({kwh_sesion:.0f} kWh) a PVPC",
                      f"{coste_pvpc_sesion:.2f} €")

# ── Comparativa ENTSO-E: ES / FR / DE ────────────────────────────────────────
st.markdown("---")
st.subheader("🌍 Comparativa de precios europeos — ENTSO-E (ES / FR / DE)")

from config.settings import ENTSOE_TOKEN

if not ENTSOE_TOKEN:
    st.info("🔑 Token ENTSO-E no configurado. Añádelo en los **Secrets** de Streamlit Cloud para activar esta sección.")
else:
    @st.cache_data(ttl=3600)
    def load_entsoe(days: int) -> pd.DataFrame:
        today = date.today()
        start = today - timedelta(days=days)
        end   = today - timedelta(days=1)
        try:
            return get_iberian_comparison(start, end)
        except Exception as e:
            return pd.DataFrame()

    with st.spinner("Cargando datos ENTSO-E (ES/FR/DE)..."):
        df_entsoe = load_entsoe(days)

    if df_entsoe.empty:
        st.warning("No se pudieron obtener datos de ENTSO-E para este período.")
    else:
        df_entsoe["datetime"] = pd.to_datetime(df_entsoe["datetime"])
        df_entsoe["hora_num"] = df_entsoe["datetime"].dt.hour

        COLORES = {"ES": "#4fc3f7", "FR": "#81c784", "DE": "#ffb74d"}

        # ── KPIs por país ─────────────────────────────────────────────────────
        stats = df_entsoe.groupby("country")["precio_eur_mwh"].agg(["mean", "min", "max"]).round(1)
        cols = st.columns(len(stats))
        for i, (pais, row) in enumerate(stats.iterrows()):
            flag = {"ES": "🇪🇸", "FR": "🇫🇷", "DE": "🇩🇪"}.get(pais, "")
            cols[i].metric(f"{flag} {pais} — Precio medio", f"{row['mean']:.1f} €/MWh",
                           f"Min {row['min']:.1f} · Max {row['max']:.1f}")

        # ── Gráfico líneas comparativo ─────────────────────────────────────────
        fig_eu = go.Figure()
        for pais, grp in df_entsoe.groupby("country"):
            grp_sorted = grp.sort_values("datetime")
            fig_eu.add_trace(go.Scatter(
                x=grp_sorted["datetime"],
                y=grp_sorted["precio_eur_mwh"],
                mode="lines", name=pais,
                line=dict(color=COLORES.get(pais, "#fff"), width=1.5),
                hovertemplate=f"<b>{pais}</b> %{{x|%d %b %H:%M}}<br>%{{y:.1f}} €/MWh<extra></extra>",
            ))
        fig_eu.update_layout(
            height=360, margin=dict(l=0, r=0, t=10, b=0),
            xaxis_title=None, yaxis_title="EUR/MWh",
            hovermode="x unified", template="plotly_dark",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_eu, use_container_width=True)

        # ── Perfil horario medio por país ──────────────────────────────────────
        col_eu1, col_eu2 = st.columns(2)

        with col_eu1:
            st.markdown("**Perfil horario medio por país**")
            hourly_eu = df_entsoe.groupby(["country", "hora_num"])["precio_eur_mwh"].mean().reset_index()
            fig_heu = go.Figure()
            for pais, grp in hourly_eu.groupby("country"):
                fig_heu.add_trace(go.Scatter(
                    x=grp["hora_num"], y=grp["precio_eur_mwh"],
                    mode="lines+markers", name=pais,
                    line=dict(color=COLORES.get(pais, "#fff"), width=2),
                    hovertemplate=f"{pais} hora %{{x}}h: %{{y:.1f}} €/MWh<extra></extra>",
                ))
            fig_heu.update_layout(
                height=300, template="plotly_dark",
                margin=dict(l=0, r=0, t=10, b=0),
                xaxis_title="Hora del día", yaxis_title="EUR/MWh",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig_heu, use_container_width=True)

        with col_eu2:
            st.markdown("**Tabla resumen por país**")
            resumen = df_entsoe.groupby("country")["precio_eur_mwh"].agg(
                Media="mean", Mínimo="min", Máximo="max",
                Volatilidad="std",
                Horas_negativas=lambda x: (x < 0).sum(),
            ).round(1).reset_index()
            resumen.columns = ["País", "Media (€/MWh)", "Mín.", "Máx.", "Volatilidad", "Horas < 0€"]
            resumen["País"] = resumen["País"].map({"ES": "🇪🇸 España", "FR": "🇫🇷 Francia", "DE": "🇩🇪 Alemania"})
            st.dataframe(resumen, use_container_width=True, hide_index=True)

            # Diferencial ES vs FR y DE
            st.markdown("**Diferencial ES respecto a vecinos**")
            if "ES" in stats.index and "FR" in stats.index:
                diff_fr = stats.loc["ES", "mean"] - stats.loc["FR", "mean"]
                arrow_fr = "↑ más caro" if diff_fr > 0 else "↓ más barato"
                st.markdown(f"- ES vs FR: `{diff_fr:+.1f} €/MWh` ({arrow_fr})")
            if "ES" in stats.index and "DE" in stats.index:
                diff_de = stats.loc["ES", "mean"] - stats.loc["DE", "mean"]
                arrow_de = "↑ más caro" if diff_de > 0 else "↓ más barato"
                st.markdown(f"- ES vs DE: `{diff_de:+.1f} €/MWh` ({arrow_de})")

st.markdown("---")
st.caption("Datos: OMIE (mercado ibérico) · ENTSO-E (precios europeos) · "
           "Peajes y cargos: CNMC 2026 (ajustables en sidebar) · Desarrollado con Streamlit + Plotly")
