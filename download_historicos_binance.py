import argparse
import io
import zipfile
from pathlib import Path

import pandas as pd
import requests


def month_iter(start_month: str, end_month: str) -> list[str]:
    start = pd.Period(start_month, freq="M")
    end = pd.Period(end_month, freq="M")
    months = []
    cur = start
    while cur <= end:
        months.append(str(cur))
        cur = cur + 1
    return months


def download_binance_month(symbol_no_slash: str, month: str) -> pd.DataFrame:
    url = (
        f"https://data.binance.vision/data/spot/monthly/klines/"
        f"{symbol_no_slash}/1m/{symbol_no_slash}-1m-{month}.zip"
    )
    resp = requests.get(url, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"No disponible ({resp.status_code}): {url}")

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
        if not names:
            raise RuntimeError(f"ZIP vacío para {symbol_no_slash} {month}")
        with zf.open(names[0]) as f:
            # Binance monthly CSV usually has no header
            df = pd.read_csv(f, header=None)

    # Expected first columns: open_time, open, high, low, close, volume
    if df.shape[1] < 6:
        raise RuntimeError(f"Formato inesperado para {symbol_no_slash} {month}")

    ts_raw = pd.to_numeric(df.iloc[:, 0], errors="coerce")
    ts_median = ts_raw.dropna().median() if ts_raw.notna().any() else 0
    if ts_median > 1e14:
        ts_sec = ts_raw // 1_000_000  # microseconds -> seconds
    elif ts_median > 1e11:
        ts_sec = ts_raw // 1000       # milliseconds -> seconds
    else:
        ts_sec = ts_raw               # already seconds

    out = pd.DataFrame()
    out["timestamp"] = ts_sec.astype("Int64")
    out["open"] = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    out["close"] = pd.to_numeric(df.iloc[:, 4], errors="coerce")
    out["high"] = pd.to_numeric(df.iloc[:, 2], errors="coerce")
    out["low"] = pd.to_numeric(df.iloc[:, 3], errors="coerce")
    out["volume"] = pd.to_numeric(df.iloc[:, 5], errors="coerce")
    out["deal"] = 0.0

    out = out.dropna().copy()
    out["timestamp"] = out["timestamp"].astype(int)
    return out


def main():
    parser = argparse.ArgumentParser(description="Descarga históricos 1m de Binance Vision y convierte al formato del bot")
    parser.add_argument("--symbols", type=str, default="BTCUSDT,ETHUSDT,SOLUSDT", help="Símbolos sin slash separados por coma")
    parser.add_argument("--start", type=str, required=True, help="Mes inicio YYYY-MM")
    parser.add_argument("--end", type=str, required=True, help="Mes fin YYYY-MM")
    parser.add_argument("--out", type=str, default="D:/01-Descargas/Historicos", help="Carpeta de salida")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    months = month_iter(args.start, args.end)

    for symbol in symbols:
        for month in months:
            try:
                print(f"Descargando {symbol} {month}...")
                df = download_binance_month(symbol, month)
                out_file = out_dir / f"{symbol}-Kline-MINUTE-Spot-{month}.csv"
                df.to_csv(out_file, index=False)
                print(f"OK {symbol} {month}: {len(df)} velas -> {out_file}")
            except Exception as e:
                print(f"SKIP {symbol} {month}: {e}")


if __name__ == "__main__":
    main()
