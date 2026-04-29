# indicators.py
# Cálculo de indicadores técnicos a partir de OHLCV (pandas). Usa ta si está disponible.

import pandas as pd
from logger_config import get_logger

logger = get_logger("indicators")

try:
    import ta
    HAS_TA = True
except ImportError:
    HAS_TA = False
    logger.warning("Librería 'ta' no instalada; se usarán cálculos simples para los indicadores.")


def _sma(series: pd.Series, period: int) -> pd.Series:
    """Media móvil simple."""
    return series.rolling(window=period, min_periods=1).mean()


def _ema(series: pd.Series, period: int) -> pd.Series:
    """Media móvil exponencial."""
    return series.ewm(span=period, adjust=False, min_periods=1).mean()


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI (Relative Strength Index)."""
    if HAS_TA:
        return ta.momentum.RSIIndicator(close=close, window=period).rsi()
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def compute_macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD: retorna (macd_line, signal_line, histogram)."""
    if HAS_TA:
        ind = ta.trend.MACD(close=close, window_slow=slow, window_fast=fast, window_sign=signal)
        return ind.macd(), ind.macd_signal(), ind.macd_diff()
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_sma(close: pd.Series, period: int) -> pd.Series:
    """SMA de periodo dado."""
    return _sma(close, period)


def compute_ema(close: pd.Series, period: int) -> pd.Series:
    """EMA de periodo dado."""
    return _ema(close, period)

def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """ADX (Average Directional Index)."""
    if HAS_TA:
        ind = ta.trend.ADXIndicator(high=high, low=low, close=close, window=period)
        return ind.adx()
    
    # Fallback manual simplificado (EWM)
    up = high.diff()
    down = low.shift(1) - low
    
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr)
    
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1)
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx

