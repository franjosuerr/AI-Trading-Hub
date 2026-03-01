# main.py
# Punto de entrada: bucle principal que orquesta análisis por par, IA, órdenes y notificaciones.
# Logs detallados de todo: balance, posiciones, OHLCV, indicadores, señales, órdenes.

import time
from collections import defaultdict
from datetime import datetime, timedelta

from config import (
    PAIRS,
    TIMEFRAME,
    CANDLE_COUNT,
    PROMPT_CANDLES,
    CONFIDENCE_THRESHOLD,
    ORDER_AMOUNT_PER_PAIR,
    INTERVAL,
    PAIR_DELAY,
    TEST_MODE,
    MAX_TRADES_PER_DAY_PER_PAIR,
    STOP_LOSS_PERCENT,
)
from logger_config import setup_logging, get_logger
from exchange_client import (
    create_exchange,
    fetch_ohlcv,
    create_order,
    fetch_ticker_price,
    fetch_balance,
    format_balance_one_line,
)
from indicators import compute_all_indicators
from ai_advisor import get_ai_signal
from telegram_notifier import (
    notify_startup,
    notify_signals_cycle,
    notify_order_executed,
    notify_critical_error,
    notify_cycle_summary,
)
from utils import format_candles_for_prompt, format_context_summary, get_order_amount_for_pair, SIGNAL_LABEL_ES

# Contador de trades por par por día (para límite de seguridad)
_trades_today: dict[str, list[datetime]] = defaultdict(list)
_DAY = timedelta(days=1)


def _clean_old_trades():
    """Elimina registros de trades de más de 24 horas."""
    cutoff = datetime.utcnow() - _DAY
    for pair in list(_trades_today.keys()):
        _trades_today[pair] = [t for t in _trades_today[pair] if t > cutoff]


def _can_trade_today(pair: str) -> bool:
    """Comprueba si aún se puede operar hoy en este par (límite MAX_TRADES_PER_DAY_PER_PAIR)."""
    _clean_old_trades()
    return len(_trades_today[pair]) < MAX_TRADES_PER_DAY_PER_PAIR


def _record_trade(pair: str):
    """Registra un trade ejecutado para el par."""
    _trades_today[pair].append(datetime.utcnow())


def _log_balance_full(logger, balance, prefix: str = "Balance"):
    """Escribe en log el balance completo por moneda (free, used, total)."""
    if not balance:
        logger.info("%s: No disponible", prefix)
        return
    logger.info("%s (cuenta): %s", prefix, format_balance_one_line(balance))
    for cur, data in sorted(balance.items()):
        if isinstance(data, dict) and (data.get("total") or data.get("free") or data.get("used")):
            logger.info(
                "  %s: free=%s used=%s total=%s",
                cur,
                data.get("free"),
                data.get("used"),
                data.get("total"),
            )


