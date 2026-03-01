"""
bot_manager.py — Orquestador de bots de trading por usuario.

Integra la lógica completa del ciclo de trading original (main.py):
  OHLCV → Indicadores → IA → Orden → Telegram → Logs

Cada usuario corre su propio asyncio.Task con su propio logger dedicado
que escribe a  logs/bots/user_{id}.log
"""

import asyncio
import time
import os
import importlib
import requests
from typing import Dict, Optional
from datetime import datetime, timedelta
from collections import defaultdict

import ccxt
import pandas as pd

# Módulos de trading originales (raíz del proyecto)
from indicators import compute_all_indicators
from ai_advisor import get_ai_signal
from utils import (
    format_candles_for_prompt,
    format_context_summary,
    get_order_amount_for_pair,
    SIGNAL_LABEL_ES,
    round_to_precision,
)
from email_notifier import send_trade_email

# Backend
from backend.database import SessionLocal
from backend.models.models import User, GlobalConfig
from backend.logger_config import get_logger, get_user_bot_logger

logger = get_logger("bot_manager")


# ─── Utilidades de exchange (inline, para no depender de config.py) ───

def _create_exchange(api_key: str, secret: str, test_mode: bool):
    """Crea instancia ccxt.coinex con las credenciales del usuario."""
    config = {
        "apiKey": api_key or "test_key",
        "secret": secret or "test_secret",
        "enableRateLimit": True,
        "options": {},
    }
    return ccxt.coinex(config)


def _fetch_ohlcv(exchange, symbol, timeframe, limit, log):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not ohlcv:
            return None
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df
    except ccxt.NetworkError as e:
        log.warning("Error de red al obtener OHLCV para %s: %s", symbol, str(e)[:150])
        return None
    except Exception as e:
        log.exception("Error al obtener OHLCV para %s: %s", symbol, e)
        return None


def _fetch_ticker_price(exchange, symbol, log) -> Optional[float]:
    try:
        ticker = exchange.fetch_ticker(symbol)
        return float(ticker.get("last", 0))
    except Exception as e:
        log.warning("Error al obtener ticker %s: %s", symbol, str(e)[:100])
        return None


def _fetch_balance(exchange, pairs, log) -> Optional[dict]:
    try:
        balance = exchange.fetch_balance()
        result = {}
        skip_keys = {"info", "timestamp", "datetime"}
        currencies = set()
        if pairs:
            for p in pairs:
                if "/" in p:
                    b, q = p.split("/", 1)
                    currencies.add(b.strip())
                    currencies.add(q.strip())
        for key, value in balance.items():
            if key in skip_keys or value is None:
                continue
            if isinstance(value, dict) and ("free" in value or "total" in value):
                free = float(value.get("free", 0) or 0)
                used = float(value.get("used", 0) or 0)
                total = float(value.get("total", 0) or 0)
                if total > 0 or free > 0 or used > 0 or key in currencies:
                    result[key] = {"free": free, "used": used, "total": total}
        log.info("Balance obtenido: %d moneda(s) con saldo.", len(result))
        return result if result else None
    except ccxt.NetworkError as e:
        log.warning("Error de red al obtener el balance: %s", str(e)[:150])
        return None
    except Exception as e:
        log.warning("Error al obtener el balance: %s", str(e)[:100])
        return None


def _format_balance_one_line(balance) -> str:
    if not balance:
        return "No disponible"
    parts = [f"{cur}={data['total']}" for cur, data in sorted(balance.items()) if data.get("total")]
    return " ".join(parts) if parts else "0"


def _log_balance_full(log, balance, prefix="Balance"):
    if not balance:
        log.info("%s: No disponible", prefix)
        return
    log.info("%s (cuenta): %s", prefix, _format_balance_one_line(balance))
    for cur, data in sorted(balance.items()):
        if isinstance(data, dict) and (data.get("total") or data.get("free") or data.get("used")):
            log.info("  %s: free=%s used=%s total=%s", cur, data.get("free"), data.get("used"), data.get("total"))


