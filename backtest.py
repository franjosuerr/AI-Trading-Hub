# backtest.py
# Script para backtesting: datos históricos por par, simula decisiones de la IA y calcula métricas.

import argparse
import json
import sys
from pathlib import Path

# Asegurar que el proyecto esté en el path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from config import PAIRS, TIMEFRAME, CANDLE_COUNT, CONFIDENCE_THRESHOLD
from logger_config import setup_logging, get_logger
from exchange_client import create_exchange, fetch_ohlcv
from indicators import compute_all_indicators, get_indicators_series
from utils import format_candles_for_prompt
from ai_advisor import get_ai_signal

setup_logging()
logger = get_logger("backtest")


def run_backtest(
    pairs: list[str] = None,
    timeframe: str = None,
    candle_count: int = None,
    use_ai: bool = True,
    confidence_threshold: float = None,
) -> dict:
    """
    Ejecuta backtest: obtiene velas históricas, opcionalmente llama a la IA por cada vela
    (costoso en tokens) o simula con reglas simples. Retorna métricas por par y globales.

    use_ai=True: llama a la IA para cada vela (solo últimas N velas por paso) — muy costoso.
    use_ai=False: usa regla simple (ej. RSI<30 buy, RSI>70 sell) para simular señales.
    """
    pairs = pairs or PAIRS
    timeframe = timeframe or TIMEFRAME
    candle_count = candle_count or min(CANDLE_COUNT, 100)
    confidence_threshold = confidence_threshold or CONFIDENCE_THRESHOLD

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

        # Simular señales: por cada paso (desde vela 200 hasta el final), decidir con IA o regla
        trades = []
        position = 0  # 0 sin posición, 1 largo, -1 corto (solo consideramos largo aquí)
        entry_price = 0.0
        start_idx = min(200, max(50, len(df) - 10))

        for i in range(start_idx, len(df)):
            window = df.iloc[: i + 1]
            ind_current = compute_all_indicators(window)
            candles_text = format_candles_for_prompt(window, 5)

            if use_ai and exchange:
                signal_data = get_ai_signal(
                    pair, timeframe, candles_text, ind_current, prompt_candles=5
                )
                if signal_data:
                    signal = signal_data["signal"]
                    conf = signal_data["confidence"]
                else:
                    signal = "hold"
                    conf = 0
            else:
                # Regla simple basada en RSI
                rsi = ind_current.get("rsi")
                if rsi is None:
                    signal, conf = "hold", 0
                elif rsi < 30:
                    signal, conf = "buy", 0.75
                elif rsi > 70:
                    signal, conf = "sell", 0.75
                else:
                    signal, conf = "hold", 0

            close = float(df["close"].iloc[i])
            if signal == "buy" and conf >= confidence_threshold and position <= 0:
                if position == -1:
                    # Cerrar corto (simplificado: no cortos en este ejemplo)
                    pass
                position = 1
                entry_price = close
                trades.append({"type": "buy", "price": close, "idx": i})
            elif signal == "sell" and conf >= confidence_threshold and position >= 1:
                pnl_pct = (close - entry_price) / entry_price * 100
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
    parser.add_argument("--no-ai", action="store_true", help="Usar reglas simples en lugar de IA")
    parser.add_argument("--threshold", type=float, default=CONFIDENCE_THRESHOLD, help="Umbral de confianza")
    parser.add_argument("--output", type=str, default="", help="Archivo JSON de salida para resultados")
    args = parser.parse_args()

    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()] or PAIRS
    results = run_backtest(
        pairs=pairs,
        timeframe=args.timeframe,
        candle_count=args.candles,
        use_ai=not args.no_ai,
        confidence_threshold=args.threshold,
    )

    print(json.dumps(results, indent=2))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        logger.info("Resultados del backtest guardados en %s", args.output)


if __name__ == "__main__":
    main()
