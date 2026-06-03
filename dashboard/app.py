"""
Dashboard de precios electricos — energy-monitor
https://ev-energy-monitor.streamlit.app
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
from config.settings import ENTSOE_TOKEN

st.set_page_config(
    page_title="Monitor Precios Electricos",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ════════════════════════════════════════════════════════
#  SIDEBAR
# ════════════════════════════════════════════════════════
st.sidebar.title("⚡ Energy Monitor")

st.sidebar.markdown("### Periodo")
days = st.sidebar.slider("Dias a mostrar", 1, 30, 7)

st.sidebar.markdown("### Paises")
paises_opciones = {"España 🇪🇸": "ES", "Portugal 🇵🇹": "PT"}
if ENTSOE_TOKEN:
    paises_opciones.update({"Francia 🇫🇷": "FR", "Alemania 🇩🇪": "DE"})
paises_sel = st.sidebar.multiselect(
    "Selecciona paises",
    list(paises_opciones.keys()),
    default=["España 🇪🇸"],
)
if not paises_sel:
    st.sidebar.warning("Selecciona al menos un pais.")
    st.stop()

paises_cod = [paises_opciones[p] for p in paises_sel]
price_col  = "precio_es" if "ES" in paises_cod else "precio_pt"

st.sidebar.markdown("### Costes regulados (EUR/MWh)")
peaje_acceso   = st.sidebar.number_input("Peaje de acceso",    value=25.0, step=1.0)
cargos_sistema = st.sidebar.number_input("Cargos del sistema", value=18.0, step=1.0)
imp_electrico  = st.sidebar.number_input("Impuesto electrico (%)", value=5.11, step=0.1)
iva            = st.sidebar.number_input("IVA (%)", value=21.0, step=1.0)

st.sidebar.markdown("### Sesion de carga EV")
kwh_sesion = st.sidebar.number_input("kWh por sesion", value=50.0, step=5.0)

COLORES = {"ES": "#4fc3f7", "PT": "#81d4fa", "FR": "#81c784", "DE": "#ffb74d"}
FLAGS   = {"ES": "🇪🇸", "PT": "🇵🇹", "FR": "🇫🇷", "DE": "🇩🇪"}

def coste_total(spot: float) -> float:
    base = max(spot, 0) + peaje_acceso + cargos_sistema
    return base * (1 + imp_electrico / 100) * (1 + iva / 100)

# ════════════════════════════════════════════════════════
#  CARGA DE DATOS
# ════════════════════════════════════════════════════════
today = date.today()
start = today - timedelta(days=days)
end   = today - timedelta(days=1)

@st.cache_data(ttl=3600)
def load_omie(days):
    today = date.today()
    start = today - timedelta(days=days)
    end   = today - timedelta(days=1)
    raw_dir = Path(__file__).parent.parent / "data" / "raw"
    frames = [pd.read_csv(f, parse_dates=["fecha"])
              for d in pd.date_range(start, end)
              if (f := raw_dir / f"omie_{d.strftime('%Y%m%d')}.csv").exists()]
    return (pd.concat(frames, ignore_index=True).sort_values("fecha")
            if frames else download_omie_range(start, end))

@st.cache_data(ttl=3600)
def load_esios_csvs(days):
    raw_dir = Path(__file__).parent.parent / "data" / "raw"
    today   = date.today()
    cutoff  = pd.Timestamp(today - timedelta(days=days))
    def _read(prefix):
        files = sorted(raw_dir.glob(f"{prefix}_*.csv"))
        if not files:
            return pd.DataFrame()
        df = pd.read_csv(files[-1])
        df["datetime"] = (pd.to_datetime(df["datetime"], utc=True)
                          .dt.tz_convert("Europe/Madrid").dt.tz_localize(None))
        df = df[df["datetime"] >= cutoff]
        df["hora"] = df["datetime"].dt.floor("h")
        return (df.groupby("hora")["precio_eur_mwh"].mean()
                  .reset_index().rename(columns={"hora": "datetime"})
                  .sort_values("datetime"))
    return _read("esios_600"), _read("esios_1001")

@st.cache_data(ttl=3600)
def load_entsoe(days):
    if not ENTSOE_TOKEN:
        return pd.DataFrame()
    today = date.today()
    try:
        return get_iberian_comparison(today - timedelta(days=days), today - timedelta(days=1))
    except Exception:
        return pd.DataFrame()

with st.spinner("Cargando datos..."):
    df_omie      = load_omie(days)
    df_esios_spot, df_esios_pvpc = load_esios_csvs(days)
    df_entsoe    = load_entsoe(days)

if df_omie.empty:
    st.error("Sin datos OMIE disponibles.")
    st.stop()

df_omie["fecha"]    = pd.to_datetime(df_omie["fecha"])
df_omie["dia"]      = df_omie["fecha"].dt.date
df_omie["hora_num"] = df_omie["hora"].astype(int)
df_omie["coste_total"] = df_omie[price_col].apply(coste_total)

if not df_entsoe.empty:
    df_entsoe["datetime"] = pd.to_datetime(df_entsoe["datetime"])
    df_entsoe["hora_num"] = df_entsoe["datetime"].dt.hour
    df_entsoe = df_entsoe[df_entsoe["country"].isin(paises_cod)]

# ════════════════════════════════════════════════════════
#  CABECERA
# ════════════════════════════════════════════════════════
st.title("⚡ Monitor de Precios Electricos")
c1, c2, c3 = st.columns(3)
c1.caption(f"**Periodo:** {df_omie['dia'].min()} → {df_omie['dia'].max()}")
c2.caption(f"**Fuentes:** OMIE {'· ESIOS' if not df_esios_spot.empty else ''} {'· ENTSO-E' if not df_entsoe.empty else ''}")
c3.caption(f"**Paises:** {' '.join([FLAGS[c] for c in paises_cod])}")

# ════════════════════════════════════════════════════════
#  TABS PRINCIPALES
# ════════════════════════════════════════════════════════
tab_mercado, tab_europa, tab_ev, tab_alertas = st.tabs([
    "📈 Mercado Iberico",
    "🌍 Comparativa Europea",
    "🔋 Optimizacion EV",
    "🚨 Alertas",
])

# ────────────────────────────────────────────────────────
#  TAB 1 — MERCADO IBERICO
# ────────────────────────────────────────────────────────
with tab_mercado:

    # KPIs
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Spot medio",       f"{df_omie[price_col].mean():.1f} €/MWh")
    k2.metric("Spot maximo",      f"{df_omie[price_col].max():.1f} €/MWh")
    k3.metric("Spot minimo",      f"{df_omie[price_col].min():.1f} €/MWh")
    k4.metric("Coste total medio",f"{df_omie['coste_total'].mean():.1f} €/MWh",
              help="Spot + peajes + cargos + IVA")
    k5.metric("Horas precio < 0", f"{(df_omie[price_col] < 0).sum()}h")

    st.markdown("---")

    # Grafico principal: todas las series disponibles
    st.markdown("#### Evolucion de precios")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_omie["fecha"], y=df_omie[price_col],
        name="Spot OMIE", line=dict(color="#4fc3f7", width=1.5),
        hovertemplate="%{x|%d %b %H:%M} — OMIE: %{y:.1f} €/MWh<extra></extra>",
    ))
    if not df_esios_spot.empty:
        fig.add_trace(go.Scatter(
            x=df_esios_spot["datetime"], y=df_esios_spot["precio_eur_mwh"],
            name="Spot ESIOS (REE)", line=dict(color="#ce93d8", width=1.5, dash="dash"),
            hovertemplate="%{x|%d %b %H:%M} — ESIOS: %{y:.1f} €/MWh<extra></extra>",
        ))
    if not df_esios_pvpc.empty:
        fig.add_trace(go.Scatter(
            x=df_esios_pvpc["datetime"], y=df_esios_pvpc["precio_eur_mwh"],
            name="PVPC (tarifa regulada)", line=dict(color="#a5d6a7", width=2),
            hovertemplate="%{x|%d %b %H:%M} — PVPC: %{y:.1f} €/MWh<extra></extra>",
        ))
    fig.add_trace(go.Scatter(
        x=df_omie["fecha"], y=df_omie["coste_total"],
        name="Coste total (c/impuestos)", line=dict(color="#ffb74d", width=1.5, dash="dot"),
        hovertemplate="%{x|%d %b %H:%M} — Total: %{y:.1f} €/MWh<extra></extra>",
    ))
    fig.update_layout(height=380, template="plotly_dark", hovermode="x unified",
                      margin=dict(l=0, r=0, t=10, b=0), yaxis_title="EUR/MWh",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02))
    st.plotly_chart(fig, use_container_width=True)

    # Heatmap + perfil horario en columnas
    col_heat, col_bar = st.columns(2)
    with col_heat:
        st.markdown("#### Heatmap spot por hora y dia")
        pivot = df_omie.pivot_table(index="hora_num", columns="dia", values=price_col, aggfunc="mean")
        fh = px.imshow(pivot, labels=dict(x="Dia", y="Hora", color="EUR/MWh"),
                       color_continuous_scale="RdYlGn_r", aspect="auto", template="plotly_dark")
        fh.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
        fh.update_xaxes(tickformat="%d %b")
        st.plotly_chart(fh, use_container_width=True)

    with col_bar:
        st.markdown("#### Perfil horario medio")
        hourly = df_omie.groupby("hora_num")[price_col].mean().reset_index()
        colors = ["#ef5350" if p > 150 else "#66bb6a" if p < 20 else "#4fc3f7"
                  for p in hourly[price_col]]
        fb = go.Figure(go.Bar(x=hourly["hora_num"], y=hourly[price_col],
                              marker_color=colors,
                              hovertemplate="Hora %{x}h: %{y:.1f} EUR/MWh<extra></extra>"))
        fb.update_layout(height=320, template="plotly_dark",
                         margin=dict(l=0, r=0, t=10, b=0),
                         xaxis_title="Hora", yaxis_title="EUR/MWh")
        st.plotly_chart(fb, use_container_width=True)

    # Desglose de costes
    with st.expander("Ver desglose de costes del sistema"):
        s = df_omie[price_col].mean()
        base  = s + peaje_acceso + cargos_sistema
        c_ie  = base * imp_electrico / 100
        total = (base + c_ie) * (1 + iva / 100)
        d1, d2, d3, d4, d5 = st.columns(5)
        d1.metric("Precio spot",        f"{s:.1f} €/MWh",           f"{s/total*100:.0f}%")
        d2.metric("Peaje de acceso",    f"{peaje_acceso:.1f} €/MWh", f"{peaje_acceso/total*100:.0f}%")
        d3.metric("Cargos del sistema", f"{cargos_sistema:.1f} €/MWh",f"{cargos_sistema/total*100:.0f}%")
        d4.metric("Imp. electrico",     f"{c_ie:.1f} €/MWh",         f"{imp_electrico:.2f}%")
        d5.metric("IVA",                f"{(base+c_ie)*iva/100:.1f} €/MWh", f"{iva:.0f}%")
        st.info(f"**Coste total medio: {total:.1f} EUR/MWh  ·  {total/1000:.4f} EUR/kWh**")

    # PVPC vs Spot
    if not df_esios_pvpc.empty:
        st.markdown("---")
        st.markdown("#### PVPC vs Spot OMIE — comparativa horaria")
        pvpc_h = (df_esios_pvpc.copy()
                  .assign(hora=lambda x: x["datetime"].dt.hour)
                  .groupby("hora")["precio_eur_mwh"].mean().reset_index())
        omie_h = df_omie.groupby("hora_num")[price_col].mean().reset_index()
        omie_h.columns = ["hora", "spot"]
        comp = pvpc_h.merge(omie_h, on="hora").rename(columns={"precio_eur_mwh": "pvpc"})
        comp["diferencia"] = (comp["pvpc"] - comp["spot"]).round(2)

        p1, p2, p3 = st.columns(3)
        p1.metric("PVPC medio", f"{comp['pvpc'].mean():.1f} EUR/MWh")
        p2.metric("Spot OMIE medio", f"{comp['spot'].mean():.1f} EUR/MWh")
        p3.metric("Diferencia media PVPC-Spot", f"{comp['diferencia'].mean():+.1f} EUR/MWh")

        fig_pvpc = go.Figure()
        fig_pvpc.add_trace(go.Bar(x=comp["hora"], y=comp["diferencia"],
            name="PVPC - Spot",
            marker_color=["#ef5350" if d > 0 else "#66bb6a" for d in comp["diferencia"]],
            hovertemplate="Hora %{x}h: %{y:+.1f} EUR/MWh<extra></extra>"))
        fig_pvpc.update_layout(height=260, template="plotly_dark",
                               margin=dict(l=0, r=0, t=10, b=0),
                               xaxis_title="Hora", yaxis_title="PVPC - Spot (EUR/MWh)",
                               showlegend=False)
        st.plotly_chart(fig_pvpc, use_container_width=True)
        st.caption("Rojo = PVPC mas caro que el mercado spot. Verde = PVPC mas barato.")

# ────────────────────────────────────────────────────────
#  TAB 2 — COMPARATIVA EUROPEA
# ────────────────────────────────────────────────────────
with tab_europa:
    if not ENTSOE_TOKEN:
        st.info("Token ENTSO-E no configurado. Añadelo en los Secrets de Streamlit Cloud.")
    elif df_entsoe.empty:
        st.warning("No se pudieron obtener datos de ENTSO-E (servidor no disponible). Intentalo mas tarde.")
    else:
        paises_disp = df_entsoe["country"].unique().tolist()

        # KPIs por pais
        stats = df_entsoe.groupby("country")["precio_eur_mwh"].agg(["mean","min","max"]).round(1)
        cols_kpi = st.columns(len(paises_disp))
        for i, pais in enumerate(paises_disp):
            if pais in stats.index:
                r = stats.loc[pais]
                cols_kpi[i].metric(
                    f"{FLAGS.get(pais,'')} {pais} — Media",
                    f"{r['mean']:.1f} EUR/MWh",
                    f"Min {r['min']:.1f}  ·  Max {r['max']:.1f}",
                )

        st.markdown("---")

        # Grafico lineas comparativo
        st.markdown("#### Evolucion de precios por pais")
        fig_eu = go.Figure()
        for pais, grp in df_entsoe.groupby("country"):
            fig_eu.add_trace(go.Scatter(
                x=grp.sort_values("datetime")["datetime"],
                y=grp.sort_values("datetime")["precio_eur_mwh"],
                name=f"{FLAGS.get(pais,'')} {pais}",
                line=dict(color=COLORES.get(pais, "#fff"), width=1.5),
                hovertemplate=f"{pais} %{{x|%d %b %H:%M}}: %{{y:.1f}} EUR/MWh<extra></extra>",
            ))
        fig_eu.update_layout(height=360, template="plotly_dark", hovermode="x unified",
                             margin=dict(l=0, r=0, t=10, b=0), yaxis_title="EUR/MWh",
                             legend=dict(orientation="h", yanchor="bottom", y=1.02))
        st.plotly_chart(fig_eu, use_container_width=True)

        col_eu1, col_eu2 = st.columns(2)
        with col_eu1:
            st.markdown("#### Perfil horario medio por pais")
            hourly_eu = df_entsoe.groupby(["country","hora_num"])["precio_eur_mwh"].mean().reset_index()
            fig_heu = go.Figure()
            for pais, grp in hourly_eu.groupby("country"):
                fig_heu.add_trace(go.Scatter(
                    x=grp["hora_num"], y=grp["precio_eur_mwh"],
                    name=f"{FLAGS.get(pais,'')} {pais}",
                    line=dict(color=COLORES.get(pais,"#fff"), width=2),
                    mode="lines+markers",
                    hovertemplate=f"{pais} hora %{{x}}h: %{{y:.1f}} EUR/MWh<extra></extra>",
                ))
            fig_heu.update_layout(height=320, template="plotly_dark",
                                  margin=dict(l=0, r=0, t=10, b=0),
                                  xaxis_title="Hora del dia", yaxis_title="EUR/MWh",
                                  legend=dict(orientation="h", yanchor="bottom", y=1.02))
            st.plotly_chart(fig_heu, use_container_width=True)

        with col_eu2:
            st.markdown("#### Resumen y diferenciales")
            resumen = stats.reset_index()
            resumen.columns = ["Pais", "Media", "Minimo", "Maximo"]
            resumen["Pais"] = resumen["Pais"].map(
                lambda x: f"{FLAGS.get(x,'')} {x}")
            resumen["Volatilidad"] = (df_entsoe.groupby("country")["precio_eur_mwh"]
                                      .std().round(1).values)
            resumen["Horas < 0"] = (df_entsoe[df_entsoe["precio_eur_mwh"] < 0]
                                    .groupby("country").size().reindex(
                                    resumen["Pais"].str[-2:]).fillna(0).astype(int).values)
            st.dataframe(resumen, use_container_width=True, hide_index=True)

            st.markdown("**Diferencial respecto a España 🇪🇸**")
            if "ES" in stats.index:
                for pais in [p for p in paises_disp if p != "ES"]:
                    if pais in stats.index:
                        diff = stats.loc["ES","mean"] - stats.loc[pais,"mean"]
                        txt  = "mas caro" if diff > 0 else "mas barato"
                        st.markdown(f"- ES vs {FLAGS.get(pais,'')} {pais}: "
                                    f"`{diff:+.1f} EUR/MWh` ({txt})")

        # Heatmap por pais
        st.markdown("#### Heatmap de precios por pais")
        for pais in paises_disp:
            grp = df_entsoe[df_entsoe["country"] == pais].copy()
            grp["dia"] = grp["datetime"].dt.date
            pivot_eu = grp.pivot_table(index="hora_num", columns="dia",
                                       values="precio_eur_mwh", aggfunc="mean")
            fig_hmap = px.imshow(pivot_eu,
                labels=dict(x="Dia", y="Hora", color="EUR/MWh"),
                color_continuous_scale="RdYlGn_r", aspect="auto", template="plotly_dark",
                title=f"{FLAGS.get(pais,'')} {pais}")
            fig_hmap.update_layout(height=280, margin=dict(l=0, r=0, t=30, b=0))
            fig_hmap.update_xaxes(tickformat="%d %b")
            st.plotly_chart(fig_hmap, use_container_width=True)

# ────────────────────────────────────────────────────────
#  TAB 3 — OPTIMIZACION EV
# ────────────────────────────────────────────────────────
with tab_ev:
    st.markdown(f"### Analisis de coste de carga EV — {kwh_sesion:.0f} kWh por sesion")

    hourly = df_omie.groupby("hora_num").agg(
        spot    =(price_col, "mean"),
        total   =("coste_total", "mean"),
    ).reset_index().rename(columns={"hora_num": "Hora"})
    hourly["coste_spot_eur"]  = hourly["spot"].apply(lambda x: max(x,0)) / 1000 * kwh_sesion
    hourly["coste_total_eur"] = hourly["total"] / 1000 * kwh_sesion

    hourly_sorted = hourly.sort_values("total")
    mejores = hourly_sorted.head(6)
    peores  = hourly_sorted.tail(6)
    ahorro  = peores["coste_total_eur"].mean() - mejores["coste_total_eur"].mean()
    pct     = ahorro / peores["coste_total_eur"].mean() * 100 if peores["coste_total_eur"].mean() > 0 else 0

    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Coste sesion en horas valle", f"{mejores['coste_total_eur'].mean():.2f} EUR")
    e2.metric("Coste sesion en horas punta", f"{peores['coste_total_eur'].mean():.2f} EUR")
    e3.metric("Ahorro por sesion",           f"{ahorro:.2f} EUR")
    e4.metric("Ahorro potencial",            f"{pct:.0f}%")

    st.markdown("---")
    col_ev1, col_ev2 = st.columns(2)

    with col_ev1:
        st.markdown("#### Coste de sesion EV por hora")
        colors_ev = ["#66bb6a" if h in mejores["Hora"].values else
                     "#ef5350" if h in peores["Hora"].values else "#90a4ae"
                     for h in hourly["Hora"]]
        fig_ev = go.Figure(go.Bar(
            x=hourly["Hora"], y=hourly["coste_total_eur"],
            marker_color=colors_ev,
            hovertemplate="Hora %{x}h: %{y:.2f} EUR/sesion<extra></extra>",
        ))
        fig_ev.update_layout(height=340, template="plotly_dark",
                             margin=dict(l=0, r=0, t=10, b=0),
                             xaxis_title="Hora", yaxis_title=f"EUR / {kwh_sesion:.0f} kWh")
        st.plotly_chart(fig_ev, use_container_width=True)
        st.success("Verde = mejores horas para cargar")
        st.error("Rojo = horas a evitar")

    with col_ev2:
        st.markdown("#### Tabla completa por hora")
        tabla = hourly[["Hora","spot","total","coste_spot_eur","coste_total_eur"]].copy()
        tabla.columns = ["Hora","Spot (EUR/MWh)","Total c/reg (EUR/MWh)",
                         f"Sesion solo spot (EUR)","Sesion con reg. (EUR)"]
        tabla = tabla.round(2).sort_values("Hora")
        st.dataframe(tabla, use_container_width=True, hide_index=True, height=380)

    # PVPC como alternativa
    if not df_esios_pvpc.empty:
        st.markdown("---")
        st.markdown("#### Alternativa: tarifa PVPC")
        pvpc_medio = df_esios_pvpc["precio_eur_mwh"].mean()
        coste_pvpc = pvpc_medio / 1000 * kwh_sesion
        coste_valle = mejores["coste_total_eur"].mean()
        p1, p2, p3 = st.columns(3)
        p1.metric("Coste sesion a PVPC",    f"{coste_pvpc:.2f} EUR",
                  help="PVPC incluye todos los costes regulados")
        p2.metric("Coste sesion en valle",  f"{coste_valle:.2f} EUR")
        p3.metric("Diferencia PVPC vs valle", f"{coste_pvpc - coste_valle:+.2f} EUR",
                  delta_color="inverse")

# ────────────────────────────────────────────────────────
#  TAB 4 — ALERTAS
# ────────────────────────────────────────────────────────
with tab_alertas:
    alerts_path = Path(__file__).parent.parent / "data" / "processed" / "alerts_log.json"
    if not alerts_path.exists():
        st.info("Sin alertas generadas aun. Ejecuta `python main.py --mode omie` localmente.")
    else:
        with open(alerts_path) as f:
            alerts = json.load(f)
        if not alerts:
            st.success("Sin alertas en el periodo analizado.")
        else:
            df_al = pd.DataFrame(alerts)
            df_al["timestamp"] = pd.to_datetime(df_al["timestamp"]).dt.strftime("%d/%m %H:%M")
            altas = df_al[df_al["nivel"] == "high"]
            opps  = df_al[df_al["nivel"] == "opportunity"]
            infos = df_al[df_al["nivel"] == "info"]

            a1, a2, a3 = st.columns(3)
            a1.metric("Criticas",     len(altas))
            a2.metric("Oportunidades",len(opps))
            a3.metric("Informativas", len(infos))

            t1, t2, t3 = st.tabs([
                f"Criticas ({len(altas)})",
                f"Oportunidades ({len(opps)})",
                f"Informativas ({len(infos)})",
            ])
            for tab, subset in [(t1, altas), (t2, opps), (t3, infos)]:
                with tab:
                    if subset.empty:
                        st.info("Sin alertas de este tipo.")
                    else:
                        st.dataframe(
                            subset[["timestamp","tipo","mensaje"]].rename(
                                columns={"timestamp":"Hora","tipo":"Tipo","mensaje":"Detalle"}),
                            use_container_width=True, hide_index=True)

# ════════════════════════════════════════════════════════
#  FOOTER
# ════════════════════════════════════════════════════════
st.markdown("---")
st.caption(
    "Fuentes: OMIE (mercado iberico) · ESIOS/REE · ENTSO-E  |  "
    "Costes regulados ajustables en el sidebar  |  "
    "Desarrollado con Streamlit + Plotly"
)