def _create_order(exchange, symbol, side, amount, order_type, test_mode, log, price=None):
    """Crea orden real o simulada."""
    if amount <= 0:
        log.warning("Monto inválido para %s: %s", symbol, amount)
        return None

    if test_mode:
        fake_order = {
            "id": f"sim_{symbol}_{side}_{int(time.time()*1000)}",
            "symbol": symbol, "side": side, "type": order_type,
            "amount": amount, "price": price, "status": "closed",
            "filled": amount, "info": {"simulated": True},
        }
        log.info("[SIMULADO] Orden %s %s %s cantidad=%s precio=%s", side, order_type, symbol, amount, price)
        return fake_order

    try:
        if order_type == "market":
            if side == "buy" and price is None:
                ticker = exchange.fetch_ticker(symbol)
                price = float(ticker.get("last", 0))
            order = exchange.create_market_order(symbol, side, amount, price)
        else:
            if price is None:
                ticker = exchange.fetch_ticker(symbol)
                price = ticker["last"]
            order = exchange.create_limit_order(symbol, side, amount, price)
        log.info("Orden ejecutada: %s %s %s id=%s cantidad=%s", side, symbol, order_type, order.get("id"), order.get("filled", amount))
        return order
    except ccxt.InsufficientFunds as e:
        log.warning("Saldo insuficiente para %s %s: %s", side, symbol, str(e)[:100])
        return None
    except Exception as e:
        log.exception("Error al crear orden %s %s: %s", side, symbol, e)
        return None


def _parse_pairs(pairs_str: str) -> list:
    return [p.strip() for p in pairs_str.split(",") if p.strip()]


def _parse_order_amounts(amounts_str: str) -> dict:
    result = {}
    if not amounts_str:
        return result
    for item in amounts_str.split(","):
        item = item.strip()
        if ":" in item:
            pair, amount = item.split(":", 1)
            try:
                result[pair.strip()] = float(amount.strip())
            except ValueError:
                pass
    return result


def _send_telegram_for_user(user, text, tg_logger=None):
    """Envía mensaje Telegram usando las credenciales del usuario. Logea resultado."""
    log = tg_logger or logger
    token = getattr(user, 'telegram_bot_token', None)
    chat_id = getattr(user, 'telegram_chat_id', None)
    if not token or not chat_id:
        log.info("Telegram: sin credenciales configuradas (token o chat_id vacío). Mensaje no enviado.")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    log.info("Telegram: enviando mensaje (%d caracteres)...", len(text))
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=15)
        if r.status_code == 200:
            log.info("Telegram: mensaje enviado OK.")
            return True
        else:
            log.warning("Telegram: API devolvió código %s. Revisa token y chat_id.", r.status_code)
            return False
    except requests.exceptions.Timeout:
        log.warning("Telegram: timeout al enviar mensaje. Telegram no respondió en 15s.")
        return False
    except requests.exceptions.ConnectionError:
        log.warning("Telegram: error de conexión/DNS. Revisa tu internet.")
        return False
    except Exception as e:
        log.warning("Telegram: error inesperado al enviar: %s", str(e)[:150])
        return False


# ─── Ciclo de trading completo (por usuario) ───

