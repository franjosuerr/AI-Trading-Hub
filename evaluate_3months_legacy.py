import glob
import os
import pandas as pd

from indicators import (
    compute_ema,
    compute_adx,
    compute_bollinger_bands,
    compute_rsi,
    compute_macd,
    compute_volume_avg,
    compute_vwap,
    compute_daily_open,
)

INITIAL = 100.0
FEE = 0.1
HIST_DIR = r"D:\01-Descargas\Historicos"
MONTHS = ["2025-01", "2025-02", "2025-03"]
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def run_test(df_raw, config):
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

    ef7 = compute_ema(df["close"], 7)
    ef30 = compute_ema(df["close"], 30)
    ema50 = compute_ema(df["close"], 50)
    ema200 = compute_ema(df["close"], 200)
    adx = compute_adx(df["high"], df["low"], df["close"], 14)
    _, bbm, bbl = compute_bollinger_bands(df["close"], 20, 2.0)
    rsi = compute_rsi(df["close"], 14)
    ml, ms_s, _ = compute_macd(df["close"])
    vol_avg = compute_volume_avg(df["volume"], 20)
    vwap = compute_vwap(df)
    daily_open = compute_daily_open(df)

    ema50_1h = compute_ema(df_1h["close"], 50)
    ema200_1h = compute_ema(df_1h["close"], 200)

    def get_macro_uptrend(dt):
        mask = df_1h["datetime"] <= dt
        if mask.sum() == 0:
            return True
        idx = mask.sum() - 1
        return float(df_1h["close"].iloc[idx]) > float(ema200_1h.iloc[idx]) and float(ema50_1h.iloc[idx]) > float(ema200_1h.iloc[idx])

    cap = INITIAL
    hold = 0.0
    ep = 0.0
    mp = 0.0
    fees = 0.0
    sells = []
    hold_time_candles = 0

    sl = config.get("sl", 3.0)
    tp = config.get("tp", 2.5)
    prev = config.get("prev", 1.0)
    trail_act = config.get("trail_act", 2.5)
    trail_dist = config.get("trail_dist", 0.8)
    inv_t = config.get("inv_t", 25)
    inv_r = config.get("inv_r", 15)
    use_vwap = config.get("use_vwap", False)
    use_daily_open = config.get("use_daily_open", False)
    risk_profile = config.get("risk_profile", "conservador")
    enhanced = bool(config.get("enhanced", False))
    pair_gate_lookback = int(config.get("pair_gate_lookback_trades", 30))
    pair_gate_min_trades = int(config.get("pair_gate_min_trades", 20))
    pair_gate_min_pf = float(config.get("pair_gate_min_pf", 0.95))
    pair_gate_min_wr = float(config.get("pair_gate_min_wr", 45.0))
    pair_gate_min_net = float(config.get("pair_gate_min_net_pnl", 0.0))

    for i in range(200, len(df)):
        p = float(df["close"].iloc[i])
        dt = df["datetime"].iloc[i]
        lef = float(ef7.iloc[i])
        pef = float(ef7.iloc[i - 1])
        les = float(ef30.iloc[i])
        pes = float(ef30.iloc[i - 1])
        le50 = float(ema50.iloc[i])
        le200 = float(ema200.iloc[i])
        la = float(adx.iloc[i])
        lr = float(rsi.iloc[i]) if not pd.isna(rsi.iloc[i]) else 50.0
        lbm_v = float(bbm.iloc[i])
        lbl_v = float(bbl.iloc[i])
        lm = float(ml.iloc[i]) if not pd.isna(ml.iloc[i]) else 0.0
        lms = float(ms_s.iloc[i]) if not pd.isna(ms_s.iloc[i]) else 0.0
        lv = float(df["volume"].iloc[i])
        lva = float(vol_avg.iloc[i])
        lvwap = float(vwap.iloc[i])
        ldaily = float(daily_open.iloc[i])
        lg = lef - les
        pg = pef - pes
        hp = (hold * p) > 1.0
        mcd = lm < lms
        macro_ok = get_macro_uptrend(dt)
        volume_ok = lv > lva

        is_trending = la >= 25
        regime = "RANGO"
        if is_trending:
            if p > le200 and le50 > le200:
                regime = "BULL"
            elif p < le200 and le50 < le200:
                regime = "BEAR"

        sig = None
        if not hp:
            # Calidad rolling del par (sobre ventas ya cerradas en esta simulación)
            pair_quality_mult = 1.0
            pair_buy_blocked = False
            if enhanced:
                recent = sells[-pair_gate_lookback:] if len(sells) > pair_gate_lookback else sells
                if len(recent) < pair_gate_min_trades:
                    pair_quality_mult = 0.75
                else:
                    rec_wins = [s for s in recent if s["pnl"] > 0]
                    rec_losses = [s for s in recent if s["pnl"] <= 0]
                    rec_wr = (len(rec_wins) / max(len(recent), 1)) * 100.0
                    rec_net = sum(s["pnl"] for s in recent)
                    rec_gp = sum(s["pnl"] for s in rec_wins)
                    rec_gl = abs(sum(s["pnl"] for s in rec_losses))
                    rec_pf = (rec_gp / rec_gl) if rec_gl > 0 else (999.0 if rec_gp > 0 else 0.0)

                    if rec_pf < pair_gate_min_pf or rec_wr < pair_gate_min_wr or rec_net < pair_gate_min_net:
                        pair_buy_blocked = True
                    elif rec_pf < 1.00:
                        pair_quality_mult = 0.60
                    elif rec_pf < 1.15:
                        pair_quality_mult = 0.80

            filter_vwap_pass = True if not use_vwap else (p > lvwap)
            filter_daily_pass = True if not use_daily_open else (p > ldaily)
            filter_vol_pass = True if risk_profile in ["muy_agresivo", "agresivo"] else volume_ok
            filter_macro_pass = True if risk_profile in ["muy_agresivo", "agresivo"] else macro_ok

            rsi_rango_threshold = 25
            if risk_profile == "suave":
                rsi_rango_threshold = 20
            elif risk_profile == "agresivo":
                rsi_rango_threshold = 28
            elif risk_profile == "muy_agresivo":
                rsi_rango_threshold = 30

            if regime == "BULL":
                is_uptrend_local = lef > les
                is_pullback = p <= (lef * 1.005)
                if is_uptrend_local and is_pullback:
                    blocked = False
                    if risk_profile == "suave" and (not filter_vwap_pass or not filter_daily_pass or not filter_vol_pass or not filter_macro_pass):
                        blocked = True
                    elif risk_profile == "conservador" and (not filter_vwap_pass or not filter_macro_pass):
                        blocked = True
                    if enhanced and pair_buy_blocked:
                        blocked = True
                    inv_t_eff = inv_t * pair_quality_mult if enhanced else inv_t
                    if not blocked and cap * (inv_t_eff / 100) > 1.0:
                        sig = "buy"

            elif regime == "BEAR":
                if risk_profile not in ["suave", "conservador"]:
                    rsi_rebote_extremo = 15 if risk_profile == "agresivo" else 20
                    is_oversold_brutal = lr < rsi_rebote_extremo
                    is_at_bb_lower = p <= lbl_v
                    inv_t_eff = inv_t * pair_quality_mult if enhanced else inv_t
                    if enhanced and pair_buy_blocked:
                        pass
                    elif is_oversold_brutal and is_at_bb_lower and cap * (inv_t_eff / 100) > 1.0:
                        sig = "buy"

            elif regime == "RANGO":
                is_oversold = lr < rsi_rango_threshold
                is_at_bb_lower = p <= lbl_v * 1.002
                if is_oversold and is_at_bb_lower:
                    blocked = risk_profile == "suave" and (not filter_vwap_pass or not filter_daily_pass)
                    if enhanced and pair_buy_blocked:
                        blocked = True
                    inv_r_eff = inv_r * pair_quality_mult if enhanced else inv_r
                    if not blocked and cap * (inv_r_eff / 100) > 1.0:
                        sig = "buy"
        else:
            pnl = ((p - ep) / ep) * 100
            mp = max(mp, p)
            mpnl = ((mp - ep) / ep) * 100

            dynamic_stop_loss = sl
            be_trigger = 0.9 if enhanced else 1.2
            if mpnl >= be_trigger:
                dynamic_stop_loss = -0.1

            hold_time_candles += 1
            time_stop = hold_time_candles >= 24 and pnl > -sl and pnl < 1.0 and not is_trending

            if mpnl >= trail_act and pnl <= (mpnl - trail_dist):
                sig = "sell"
            elif pnl <= -dynamic_stop_loss:
                sig = "sell"
            elif time_stop:
                sig = "sell"
            elif not is_trending and lr > 65 and p >= lbm_v and pnl > 0:
                sig = "sell"
            tp_trigger = min(tp, 2.0) if enhanced else tp
            prev_trigger = min(prev, 1.0) if enhanced else prev
            if enhanced and mpnl >= 2.0 and pnl <= (mpnl - max(0.25, trail_dist * 0.8)):
                sig = "sell"
            elif pnl > tp_trigger and (lg < pg or mcd):
                sig = "sell"
            elif mcd and pnl > prev_trigger:
                sig = "sell"

        if sig == "buy":
            ip = inv_t if is_trending else inv_r
            if enhanced:
                recent = sells[-pair_gate_lookback:] if len(sells) > pair_gate_lookback else sells
                if len(recent) < pair_gate_min_trades:
                    ip *= 0.75
                else:
                    rec_wins = [s for s in recent if s["pnl"] > 0]
                    rec_losses = [s for s in recent if s["pnl"] <= 0]
                    rec_gp = sum(s["pnl"] for s in rec_wins)
                    rec_gl = abs(sum(s["pnl"] for s in rec_losses))
                    rec_pf = (rec_gp / rec_gl) if rec_gl > 0 else (999.0 if rec_gp > 0 else 0.0)
                    if rec_pf < 1.00:
                        ip *= 0.60
                    elif rec_pf < 1.15:
                        ip *= 0.80
            ia = cap * (ip / 100)
            f = ia * (FEE / 100)
            fees += f
            hold = (ia - f) / p
            cap -= ia
            ep = p
            mp = p
            hold_time_candles = 0
        elif sig == "sell":
            sv = hold * p
            f = sv * (FEE / 100)
            fees += f
            pu = (sv - f) - (hold * ep)
            pp = ((p - ep) / ep) * 100
            cap += sv - f
            sells.append({"pnl": pu, "pnl_pct": pp})
            hold = 0
            ep = 0
            mp = 0
            hold_time_candles = 0

    fv = cap + hold * float(df["close"].iloc[-1])
    ret = ((fv - INITIAL) / INITIAL) * 100

    wins = [s for s in sells if s["pnl"] > 0]
    losses = [s for s in sells if s["pnl"] <= 0]
    gross_profit = sum(s["pnl"] for s in wins)
    gross_loss = abs(sum(s["pnl"] for s in losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else 999.0
    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = (sum(s["pnl"] for s in losses) / len(losses)) if losses else 0.0

    return {
        "ret": ret,
        "wr": len(wins) / max(len(sells), 1) * 100,
        "n": len(sells),
        "fv": fv,
        "fees": fees,
        "pf": pf,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
    }


def load_three_months(coin):
    dfs = []
    for month in MONTHS:
        pattern = os.path.join(HIST_DIR, f"{coin}-Kline-MINUTE-Spot-{month}.csv")
        files = glob.glob(pattern)
        if not files:
            raise FileNotFoundError(f"No file for {coin} {month}")
        df = pd.read_csv(files[0])
        dfs.append(df)
    out = pd.concat(dfs, ignore_index=True)
    out = out.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return out


def main():
    cfgs_before = {
        "suave": {"inv_t": 25, "inv_r": 15, "use_vwap": True, "use_daily_open": True, "risk_profile": "suave"},
        "conservador": {"inv_t": 25, "inv_r": 15, "use_vwap": True, "use_daily_open": False, "risk_profile": "conservador"},
        "agresivo": {"inv_t": 25, "inv_r": 15, "use_vwap": False, "use_daily_open": False, "risk_profile": "agresivo"},
    }
    cfgs_after = {
        "mejorado_auto": {
            "inv_t": 25,
            "inv_r": 15,
            "use_vwap": True,
            "use_daily_open": False,
            "risk_profile": "conservador",
            "enhanced": True,
            "pair_gate_lookback_trades": 30,
            "pair_gate_min_trades": 20,
            "pair_gate_min_pf": 0.95,
            "pair_gate_min_wr": 45.0,
            "pair_gate_min_net_pnl": 0.0,
        }
    }

    lines = []
    lines.append("VALORACION 3 MESES (2025-01 a 2025-03) - CONTINUO")
    lines.append("=" * 88)
    lines.append("Formato: retorno%, win rate%, trades, final$, PF, avg_win$, avg_loss$")
    lines.append("")

    summary_before = {k: {"ret": 0.0, "wr": [], "n": 0, "pf": [], "coins": 0} for k in cfgs_before.keys()}
    summary_after = {k: {"ret": 0.0, "wr": [], "n": 0, "pf": [], "coins": 0} for k in cfgs_after.keys()}

    for coin in COINS:
        df = load_three_months(coin)
        lines.append(f"{coin}:")
        lines.append("  [ANTES]")
        for name, cfg in cfgs_before.items():
            r = run_test(df, cfg)
            lines.append(
                f"  - {name:<12} ret={r['ret']:>7.2f}% | wr={r['wr']:>5.1f}% | n={r['n']:>3} | "
                f"final=${r['fv']:.2f} | pf={r['pf']:.2f} | aw={r['avg_win']:+.4f} | al={r['avg_loss']:+.4f}"
            )
            summary_before[name]["ret"] += r["ret"]
            summary_before[name]["wr"].append(r["wr"])
            summary_before[name]["n"] += r["n"]
            summary_before[name]["pf"].append(r["pf"])
            summary_before[name]["coins"] += 1

        lines.append("  [DESPUES]")
        for name, cfg in cfgs_after.items():
            r = run_test(df, cfg)
            lines.append(
                f"  - {name:<12} ret={r['ret']:>7.2f}% | wr={r['wr']:>5.1f}% | n={r['n']:>3} | "
                f"final=${r['fv']:.2f} | pf={r['pf']:.2f} | aw={r['avg_win']:+.4f} | al={r['avg_loss']:+.4f}"
            )
            summary_after[name]["ret"] += r["ret"]
            summary_after[name]["wr"].append(r["wr"])
            summary_after[name]["n"] += r["n"]
            summary_after[name]["pf"].append(r["pf"])
            summary_after[name]["coins"] += 1
        lines.append("")

    lines.append("RESUMEN GLOBAL (promedio por par)")
    lines.append("-" * 88)
    lines.append("  [ANTES]")
    for name, agg in summary_before.items():
        c = max(agg["coins"], 1)
        ret_avg = agg["ret"] / c
        wr_avg = sum(agg["wr"]) / max(len(agg["wr"]), 1)
        pf_avg = sum(agg["pf"]) / max(len(agg["pf"]), 1)
        lines.append(
            f"  - {name:<12} ret_prom={ret_avg:>7.2f}% | wr_prom={wr_avg:>5.1f}% | trades={agg['n']:>3} | pf_prom={pf_avg:.2f}"
        )
    lines.append("  [DESPUES]")
    for name, agg in summary_after.items():
        c = max(agg["coins"], 1)
        ret_avg = agg["ret"] / c
        wr_avg = sum(agg["wr"]) / max(len(agg["wr"]), 1)
        pf_avg = sum(agg["pf"]) / max(len(agg["pf"]), 1)
        lines.append(
            f"  - {name:<12} ret_prom={ret_avg:>7.2f}% | wr_prom={wr_avg:>5.1f}% | trades={agg['n']:>3} | pf_prom={pf_avg:.2f}"
        )

    report_path = "valoracion_3m.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("\n".join(lines))
    print(f"\nReporte guardado en {report_path}")


if __name__ == "__main__":
    main()