def run_cycle(exchange, logger):
    """
    Un ciclo completo: balance → por cada par (OHLCV, indicadores, IA, orden si aplica) → resumen.
    Logs detallados de todo; notificaciones Telegram con máxima información.
    """
    cycle_start = datetime.utcnow().isoformat()
    logger.info("========== INICIO DE CICLO %s ==========", cycle_start)

    # Balance al inicio del ciclo
    balance_start = fetch_balance(exchange, PAIRS)
    _log_balance_full(logger, balance_start, "Balance al inicio del ciclo")
    balance_summary_start = format_balance_one_line(balance_start)

    signals_for_telegram = []
    orders_this_cycle = []
    errors_this_cycle = []

    for pair in PAIRS:
        try:
            time.sleep(PAIR_DELAY)
        except KeyboardInterrupt:
            raise

        logger.info("---------- Par: %s ----------", pair)

        # 1. Obtener velas
        df = fetch_ohlcv(exchange, pair, TIMEFRAME, CANDLE_COUNT)
        if df is None or df.empty:
            logger.warning("Sin datos OHLCV para %s, se omite.", pair)
            errors_this_cycle.append(f"{pair}: sin datos OHLCV")
            continue

        n_candles = len(df)
        last = df.iloc[-1]
        last_o, last_h, last_l, last_c = last.get("open"), last.get("high"), last.get("low"), last.get("close")
        last_v = last.get("volume", 0)
        logger.info(
            "OHLCV: %d velas | Última: O=%s H=%s L=%s C=%s V=%s",
            n_candles, last_o, last_h, last_l, last_c, last_v,
        )

        # 2. Indicadores
        indicators = compute_all_indicators(df)
        candles_text = format_candles_for_prompt(df, PROMPT_CANDLES)
        context_summary = format_context_summary(df, last_n=min(30, len(df)))
        logger.info(
            "Indicadores: RSI=%s MACD_line=%s MACD_signal=%s MACD_hist=%s SMA50=%s SMA200=%s BB_upper=%s BB_lower=%s volume=%s volume_avg=%s",
            indicators.get("rsi"),
            indicators.get("macd_line"),
            indicators.get("macd_signal"),
            indicators.get("macd_histogram"),
            indicators.get("sma50"),
            indicators.get("sma200"),
            indicators.get("bb_upper"),
            indicators.get("bb_lower"),
            indicators.get("volume"),
            indicators.get("volume_avg"),
        )

        # Precio actual (ticker) para logs, Telegram y contexto de la IA
        current_price = fetch_ticker_price(exchange, pair)
        if current_price is not None:
            logger.info("Precio actual (ticker) %s: %s", pair, current_price)

        # Balance disponible para este par (para contexto de la IA)
        base_currency = pair.split("/")[0] if "/" in pair else pair
        quote_currency = pair.split("/")[1] if "/" in pair else "USDT"
        free_base = 0.0
        free_quote = 0.0
        if balance_start:
            if base_currency in balance_start and isinstance(balance_start[base_currency], dict):
                free_base = float(balance_start[base_currency].get("free", 0) or 0)
            if quote_currency in balance_start and isinstance(balance_start[quote_currency], dict):
                free_quote = float(balance_start[quote_currency].get("free", 0) or 0)
        balance_hint = f"{quote_currency}: {free_quote:.4f}, {base_currency}: {free_base:.6f}"

        # 3. Señal de la IA (con precio actual, balance, stop-loss y conservadurismo)
        signal_data = get_ai_signal(
            pair,
            TIMEFRAME,
            candles_text,
            indicators,
            PROMPT_CANDLES,
            context_summary,
            current_price=current_price,
            balance_hint=balance_hint,
            stop_loss_percent=STOP_LOSS_PERCENT,
        )
        if signal_data is None:
            logger.warning("No se pudo obtener señal IA para %s.", pair)
            errors_this_cycle.append(f"{pair}: sin señal IA")
            continue

        logger.info(
            "Señal IA: señal=%s confianza=%s razón=%s",
            SIGNAL_LABEL_ES.get(signal_data["signal"], signal_data["signal"]),
            signal_data["confidence"],
            signal_data["reason"],
        )

        # Datos ricos para Telegram (precio + indicadores clave)
        signals_for_telegram.append({
            "pair": pair,
            "signal": signal_data["signal"],
            "confidence": signal_data["confidence"],
            "reason": signal_data["reason"],
            "price": current_price,
            "last_close": float(last_c) if last_c is not None else None,
            "volume": float(last_v) if last_v is not None else None,
            "rsi": indicators.get("rsi"),
            "macd_histogram": indicators.get("macd_histogram"),
            "sma50": indicators.get("sma50"),
            "sma200": indicators.get("sma200"),
        })

        # 4. ¿Ejecutar orden?
        if signal_data["signal"] not in ("buy", "sell"):
            logger.info("Sin orden: señal es %s (solo comprar/vender ejecutan).", SIGNAL_LABEL_ES.get(signal_data["signal"], signal_data["signal"]))
            continue
        if signal_data["confidence"] < CONFIDENCE_THRESHOLD:
            logger.info(
                "Sin orden: confianza %.2f < umbral %.2f para %s.",
                signal_data["confidence"],
                CONFIDENCE_THRESHOLD,
                pair,
            )
            continue
        if not _can_trade_today(pair):
            logger.warning("Límite de trades diarios alcanzado para %s.", pair)
            errors_this_cycle.append(f"{pair}: límite diario")
            continue

        # 5. Crear orden (market; en test mode se simula)
        amount = get_order_amount_for_pair(pair, ORDER_AMOUNT_PER_PAIR)
        if amount <= 0:
            logger.warning("Monto no configurado para %s.", pair)
            continue

        # Para VENDER hay que tener la moneda base (ej. ETH); comprobar saldo antes
        if signal_data["signal"] == "sell":
            base_currency = pair.split("/")[0] if "/" in pair else pair
            balance_now = fetch_balance(exchange, PAIRS)
            free_base = 0.0
            if balance_now and base_currency in balance_now:
                free_base = float(balance_now[base_currency].get("free", 0) or 0)
            if free_base < amount:
                logger.warning(
                    "Saldo insuficiente de %s para vender: tienes %s, se requiere %s. Se omite la orden.",
                    base_currency,
                    free_base,
                    amount,
                )
                errors_this_cycle.append(f"{pair}: saldo insuficiente de {base_currency} para vender")
                continue

        logger.info("Ejecutando orden: %s %s cantidad=%s (market)", signal_data["signal"], pair, amount)
        order = create_order(exchange, pair, signal_data["signal"], amount, "market")
        if order:
            _record_trade(pair)
            price = order.get("average") or order.get("price")
            order_id = order.get("id", "N/A")
            filled = order.get("filled", amount)
            simulated = TEST_MODE or order.get("info", {}).get("simulated", False)
            logger.info(
                ">>> ORDEN EJECUTADA: %s %s | cantidad=%s | precio=%s | id_orden=%s | simulada=%s",
                SIGNAL_LABEL_ES.get(signal_data["signal"], signal_data["signal"]).upper(),
                pair,
                filled,
                price,
                order_id,
                simulated,
            )
            orders_this_cycle.append({
                "pair": pair,
                "side": signal_data["signal"],
                "amount": filled,
                "price": price,
                "order_id": order_id,
                "simulated": simulated,
            })
            notify_order_executed(
                pair,
                signal_data["signal"],
                filled,
                price,
                order_id,
                simulated=simulated,
                balance_after=format_balance_one_line(fetch_balance(exchange, PAIRS)),
            )
        else:
            errors_this_cycle.append(f"{pair}: fallo al crear orden")

    # Balance al final del ciclo
    balance_end = fetch_balance(exchange, PAIRS)
    _log_balance_full(logger, balance_end, "Balance al final del ciclo")
    balance_summary_end = format_balance_one_line(balance_end)

    logger.info(
        "========== FIN DE CICLO | Órdenes ejecutadas: %d | Señales: %d ==========",
        len(orders_this_cycle),
        len(signals_for_telegram),
    )
    for o in orders_this_cycle:
        logger.info("  Orden: %s %s cantidad=%s precio=%s id=%s", SIGNAL_LABEL_ES.get(o["side"], o["side"]), o["pair"], o["amount"], o["price"], o["order_id"])
    if errors_this_cycle:
        for err in errors_this_cycle:
            logger.warning("  Error en ciclo: %s", err)

    # Notificaciones Telegram
    if signals_for_telegram:
        notify_signals_cycle(signals_for_telegram)
    notify_cycle_summary(
        balance_start=balance_summary_start,
        balance_end=balance_summary_end,
        orders=orders_this_cycle,
        signals_count=len(signals_for_telegram),
        errors=errors_this_cycle,
    )


