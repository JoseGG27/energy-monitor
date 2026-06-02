# Monitor de Precios y Regulación Energética

Herramienta de análisis de precios eléctricos y seguimiento regulatorio para el sector energético y movilidad eléctrica.

## Fuentes de datos

| Fuente | Cobertura | Token | Estado |
|--------|-----------|-------|--------|
| OMIE | Mercado ibérico spot (ES/PT) hora a hora | No necesario | ✅ Listo |
| ESIOS (REE) | PVPC + precio spot España | Sí - consultasios@ree.es | ⏳ Pendiente token |
| ENTSO-E | Precios day-ahead ES/FR/DE | Sí - transparency@entsoe.eu | ⏳ Pendiente token |

## Instalación

```bash
pip install -r requirements.txt
cp .env.example .env
# Edita .env con tus tokens cuando los recibas
```

## Uso

```bash
# Sin tokens (solo OMIE, funciona ya)
python main.py --mode omie --days 7

# Con tokens (todas las fuentes)
python main.py --mode full --days 30

# Dashboard web
streamlit run dashboard/app.py
```

## Estructura

```
energy-monitor/
├── collectors/       # Conexión a APIs externas
├── analysis/         # Análisis de precios y anomalías
├── alerts/           # Motor de alertas
├── dashboard/        # Visualización Streamlit
├── data/
│   ├── raw/          # CSVs descargados
│   └── processed/    # Análisis y reportes
└── config/           # Tokens y configuración
```

## Casos de uso (ABEI / Movilidad eléctrica)

- Identificar **horas valle** para optimizar carga en sites EV
- Detectar **picos de precio** que impactan márgenes
- Comparar precios **ES vs FR vs DE** para decisiones de inversión
- Monitorizar **regulación AFIR** y cambios en mercados objetivo
