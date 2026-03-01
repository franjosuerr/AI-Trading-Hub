# telegram_notifier.py
# Envío de notificaciones al chat de Telegram: inicio, señales por ciclo, órdenes y errores críticos.

import requests
from typing import Optional

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from logger_config import get_logger
from utils import SIGNAL_LABEL_ES

logger = get_logger("telegram")

BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"
# Timeout en segundos; evita bloquear el bot si Telegram no responde
TELEGRAM_TIMEOUT = 15


def _safe_telegram_error_message(exc: Exception) -> str:
    """Devuelve un mensaje seguro para el log (nunca incluir token ni URL completa)."""
    exc_type = type(exc).__name__
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "timeout de conexión. Comprueba conectividad con api.telegram.org."
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "error de conexión (red/DNS). Comprueba internet y acceso a api.telegram.org."
    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout. Telegram no respondió a tiempo."
    return f"error de red o API ({exc_type})."


def send_telegram_message(text: str) -> bool:
    """
    Envía un mensaje de texto al chat configurado. Retorna True si se envió correctamente.
    No se registra nunca el token ni la URL en los logs.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug("Telegram no configurado (token o chat_id faltante). No se envía mensaje.")
        return False
    url = BASE_URL.format(token=TELEGRAM_BOT_TOKEN)
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=TELEGRAM_TIMEOUT)
        if r.status_code != 200:
            logger.warning("Telegram API: código %s. Revisa token y chat_id.", r.status_code)
            return False
        return True
    except Exception as e:
        logger.warning(
            "Error al enviar mensaje Telegram: %s",
            _safe_telegram_error_message(e),
        )
        logger.debug("Excepción Telegram (sin datos sensibles): %s", type(e).__name__)
        return False


def notify_startup(
    pairs: list,
    timeframe: str,
    test_mode: bool,
    balance_summary: Optional[str] = None,
    interval_seconds: Optional[int] = None,
    pair_delay_seconds: Optional[float] = None,
):
    """Notifica que el bot ha iniciado, con balance y parámetros del ciclo."""
    mode = "SIMULACIÓN (test)" if test_mode else "REAL"
    msg = (
        f"🤖 <b>Bot de trading iniciado</b>\n"
        f"Modo: <b>{mode}</b>\n"
        f"Pares: {', '.join(pairs)}\n"
        f"Timeframe: {timeframe}\n"
    )
    if balance_summary:
        msg += f"💰 <b>Balance actual:</b> {balance_summary}\n"
    if interval_seconds is not None:
        msg += f"⏱ Ciclo cada: {interval_seconds}s\n"
    if pair_delay_seconds is not None:
        msg += f"⏱ Pausa entre pares: {pair_delay_seconds}s"
    send_telegram_message(msg)


def notify_signals_cycle(signals: list) -> bool:
    """
    Mensaje con todas las señales del ciclo: par, señal, confianza, razón, precio e indicadores.
    signals: lista de dicts con pair, signal, confidence, reason, price, last_close, volume, rsi, macd_histogram, sma50, sma200
    """
    if not signals:
        return True
    lines = ["📊 <b>Señales del ciclo</b>"]
    for s in signals:
        pair = s.get("pair", "?")
        signal = s.get("signal", "?")
        signal_es = SIGNAL_LABEL_ES.get(signal, signal)
        conf = s.get("confidence", 0)
        reason = (s.get("reason") or "")[:180]
        price = s.get("price")
        price_str = f" | Precio: {price}" if price is not None else ""
        rsi = s.get("rsi")
        rsi_str = f" RSI: {float(rsi):.1f}" if rsi is not None else ""
        sma50 = s.get("sma50")
        sma50_str = f" SMA50: {sma50}" if sma50 is not None else ""
        last_close = s.get("last_close")
        close_str = f" Cierre: {last_close}" if last_close is not None else ""
        lines.append(
            f"• <b>{pair}</b>: {signal_es.upper()} (confianza: {conf:.2f}){price_str}{rsi_str}{sma50_str}{close_str}\n  → {reason}"
        )
    msg = "\n".join(lines)
    return send_telegram_message(msg)


def notify_order_executed(
    pair: str,
    side: str,
    amount: float,
    price: Optional[float],
    order_id: str,
    simulated: bool = False,
    balance_after: Optional[str] = None,
):
    """Notifica que se ejecutó una orden (real o simulada), con balance después si se proporciona."""
    tag = "[SIMULADA] " if simulated else ""
    price_str = f" @ {price}" if price else ""
    side_es = SIGNAL_LABEL_ES.get(side, side)
    msg = (
        f"📌 {tag}<b>Orden ejecutada</b>\n"
        f"Par: {pair} | Lado: {side_es.upper()}\n"
        f"Cantidad: {amount}{price_str}\n"
        f"ID de orden: {order_id}"
    )
    if balance_after:
        msg += f"\n💰 Balance después: {balance_after}"
    send_telegram_message(msg)


def notify_cycle_summary(
    balance_start: str,
    balance_end: str,
    orders: list,
    signals_count: int,
    errors: Optional[list] = None,
):
    """Notifica el resumen del ciclo: balances inicio/fin, número de señales, órdenes ejecutadas y errores."""
    msg = (
        "📋 <b>Resumen del ciclo</b>\n"
        f"💰 Balance inicio: {balance_start}\n"
        f"💰 Balance final: {balance_end}\n"
        f"📊 Señales: {signals_count} | 📌 Órdenes: {len(orders)}"
    )
    if orders:
        msg += "\n<b>Órdenes:</b>"
        for o in orders:
            sim = " (simulada)" if o.get("simulated") else ""
            side_es = SIGNAL_LABEL_ES.get(o.get("side", ""), o.get("side", "?"))
            msg += f"\n  • {side_es.upper()} {o.get('pair', '?')} {o.get('amount')} @ {o.get('price')}{sim}"
    if errors:
        msg += "\n⚠️ Errores: " + "; ".join(errors[:5])
        if len(errors) > 5:
            msg += f" (+{len(errors) - 5} más)"
    send_telegram_message(msg)


def notify_critical_error(title: str, detail: str):
    """Notifica un error crítico que puede detener el bot."""
    from datetime import datetime
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    msg = f"🚨 <b>Error crítico</b> [{ts}]\n{title}\n<code>{detail[:500]}</code>"
    send_telegram_message(msg)
