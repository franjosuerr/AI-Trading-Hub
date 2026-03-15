# exchange_client.py
# Conexión a CoinEx vía ccxt: obtener velas OHLCV y colocar órdenes (o simular en test mode).

import ccxt
import pandas as pd
import time
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


def with_exponential_backoff(retries=3, base_delay=2.0):
    """
    Decorador para reintentar peticiones a la API en caso de fallos de red o RateLimitExceeded.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            delay = base_delay
            for attempt in range(retries + 1):
                try:
                    return func(*args, **kwargs)
                except (ccxt.NetworkError, ccxt.RateLimitExceeded) as e:
                    if attempt == retries:
                        logger.error("Fallo definitivo en %s tras %d reintentos: %s", func.__name__, retries, str(e)[:100])
                        return None
                    logger.warning("Error de red/RateLimit en %s. Reintento %d/%d en %.1fs...", func.__name__, attempt+1, retries, delay)
                    time.sleep(delay)
                    delay *= 2
                except ccxt.InsufficientFunds as e:
                    logger.warning("Fallo por InsufficientFunds en %s: %s", func.__name__, str(e)[:100])
                    return None
                except ccxt.ExchangeError as e:
                    logger.warning("ExchangeError en %s: %s", func.__name__, str(e)[:100])
                    return None
                except Exception as e:
                    logger.exception("Error fatal no reintentable en %s: %s", func.__name__, e)
                    return None
            return None
        return wrapper
    return decorator


def check_minimum_notional(exchange: ccxt.Exchange, symbol: str, amount: float, price: float) -> bool:
    """Verifica límites amount y cost (notional) según el mercado actual."""
    try:
        market = exchange.market(symbol)
        limits = market.get("limits", {})
        
        # Check minimum amount
        min_amount = limits.get("amount", {}).get("min")
        if min_amount and amount < min_amount:
            logger.warning("Orden rechazada localmente: monto %f menor al mínimo %f para %s", amount, min_amount, symbol)
            return False
            
        # Check minimum cost
        cost = amount * price
        min_cost = limits.get("cost", {}).get("min")
        if min_cost and cost < min_cost:
            logger.warning("Orden rechazada localmente: coste total %f menor al mínimo notional %f para %s", cost, min_cost, symbol)
            return False
            
        return True
    except Exception as e:
        logger.warning("No se pudieron verificar mínimos para %s: %s", symbol, e)
        return True



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


@with_exponential_backoff(retries=3, base_delay=2.0)
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


@with_exponential_backoff(retries=3, base_delay=2.0)
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

    if order_type == "market":
        # CoinEx exige el precio en compras a mercado para calcular el coste (amount * price)
        if side == "buy" and price is None:
            ticker = exchange.fetch_ticker(symbol)
            price = float(ticker.get("last", 0))
        if price is not None:
            price = round_to_precision(price, precision["price"])
        
        # Validar mínimos (amount vs cost)
        if not check_minimum_notional(exchange, symbol, amount, price):
            return None
            
        order = exchange.create_market_order(symbol, side, amount, price)
    else:
        if price is None:
            ticker = exchange.fetch_ticker(symbol)
            price = ticker["last"]
        price = round_to_precision(price, precision["price"])
        
        if not check_minimum_notional(exchange, symbol, amount, price):
            return None
            
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


@with_exponential_backoff(retries=3, base_delay=2.0)
def fetch_ticker_price(exchange: ccxt.Exchange, symbol: str) -> Optional[float]:
    """Obtiene el precio actual (last) del par."""
    ticker = exchange.fetch_ticker(symbol)
    return float(ticker.get("last", 0))


@with_exponential_backoff(retries=3, base_delay=2.0)
def fetch_balance(exchange: ccxt.Exchange, pairs: Optional[list] = None) -> Optional[dict]:
    """
    Obtiene el balance de la cuenta. Retorna dict por moneda: { "BTC": {"free": x, "used": y, "total": z}, ... }.
    Si pairs está definido, incluye solo las bases y cotizaciones de esos pares más cualquier con total > 0.
    """
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


def format_balance_one_line(balance: Optional[dict]) -> str:
    """Formato corto del balance para logs/Telegram: BTC=0.001 USDT=100 ..."""
    if not balance:
        return "No disponible"
    parts = [f"{cur}={data['total']}" for cur, data in sorted(balance.items()) if data.get("total")]
    return " ".join(parts) if parts else "0"
