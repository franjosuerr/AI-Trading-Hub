# exchange_client.py
# Conexión a CoinEx vía ccxt: obtener velas OHLCV y colocar órdenes (o simular en test mode).

import ccxt
import pandas as pd
from typing import Optional

from config import (
    COINEX_API_KEY,
    COINEX_SECRET,
    TEST_MODE,
    CANDLE_COUNT,
    TIMEFRAME,
)
from logger_config import get_logger
from utils import round_to_precision

logger = get_logger("exchange")


def create_exchange():
    """
    Crea y retorna la instancia de ccxt para CoinEx.
    En test mode no hay testnet oficial; las órdenes se simularán en código.
    """
    config = {
        "apiKey": COINEX_API_KEY or "test_key",
        "secret": COINEX_SECRET or "test_secret",
        "enableRateLimit": True,
        "options": {},
    }
    exchange = ccxt.coinex(config)
    logger.info("Cliente CoinEx creado (modo test=%s)", TEST_MODE)
    return exchange


def fetch_ohlcv(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str = TIMEFRAME,
    limit: int = CANDLE_COUNT,
) -> Optional[pd.DataFrame]:
    """
    Obtiene velas OHLCV para el par y timeframe. Retorna DataFrame con columnas
    timestamp, open, high, low, close, volume.
    """
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not ohlcv:
            logger.warning("Sin datos OHLCV para %s.", symbol)
            return None
        df = pd.DataFrame(
            ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        logger.debug("OHLCV obtenido para %s: %d velas.", symbol, len(df))
        return df
    except ccxt.NetworkError as e:
        logger.warning(
            "Error de red o DNS al conectar con CoinEx (sin datos para %s). "
            "Comprueba tu conexión a internet y que api.coinex.com sea accesible.",
            symbol,
        )
        logger.debug("CoinEx NetworkError para %s: %s", symbol, e)
        return None
    except ccxt.ExchangeError as e:
        logger.warning("Error de la exchange CoinEx para %s: %s", symbol, str(e)[:200])
        return None
    except Exception as e:
        logger.exception("Error al obtener OHLCV para %s: %s", symbol, e)
        return None


def get_market_precision(exchange: ccxt.Exchange, symbol: str) -> dict:
    """
    Obtiene precisión de precio y cantidad para el mercado (CoinEx).
    """
    try:
        market = exchange.market(symbol)
        # ccxt: precision puede estar en 'precision' (mode tickSize) o 'limits'
        price_precision = 8
        amount_precision = 8
        if market.get("precision"):
            p = market["precision"]
            if isinstance(p, dict):
                if p.get("price") is not None:
                    price_precision = _precision_from_value(p["price"])
                if p.get("amount") is not None:
                    amount_precision = _precision_from_value(p["amount"])
            elif isinstance(p, list):
                if len(p) >= 2:
                    amount_precision = _precision_from_value(p[0])
                    price_precision = _precision_from_value(p[1])
        if market.get("precisionMode") == ccxt.DECIMAL_PLACES:
            pass  # ya en decimal places
        return {"price": price_precision, "amount": amount_precision}
    except Exception as e:
        logger.warning("No se pudo obtener la precisión para %s: %s. Se usa 8.", symbol, e)
        return {"price": 8, "amount": 8}


def _precision_from_value(value) -> int:
    """Convierte tickSize/step a número de decimales."""
    if value is None:
        return 8
    if isinstance(value, (int, float)):
        if value >= 1:
            return 0
        s = f"{value:.10f}".rstrip("0")
        if "." in s:
            return len(s.split(".")[-1])
        return 8
    return 8


def create_order(
    exchange: ccxt.Exchange,
    symbol: str,
    side: str,
    amount: float,
    order_type: str = "market",
    price: Optional[float] = None,
) -> Optional[dict]:
    """
    Crea una orden en CoinEx. side: 'buy' | 'sell', order_type: 'market' | 'limit'.
    En TEST_MODE no llama a createOrder y devuelve un dict simulado.
    """
    precision = get_market_precision(exchange, symbol)
    amount = round_to_precision(amount, precision["amount"])
    if amount <= 0:
        logger.warning("Monto inválido para %s: %s", symbol, amount)
        return None

    if TEST_MODE:
        # Simular orden: no enviar a la exchange
        fake_order = {
            "id": f"sim_{symbol}_{side}_{exchange.milliseconds()}",
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "amount": amount,
            "price": price,
            "status": "closed",
            "filled": amount,
            "info": {"simulated": True},
        }
        logger.info(
            "[SIMULADO] Orden %s %s %s cantidad=%s precio=%s",
            side,
            order_type,
            symbol,
            amount,
            price,
        )
        return fake_order

    try:
        if order_type == "market":
            # CoinEx exige el precio en compras a mercado para calcular el coste (amount * price)
            if side == "buy" and price is None:
                ticker = exchange.fetch_ticker(symbol)
                price = float(ticker.get("last", 0))
            if price is not None:
                price = round_to_precision(price, precision["price"])
            order = exchange.create_market_order(symbol, side, amount, price)
        else:
            if price is None:
                ticker = exchange.fetch_ticker(symbol)
                price = ticker["last"]
            price = round_to_precision(price, precision["price"])
            order = exchange.create_limit_order(symbol, side, amount, price)
        logger.info(
            "Orden ejecutada: %s %s %s id=%s cantidad=%s",
            side,
            symbol,
            order_type,
            order.get("id"),
            order.get("filled", amount),
        )
        return order
    except ccxt.InsufficientFunds as e:
        logger.warning(
            "Saldo insuficiente para la orden %s %s: la cuenta no tiene suficiente saldo. %s",
            side,
            symbol,
            str(e)[:100],
        )
        return None
    except Exception as e:
        logger.exception("Error al crear la orden %s %s %s: %s", side, symbol, order_type, e)
        return None


def fetch_ticker_price(exchange: ccxt.Exchange, symbol: str) -> Optional[float]:
    """Obtiene el precio actual (last) del par."""
    try:
        ticker = exchange.fetch_ticker(symbol)
        return float(ticker.get("last", 0))
    except Exception as e:
        logger.exception("Error al obtener el ticker %s: %s", symbol, e)
        return None


def fetch_balance(exchange: ccxt.Exchange, pairs: Optional[list] = None) -> Optional[dict]:
    """
    Obtiene el balance de la cuenta. Retorna dict por moneda: { "BTC": {"free": x, "used": y, "total": z}, ... }.
    Si pairs está definido, incluye solo las bases y cotizaciones de esos pares más cualquier con total > 0.
    """
    try:
        balance = exchange.fetch_balance()
        result = {}
        skip_keys = {"info", "timestamp", "datetime"}
        currencies = set()
        if pairs:
            for p in pairs:
                if "/" in p:
                    base, quote = p.split("/", 1)
                    currencies.add(base.strip())
                    currencies.add(quote.strip())
        for key, value in balance.items():
            if key in skip_keys or value is None:
                continue
            if isinstance(value, dict) and ("free" in value or "total" in value):
                free = float(value.get("free", 0) or 0)
                used = float(value.get("used", 0) or 0)
                total = float(value.get("total", 0) or 0)
                if total > 0 or free > 0 or used > 0 or (currencies and key in currencies):
                    result[key] = {"free": free, "used": used, "total": total}
        logger.info("Balance obtenido: %d moneda(s) con saldo.", len(result))
        return result if result else None
    except ccxt.NetworkError as e:
        logger.warning("Error de red al obtener el balance: %s", str(e)[:150])
        return None
    except ccxt.ExchangeError as e:
        logger.warning("Error de la exchange al obtener el balance: %s", str(e)[:150])
        return None
    except Exception as e:
        logger.exception("Error al obtener el balance: %s", e)
        return None


def format_balance_one_line(balance: Optional[dict]) -> str:
    """Formato corto del balance para logs/Telegram: BTC=0.001 USDT=100 ..."""
    if not balance:
        return "No disponible"
    parts = [f"{cur}={data['total']}" for cur, data in sorted(balance.items()) if data.get("total")]
    return " ".join(parts) if parts else "0"