async def _run_trading_cycle(exchange, user, config, pairs, order_amounts, user_logger, cycle_count):
    """Ejecuta un ciclo completo de trading: Balance → Pares → IA → Órdenes → Telegram."""

    test_mode = config.test_mode if config.test_mode is not None else True
    timeframe = config.timeframe or "15m"
    candle_count = config.candle_count or 210
    prompt_candles = config.prompt_candles or 10
    confidence_threshold = config.confidence_threshold or 0.7
    stop_loss = config.stop_loss_percent or 2.0
    pair_delay = config.pair_delay or 2
    max_trades = config.max_trades_per_day or 5

    # Determinar proveedor y modelo de IA desde la config global
    ai_provider = config.ai_provider or "groq"
    ai_config = {
        "provider": ai_provider,
        "openai_api_key": config.openai_api_key or "",
        "groq_api_key": config.groq_api_key or "",
        "google_api_key": config.google_api_key or "",
        "ollama_host": config.ollama_host or "http://localhost:11434",
        "openai_model": config.openai_model or "gpt-4o-mini",
        "groq_model": config.groq_model or "llama-3.1-8b-instant",
        "gemini_model": config.gemini_model or "gemini-2.0-flash",
        "ollama_model": config.ollama_model or "llama2",
    }

    cycle_start = datetime.utcnow().isoformat()
    user_logger.info("========== INICIO DE CICLO #%d | %s ==========", cycle_count, cycle_start)

    # Balance al inicio
    balance_start = await asyncio.to_thread(_fetch_balance, exchange, pairs, user_logger)
    _log_balance_full(user_logger, balance_start, "Balance al inicio del ciclo")
    balance_summary_start = _format_balance_one_line(balance_start)

    signals_for_telegram = []
    orders_this_cycle = []
    errors_this_cycle = []

    for pair in pairs:
        # Delay entre pares
        await asyncio.sleep(pair_delay)

        user_logger.info("---------- Par: %s ----------", pair)

        # 1. Obtener velas OHLCV
        df = await asyncio.to_thread(_fetch_ohlcv, exchange, pair, timeframe, candle_count, user_logger)
        if df is None or df.empty:
            user_logger.warning("Sin datos OHLCV para %s, se omite.", pair)
            errors_this_cycle.append(f"{pair}: sin datos OHLCV")
            continue

        last = df.iloc[-1]
        user_logger.info(
            "OHLCV: %d velas | Última: O=%s H=%s L=%s C=%s V=%s",
            len(df), last.get("open"), last.get("high"), last.get("low"), last.get("close"), last.get("volume", 0)
        )

        # 2. Indicadores técnicos
        indicators = compute_all_indicators(df)
        candles_text = format_candles_for_prompt(df, prompt_candles)
        context_summary = format_context_summary(df, last_n=min(30, len(df)))
        user_logger.info(
            "Indicadores: RSI=%s MACD_line=%s MACD_signal=%s MACD_hist=%s SMA50=%s SMA200=%s BB_upper=%s BB_lower=%s volume=%s volume_avg=%s",
            indicators.get("rsi"), indicators.get("macd_line"), indicators.get("macd_signal"),
            indicators.get("macd_histogram"), indicators.get("sma50"), indicators.get("sma200"),
            indicators.get("bb_upper"), indicators.get("bb_lower"), indicators.get("volume"), indicators.get("volume_avg")
        )

        # 3. Precio actual
        current_price = await asyncio.to_thread(_fetch_ticker_price, exchange, pair, user_logger)
        if current_price is not None:
            user_logger.info("Precio actual (ticker) %s: %s", pair, current_price)

        # Balance hint para la IA
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

        # 4. Señal de la IA — configurar variables de entorno temporalmente
        old_env = {}
        env_overrides = {
            "AI_PROVIDER": ai_config["provider"],
            "OPENAI_API_KEY": ai_config["openai_api_key"],
            "GROQ_API_KEY": ai_config["groq_api_key"],
            "GOOGLE_API_KEY": ai_config["google_api_key"],
            "OLLAMA_HOST": ai_config["ollama_host"],
            "OPENAI_MODEL": ai_config["openai_model"],
            "GROQ_MODEL": ai_config["groq_model"],
            "GEMINI_MODEL": ai_config["gemini_model"],
            "OLLAMA_MODEL": ai_config["ollama_model"],
        }
        for k, v in env_overrides.items():
            old_env[k] = os.environ.get(k)
            os.environ[k] = v

        # Recargar config para que ai_advisor use los valores correctos
        import config as cfg_module
        import ai_advisor as ai_module
        importlib.reload(cfg_module)
        importlib.reload(ai_module)

        signal_data = ai_module.get_ai_signal(
            pair, timeframe, candles_text, indicators, prompt_candles,
            context_summary, current_price=current_price,
            balance_hint=balance_hint, stop_loss_percent=stop_loss,
        )

        # Restaurar variables de entorno
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

        if signal_data is None:
            user_logger.warning("No se pudo obtener señal IA para %s.", pair)
            errors_this_cycle.append(f"{pair}: sin señal IA")
            continue

        user_logger.info(
            "Señal IA: señal=%s confianza=%s razón=%s",
            SIGNAL_LABEL_ES.get(signal_data["signal"], signal_data["signal"]),
            signal_data["confidence"], signal_data["reason"]
        )

        # Datos para Telegram
        signals_for_telegram.append({
            "pair": pair, "signal": signal_data["signal"],
            "confidence": signal_data["confidence"], "reason": signal_data["reason"],
            "price": current_price,
            "last_close": float(last.get("close")) if last.get("close") is not None else None,
            "volume": float(last.get("volume", 0)),
            "rsi": indicators.get("rsi"), "macd_histogram": indicators.get("macd_histogram"),
            "sma50": indicators.get("sma50"), "sma200": indicators.get("sma200"),
        })

        # 5. ¿Ejecutar orden?
        if signal_data["signal"] not in ("buy", "sell"):
            user_logger.info("Sin orden: señal es %s (solo comprar/vender ejecutan).", SIGNAL_LABEL_ES.get(signal_data["signal"], signal_data["signal"]))
            continue
        if signal_data["confidence"] < confidence_threshold:
            user_logger.info("Sin orden: confianza %.2f < umbral %.2f para %s.", signal_data["confidence"], confidence_threshold, pair)
            continue

        amount = get_order_amount_for_pair(pair, order_amounts)
        if amount <= 0:
            user_logger.warning("Monto no configurado para %s.", pair)
            continue

        # Verificar saldo antes de ejecutar la orden
        balance_now = await asyncio.to_thread(_fetch_balance, exchange, pairs, user_logger)

        if signal_data["signal"] == "buy":
            # Para compra: verificar que hay suficiente quote currency (ej. USDT)
            free_quote_now = 0.0
            if balance_now and quote_currency in balance_now:
                free_quote_now = float(balance_now[quote_currency].get("free", 0) or 0)
            cost_estimate = amount * current_price if current_price else 0
            if cost_estimate > 0 and free_quote_now < cost_estimate:
                user_logger.warning(
                    "Saldo insuficiente de %s para comprar %s: tienes %.4f, se requiere ~%.4f. Se omite la orden.",
                    quote_currency, pair, free_quote_now, cost_estimate
                )
                errors_this_cycle.append(f"{pair}: saldo insuficiente de {quote_currency} para comprar (~{cost_estimate:.4f} necesarios)")
                continue

        if signal_data["signal"] == "sell":
            # Para venta: verificar que hay suficiente base currency (ej. SOL)
            free_base_now = 0.0
            if balance_now and base_currency in balance_now:
                free_base_now = float(balance_now[base_currency].get("free", 0) or 0)
            if free_base_now < amount:
                user_logger.warning(
                    "Saldo insuficiente de %s para vender: tienes %s, se requiere %s. Se omite la orden.",
                    base_currency, free_base_now, amount
                )
                errors_this_cycle.append(f"{pair}: saldo insuficiente de {base_currency} para vender")
                continue

        user_logger.info("Ejecutando orden: %s %s cantidad=%s (market)", signal_data["signal"], pair, amount)
        order = await asyncio.to_thread(_create_order, exchange, pair, signal_data["signal"], amount, "market", test_mode, user_logger)

        if order:
            price_exec = order.get("average") or order.get("price")
            order_id = order.get("id", "N/A")
            filled = order.get("filled", amount)
            simulated = test_mode or order.get("info", {}).get("simulated", False)
            user_logger.info(
                ">>> ORDEN EJECUTADA: %s %s | cantidad=%s | precio=%s | id_orden=%s | simulada=%s",
                SIGNAL_LABEL_ES.get(signal_data["signal"], signal_data["signal"]).upper(),
                pair, filled, price_exec, order_id, simulated
            )
            orders_this_cycle.append({
                "pair": pair, "side": signal_data["signal"], "amount": filled,
                "price": price_exec, "order_id": order_id, "simulated": simulated,
            })
            # Telegram para la orden
            balance_after = await asyncio.to_thread(_fetch_balance, exchange, pairs, user_logger)
            await asyncio.to_thread(_send_telegram_for_user, user, (
                f"📌 {'[SIMULADA] ' if simulated else ''}<b>Orden ejecutada</b>\n"
                f"Par: {pair} | Lado: {SIGNAL_LABEL_ES.get(signal_data['signal'], signal_data['signal']).upper()}\n"
                f"Cantidad: {filled} @ {price_exec}\n"
                f"ID: {order_id}\n💰 Balance: {_format_balance_one_line(balance_after)}"
            ))
            # Email de notificación del trade
            await asyncio.to_thread(
                send_trade_email,
                to_email=user.email,
                pair=pair,
                side=signal_data["signal"],
                amount=filled,
                price=float(price_exec) if price_exec else 0.0,
                order_id=order_id,
                simulated=simulated,
                indicators=indicators,
                balance_after=_format_balance_one_line(balance_after),
                confidence=signal_data.get("confidence", 0.0),
                reason=signal_data.get("reason", ""),
            )
        else:
            errors_this_cycle.append(f"{pair}: fallo al crear orden")

    # Balance al final
    balance_end = await asyncio.to_thread(_fetch_balance, exchange, pairs, user_logger)
    _log_balance_full(user_logger, balance_end, "Balance al final del ciclo")
    balance_summary_end = _format_balance_one_line(balance_end)

    user_logger.info(
        "========== FIN DE CICLO | Órdenes ejecutadas: %d | Señales: %d ==========",
        len(orders_this_cycle), len(signals_for_telegram)
    )
    for o in orders_this_cycle:
        user_logger.info("  Orden: %s %s cantidad=%s precio=%s id=%s",
            SIGNAL_LABEL_ES.get(o["side"], o["side"]), o["pair"], o["amount"], o["price"], o["order_id"])
    if errors_this_cycle:
        for err in errors_this_cycle:
            user_logger.warning("  Error en ciclo: %s", err)

    # Telegram: señales + resumen del ciclo
    if signals_for_telegram:
        lines = ["📊 <b>Señales del ciclo</b>"]
        for s in signals_for_telegram:
            sig_es = SIGNAL_LABEL_ES.get(s["signal"], s["signal"])
            price_s = f" | Precio: {s['price']}" if s.get("price") else ""
            rsi_s = f" RSI: {s['rsi']:.1f}" if s.get("rsi") is not None else ""
            lines.append(f"• <b>{s['pair']}</b>: {sig_es.upper()} (confianza: {s['confidence']:.2f}){price_s}{rsi_s}\n  → {s.get('reason','')[:180]}")
        await asyncio.to_thread(_send_telegram_for_user, user, "\n".join(lines))

    # Resumen del ciclo
    summary_msg = (
        f"📋 <b>Resumen del ciclo</b>\n"
        f"💰 Balance inicio: {balance_summary_start}\n"
        f"💰 Balance final: {balance_summary_end}\n"
        f"📊 Señales: {len(signals_for_telegram)} | 📌 Órdenes: {len(orders_this_cycle)}"
    )
    if errors_this_cycle:
        summary_msg += "\n⚠️ Errores: " + "; ".join(errors_this_cycle[:5])
    await asyncio.to_thread(_send_telegram_for_user, user, summary_msg)

    return len(orders_this_cycle), len(signals_for_telegram)


