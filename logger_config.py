"""
logger_config.py (raíz) — Puente para módulos de trading originales.
Re-exporta funciones desde backend.logger_config para que
indicators.py, ai_advisor.py, utils.py, etc. sigan funcionando.
"""
from backend.logger_config import get_logger, setup_backend_logging

def setup_logging():
    """Alias para compatibilidad con main.py original."""
    setup_backend_logging()
