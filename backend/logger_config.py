import logging
import os
import glob
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler

LOG_DIR = "logs"
BOT_LOG_DIR = os.path.join(LOG_DIR, "bots")

def colombia_converter(timestamp):
    """Convierte un timestamp a hora de Colombia (UTC-5)."""
    # Crear datetime en UTC desde el timestamp
    dt = datetime.fromtimestamp(timestamp, timezone.utc)
    # Restar 5 horas para Colombia
    col_dt = dt - timedelta(hours=5)
    return col_dt.timetuple()

# --- Formato compartido ---
FORMATTER = logging.Formatter(
    '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
FORMATTER.converter = colombia_converter

CONSOLE_FORMATTER = logging.Formatter(
    '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
CONSOLE_FORMATTER.converter = colombia_converter


def _ensure_dirs():
    """Crea directorios de logs si no existen."""
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(BOT_LOG_DIR, exist_ok=True)


def _create_daily_handler(filepath, backup_days=30):
    """Crea un handler con rotación diaria y retención de N días."""
    handler = TimedRotatingFileHandler(
        filepath, when="midnight", interval=1,
        backupCount=backup_days, encoding="utf-8"
    )
    handler.setFormatter(FORMATTER)
    handler.suffix = "%Y-%m-%d"
    return handler


def setup_backend_logging():
    """Configura el sistema de logs principal del backend (API + uvicorn)."""
    _ensure_dirs()

    # --- Backend log file ---
    backend_handler = _create_daily_handler(os.path.join(LOG_DIR, "backend.log"))

    # --- Console handler ---
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(CONSOLE_FORMATTER)

    # --- Root logger (captura todo lo que no tenga handler propio) ---
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    # Limpiar handlers previos (evita duplicados en --reload)
    root_logger.handlers.clear()
    root_logger.addHandler(backend_handler)
    root_logger.addHandler(console_handler)

    # Uvicorn usa sus propios loggers; los redirigimos
    for uv_name in ("uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(uv_name)
        uv_logger.handlers = [backend_handler, console_handler]
        uv_logger.propagate = False


def setup_frontend_logger():
    """Crea un logger dedicado para mensajes del frontend."""
    _ensure_dirs()

    frontend_logger = logging.getLogger("frontend")
    # Evitar duplicados en reloads
    if frontend_logger.handlers:
        return frontend_logger

    frontend_handler = _create_daily_handler(os.path.join(LOG_DIR, "frontend.log"))

    # Consola también para visibilidad inmediata
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(CONSOLE_FORMATTER)

    frontend_logger.addHandler(frontend_handler)
    frontend_logger.addHandler(console_handler)
    frontend_logger.propagate = False  # No duplicar al root
    frontend_logger.setLevel(logging.INFO)

    return frontend_logger


def get_user_bot_logger(user_id: int, username: str = "unknown"):
    """Devuelve un logger que escribe en logs/bots/user_{id}.log"""
    _ensure_dirs()

    logger_name = f"bot.user_{user_id}"
    bot_logger = logging.getLogger(logger_name)

    # Evitar duplicados de handlers
    if bot_logger.handlers:
        return bot_logger

    filepath = os.path.join(BOT_LOG_DIR, f"user_{user_id}.log")
    file_handler = _create_daily_handler(filepath)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(CONSOLE_FORMATTER)

    bot_logger.addHandler(file_handler)
    bot_logger.addHandler(console_handler)
    bot_logger.propagate = False  # No subir al root/backend.log
    bot_logger.setLevel(logging.INFO)

    return bot_logger


def cleanup_old_logs(max_days=30):
    """Elimina archivos .log con más de max_days días de antigüedad."""
    cutoff = datetime.now() - timedelta(days=max_days)

    for dirpath, _, filenames in os.walk(LOG_DIR):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                if mtime < cutoff:
                    os.remove(filepath)
                    logging.getLogger("api").info(f"Log antiguo eliminado: {filepath}")
            except Exception:
                pass


def get_logger(name: str):
    """Acceso rápido a un logger estándar."""
    return logging.getLogger(name)
