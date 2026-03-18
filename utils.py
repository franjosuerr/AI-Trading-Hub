# utils.py
# Funciones auxiliares: validación de señal IA, formateo, precisión numérica.

import json
import re
from typing import Any, Optional
from datetime import datetime, timedelta

def get_colombia_time() -> datetime:
    """Retorna la fecha y hora actual en la zona horaria de Colombia (UTC-5) como un datetime naive."""
    return datetime.utcnow() - timedelta(hours=5)

from logger_config import get_logger

logger = get_logger("utils")

# Estructura esperada de la respuesta de la IA
SIGNAL_KEYS = ("signal", "confidence", "reason")
# Etiquetas en español para logs y Telegram
SIGNAL_LABEL_ES = {"buy": "comprar", "sell": "vender", "hold": "mantener"}


def validate_ai_signal(data: Any) -> Optional[dict]:
    """
    Valida que el dato sea un dict con signal ('buy'|'sell'|'hold'),
    confidence (float 0-1), reason (string), y opcionalmente
    amount_usdt (para buy) o sell_percentage (para sell).
    Retorna el dict normalizado o None si es inválido.
    """
    if data is None:
        return None
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            # Intentar extraer JSON desde texto
            match = re.search(r"\{[^{}]*\"signal\"[^{}]*\}", data)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    return None
            else:
                return None
    if not isinstance(data, dict):
        return None
    signal = (data.get("signal") or "").strip().lower()
    if signal not in ("buy", "sell", "hold"):
        logger.warning("Señal IA inválida: '%s' (esperado: comprar/vender/mantener)", signal)
        return None
    try:
        confidence = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    reason = str(data.get("reason") or "").strip() or "Sin razón proporcionada"
    result = {"signal": signal, "confidence": confidence, "reason": reason}

    # Extraer monto USDT para órdenes de compra
    if signal == "buy":
        try:
            amount_usdt = float(data.get("amount_usdt", 0))
            result["amount_usdt"] = max(0.0, amount_usdt)
        except (TypeError, ValueError):
            result["amount_usdt"] = 0.0

    # Extraer porcentaje de venta para órdenes de venta
    if signal == "sell":
        try:
            sell_pct = float(data.get("sell_percentage", 100))
            result["sell_percentage"] = max(1.0, min(100.0, sell_pct))
        except (TypeError, ValueError):
            result["sell_percentage"] = 100.0

    return result


def round_to_precision(value: float, precision: int) -> float:
    """
    Redondea value al número de decimales dado (precision = cantidad de decimales).
    """
    if precision <= 0:
        return round(value, 0)
    return round(value, precision)


def format_candles_for_prompt(df, last_n: int = 5) -> str:
    """
    Formatea las últimas N filas del DataFrame OHLCV para incluir en el prompt.
    """
    if df is None or df.empty:
        return "No hay datos de velas."
    cols = ["open", "high", "low", "close", "volume"]
    available = [c for c in cols if c in df.columns]
    tail = df[available].tail(last_n)
    lines = []
    for idx, row in tail.iterrows():
        parts = [f"{c}={row[c]}" for c in available]
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def format_context_summary(df, last_n: int = 20) -> str:
    """
    Genera un resumen de contexto para la IA: tendencia reciente, máximos/mínimos,
    y comparación de precios hace N velas. Ayuda a la IA a tomar mejores decisiones.
    """
    if df is None or df.empty or "close" not in df.columns:
        return ""
    tail = df.tail(last_n)
    if tail.empty:
        return ""
    closes = tail["close"].astype(float)
    current = float(closes.iloc[-1])
    min_close = float(closes.min())
    max_close = float(closes.max())
    # Precio hace 5 y 10 velas (si hay datos)
    close_5_ago = float(closes.iloc[-5]) if len(closes) >= 5 else current
    close_10_ago = float(closes.iloc[-10]) if len(closes) >= 10 else current
    # Tendencia corta
    if close_5_ago > 0:
        change_5 = (current - close_5_ago) / close_5_ago * 100
    else:
        change_5 = 0
    if close_10_ago > 0:
        change_10 = (current - close_10_ago) / close_10_ago * 100
    else:
        change_10 = 0
    if change_5 > 0.3:
        trend_5 = "sube"
    elif change_5 < -0.3:
        trend_5 = "baja"
    else:
        trend_5 = "lateral"
    if change_10 > 0.3:
        trend_10 = "sube"
    elif change_10 < -0.3:
        trend_10 = "baja"
    else:
        trend_10 = "lateral"
    lines = [
        f"Velas analizadas (últimas {len(tail)}): cierre mínimo={min_close:.4f}, máximo={max_close:.4f}, actual={current:.4f}.",
        f"Precio hace 5 velas: {close_5_ago:.4f} (variación {change_5:+.2f}%) → tendencia {trend_5}.",
        f"Precio hace 10 velas: {close_10_ago:.4f} (variación {change_10:+.2f}%) → tendencia {trend_10}.",
    ]
    return "\n".join(lines)
