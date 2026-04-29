import glob
import itertools
import os
import random
import sys
from statistics import mean, pstdev

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:\10-Cripto\Bot Tradding con IA - API 2")
from indicators import (
    compute_adx,
    compute_bollinger_bands,
    compute_daily_open,
    compute_donchian_channels,
    compute_ema,
    compute_fibonacci_retracement_levels,
    compute_macd,
    compute_rsi,
    compute_volume_avg,
    compute_volume_balance,
    compute_vwap,
)

FILES = glob.glob(r"D:\01-Descargas\Historicos\*.csv")
INITIAL = 1000.0
FEE = 0.1


def build_features(df_raw: pd.DataFrame, p: dict):
    df_raw = df_raw.copy()
    df_raw["datetime"] = pd.to_datetime(df_raw["timestamp"], unit="s")
    df_raw = df_raw.sort_values("datetime").reset_index(drop=True)
    df_raw.set_index("datetime", inplace=True)

    df = (
        df_raw.resample("15min")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
        .reset_index()
    )
    df_1h = (
        df_raw.resample("1h")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
        .reset_index()
    )

    f = {}
    f["ema_fast"] = compute_ema(df["close"], p["ema_fast"])
    f["ema_slow"] = compute_ema(df["close"], p["ema_slow"])
    f["ema_50"] = compute_ema(df["close"], 50)
    f["ema_200"] = compute_ema(df["close"], 200)
    f["adx"] = compute_adx(df["high"], df["low"], df["close"], 14)
    f["bb_u"], f["bb_m"], f["bb_l"] = compute_bollinger_bands(df["close"], 20, 2.0)
    f["rsi"] = compute_rsi(df["close"], 14)
    f["macd"], f["macd_sig"], _ = compute_macd(df["close"])
    f["vol_avg"] = compute_volume_avg(df["volume"], 20)
    f["vwap"] = compute_vwap(df)
    f["daily_open"] = compute_daily_open(df)
    f["donch_u"], f["donch_m"], f["donch_l"] = compute_donchian_channels(df["high"], df["low"], 20)
    fib = compute_fibonacci_retracement_levels(df["high"], df["low"], 55)
    f["fib_382"] = fib["fib_382"]
    f["fib_618"] = fib["fib_618"]
    _, _, f["vol_bal"] = compute_volume_balance(df["close"], df["volume"], 20)

    f["ema50_1h"] = compute_ema(df_1h["close"], 50)
    f["ema200_1h"] = compute_ema(df_1h["close"], 200)
    f["df"] = df
    f["df_1h"] = df_1h
    return f


