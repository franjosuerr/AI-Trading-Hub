import argparse
import calendar
import time
from pathlib import Path

import ccxt
import pandas as pd


def month_range_utc(year: int, month: int) -> tuple[int, int]:
    start_ts = int(pd.Timestamp(year=year, month=month, day=1, tz="UTC").timestamp() * 1000)
    last_day = calendar.monthrange(year, month)[1]
    end_ts = int(pd.Timestamp(year=year, month=month, day=last_day, hour=23, minute=59, second=59, tz="UTC").timestamp() * 1000) + 1000
    return start_ts, end_ts


def fetch_month_1m(exchange, symbol: str, start_ms: int, end_ms: int) -> list[list[float]]:
    all_rows = []
    since = start_ms
    while since < end_ms:
        batch = exchange.fetch_ohlcv(symbol, timeframe="1m", since=since, limit=1000)
        if not batch:
            break

        valid = [row for row in batch if row[0] < end_ms]
        all_rows.extend(valid)

        last_ts = batch[-1][0]
        next_since = last_ts + 60_000
        if next_since <= since:
            break
        since = next_since
        time.sleep(max(exchange.rateLimit, 200) / 1000.0)

    # dedupe by timestamp
    dedup = {}
    for row in all_rows:
        dedup[row[0]] = row
    rows = [dedup[k] for k in sorted(dedup.keys())]
    return rows


def to_expected_csv(rows: list[list[float]]) -> pd.DataFrame:
    # CCXT row format: [ts_ms, open, high, low, close, volume]
    df = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df["timestamp"] = (df["ts_ms"] // 1000).astype(int)
    df["deal"] = 0.0

    # Match local format used in existing historicos folder
    out = df[["timestamp", "open", "close", "high", "low", "volume", "deal"]].copy()
    return out


def main():
    parser = argparse.ArgumentParser(description="Descarga históricos 1m de CoinEx en formato compatible con run_final_test.py")
    parser.add_argument("--symbols", type=str, default="BTC/USDT,ETH/USDT,SOL/USDT", help="Pares separados por coma")
    parser.add_argument("--month", type=str, required=True, help="Mes en formato YYYY-MM")
    parser.add_argument("--out", type=str, default="D:/01-Descargas/Historicos", help="Carpeta de salida")
    args = parser.parse_args()

    year, month = [int(x) for x in args.month.split("-")]
    start_ms, end_ms = month_range_utc(year, month)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    exchange = ccxt.coinex({"enableRateLimit": True})

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    for symbol in symbols:
        print(f"Descargando {symbol} {args.month}...")
        rows = fetch_month_1m(exchange, symbol, start_ms, end_ms)
        if not rows:
            print(f"Sin datos para {symbol} en {args.month}")
            continue

        df_out = to_expected_csv(rows)
        sym_label = symbol.replace("/", "")
        out_file = out_dir / f"{sym_label}-Kline-MINUTE-Spot-{args.month}.csv"
        df_out.to_csv(out_file, index=False)
        print(f"OK {symbol}: {len(df_out)} velas -> {out_file}")


if __name__ == "__main__":
    main()
