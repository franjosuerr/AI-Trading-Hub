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
import requests
from typing import Dict, Optional
from datetime import datetime, timedelta
from collections import defaultdict

import ccxt
import pandas as pd

# Módulos de trading originales (raíz del proyecto)
from indicators import compute_all_indicators
from utils import (
    SIGNAL_LABEL_ES,
    round_to_precision,
)
from email_notifier import send_trade_email

# Backend
from backend.database import SessionLocal
from backend.models.models import User, GlobalConfig, Trade
from backend.logger_config import get_logger, get_user_bot_logger

logger = get_logger("bot_manager")

# --- Historial de señales por (user_id, pair) para contexto de la IA ---
_signal_history: Dict[tuple, list] = defaultdict(list)
MAX_SIGNAL_HISTORY = 10

# --- Balance virtual para modo test (persiste durante la sesión del bot) ---
_virtual_balances: Dict[int, Dict[str, float]] = {}


def _init_virtual_balance(user_id: int, exchange_balance: dict):
    """Inicializa el balance virtual a partir del balance real del exchange (para test mode)."""
    vb = {}
    if exchange_balance:
        for cur, data in exchange_balance.items():
            if isinstance(data, dict):
                vb[cur] = float(data.get("total", 0) or 0)
    _virtual_balances[user_id] = vb
    logger.info("Balance virtual inicializado para usuario %d: %s", user_id,
                ", ".join(f"{k}={v:.4f}" for k, v in vb.items() if v > 0))


def _update_virtual_balance(user_id: int, side: str, pair: str, amount: float, price: float):
    """Actualiza el balance virtual después de un trade simulado."""
    if user_id not in _virtual_balances:
        return
    base = pair.split("/")[0] if "/" in pair else pair
    quote = pair.split("/")[1] if "/" in pair else "USDT"
    vb = _virtual_balances[user_id]
    if side == "buy":
        cost = amount * price
        vb[quote] = vb.get(quote, 0) - cost
        vb[base] = vb.get(base, 0) + amount
    elif side == "sell":
        revenue = amount * price
        vb[quote] = vb.get(quote, 0) + revenue
        vb[base] = max(0.0, vb.get(base, 0) - amount)


def _get_effective_balance(user_id: int, exchange_balance: dict, test_mode: bool) -> dict:
    """Retorna balance virtual en test mode, balance real en producción."""
    if not test_mode or user_id not in _virtual_balances:
        return exchange_balance or {}
    vb = _virtual_balances[user_id]
    result = {}
    for cur, amount in vb.items():
        val = max(0.0, amount)
        if val > 0.000001:
            result[cur] = {"free": val, "used": 0.0, "total": val}
    return result if result else exchange_balance or {}


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


