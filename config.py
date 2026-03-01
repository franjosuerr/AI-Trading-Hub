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

# --- IA: proveedor y claves (puedes usar Groq, Gemini u Ollama sin pagar OpenAI) ---
# Proveedor: openai | groq | gemini | ollama
AI_PROVIDER = os.getenv("AI_PROVIDER", "groq").strip().lower()
if AI_PROVIDER not in ("openai", "groq", "gemini", "ollama"):
    AI_PROVIDER = "groq"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")  # Gemini en Google AI Studio
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip().rstrip("/")

# Modelo por proveedor (solo se usa el del proveedor activo)
AI_MODEL = os.getenv("AI_MODEL", "").strip() or None  # Si vacío, se usa el default del proveedor

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

# --- Cantidad de velas recientes a incluir en el prompt a la IA (más = mejor contexto, más tokens) ---
PROMPT_CANDLES = int(os.getenv("PROMPT_CANDLES", "10"))

# --- Umbral de confianza (0-1): solo ejecutar orden si confidence >= este valor ---
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.7"))

# --- Monto por orden por par ---
# Formato env: "BTC/USDT:0.001,ETH/USDT:0.01,SOL/USDT:1" (base amount)
# O un valor fijo en quote: ORDER_AMOUNT_QUOTE=10 (opcional, ver utils)
ORDER_AMOUNT_PER_PAIR_STR = os.getenv("ORDER_AMOUNT_PER_PAIR", "BTC/USDT:0.001,ETH/USDT:0.01,SOL/USDT:1")
ORDER_AMOUNT_PER_PAIR = {}
for item in ORDER_AMOUNT_PER_PAIR_STR.split(","):
    item = item.strip()
    if ":" in item:
        pair, amount = item.split(":", 1)
        ORDER_AMOUNT_PER_PAIR[pair.strip()] = float(amount.strip())
    else:
        break
# Si no hay mapeo, usar un default por par conocido
if not ORDER_AMOUNT_PER_PAIR:
    ORDER_AMOUNT_PER_PAIR = {"BTC/USDT": 0.001, "ETH/USDT": 0.01, "SOL/USDT": 1.0}

# --- Intervalo entre ciclos completos de análisis (segundos) ---
INTERVAL = int(os.getenv("INTERVAL", "300"))

# --- Pausa entre el procesamiento de cada par (segundos), para no saturar APIs ---
PAIR_DELAY = float(os.getenv("PAIR_DELAY", "2"))

# --- Límite de trades por día por par (seguridad) ---
MAX_TRADES_PER_DAY_PER_PAIR = int(os.getenv("MAX_TRADES_PER_DAY_PER_PAIR", "5"))

# --- Stop-loss simple: porcentaje bajo el precio de entrada para vender ---
STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS_PERCENT", "2.0"))

# Modelo por proveedor (solo si quieres sobreescribir el default)
# OpenAI: gpt-4o-mini, gpt-4o | Groq: llama-3.1-8b-instant, llama-3.3-70b-versatile | Gemini: gemini-1.5-flash | Ollama: llama2, mistral
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
# En Google AI Studio los nombres pueden variar; si da 404 prueba gemini-2.0-flash o gemini-pro
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama2")

# --- Logs: ruta y rotación ---
# Directorio donde se guardan los archivos de log (se crea si no existe)
LOG_DIR = os.getenv("LOG_DIR", "logs").strip() or "logs"
# Nombre base del archivo (sin extensión; la extensión .log se añade)
LOG_FILE = os.getenv("LOG_FILE", "trading_bot.log").strip().replace(".log", "").replace(".LOG", "") or "trading_bot"
# Si True, se genera un archivo por día (rotación a medianoche); si False, rotación por tamaño
LOG_DAILY = os.getenv("LOG_DAILY", "true").lower() in ("true", "1", "yes")
# Días de logs diarios a conservar (solo cuando LOG_DAILY=true)
LOG_BACKUP_DAYS = int(os.getenv("LOG_BACKUP_DAYS", "30"))

# --- Nivel de log (DEBUG, INFO, WARNING, ERROR) ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
