"""
Configuración central del proyecto.
Copia .env.example a .env y rellena tus tokens.
"""
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Tokens API (llegan por email) ---
ESIOS_TOKEN   = os.getenv("ESIOS_TOKEN", "")       # REE: consultasios@ree.es
ENTSOE_TOKEN  = os.getenv("ENTSOE_TOKEN", "")      # ENTSO-E: transparency@entsoe.eu

# --- ESIOS endpoints ---
ESIOS_BASE_URL       = "https://api.esios.ree.es"
ESIOS_INDICATOR_PVPC = 1001
ESIOS_INDICATOR_SPOT = 600

# --- ENTSO-E areas ---
ENTSOE_BASE_URL = "https://web-api.tp.entsoe.eu/api"
ENTSOE_AREA_ES  = "10YES-REE------0"
ENTSOE_AREA_FR  = "10YFR-RTE------C"
ENTSOE_AREA_DE  = "10Y1001A1001A82H"   # DE-LU (correcto desde 2018)

# --- Almacenamiento local ---
DATA_RAW_DIR       = BASE_DIR / "data" / "raw"
DATA_PROCESSED_DIR = BASE_DIR / "data" / "processed"
DB_PATH            = BASE_DIR / "data" / "energy_monitor.db"

DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# --- Umbrales de alerta ---
ALERT_PRICE_HIGH_EUR_MWH = 150.0
ALERT_PRICE_LOW_EUR_MWH  = 20.0