def _get_portfolio_for_pair(user_id, pair, exchange_balance, current_price, log):
    """Obtiene contexto de portafolio para un par: holdings reales + historial de trades + P&L."""
    base = pair.split("/")[0] if "/" in pair else pair
    quote = pair.split("/")[1] if "/" in pair else "USDT"

    # Holdings reales del exchange
    holdings = 0.0
    if exchange_balance and base in exchange_balance and isinstance(exchange_balance[base], dict):
        holdings = float(exchange_balance[base].get("free", 0) or 0)

    free_quote = 0.0
    if exchange_balance and quote in exchange_balance and isinstance(exchange_balance[quote], dict):
        free_quote = float(exchange_balance[quote].get("free", 0) or 0)

    # Historial de trades para calcular costo promedio (método de posición neta)
    # Recorre trades cronológicamente y simula la posición acumulada
    net_position = 0.0  # unidades base acumuladas
    net_cost = 0.0      # costo total acumulado en quote
    total_buys = 0
    total_sells = 0

    try:
        db = SessionLocal()
        try:
            trades = db.query(Trade).filter(
                Trade.user_id == user_id,
                Trade.pair == pair
            ).order_by(Trade.timestamp.asc()).all()  # cronológico

            # Materializar datos antes de cerrar sesión
            trades_data = [(t.side, t.amount, t.price) for t in trades]
        finally:
            db.close()

        for t_side, t_amount, t_price in trades_data:
            if t_side == "buy":
                net_position += t_amount
                net_cost += t_amount * t_price
                total_buys += 1
            elif t_side == "sell":
                if net_position > 0:
                    sell_ratio = min(t_amount / net_position, 1.0)
                    net_cost *= (1.0 - sell_ratio)
                    net_position = max(0.0, net_position - t_amount)
                total_sells += 1
    except Exception as e:
        log.warning("Error al obtener historial de trades para %s: %s", pair, str(e)[:100])

    # Precio promedio de compra basado en posición neta actual
    avg_entry_price = net_cost / net_position if net_position > 0 else 0.0

    # Calcular P&L
    invested_value = holdings * avg_entry_price if holdings > 0 and avg_entry_price > 0 else 0.0
    current_value = holdings * current_price if holdings > 0 and current_price else 0.0
    pnl_usdt = current_value - invested_value if invested_value > 0 else 0.0
    pnl_pct = ((current_price - avg_entry_price) / avg_entry_price * 100) if avg_entry_price > 0 and current_price else 0.0

    portfolio = {
        "base": base,
        "quote": quote,
        "holdings": holdings,
        "free_quote": free_quote,
        "avg_entry_price": avg_entry_price,
        "invested_value": invested_value,
        "current_value": current_value,
        "pnl_usdt": pnl_usdt,
        "pnl_pct": pnl_pct,
        "total_trades_buy": total_buys,
        "total_trades_sell": total_sells,
    }

    log.info(
        "Portafolio %s: holdings=%.8f, precio_promedio=%.6f, invertido=%.4f, valor_actual=%.4f, P&L=%.4f (%.2f%%), USDT_libre=%.4f",
        pair, holdings, avg_entry_price, invested_value, current_value, pnl_usdt, pnl_pct, free_quote
    )
    return portfolio


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


# ─── Utilidad: cooldown post-reinicio ───

def _check_recent_trades_cooldown(user_id: int, pair: str, cooldown_minutes: int, log) -> bool:
    """Retorna True si hay compras recientes dentro del cooldown y NO se debe operar."""
    try:
        db = SessionLocal()
        try:
            cutoff = datetime.utcnow() - timedelta(minutes=cooldown_minutes)
            recent = db.query(Trade).filter(
                Trade.user_id == user_id,
                Trade.pair == pair,
                Trade.side == 'buy',
                Trade.timestamp >= cutoff,
            ).count()
        finally:
            db.close()
        if recent > 0:
            log.info(
                "Cooldown anti-spam activo para %s: %d compra(s) en los últimos %d minutos. Se omite.",
                pair, recent, cooldown_minutes
            )
            return True
        return False
    except Exception as e:
        log.warning("Error al verificar cooldown para %s: %s", pair, str(e)[:100])
        return False

def _check_stop_loss_cooldown(user_id: int, pair: str, cooldown_minutes: int, log) -> bool:
    """Retorna True si hubo un trade de VENTA reciente con pérdida (Stop-Loss)."""
    try:
        db = SessionLocal()
        try:
            cutoff = datetime.utcnow() - timedelta(minutes=cooldown_minutes)
            recent_sl = db.query(Trade).filter(
                Trade.user_id == user_id,
                Trade.pair == pair,
                Trade.side == 'sell',
                Trade.profit < 0,
                Trade.timestamp >= cutoff,
            ).first()
        finally:
            db.close()
        if recent_sl:
            log.info(
                "Cooldown activo (%d min) por STOP-LOSS previo en %s. Última venta con pérdida: %s.",
                cooldown_minutes, pair, recent_sl.timestamp
            )
            return True
        return False
    except Exception as e:
        log.warning("Error al verificar cooldown SL para %s: %s", pair, str(e)[:100])
        return False