# ─── BotManager ───

class BotManager:
    def __init__(self):
        self.active_bots: Dict[int, asyncio.Task] = {}

    async def start_bot(self, user_id: int):
        if user_id in self.active_bots:
            logger.warning(f"Intento de iniciar bot ya activo para usuario {user_id}")
            return False
        logger.info(f"Iniciando bot para usuario {user_id}...")
        task = asyncio.create_task(self._run_bot_loop(user_id))
        self.active_bots[user_id] = task
        return True

    async def stop_bot(self, user_id: int):
        if user_id in self.active_bots:
            logger.info(f"Deteniendo bot para usuario {user_id}...")
            self.active_bots[user_id].cancel()
            del self.active_bots[user_id]
            return True
        logger.warning(f"Intento de detener bot no activo para usuario {user_id}")
        return False

    async def _run_bot_loop(self, user_id: int):
        """Bucle principal del bot para un usuario. Protegido contra errores silenciosos."""
        try:
            await self._run_bot_loop_inner(user_id)
        except asyncio.CancelledError:
            logger.info(f"Bot para usuario {user_id} cancelado.")
            raise  # Re-raise para que asyncio lo maneje correctamente
        except Exception as e:
            logger.exception(f"ERROR FATAL en bot de usuario {user_id}: {e}")

    async def _run_bot_loop_inner(self, user_id: int):
        # Setup inicial
        db = SessionLocal()
        user = db.query(User).filter(User.id == user_id).first()
        config = db.query(GlobalConfig).first()
        db.close()

        if not user or not config:
            logger.error(f"Configuración no encontrada para usuario {user_id}. Abortando.")
            return

        username = user.username
        user_logger = get_user_bot_logger(user_id, username)

        # Parsear config
        pairs = _parse_pairs(config.pairs or "SOL/USDT,ETH/USDT")
        order_amounts = _parse_order_amounts(config.order_amount_per_pair or "")
        test_mode = config.test_mode if config.test_mode is not None else True
        interval = config.interval or 300

        # Crear exchange con credenciales del usuario
        try:
            exchange = _create_exchange(user.coinex_api_key, user.coinex_secret, test_mode)
            user_logger.info("Cliente CoinEx creado (modo test=%s)", test_mode)
        except Exception as e:
            user_logger.exception("No se pudo crear cliente CoinEx: %s", e)
            await asyncio.to_thread(_send_telegram_for_user, user, f"🚨 <b>Error crítico</b>\nNo se pudo conectar a CoinEx: {str(e)[:200]}")
            return

        user_logger.info(
            "Iniciando bot. Pares: %s | Timeframe: %s | Test mode: %s | Intervalo: %ss | Delay entre pares: %ss",
            pairs, config.timeframe, test_mode, interval, config.pair_delay
        )

        # Balance al arranque
        balance_at_start = await asyncio.to_thread(_fetch_balance, exchange, pairs, user_logger)
        _log_balance_full(user_logger, balance_at_start, "Balance al arranque")

        # Telegram de arranque
        try:
            await asyncio.to_thread(_send_telegram_for_user, user, (
                f"🤖 <b>Bot de trading iniciado</b>\n"
                f"Modo: <b>{'SIMULACIÓN (test)' if test_mode else 'REAL'}</b>\n"
                f"Pares: {', '.join(pairs)}\n"
                f"Timeframe: {config.timeframe}\n"
                f"💰 <b>Balance actual:</b> {_format_balance_one_line(balance_at_start)}\n"
                f"⏱ Ciclo cada: {interval}s"
            ))
        except Exception as e:
            user_logger.warning("Error al enviar Telegram de arranque: %s", e)

        user_logger.info("Entrando al bucle principal de trading...")

        cycle_count = 0
        try:
            while True:
                cycle_count += 1

                # Recargar config desde la DB en cada ciclo
                db = SessionLocal()
                user = db.query(User).filter(User.id == user_id).first()
                config = db.query(GlobalConfig).first()
                db.close()

                if not user or not config:
                    user_logger.error("Configuración no encontrada. Cerrando bucle.")
                    break

                # Actualizar parámetros dinámicos
                pairs = _parse_pairs(config.pairs or "SOL/USDT,ETH/USDT")
                order_amounts = _parse_order_amounts(config.order_amount_per_pair or "")
                interval = config.interval or 300

                try:
                    await _run_trading_cycle(
                        exchange, user, config, pairs, order_amounts, user_logger, cycle_count
                    )
                except Exception as e:
                    user_logger.exception("Error en ciclo de trading #%d: %s", cycle_count, e)
                    await asyncio.to_thread(_send_telegram_for_user, user, f"🚨 Error en ciclo #{cycle_count}: {str(e)[:200]}")
                    await asyncio.sleep(60)
                    continue

                user_logger.info("Próximo ciclo en %s segundos.", interval)
                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            user_logger.info(
                "========== BOT DETENIDO para %s (ciclos completados: %d) ==========",
                username, cycle_count
            )
            await asyncio.to_thread(_send_telegram_for_user, user, f"⏹ <b>Bot detenido</b>\nCiclos completados: {cycle_count}")
        except Exception as e:
            user_logger.exception("Error crítico en bucle de bot: %s", e)


bot_manager = BotManager()