def run_backtest(features: dict, p: dict):
    df = features["df"]
    df_1h = features["df_1h"]

    cap = INITIAL
    hold = 0.0
    entry = 0.0
    max_price = 0.0
    hold_candles = 0

    sells = []
    equity = [INITIAL]

    def macro_up(dt):
        mask = df_1h["datetime"] <= dt
        if mask.sum() == 0:
            return True
        i = mask.sum() - 1
        c = float(df_1h["close"].iloc[i])
        e50 = float(features["ema50_1h"].iloc[i])
        e200 = float(features["ema200_1h"].iloc[i])
        return c > e200 and e50 > e200

    for i in range(210, len(df)):
        price = float(df["close"].iloc[i])
        dt = df["datetime"].iloc[i]

        ef = float(features["ema_fast"].iloc[i])
        es = float(features["ema_slow"].iloc[i])
        ef_prev = float(features["ema_fast"].iloc[i - 1])
        es_prev = float(features["ema_slow"].iloc[i - 1])

        e50 = float(features["ema_50"].iloc[i])
        e200 = float(features["ema_200"].iloc[i])
        adx = float(features["adx"].iloc[i])
        rsi = float(features["rsi"].iloc[i]) if not pd.isna(features["rsi"].iloc[i]) else 50.0

        bb_m = float(features["bb_m"].iloc[i])
        bb_l = float(features["bb_l"].iloc[i])

        donch_u = float(features["donch_u"].iloc[i])
        donch_m = float(features["donch_m"].iloc[i])
        donch_l = float(features["donch_l"].iloc[i])

        fib_382 = float(features["fib_382"].iloc[i])
        fib_618 = float(features["fib_618"].iloc[i])

        macd = float(features["macd"].iloc[i]) if not pd.isna(features["macd"].iloc[i]) else 0.0
        macd_sig = float(features["macd_sig"].iloc[i]) if not pd.isna(features["macd_sig"].iloc[i]) else 0.0

        vol = float(df["volume"].iloc[i])
        vol_avg = float(features["vol_avg"].iloc[i]) if not pd.isna(features["vol_avg"].iloc[i]) else 0.0
        vol_bal = float(features["vol_bal"].iloc[i]) if not pd.isna(features["vol_bal"].iloc[i]) else 1.0

        vwap = float(features["vwap"].iloc[i]) if not pd.isna(features["vwap"].iloc[i]) else 0.0
        daily_open = float(features["daily_open"].iloc[i]) if not pd.isna(features["daily_open"].iloc[i]) else 0.0

        is_trending = adx >= p["adx_th"]
        regime = "RANGO"
        if is_trending:
            if price > e200 and e50 > e200:
                regime = "BULL"
            elif price < e200 and e50 < e200:
                regime = "BEAR"

        has_pos = (hold * price) > 1.0

        signal = None
        if not has_pos:
            vwap_ok = True if not p["use_vwap"] else price > vwap
            daily_ok = True if not p["use_daily"] else price > daily_open
            macro_ok = macro_up(dt)
            vol_ok = vol > vol_avg
            vol_flow_ok = vol_bal >= p["vol_bal_min"]

            if regime == "BULL":
                pullback = (ef > es) and (price <= es * p["pullback_mult"])
                confirmations = 0
                confirmations += 1 if (fib_618 <= price <= fib_382) else 0
                confirmations += 1 if (price <= donch_m * 1.003) else 0
                confirmations += 1 if vol_ok else 0
                confirmations += 1 if vol_flow_ok else 0
                confirmations += 1 if (p["rsi_bull_min"] <= rsi <= p["rsi_bull_max"]) else 0
                if pullback and vwap_ok and daily_ok and macro_ok and confirmations >= p["bull_min_conf"]:
                    signal = "buy"
                    invest_pct = p["inv_t"]
            elif regime == "RANGO":
                confirmations = 0
                confirmations += 1 if rsi < p["rsi_rango_max"] else 0
                confirmations += 1 if price <= bb_l * 1.002 else 0
                confirmations += 1 if price <= donch_l * 1.003 else 0
                confirmations += 1 if price <= fib_618 else 0
                confirmations += 1 if vol_flow_ok else 0
                if vwap_ok and daily_ok and confirmations >= p["range_min_conf"]:
                    signal = "buy"
                    invest_pct = p["inv_r"]
            elif regime == "BEAR" and p["enable_bear_reversal"]:
                confirmations = 0
                confirmations += 1 if rsi < p["rsi_bear_max"] else 0
                confirmations += 1 if price <= bb_l else 0
                confirmations += 1 if price <= donch_l * 1.002 else 0
                confirmations += 1 if price <= fib_618 else 0
                confirmations += 1 if vol_flow_ok else 0
                confirmations += 1 if macd >= macd_sig else 0
                if confirmations >= p["bear_min_conf"] and macro_ok:
                    signal = "buy"
                    invest_pct = p["inv_t"] * 0.5

            if signal == "buy" and cap > 1.0:
                invest = cap * (invest_pct / 100.0)
                fee = invest * (FEE / 100.0)
                hold = (invest - fee) / price
                cap -= invest
                entry = price
                max_price = price
                hold_candles = 0

        else:
            pnl = ((price - entry) / entry) * 100.0
            max_price = max(max_price, price)
            max_pnl = ((max_price - entry) / entry) * 100.0
            hold_candles += 1

            dynamic_sl = p["sl"]
            if max_pnl >= p["be_trigger"]:
                dynamic_sl = -0.1

            trailing = max_pnl >= p["trail_act"] and pnl <= (max_pnl - p["trail_dist"])
            time_stop = hold_candles >= p["time_stop_candles"] and pnl < 1.0 and pnl > -p["sl"] and not is_trending
            dist_exit = pnl > p["tp"] and price >= donch_u and vol_bal < 0.98
            macd_exit = (macd < macd_sig and pnl > p["prev_take"])
            range_exit = (not is_trending and rsi > 65 and price >= bb_m and pnl > 0)
            sl_hit = pnl <= -dynamic_sl

            if trailing or sl_hit or time_stop or dist_exit or macd_exit or range_exit:
                sell_value = hold * price
                fee = sell_value * (FEE / 100.0)
                net = sell_value - fee
                trade_pnl_usdt = net - (hold * entry)
                cap += net
                sells.append(trade_pnl_usdt)
                hold = 0.0
                entry = 0.0
                max_price = 0.0
                hold_candles = 0

        equity.append(cap + (hold * price if hold > 0 else 0.0))

    final_value = equity[-1]
    ret = ((final_value - INITIAL) / INITIAL) * 100.0
    n = len(sells)
    wins = sum(1 for x in sells if x > 0)
    wr = (wins / n * 100.0) if n else 0.0

    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = ((peak - v) / peak) * 100.0 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    avg_win = mean([x for x in sells if x > 0]) if any(x > 0 for x in sells) else 0.0
    avg_loss = mean([x for x in sells if x <= 0]) if any(x <= 0 for x in sells) else 0.0

    return {
        "ret": ret,
        "wr": wr,
        "trades": n,
        "final": final_value,
        "max_dd": max_dd,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
    }


