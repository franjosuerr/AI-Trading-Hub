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
    get_colombia_time
)
from email_notifier import send_trade_email

# Backend
from backend.database import SessionLocal
from backend.models.models import User, Trade
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

def _send_telegram_document_for_user(user, doc_path: str, tg_logger=None):
    """Envía un archivo por Telegram usando las credenciales del usuario."""
    log = tg_logger or logger
    token = getattr(user, 'telegram_bot_token', None)
    chat_id = getattr(user, 'telegram_chat_id', None)
    if not token or not chat_id:
        log.info("Telegram: sin credenciales para enviar documento.")
        return False
    if not os.path.exists(doc_path):
        log.warning("Telegram: el archivo %s no existe.", doc_path)
        return False
        
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    log.info("Telegram: enviando documento %s...", doc_path)
    try:
        # Extraemos el nombre base para el archivo enviado
        filename = os.path.basename(doc_path)
        with open(doc_path, 'rb') as f:
            r = requests.post(
                url, 
                data={"chat_id": chat_id, "caption": f"📄 Tu archivo de actividad diaria ({filename})"}, 
                files={"document": f},
                timeout=30
            )
        if r.status_code == 200:
            log.info("Telegram: documento enviado OK.")
            return True
        else:
            log.warning("Telegram: API devolvió código %s al enviar doc: %s", r.status_code, r.text[:100])
            return False
    except requests.exceptions.Timeout:
        log.warning("Telegram: timeout al enviar documento.")
        return False
    except requests.exceptions.ConnectionError:
        log.warning("Telegram: error de red al enviar documento.")
        return False
    except Exception as e:
        log.warning("Telegram: error inesperado al enviar documento: %s", str(e)[:150])
        return False


# ─── Utilidad: cooldown post-reinicio ───

