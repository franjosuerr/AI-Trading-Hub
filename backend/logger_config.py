import logging
import os
import glob
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler
from threading import Lock

LOG_DIR = "logs"
BOT_LOG_DIR = os.path.join(LOG_DIR, "bots")
ANALYSIS_LOG_DIR = os.path.join(LOG_DIR, "analysis")

_analysis_lock = Lock()

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
    os.makedirs(ANALYSIS_LOG_DIR, exist_ok=True)


def _create_daily_handler(filepath, backup_days=90):
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

    # Para logs analíticos por usuario (fichero único), purga por líneas.
    try:
        for filename in os.listdir(ANALYSIS_LOG_DIR):
            if filename.endswith("_analysis.log"):
                _purge_analysis_log_older_than(os.path.join(ANALYSIS_LOG_DIR, filename), max_days=max_days)
    except Exception:
        pass


def get_logger(name: str):
    """Acceso rápido a un logger estándar."""
    return logging.getLogger(name)


def _parse_log_datetime(line: str):
    """Parsea timestamps al inicio de línea con formato [YYYY-MM-DD HH:MM:SS]."""
    try:
        if not line.startswith("["):
            return None
        close_idx = line.find("]")
        if close_idx <= 1:
            return None
        raw = line[1:close_idx]
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _purge_analysis_log_older_than(filepath: str, max_days: int = 90):
    """Mantiene un solo fichero por usuario, eliminando líneas con más de max_days días."""
    if not os.path.exists(filepath):
        return

    cutoff = datetime.utcnow() - timedelta(hours=5) - timedelta(days=max_days)

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return

    kept = []
    for line in lines:
        dt = _parse_log_datetime(line)
        if dt is None or dt >= cutoff:
            kept.append(line)

    if len(kept) != len(lines):
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.writelines(kept)
        except Exception:
            return


def append_user_analysis_log(user_id: int, username: str, section: str, message: str):
    """
    Escribe contexto detallado para agentes de mejora en un único fichero por usuario.
    Archivo: logs/analysis/user_{id}_analysis.log
    """
    _ensure_dirs()
    filepath = os.path.join(ANALYSIS_LOG_DIR, f"user_{user_id}_analysis.log")

    now_col = datetime.utcnow() - timedelta(hours=5)
    ts = now_col.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [user_{user_id}:{username}] [{section}] {message}\n"

    with _analysis_lock:
        _purge_analysis_log_older_than(filepath, max_days=90)
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(line)


def get_user_analysis_log_path(user_id: int) -> str:
    _ensure_dirs()
    return os.path.join(ANALYSIS_LOG_DIR, f"user_{user_id}_analysis.log")