def compute_bollinger_bands(
    close: pd.Series, period: int = 20, std_dev: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands: (upper, middle, lower)."""
    if HAS_TA:
        ind = ta.volatility.BollingerBands(close=close, window=period, window_dev=std_dev)
        return ind.bollinger_hband(), ind.bollinger_mavg(), ind.bollinger_lband()
    middle = close.rolling(window=period, min_periods=1).mean()
    std = close.rolling(window=period, min_periods=1).std().fillna(0)
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


def compute_volume_avg(volume: pd.Series, period: int = 20) -> pd.Series:
    """Media móvil del volumen."""
    return volume.rolling(window=period, min_periods=1).mean()


def compute_vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP (Volume Weighted Average Price) anclado al inicio de cada día."""
    required = ["high", "low", "close", "volume"]
    if not all(col in df.columns for col in required):
        return pd.Series([0] * len(df), index=df.index)
        
    if "datetime" in df.columns:
        date_group = df["datetime"].dt.date
    elif isinstance(df.index, pd.DatetimeIndex):
        date_group = df.index.date
    else:
        # No se puede anclar por día, usar acumulado total (fallback)
        date_group = [1] * len(df)
        
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    tp_v = typical_price * df["volume"]
    
    vwap = tp_v.groupby(date_group).cumsum() / df["volume"].groupby(date_group).cumsum()
    return vwap


def compute_daily_open(df: pd.DataFrame) -> pd.Series:
    """Saca la apertura (open) del primer periodo del día y la propaga por todo el día."""
    if "open" not in df.columns:
        return pd.Series([0] * len(df), index=df.index)
        
    if "datetime" in df.columns:
        date_group = df["datetime"].dt.date
    elif isinstance(df.index, pd.DatetimeIndex):
        date_group = df.index.date
    else:
        date_group = [1] * len(df)
        
    daily_open = df["open"].groupby(date_group).transform("first")
    return daily_open


def compute_donchian_channels(
    high: pd.Series, low: pd.Series, period: int = 20
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Canales de Donchian: (upper, middle, lower)."""
    upper = high.rolling(window=period, min_periods=1).max()
    lower = low.rolling(window=period, min_periods=1).min()
    middle = (upper + lower) / 2.0
    return upper, middle, lower


def compute_fibonacci_retracement_levels(
    high: pd.Series, low: pd.Series, lookback: int = 55
) -> dict[str, pd.Series]:
    """Niveles de Fibonacci dinámicos sobre swing high/low del lookback."""
    swing_high = high.rolling(window=lookback, min_periods=1).max()
    swing_low = low.rolling(window=lookback, min_periods=1).min()
    diff = (swing_high - swing_low).replace(0, 1e-10)

    level_236 = swing_high - (diff * 0.236)
    level_382 = swing_high - (diff * 0.382)
    level_500 = swing_high - (diff * 0.500)
    level_618 = swing_high - (diff * 0.618)
    level_786 = swing_high - (diff * 0.786)

    return {
        "swing_high": swing_high,
        "swing_low": swing_low,
        "fib_236": level_236,
        "fib_382": level_382,
        "fib_500": level_500,
        "fib_618": level_618,
        "fib_786": level_786,
    }


def compute_volume_balance(
    close: pd.Series, volume: pd.Series, period: int = 20
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Balanceo de volumen por dirección de vela.
    Retorna: (buy_volume_avg, sell_volume_avg, buy_sell_ratio).
    """
    prev_close = close.shift(1)
    up_mask = close >= prev_close
    down_mask = close < prev_close

    buy_volume = volume.where(up_mask, 0.0)
    sell_volume = volume.where(down_mask, 0.0)

    buy_avg = buy_volume.rolling(window=period, min_periods=1).mean()
    sell_avg = sell_volume.rolling(window=period, min_periods=1).mean()
    ratio = buy_avg / sell_avg.replace(0, 1e-10)
    return buy_avg, sell_avg, ratio


def compute_all_indicators(df: pd.DataFrame) -> dict:
    """
    Dado un DataFrame con columnas: open, high, low, close, volume (y opcional timestamp),
    calcula todos los indicadores y devuelve un diccionario con valores escalares
    para la última vela (útil para el prompt de la IA).
    """
    if df is None or df.empty or "close" not in df.columns:
        return {}

    close = df["close"]
    volume = df["volume"] if "volume" in df.columns else pd.Series([0] * len(df))

    rsi = compute_rsi(close, 14)
    macd_line, signal_line, histogram = compute_macd(close)
    ema50 = compute_ema(close, 50)
    ema200 = compute_ema(close, 200)
    bb_upper, bb_mid, bb_lower = compute_bollinger_bands(close, 20, 2.0)
    vol_avg = compute_volume_avg(volume, 20)
    donch_upper, donch_mid, donch_lower = compute_donchian_channels(df["high"], df["low"], 20)
    fib_levels = compute_fibonacci_retracement_levels(df["high"], df["low"], 55)
    _, _, vol_balance_ratio = compute_volume_balance(close, volume, 20)
    
    vwap = compute_vwap(df)
    daily_open = compute_daily_open(df)

    # Valores de la última vela (la más reciente)
    def _last(series: pd.Series):
        try:
            v = series.iloc[-1]
            return None if pd.isna(v) else float(v)
        except Exception:
            return None

    last_rsi = _last(rsi)
    last_macd = _last(macd_line)
    last_signal = _last(signal_line)
    last_hist = _last(histogram)
    last_ema50 = _last(ema50)
    last_ema200 = _last(ema200)
    last_bb_upper = _last(bb_upper)
    last_bb_lower = _last(bb_lower)
    last_vol_avg = _last(vol_avg)
    last_volume = _last(volume)
    last_vwap = _last(vwap)
    last_daily_open = _last(daily_open)
    last_donch_upper = _last(donch_upper)
    last_donch_mid = _last(donch_mid)
    last_donch_lower = _last(donch_lower)
    last_fib_382 = _last(fib_levels["fib_382"])
    last_fib_500 = _last(fib_levels["fib_500"])
    last_fib_618 = _last(fib_levels["fib_618"])
    last_volume_balance = _last(vol_balance_ratio)

    return {
        "rsi": last_rsi,
        "macd_line": last_macd,
        "macd_signal": last_signal,
        "macd_histogram": last_hist,
        "ema50": last_ema50,
        "ema200": last_ema200,
        "bb_upper": last_bb_upper,
        "bb_lower": last_bb_lower,
        "volume": last_volume,
        "volume_avg": last_vol_avg,
        "vwap": last_vwap,
        "daily_open": last_daily_open,
        "donchian_upper": last_donch_upper,
        "donchian_mid": last_donch_mid,
        "donchian_lower": last_donch_lower,
        "fib_382": last_fib_382,
        "fib_500": last_fib_500,
        "fib_618": last_fib_618,
        "volume_balance_ratio": last_volume_balance,
    }


def get_indicators_series(df: pd.DataFrame) -> dict:
    """
    Devuelve las series completas de indicadores (para backtest o análisis).
    """
    if df is None or df.empty or "close" not in df.columns:
        return {}
    close = df["close"]
    volume = df["volume"] if "volume" in df.columns else pd.Series([0] * len(df))
    rsi = compute_rsi(close, 14)
    macd_line, signal_line, histogram = compute_macd(close)
    ema50 = compute_ema(close, 50)
    ema200 = compute_ema(close, 200)
    bb_upper, bb_mid, bb_lower = compute_bollinger_bands(close, 20, 2.0)
    vol_avg = compute_volume_avg(volume, 20)
    donch_upper, donch_mid, donch_lower = compute_donchian_channels(df["high"], df["low"], 20)
    fib_levels = compute_fibonacci_retracement_levels(df["high"], df["low"], 55)
    vol_buy, vol_sell, vol_balance_ratio = compute_volume_balance(close, volume, 20)
    return {
        "rsi": rsi,
        "macd_line": macd_line,
        "macd_signal": signal_line,
        "macd_histogram": histogram,
        "ema50": ema50,
        "ema200": ema200,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "volume_avg": vol_avg,
        "donchian_upper": donch_upper,
        "donchian_mid": donch_mid,
        "donchian_lower": donch_lower,
        "fib_382": fib_levels["fib_382"],
        "fib_500": fib_levels["fib_500"],
        "fib_618": fib_levels["fib_618"],
        "volume_buy_avg": vol_buy,
        "volume_sell_avg": vol_sell,
        "volume_balance_ratio": vol_balance_ratio,
    }