def main():
    setup_logging()
    logger = get_logger("main")

    if not PAIRS:
        logger.error("No hay pares configurados (PAIRS). Revisa config o .env.")
        return

    logger.info(
        "Iniciando bot. Pares: %s | Timeframe: %s | Test mode: %s | Intervalo: %ss | Delay entre pares: %ss",
        PAIRS, TIMEFRAME, TEST_MODE, INTERVAL, PAIR_DELAY,
    )

    try:
        exchange = create_exchange()
    except Exception as e:
        logger.exception("No se pudo crear cliente CoinEx: %s", e)
        notify_critical_error("Error de conexión CoinEx", str(e))
        return

    balance_at_start = fetch_balance(exchange, PAIRS)
    _log_balance_full(logger, balance_at_start, "Balance al arranque")
    notify_startup(
        pairs=PAIRS,
        timeframe=TIMEFRAME,
        test_mode=TEST_MODE,
        balance_summary=format_balance_one_line(balance_at_start),
        interval_seconds=INTERVAL,
        pair_delay_seconds=PAIR_DELAY,
    )

    while True:
        try:
            run_cycle(exchange, logger)
        except KeyboardInterrupt:
            logger.info("Detención solicitada (Ctrl+C). Cerrando...")
            break
        except Exception as e:
            logger.exception("Error en ciclo principal: %s", e)
            notify_critical_error("Error en ciclo principal", str(e))
            # Continuar tras un respiro
            time.sleep(60)

        logger.info("Próximo ciclo en %s segundos.", INTERVAL)
        try:
            time.sleep(INTERVAL)
        except KeyboardInterrupt:
            logger.info("Detención solicitada. Cerrando...")
            break

    logger.info("Bot detenido correctamente.")


if __name__ == "__main__":
    main()
