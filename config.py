# config.py
# Carga variables de entorno y configuración del bot (pares, timeframes, umbrales, etc.)

import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar .env desde la raíz del proyecto
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_env_path)

# --- Exchange (CoinEx) ---
COINEX_API_KEY = os.getenv("COINEX_API_KEY", "")
COINEX_SECRET = os.getenv("COINEX_SECRET", "")



# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# --- Modo test: si True, no se envían órdenes reales a CoinEx ---
TEST_MODE = os.getenv("TEST_MODE", "true").lower() in ("true", "1", "yes")

# --- Pares a operar ---
# Formato: lista de strings "BASE/QUOTE", ej: ["BTC/USDT", "ETH/USDT"]
PAIRS_STR = os.getenv("PAIRS", "BTC/USDT,ETH/USDT,SOL/USDT")
PAIRS = [p.strip() for p in PAIRS_STR.split(",") if p.strip()]

# --- Timeframe para velas (1m, 5m, 15m, 1h, 4h, 1d, etc.) ---
TIMEFRAME = os.getenv("TIMEFRAME", "1h")

# --- Cantidad de velas a obtener y analizar (más velas = indicadores MACD/SMA200 correctos) ---
CANDLE_COUNT = int(os.getenv("CANDLE_COUNT", "50"))



# --- Intervalo entre ciclos completos de análisis (segundos) ---
INTERVAL = int(os.getenv("INTERVAL", "300"))

# --- Pausa entre el procesamiento de cada par (segundos), para no saturar APIs ---
PAIR_DELAY = float(os.getenv("PAIR_DELAY", "2"))

# --- Límite de trades por día por par (seguridad) ---
MAX_TRADES_PER_DAY_PER_PAIR = int(os.getenv("MAX_TRADES_PER_DAY_PER_PAIR", "5"))

# --- Stop-loss simple: porcentaje bajo el precio de entrada para vender ---
STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS_PERCENT", "2.0"))


# --- Logs: ruta y rotación ---
# Directorio donde se guardan los archivos de log (se crea si no existe)
LOG_DIR = os.getenv("LOG_DIR", "/data/logs").strip() or "/data/logs"
# Nombre base del archivo (sin extensión; la extensión .log se añade)
LOG_FILE = os.getenv("LOG_FILE", "trading_bot.log").strip().replace(".log", "").replace(".LOG", "") or "trading_bot"
# Si True, se genera un archivo por día (rotación a medianoche); si False, rotación por tamaño
LOG_DAILY = os.getenv("LOG_DAILY", "true").lower() in ("true", "1", "yes")
# Días de logs diarios a conservar (solo cuando LOG_DAILY=true)
LOG_BACKUP_DAYS = int(os.getenv("LOG_BACKUP_DAYS", "30"))

# --- Nivel de log (DEBUG, INFO, WARNING, ERROR) ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