def _check_recent_trades_cooldown(user_id: int, pair: str, cooldown_minutes: int, log) -> bool:
    """Retorna True si hay compras recientes dentro del cooldown y NO se debe operar."""
    try:
        db = SessionLocal()
        try:
            cutoff = get_colombia_time() - timedelta(minutes=cooldown_minutes)
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
            cutoff = get_colombia_time() - timedelta(minutes=cooldown_minutes)
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
    candle_count = config.candle_count or 350
    stop_loss = config.stop_loss_percent or 3.0
    pair_delay = config.pair_delay or 2
    max_trades = config.max_trades_per_day or 10
    
    ema_fast_len = config.ema_fast or 7
    ema_slow_len = config.ema_slow or 30
    adx_period = config.adx_period or 14
    adx_thresh = config.adx_threshold or 25
    invest_pct_trending = config.invest_percentage or 25.0
    invest_pct_ranging = getattr(config, "invest_percentage_ranging", 15.0) or 15.0
    
    # Pro params
    trailing_activation = getattr(config, "trailing_stop_activation", 2.5)
    trailing_distance = getattr(config, "trailing_stop_distance", 0.8)
    macro_tf = getattr(config, "macro_timeframe", "1h")
    risk_profile = getattr(config, "risk_profile", "conservador")
    use_vwap = getattr(config, "use_vwap_filter", False)
    use_daily = getattr(config, "use_daily_open_filter", False)

    cycle_start = get_colombia_time().isoformat()
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
        from indicators import compute_ema, compute_adx, compute_bollinger_bands, compute_rsi, compute_volume_avg, compute_macd, compute_vwap, compute_daily_open
        ema_fast = compute_ema(df["close"], ema_fast_len)
        ema_slow = compute_ema(df["close"], ema_slow_len)
        ema_50 = compute_ema(df["close"], 50)
        ema_200 = compute_ema(df["close"], 200)
        adx = compute_adx(df["high"], df["low"], df["close"], adx_period)
        bb_upper, bb_mid, bb_lower = compute_bollinger_bands(df["close"], 20, 2.0)
        rsi_series = compute_rsi(df["close"], 14)
        vol_avg_series = compute_volume_avg(df["volume"], 20)
        macd_line, macd_signal, _ = compute_macd(df["close"])
        vwap_series = compute_vwap(df)
        daily_open_series = compute_daily_open(df)

        last_rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else 50.0
        last_bb_upper = float(bb_upper.iloc[-1])
        last_bb_mid = float(bb_mid.iloc[-1])
        last_bb_lower = float(bb_lower.iloc[-1])
        last_ema_200 = float(ema_200.iloc[-1])
        last_volume = float(df["volume"].iloc[-1]) if "volume" in df.columns else 0
        last_vol_avg = float(vol_avg_series.iloc[-1]) if not pd.isna(vol_avg_series.iloc[-1]) else 0
        last_vwap = float(vwap_series.iloc[-1]) if not pd.isna(vwap_series.iloc[-1]) else 0.0
        last_daily_open = float(daily_open_series.iloc[-1]) if not pd.isna(daily_open_series.iloc[-1]) else 0.0

        current_price = await asyncio.to_thread(_fetch_ticker_price, exchange, pair, user_logger)
        
        # Consolida los indicadores calculados unificando variables transversales
        indicators_dict = {
            "macd_line": float(macd_line.iloc[-1]) if not pd.isna(macd_line.iloc[-1]) else 0.0,
            "macd_signal": float(macd_signal.iloc[-1]) if not pd.isna(macd_signal.iloc[-1]) else 0.0,
        }

        price_above_ema200 = (current_price > last_ema_200) if current_price else True
        volume_ok = (last_volume > last_vol_avg)
                
        user_logger.info(
            "Últimos indicadores - RSI: %.1f | MACD: %.4f | ADX: %.1f | BB(L,M,U): %.2f, %.2f, %.2f | EMA200: %.2f | VOL:%s(avg=%.0f) | VWAP:%.2f | DailyOpen:%.2f",
            last_rsi,
            indicators_dict.get("macd_line") or 0,
            float(adx.iloc[-1]),
            last_bb_lower, last_bb_mid, last_bb_upper,
            last_ema_200,
            "OK" if volume_ok else "BAJO", last_vol_avg,
            last_vwap, last_daily_open
        )

        if current_price is not None:
            user_logger.info("Precio actual (ticker) %s: %s", pair, current_price)

        # 3.5. Multi-Timeframe (Macro) Check
        macro_uptrend = True
        try:
            df_macro = await asyncio.to_thread(_fetch_ohlcv, exchange, pair, macro_tf, 210, user_logger)
            if df_macro is not None and not df_macro.empty:
                from indicators import compute_ema
                ema50_macro = compute_ema(df_macro["close"], 50)
                ema200_macro = compute_ema(df_macro["close"], 200)
                last_ema50_m = float(ema50_macro.iloc[-1])
                last_ema200_m = float(ema200_macro.iloc[-1])
                last_close_m = float(df_macro["close"].iloc[-1])
                macro_uptrend = (last_close_m > last_ema200_m) and (last_ema50_m > last_ema200_m)
                user_logger.info("Filtro Macro %s: Alcista=%s (C=%.4f, EMA50=%.4f, EMA200=%.4f)", macro_tf, macro_uptrend, last_close_m, last_ema50_m, last_ema200_m)
            else:
                user_logger.warning("Filtro Macro %s: Sin datos, asumiendo alcista para no bloquear.", macro_tf)
        except Exception as e:
            user_logger.warning("Error evaluando MTF %s: %s", macro_tf, e)

        # Contexto de portafolio (holdings, costo, P&L)
        base_currency = pair.split("/")[0] if "/" in pair else pair
        quote_currency = pair.split("/")[1] if "/" in pair else "USDT"
        portfolio_ctx = await asyncio.to_thread(
            _get_portfolio_for_pair, user.id, pair, balance_effective, current_price, user_logger
        )

        # ════════════════════════════════════════════════════════════
        # 4. LÓGICA DE DETECCIÓN DE RÉGIMEN Y ESTRATEGIA
        # ════════════════════════════════════════════════════════════
        last_ema_fast = float(ema_fast.iloc[-1])
        prev_ema_fast = float(ema_fast.iloc[-2])
        last_ema_slow = float(ema_slow.iloc[-1])
        prev_ema_slow = float(ema_slow.iloc[-2])
        last_ema_50 = float(ema_50.iloc[-1])
        last_adx = float(adx.iloc[-1])
        
        last_gap = last_ema_fast - last_ema_slow
        prev_gap = prev_ema_fast - prev_ema_slow
        
        holdings = portfolio_ctx.get("holdings", 0.0)
        has_open_position = (holdings * current_price) > 5.0 if current_price else False
        
        # --- 4.1 Definir Régimen de Mercado ---
        # Rango: ADX < 25
        # Bull/Bear: ADX >= 25 evaluado con Precio, EMA 200 y EMA 50
        is_trending = last_adx >= adx_thresh
        regime = "RANGO"
        if is_trending:
            if current_price and current_price > last_ema_200 and last_ema_50 > last_ema_200:
                regime = "BULL"
            elif current_price and current_price < last_ema_200 and last_ema_50 < last_ema_200:
                regime = "BEAR"
            else:
                # Escenario de transición, asume RANGO para ser prudente
                regime = "RANGO"
                
        user_logger.info("Régimen de mercado: %s (ADX=%.1f, umbral=%d, EMA50=%.2f, EMA200=%.2f)", regime, last_adx, adx_thresh, last_ema_50, last_ema_200)
        
        signal = "hold"
        reason = "Esperando señal..."
        amount_to_invest = 0.0
        strategy_name = ""
        free_quote_now = float(balance_effective.get(quote_currency, {}).get("free", 0.0) or 0)
        
        if not has_open_position:
            # ─── COMPRA ───
            # --- Perfiles de Riesgo y Flexibilidades ---
            # VWAP & Daily Open filters
            filter_vwap_pass = True if not use_vwap else (current_price > last_vwap)
            filter_daily_pass = True if not use_daily else (current_price > last_daily_open)
            filter_vol_pass = True if risk_profile in ["muy_agresivo", "agresivo"] else volume_ok
            filter_macro_pass = True if risk_profile in ["muy_agresivo", "agresivo"] else macro_uptrend
            
            # Ajustar umbrales según perfil
            rsi_rango_threshold = 25
            if risk_profile == "suave": rsi_rango_threshold = 20
            elif risk_profile == "agresivo": rsi_rango_threshold = 28
            elif risk_profile == "muy_agresivo": rsi_rango_threshold = 30

            if regime == "BULL":
                # ═══ ESTRATEGIA TENDENCIAL BULL: Pullback a EMA ═══
                strategy_name = "Trend Following - Bull"
                is_uptrend_local = last_ema_fast > last_ema_slow
                is_pullback = current_price is not None and current_price <= (last_ema_fast * 1.005)
                
                if is_uptrend_local and is_pullback:
                    if risk_profile == "suave" and (not filter_vwap_pass or not filter_daily_pass or not filter_vol_pass or not filter_macro_pass):
                        reason = f"[BULL] Compra bloqueada por perfil Suave (VWAP/Daily/Vol/Macro falló)"
                    elif risk_profile == "conservador" and (not filter_vwap_pass or not filter_macro_pass):
                        reason = f"[BULL] Compra bloqueada por perfil Conservador (VWAP o Macro bajista)"
                    else:
                        signal = "buy"
                        reason = f"[BULL] Trend Following: Pullback detectado (P={current_price} <= EMA_fast*1.005={last_ema_fast * 1.005:.2f})"
                        amount_to_invest = free_quote_now * (invest_pct_trending / 100.0)
                else:
                    reason = f"[BULL] Esperando pullback a EMA Rápida ({last_ema_fast:.2f})"

            elif regime == "BEAR":
                # ═══ ESTRATEGIA BEAR: Protección o Mean Reversion Extrema ═══
                strategy_name = "Protección - Bear"
                if risk_profile in ["suave", "conservador"]:
                    reason = f"[BEAR] Bloqueado. Perfil {risk_profile} no opera en tendencia bajista."
                else:
                    # En Agresivo/Muy Agresivo: busca rebote extremo
                    rsi_rebote_extremo = 15 if risk_profile == "agresivo" else 20
                    is_oversold_brutal = last_rsi < rsi_rebote_extremo
                    is_at_bb_lower = current_price is not None and current_price <= last_bb_lower
                    
                    if is_oversold_brutal and is_at_bb_lower:
                        signal = "buy"
                        reason = f"[BEAR] Mean Reversion Extrema (Contratendencia): RSI={last_rsi:.1f}<{rsi_rebote_extremo} y en BB Inferior"
                        amount_to_invest = free_quote_now * (invest_pct_trending / 100.0)
                    else:
                        reason = f"[BEAR] Buscando sobreventa extrema (RSI<{rsi_rebote_extremo}) para rebote"

            elif regime == "RANGO":
                # ═══ ESTRATEGIA MEAN REVERSION: RSI + Bollinger ═══
                strategy_name = "Mean Reversion - Rango"
                is_oversold = last_rsi < rsi_rango_threshold
                is_at_bb_lower = current_price is not None and current_price <= last_bb_lower * 1.002
                
                if is_oversold and is_at_bb_lower:
                    if risk_profile == "suave" and (not filter_vwap_pass or not filter_daily_pass):
                        reason = f"[RANGO] Bloqueado por perfil Suave (Filtros Intradiarios negativos)"
                    else:
                        signal = "buy"
                        reason = f"[RANGO] Mean Reversion: RSI={last_rsi:.1f}<{rsi_rango_threshold} + P={current_price} <= BB_lower={last_bb_lower:.2f}"
                        amount_to_invest = free_quote_now * (invest_pct_ranging / 100.0)
                else:
                    reason = f"[RANGO] Esperando sobreventa (RSI<{rsi_rango_threshold} y BB_lower)"
        else:
            # ─── VENTA (con posición abierta) ───
            avg_entry_price = portfolio_ctx.get("avg_entry_price", 0.0)
            pnl_pct = portfolio_ctx.get("pnl_pct", 0.0)
            
            # Recuperar variables para Trailing Stop, Break-Even y Time-Stop
            max_pnl_pct = 0.0
            trade_duration_hours = 0.0
            try:
                db = SessionLocal()
                try:
                    open_trades = db.query(Trade).filter(Trade.user_id == user.id, Trade.pair == pair, Trade.side == 'buy').order_by(Trade.timestamp.desc()).all()
                    if open_trades:
                        last_trade = open_trades[0]
                        # Calc max pnl
                        last_max = last_trade.max_price_reached or 0.0
                        if current_price and current_price > last_max:
                            last_trade.max_price_reached = current_price
                            db.commit()
                            last_max = current_price
                        if avg_entry_price > 0:
                            max_pnl_pct = ((last_max - avg_entry_price) / avg_entry_price) * 100
                        # Calc time duration
                        if last_trade.timestamp:
                            delta = get_colombia_time() - last_trade.timestamp
                            trade_duration_hours = delta.total_seconds() / 3600.0
                finally:
                    db.close()
            except Exception as e:
                user_logger.warning("Error consultando Trade DB para Venta: %s", e)
                
            # Verificar MACD
            last_macd = indicators_dict.get("macd_line")
            last_macd_signal = indicators_dict.get("macd_signal")
            macd_cross_down = False
            if last_macd is not None and last_macd_signal is not None:
                macd_cross_down = last_macd < last_macd_signal
            
            # Evaluar Break-Even Dinámico
            dynamic_stop_loss = stop_loss
            if max_pnl_pct >= 1.2:
                # Si llegó a ganar +1.2%, el Stop Loss se vuelve +0.1% (Break-Even)
                dynamic_stop_loss = -0.1

            # Evaluar Time-Stop
            is_time_stop = False
            if trade_duration_hours >= 6.0 and pnl_pct > -stop_loss and pnl_pct < 1.0 and not is_trending:
                is_time_stop = True

            # Evaluar Trailing Stop
            is_trailing_stop = False
            if max_pnl_pct >= trailing_activation and pnl_pct <= (max_pnl_pct - trailing_distance):
                is_trailing_stop = True

            # ═══ Condiciones de venta (priorizadas) ═══
            if is_trailing_stop:
                signal = "sell"
                reason = f"Trailing Stop: Cae a {pnl_pct:.2f}% desde máximo {max_pnl_pct:.2f}%"
            elif pnl_pct <= -dynamic_stop_loss:
                signal = "sell"
                if dynamic_stop_loss == -0.1:
                    reason = f"Break-Even Stop: Salida sin pérdidas en {pnl_pct:.2f}% (Máximo previo {max_pnl_pct:.2f}%)"
                else:
                    reason = f"Stop Loss: {pnl_pct:.2f}% <= -{stop_loss}%"
            elif is_time_stop:
                signal = "sell"
                reason = f"Time-Stop: Agotamiento de tendencia ({trade_duration_hours:.1f} horas estancado). P&L={pnl_pct:.2f}%"
            elif not is_trending and last_rsi > 65 and current_price >= last_bb_mid and pnl_pct > 0:
                # Mean Reversion Exit: RSI alto + sobre BB media + en profit
                signal = "sell"
                reason = f"[RANGO] Mean Reversion Exit: RSI={last_rsi:.1f}>65, P={current_price}>=BB_mid={last_bb_mid:.2f}, P&L={pnl_pct:.2f}%"
            elif pnl_pct > 2.5 and (last_gap < prev_gap or macd_cross_down):
                signal = "sell"
                reason = f"Toma de ganancias: P&L={pnl_pct:.2f}% (MACD bajista={macd_cross_down}, Gap decreciente={last_gap:.4f}<{prev_gap:.4f})"
            elif macd_cross_down and pnl_pct > 1.0:
                signal = "sell"
                reason = f"Venta preventiva: MACD bajista + profit {pnl_pct:.2f}%"
            else:
                sl_label = f"BE:0.1%" if dynamic_stop_loss == -0.1 else f"SL:-{stop_loss}%"
                reason = f"Hold: P&L={pnl_pct:.2f}% (Max={max_pnl_pct:.2f}%, {sl_label}, RSI={last_rsi:.1f})"

        confidence_val = 0.0
        if signal == "buy":
            # Calcular 'confidence' basado en fuerza de señal
            if is_trending and last_adx > 35:
                confidence_val = 0.95
            elif regime == "BEAR" and last_rsi <= 20: # Oversold Brutal
                confidence_val = 0.99
            elif regime == "RANGO" and last_rsi < 35:
                confidence_val = 0.85
            else:
                confidence_val = 0.8
        elif signal == "sell":
            # Salidas por sistema algorítmico implican 100% de confianza matemática
            confidence_val = 1.0

        signal_data = {
            "signal": signal,
            "confidence": confidence_val,
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
            "regime": regime, "rsi": last_rsi,
            "bb_upper": last_bb_upper, "bb_mid": last_bb_mid, "bb_lower": last_bb_lower,
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
                today_start = get_colombia_time().replace(hour=0, minute=0, second=0, microsecond=0)
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

        # Enviar siempre limit orders para ahorrar fees
        user_logger.info("Ejecutando orden: %s %s cantidad=%s (limit)", signal_data["signal"], pair, amount)
        order = await asyncio.to_thread(_create_order, exchange, pair, signal_data["signal"], amount, "limit", test_mode, user_logger, current_price)

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
                        max_price_reached=trade_price if signal_data["signal"] == "buy" else 0.0
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
                indicators=indicators_dict,
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
            if not user:
                logger.error(f"Usuario no encontrado {user_id}. Abortando.")
                return
            config = user
            
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
        
        # Sincronización de Estado (Reinicio)
        def _sync_open_orders_and_holdings(user_id, balance_start, test_mode, user_log):
            if test_mode or not balance_start: return
            try:
                db = SessionLocal()
                # Obtener pares con compras en la historia
                pairs_db = db.query(Trade.pair).filter(Trade.user_id == user_id).distinct().all()
                for (t_pair,) in pairs_db:
                    base_currency = t_pair.split("/")[0] if "/" in t_pair else t_pair
                    holdings = 0.0
                    if base_currency in balance_start and isinstance(balance_start[base_currency], dict):
                        holdings = float(balance_start[base_currency].get("free", 0) or 0)
                        
                    trades = db.query(Trade).filter(Trade.user_id == user_id, Trade.pair == t_pair).order_by(Trade.timestamp.asc()).all()
                    net_position = sum(t.amount if t.side == 'buy' else -t.amount for t in trades)
                    
                    if net_position > 0.0001 and holdings < 0.0001:
                        user_log.warning("[SYNC] Desincronización en %s: BD asume %.4f pero Exchange tiene %.4f. Nivelando internamente a 0...", t_pair, net_position, holdings)
                        adj_trade = Trade(user_id=user_id, pair=t_pair, side="sell", amount=net_position, price=0.0, order_id="sync_adjustment", simulated=True, profit=0.0)
                        db.add(adj_trade)
                db.commit()
            except Exception as e:
                user_log.warning("Error en sincronización inicial de holdings: %s", e)
            finally:
                db.close()
                
        await asyncio.to_thread(_sync_open_orders_and_holdings, user_id, balance_at_start, test_mode, user_logger)

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
        last_log_sent_date = None

        try:
            while True:
                cycle_count += 1

                # Recargar config desde la DB en cada ciclo
                db = SessionLocal()
                try:
                    user = db.query(User).filter(User.id == user_id).first()
                    config = user
                finally:
                    db.close()

                if not user:
                    user_logger.error("Usuario/Configuración no encontrada. Cerrando bucle.")
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

                # --- Envío Diario de Logs ---
                current_time = get_colombia_time()
                current_date = current_time.date()
                if current_time.hour == 23 and last_log_sent_date != current_date:
                    user_logger.info("Hora de cierre (23:00). Enviando log diario a Telegram...")
                    log_file_path = os.path.join("logs", "bots", f"user_{user_id}.log")
                    await asyncio.to_thread(_send_telegram_document_for_user, user, log_file_path, user_logger)
                    last_log_sent_date = current_date

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