def _get_total_invested_percentage(user_id: int, pairs: list, exchange_balance: dict, exchange, log) -> float:
    """Calcula el porcentaje del portafolio total que ya está invertido (no en USDT)."""
    try:
        if not exchange_balance:
            return 0.0

        # USDT libre
        free_usdt = 0.0
        if "USDT" in exchange_balance and isinstance(exchange_balance["USDT"], dict):
            free_usdt = float(exchange_balance["USDT"].get("total", 0) or 0)

        # Valor de las posiciones en USDT
        invested_value = 0.0
        for pair in pairs:
            base = pair.split("/")[0] if "/" in pair else pair
            if base in exchange_balance and isinstance(exchange_balance[base], dict):
                base_amount = float(exchange_balance[base].get("total", 0) or 0)
                if base_amount > 0:
                    try:
                        ticker = exchange.fetch_ticker(pair)
                        price = float(ticker.get("last", 0))
                        invested_value += base_amount * price
                    except Exception:
                        pass

        total_value = free_usdt + invested_value
        if total_value <= 0:
            return 0.0
        pct = (invested_value / total_value) * 100
        log.info(
            "Portafolio total: %.4f USDT libre + %.4f USDT invertido = %.4f USDT total (%.1f%% invertido)",
            free_usdt, invested_value, total_value, pct
        )
        return pct
    except Exception as e:
        log.warning("Error al calcular % invertido: %s", str(e)[:100])
        return 0.0


# ─── Ciclo de trading completo (por usuario) ───

