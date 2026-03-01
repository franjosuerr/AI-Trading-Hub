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
    sma50 = compute_sma(close, 50)
    sma200 = compute_sma(close, 200)
    bb_upper, bb_mid, bb_lower = compute_bollinger_bands(close, 20, 2.0)
    vol_avg = compute_volume_avg(volume, 20)

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
    last_sma50 = _last(sma50)
    last_sma200 = _last(sma200)
    last_bb_upper = _last(bb_upper)
    last_bb_lower = _last(bb_lower)
    last_vol_avg = _last(vol_avg)
    last_volume = _last(volume)

    return {
        "rsi": last_rsi,
        "macd_line": last_macd,
        "macd_signal": last_signal,
        "macd_histogram": last_hist,
        "sma50": last_sma50,
        "sma200": last_sma200,
        "bb_upper": last_bb_upper,
        "bb_lower": last_bb_lower,
        "volume": last_volume,
        "volume_avg": last_vol_avg,
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
    sma50 = compute_sma(close, 50)
    sma200 = compute_sma(close, 200)
    bb_upper, bb_mid, bb_lower = compute_bollinger_bands(close, 20, 2.0)
    vol_avg = compute_volume_avg(volume, 20)
    return {
        "rsi": rsi,
        "macd_line": macd_line,
        "macd_signal": signal_line,
        "macd_histogram": histogram,
        "sma50": sma50,
        "sma200": sma200,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "volume_avg": vol_avg,
    }