def score_config(results: list[dict]):
    rets = [r["ret"] for r in results]
    dds = [r["max_dd"] for r in results]
    wrs = [r["wr"] for r in results]

    # Robust score: favor return, penalize drawdown and instability.
    return mean(rets) - (0.45 * mean(dds)) - (0.20 * pstdev(rets)) + (0.05 * mean(wrs))


def main():
    if not FILES:
        print("No se encontraron CSV en D:\\01-Descargas\\Historicos")
        return

    raw_data = {os.path.basename(f).split("-")[0]: pd.read_csv(f) for f in FILES}

    random.seed(42)
    search_space = {
        "ema_fast": [5, 7, 9],
        "ema_slow": [20, 26, 30],
        "adx_th": [23, 25, 28],
        "sl": [2.0, 2.5, 3.0],
        "tp": [1.8, 2.2, 2.8],
        "prev_take": [0.8, 1.0, 1.3],
        "trail_act": [1.2, 1.8, 2.5],
        "trail_dist": [0.35, 0.55, 0.8],
        "inv_t": [10, 15, 20],
        "inv_r": [5, 10, 15],
        "use_vwap": [True],
        "use_daily": [False, True],
        "vol_bal_min": [1.03, 1.08, 1.15],
        "pullback_mult": [1.002, 1.004],
        "rsi_bull_min": [35],
        "rsi_bull_max": [58, 62],
        "rsi_rango_max": [24, 28],
        "rsi_bear_max": [16, 20],
        "bull_min_conf": [3, 4],
        "range_min_conf": [4],
        "bear_min_conf": [5, 6],
        "enable_bear_reversal": [False, True],
        "be_trigger": [1.0, 1.4],
        "time_stop_candles": [24, 32],
    }
    keys = list(search_space.keys())
    max_samples = 25

    def sample_params():
        return {k: random.choice(search_space[k]) for k in keys}

    best = []
    tested = 0

    seen = set()
    attempts = 0
    while attempts < max_samples:
        p = sample_params()
        attempts += 1
        signature = tuple((k, p[k]) for k in keys)
        if signature in seen:
            continue
        seen.add(signature)
        if p["ema_fast"] >= p["ema_slow"]:
            continue
        if p["inv_r"] > p["inv_t"]:
            continue

        per_coin = []
        ok = True
        for coin, df_raw in raw_data.items():
            try:
                feats = build_features(df_raw, p)
                res = run_backtest(feats, p)
                res["coin"] = coin
                per_coin.append(res)
            except Exception:
                ok = False
                break

        if not ok:
            continue

        tested += 1
        if tested % 5 == 0:
            print(f"avance: {tested}/{max_samples} configuraciones validas")
        sc = score_config(per_coin)
        rets = [x["ret"] for x in per_coin]
        if min(rets) < -12.0:
            continue

        row = {
            "score": sc,
            "params": p,
            "avg_ret": mean([x["ret"] for x in per_coin]),
            "avg_wr": mean([x["wr"] for x in per_coin]),
            "avg_dd": mean([x["max_dd"] for x in per_coin]),
            "total_trades": int(sum([x["trades"] for x in per_coin])),
            "coins": per_coin,
        }
        best.append(row)
        best = sorted(best, key=lambda x: x["score"], reverse=True)[:10]

    out = []
    out.append("OPTIMIZACION ROBUSTA SOBRE HISTORICOS")
    out.append("=" * 80)
    out.append(f"Archivos: {len(FILES)}")
    out.append(f"Configuraciones evaluadas: {tested}")
    out.append("")

    if not best:
        out.append("No se encontraron configuraciones robustas con los filtros actuales.")
    else:
        for i, b in enumerate(best, 1):
            out.append(
                f"TOP {i}: score={b['score']:.3f} | avg_ret={b['avg_ret']:+.2f}% | avg_wr={b['avg_wr']:.1f}% | avg_dd={b['avg_dd']:.2f}% | trades={b['total_trades']}"
            )
            out.append(f"params={b['params']}")
            for c in b["coins"]:
                out.append(
                    f"  {c['coin']}: ret={c['ret']:+.2f}% wr={c['wr']:.1f}% dd={c['max_dd']:.2f}% trades={c['trades']} final=${c['final']:.2f}"
                )
            out.append("")

    report_path = r"D:\10-Cripto\Bot Tradding con IA - API 2\optimizacion_historicos.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))

    print(f"OK - reporte generado en {report_path}")


if __name__ == "__main__":
    main()