async def _run_trading_cycle(exchange, user, config, pairs, user_logger, cycle_count):
    """Ejecuta un ciclo completo de trading: Balance → Portafolio → IA (decide monto) → Órdenes → Telegram."""

    test_mode = config.test_mode if config.test_mode is not None else True
    timeframe = config.timeframe or "15m"
    candle_count = config.candle_count or 210
    stop_loss = config.stop_loss_percent or 2.0
    pair_delay = config.pair_delay or 2
    max_trades = config.max_trades_per_day or 5
    
    ema_fast_len = config.ema_fast or 7
    ema_slow_len = config.ema_slow or 30
    adx_period = config.adx_period or 14
    adx_thresh = config.adx_threshold or 25
    invest_pct = config.invest_percentage or 75.0

    cycle_start = datetime.utcnow().isoformat()
    user_logger.info("========== INICIO DE CICLO #%d | %s ==========", cycle_count, cycle_start)

    # Balance al inicio
    balance_start = await asyncio.to_thread(_fetch_balance, exchange, pairs, user_logger)
    _log_balance_full(user_logger, balance_start, "Balance al inicio del ciclo")
    balance_summary_start = _format_balance_one_line(balance_start)

    # Balance efectivo (virtual en test mode, real en producción)
    balance_effective = _get_effective_balance(user.id, balance_start, test_mode)
    if test_mode:
        user_logger.info("Balance virtual: %s", _format_balance_one_line(balance_effective))

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
        indicators_dict = compute_all_indicators(df)
        
        # Calcular los específicos para esta estrategia y añadirlos en df para vectorizarlos
        from indicators import compute_ema, compute_adx
        ema_fast = compute_ema(df["close"], ema_fast_len)
        ema_slow = compute_ema(df["close"], ema_slow_len)
        adx = compute_adx(df["high"], df["low"], df["close"], adx_period)
        
        user_logger.info(
            "Indicadores Base: RSI=%s MACD=%s SMA200=%s",
            indicators_dict.get("rsi"), indicators_dict.get("macd_line"), indicators_dict.get("sma200")
        )

        # 3. Precio actual
        current_price = await asyncio.to_thread(_fetch_ticker_price, exchange, pair, user_logger)
        if current_price is not None:
            user_logger.info("Precio actual (ticker) %s: %s", pair, current_price)

        # Contexto de portafolio para la IA (holdings, costo, P&L)
        base_currency = pair.split("/")[0] if "/" in pair else pair
        quote_currency = pair.split("/")[1] if "/" in pair else "USDT"
        portfolio_ctx = await asyncio.to_thread(
            _get_portfolio_for_pair, user.id, pair, balance_effective, current_price, user_logger
        )

        # 4. Lógica de Estrategia EMA Crossover
        last_ema_fast = float(ema_fast.iloc[-1])
        prev_ema_fast = float(ema_fast.iloc[-2])
        last_ema_slow = float(ema_slow.iloc[-1])
        prev_ema_slow = float(ema_slow.iloc[-2])
        last_adx = float(adx.iloc[-1])
        
        last_gap = last_ema_fast - last_ema_slow
        prev_gap = prev_ema_fast - prev_ema_slow
        
        holdings = portfolio_ctx.get("holdings", 0.0)
        has_open_position = (holdings * current_price) > 5.0
        
        signal = "hold"
        reason = "Esperando señal..."
        amount_to_invest = 0.0
        
        if not has_open_position:
            # Lógica Condición de COMPRA: cruce hacia arriba
            if last_ema_fast > last_ema_slow and prev_ema_fast <= prev_ema_slow:
                if last_adx > adx_thresh:
                    signal = "buy"
                    reason = f"Cruce EMA{ema_fast_len} > EMA{ema_slow_len} con ADX={last_adx:.1f} > {adx_thresh}"
                    free_quote_now = float(balance_effective.get(quote_currency, {}).get("free", 0.0) or 0)
                    amount_to_invest = free_quote_now * (invest_pct / 100.0)
                else:
                    reason = f"Cruce EMA{ema_fast_len} > EMA{ema_slow_len} ignorado por tendencia débil (ADX={last_adx:.1f} <= {adx_thresh})"
        else:
            # Lógica Condición de VENTA
            avg_price = portfolio_ctx.get("avg_price", 0.0)
            pnl_percent = portfolio_ctx.get("pnl_percent", 0.0)
            
            if last_gap < prev_gap and current_price > avg_price:
                signal = "sell"
                reason = f"Gap reduciéndose ({last_gap:.4f} < {prev_gap:.4f}) y Profit del {pnl_percent:.2f}% asegurado"
            elif pnl_percent <= -stop_loss:
                signal = "sell"
                reason = f"Stop Loss alcanzado: {pnl_percent:.2f}% <= -{stop_loss}%"
            else:
                reason = f"Hold Posición: Gap {last_gap:.4f} (prev: {prev_gap:.4f}), P&L: {pnl_percent:.2f}%"

        signal_data = {
            "signal": signal,
            "confidence": 1.0 if signal != "hold" else 0.0,
            "reason": reason,
            "amount_usdt": amount_to_invest,
            "sell_percentage": 100.0
        }

        # Guardar señal en historial para contexto futuro
        _signal_history[(user.id, pair)].append({
            "signal": signal_data["signal"],
            "confidence": signal_data["confidence"],
            "reason": signal_data.get("reason", "")[:100],
            "price": current_price,
        })
        if len(_signal_history[(user.id, pair)]) > MAX_SIGNAL_HISTORY:
            _signal_history[(user.id, pair)] = _signal_history[(user.id, pair)][-MAX_SIGNAL_HISTORY:]

        # Log de señal
        user_logger.info(
            "Señal Estrategia: señal=%s confianza=%s razón=%s",
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
            "ema_fast": last_ema_fast, "ema_slow": last_ema_slow, "adx": last_adx,
        })

        # 5. ¿Ejecutar orden?
        if signal_data["signal"] not in ("buy", "sell"):
            user_logger.info("Sin orden: señal es %s (solo comprar/vender ejecutan).", SIGNAL_LABEL_ES.get(signal_data["signal"], signal_data["signal"]))
            continue
        if signal_data["confidence"] < 0.7:
            # Para la estrategia técnica, la confianza es 1.0 si hay señal, o 0.0 si es hold.
            # Por lo tanto, si es menor a 0.7 (es 0.0), no hacemos nada
            continue

        # Verificar límite de trades diarios por par (solo bloquea COMPRAS, ventas siempre permitidas)
        try:
            db = SessionLocal()
            try:
                today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                trades_today = db.query(Trade).filter(
                    Trade.user_id == user.id,
                    Trade.pair == pair,
                    Trade.timestamp >= today_start,
                ).count()
            finally:
                db.close()
            if trades_today >= max_trades and signal_data["signal"] == "buy":
                user_logger.info(
                    "Límite diario de COMPRAS alcanzado para %s: %d/%d trades hoy. Ventas aún permitidas.",
                    pair, trades_today, max_trades
                )
                continue
        except Exception as e:
            user_logger.warning("Error al verificar límite diario: %s", str(e)[:100])

        # COOLDOWN DE COMPRAS y STOP-LOSS
        # Cooldown anti-spam (min 15 min)
        anti_spam_minutes = max(int((config.interval or 300) / 60) * 3, 15)
        # Cooldown real de Stop Loss (usamos la config global, ej. 120 min)
        sl_cooldown_minutes = config.cooldown_minutes or 120
        
        if signal_data["signal"] == "buy":
            # 1. Verificar Anti-Spam
            if await asyncio.to_thread(_check_recent_trades_cooldown, user.id, pair, anti_spam_minutes, user_logger):
                continue
                
            # 2. Verificar Cooldown de Stop Loss
            if await asyncio.to_thread(_check_stop_loss_cooldown, user.id, pair, sl_cooldown_minutes, user_logger):
                continue

            # LÍMITE DE INVERSIÓN TOTAL: No exceder la exposición máxima
            max_exposure = config.max_exposure_percent or 100.0  # Por defecto 100% para la nueva estrategia
            invested_pct = await asyncio.to_thread(
                _get_total_invested_percentage, user.id, pairs, balance_effective, exchange, user_logger
            )
            if invested_pct >= max_exposure:
                user_logger.warning(
                    "Portafolio ya %.1f%% invertido (límite %.1f%%). No se admiten nuevas compras.",
                    invested_pct, max_exposure
                )
                errors_this_cycle.append(f"{pair}: portafolio >{max_exposure}% invertido")
                continue

        # Calcular monto dinámico decidido por la IA
        amount = 0.0
        balance_now = await asyncio.to_thread(_fetch_balance, exchange, pairs, user_logger)
        balance_now_effective = _get_effective_balance(user.id, balance_now, test_mode)

        if signal_data["signal"] == "buy":
            amount_usdt = signal_data.get("amount_usdt", 0)
            if amount_usdt <= 0 or not current_price or current_price <= 0:
                user_logger.warning("La estrategia no especificó monto válido para comprar %s (amount_usdt=%.4f).", pair, amount_usdt)
                errors_this_cycle.append(f"{pair}: monto inválido para compra")
                continue

            # Verificar saldo (virtual en test mode, real en producción)
            free_quote_now = 0.0
            if balance_now_effective and quote_currency in balance_now_effective:
                free_quote_now = float(balance_now_effective[quote_currency].get("free", 0) or 0)

            # SEGURIDAD: mínimo 5 USDT de balance para operar (como dice el prompt)
            if free_quote_now < 5.0:
                user_logger.warning(
                    "Balance %s insuficiente: %.4f < 5.0 mínimo. No se compra %s.",
                    quote_currency, free_quote_now, pair
                )
                errors_this_cycle.append(f"{pair}: balance {quote_currency} < 5")
                continue

            # Comprobar límite de balance
            if amount_usdt > free_quote_now:
                user_logger.warning(
                    "Monto calculado %.4f mayor a saldo libre %.4f. Ajustando límite de inversión.",
                    amount_usdt, free_quote_now
                )
                amount_usdt = free_quote_now

            # Limitar al saldo disponible real (segunda capa de seguridad)
            if amount_usdt > free_quote_now * 0.95:
                user_logger.warning(
                    "Monto %.4f excede 95%% del saldo. Ajustando a %.4f %s.",
                    amount_usdt, free_quote_now * 0.95, quote_currency
                )
                amount_usdt = free_quote_now * 0.95  # dejar 5% de margen para fees

            if amount_usdt < 1.0:
                user_logger.warning("Monto insuficiente para comprar %s: %.4f %s. Mínimo ~1 USDT.", pair, amount_usdt, quote_currency)
                errors_this_cycle.append(f"{pair}: saldo insuficiente ({amount_usdt:.4f} {quote_currency})")
                continue

            # Convertir USDT a moneda base
            amount = amount_usdt / current_price
            user_logger.info(
                "Compra validada: %.4f %s en %s → %.8f %s al precio %.6f (%.1f%% del balance)",
                amount_usdt, quote_currency, pair, amount, base_currency, current_price,
                (amount_usdt / free_quote_now * 100) if free_quote_now > 0 else 0,
            )

        elif signal_data["signal"] == "sell":
            # Decidimos qué porcentaje de la posición vender
            sell_pct = signal_data.get("sell_percentage", 100)
            free_base_now = 0.0
            if balance_now_effective and base_currency in balance_now_effective:
                free_base_now = float(balance_now_effective[base_currency].get("free", 0) or 0)

            if free_base_now <= 0:
                user_logger.warning("No tienes %s para vender (saldo=0).", base_currency)
                errors_this_cycle.append(f"{pair}: sin {base_currency} para vender")
                continue

            amount = free_base_now * (sell_pct / 100.0)
            if amount <= 0:
                user_logger.warning("Monto de venta calculado es 0 para %s.", pair)
                continue

            # Verificar que el valor de la venta sea significativo (>= 1 USDT)
            sell_value_usdt = amount * current_price if current_price else 0
            if sell_value_usdt < 1.0:
                user_logger.warning(
                    "Venta de %.8f %s vale solo %.4f USDT (< 1 USDT mínimo). Se omite %s.",
                    amount, base_currency, sell_value_usdt, pair
                )
                errors_this_cycle.append(f"{pair}: venta < 1 USDT")
                continue

            user_logger.info(
                "Venta validada: %.1f%% de %s → %.8f %s (de %.8f disponibles, valor ~%.2f USDT)",
                sell_pct, pair, amount, base_currency, free_base_now, sell_value_usdt,
            )

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

            # Guardar trade en la DB para tracking de portafolio
            trade_amount = float(filled) if filled else float(amount)
            trade_price = float(price_exec) if price_exec else (current_price or 0.0)
            try:
                db = SessionLocal()
                try:
                    real_pnl = portfolio_ctx.get("pnl_usdt", 0.0) if signal_data["signal"] == "sell" else 0.0
                    new_trade = Trade(
                        user_id=user.id,
                        pair=pair,
                        side=signal_data["signal"],
                        amount=trade_amount,
                        price=trade_price,
                        order_id=str(order_id),
                        simulated=simulated,
                        profit=real_pnl,
                    )
                    db.add(new_trade)
                    db.commit()
                    user_logger.info("Trade guardado en DB: %s %s %.8f @ %.6f", signal_data["signal"], pair, trade_amount, trade_price)
                finally:
                    db.close()
            except Exception as e:
                user_logger.warning("Error al guardar trade en DB: %s", str(e)[:150])

            # Actualizar balance virtual (solo en test mode)
            if test_mode:
                _update_virtual_balance(user.id, signal_data["signal"], pair, trade_amount, trade_price)
                user_logger.info("Balance virtual actualizado: %s", _format_balance_one_line(
                    _get_effective_balance(user.id, balance_now, test_mode)
                ))

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
        try:
            user = db.query(User).filter(User.id == user_id).first()
            config = db.query(GlobalConfig).first()
            if not user or not config:
                logger.error(f"Configuración no encontrada para usuario {user_id}. Abortando.")
                return
            # Materializar datos antes de cerrar sesión
            username = user.username
            _user_api_key = user.coinex_api_key
            _user_secret = user.coinex_secret
        finally:
            db.close()
        user_logger = get_user_bot_logger(user_id, username)

        # Parsear config
        pairs = _parse_pairs(config.pairs or "SOL/USDT,ETH/USDT")
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

        # Inicializar balance virtual para modo test
        if test_mode:
            _init_virtual_balance(user_id, balance_at_start)

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
                try:
                    user = db.query(User).filter(User.id == user_id).first()
                    config = db.query(GlobalConfig).first()
                finally:
                    db.close()

                if not user or not config:
                    user_logger.error("Configuración no encontrada. Cerrando bucle.")
                    break

                # Actualizar parámetros dinámicos
                pairs = _parse_pairs(config.pairs or "SOL/USDT,ETH/USDT")
                interval = config.interval or 300

                try:
                    await _run_trading_cycle(
                        exchange, user, config, pairs, user_logger, cycle_count
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
