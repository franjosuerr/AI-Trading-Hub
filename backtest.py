# backtest.py
# Script para backtesting: datos históricos por par, simula decisiones de la IA y calcula métricas.

import argparse
import json
import sys
from pathlib import Path

# Asegurar que el proyecto esté en el path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from config import PAIRS, TIMEFRAME, CANDLE_COUNT
from logger_config import setup_logging, get_logger
from exchange_client import create_exchange, fetch_ohlcv
from indicators import compute_all_indicators, get_indicators_series

setup_logging()
logger = get_logger("backtest")


def run_backtest(
    pairs: list[str] = None,
    timeframe: str = None,
    candle_count: int = None,
) -> dict:
    """
    Ejecuta backtest: obtiene velas históricas y simula con reglas simples. Retorna métricas por par y globales.
    """
    pairs = pairs or PAIRS
    timeframe = timeframe or TIMEFRAME
    candle_count = candle_count or min(CANDLE_COUNT, 100)
    confidence_threshold = 0.7

    results = {}
    try:
        exchange = create_exchange()
    except Exception as e:
        logger.error("No se pudo conectar a la exchange (necesario para datos históricos): %s", e)
        return {"_error": str(e), "_summary": {"total_trades": 0, "total_pnl_pct": 0}}

    for pair in pairs:
        logger.info("Backtest del par: %s", pair)
        df = fetch_ohlcv(exchange, pair, timeframe, limit=candle_count)

        if df is None or len(df) < 20:
            logger.warning("Datos insuficientes para %s. Se omite.", pair)
            results[pair] = {"error": "Datos insuficientes", "trades": 0, "pnl_pct": 0}
            continue

        indicators = get_indicators_series(df)
        if not indicators:
            results[pair] = {"error": "Indicadores no calculados", "trades": 0, "pnl_pct": 0}
            continue

        from indicators import compute_ema, compute_adx
        
        # Parámetros por defecto para el backtest (para simplificar, hardcoded según la estrategia)
        ema_fast_len = 7
        ema_slow_len = 30
        adx_period = 14
        adx_thresh = 25
        
        df["ema_fast"] = compute_ema(df["close"], ema_fast_len)
        df["ema_slow"] = compute_ema(df["close"], ema_slow_len)
        df["adx"] = compute_adx(df["high"], df["low"], df["close"], adx_period)

        # Simular señales: por cada paso
        trades = []
        position = 0  # 0 sin posición, 1 largo, -1 corto (solo consideramos largo aquí)
        entry_price = 0.0
        start_idx = max(50, ema_slow_len)

        for i in range(start_idx, len(df)):
            last_ema_fast = float(df["ema_fast"].iloc[i])
            prev_ema_fast = float(df["ema_fast"].iloc[i-1])
            last_ema_slow = float(df["ema_slow"].iloc[i])
            prev_ema_slow = float(df["ema_slow"].iloc[i-1])
            last_adx = float(df["adx"].iloc[i])
            
            last_gap = last_ema_fast - last_ema_slow
            prev_gap = prev_ema_fast - prev_ema_slow

            close = float(df["close"].iloc[i])
            
            if position == 0:
                # Condición de COMPRA: cruce EMA hacia arriba + ADX fuerte
                if last_ema_fast > last_ema_slow and prev_ema_fast <= prev_ema_slow:
                    if last_adx > adx_thresh:
                        position = 1
                        entry_price = close
                        trades.append({"type": "buy", "price": close, "idx": i})
            
            elif position == 1:
                # Condiciones de VENTA: Gap se reduce con profit, o Stop Loss
                pnl_pct = (close - entry_price) / entry_price * 100
                
                if last_gap < prev_gap and close > entry_price:
                    trades.append({"type": "sell", "price": close, "idx": i, "pnl_pct": pnl_pct})
                    position = 0
                elif pnl_pct <= -2.0:
                    trades.append({"type": "sell", "price": close, "idx": i, "pnl_pct": pnl_pct})
                    position = 0

        # Cerrar posición al final si queda abierta
        if position == 1 and len(df) > 0:
            close = float(df["close"].iloc[-1])
            pnl_pct = (close - entry_price) / entry_price * 100
            trades.append({"type": "sell", "price": close, "idx": len(df) - 1, "pnl_pct": pnl_pct})

        sell_trades = [t for t in trades if t.get("type") == "sell" and "pnl_pct" in t]
        total_pnl_pct = sum(t["pnl_pct"] for t in sell_trades) if sell_trades else 0
        results[pair] = {
            "trades": len(sell_trades),
            "pnl_pct": round(total_pnl_pct, 2),
            "signals_count": len(trades),
        }

    # Resumen global
    total_trades = sum(r.get("trades", 0) for r in results.values() if isinstance(r, dict))
    total_pnl = sum(r.get("pnl_pct", 0) for r in results.values() if isinstance(r, dict))
    results["_summary"] = {"total_trades": total_trades, "total_pnl_pct": round(total_pnl, 2)}
    return results


def main():
    parser = argparse.ArgumentParser(description="Backtest del bot de trading")
    parser.add_argument("--pairs", type=str, default="", help="Pares separados por coma (default: config)")
    parser.add_argument("--timeframe", type=str, default=TIMEFRAME, help="Timeframe (ej. 1h)")
    parser.add_argument("--candles", type=int, default=100, help="Número de velas históricas")
    parser.add_argument("--output", type=str, default="", help="Archivo JSON de salida para resultados")
    args = parser.parse_args()

    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()] or PAIRS
    results = run_backtest(
        pairs=pairs,
        timeframe=args.timeframe,
        candle_count=args.candles,
    )

    print(json.dumps(results, indent=2))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        logger.info("Resultados del backtest guardados en %s", args.output)


if __name__ == "__main__":
    main()
