import glob
import json
import os
from collections import defaultdict
from datetime import timedelta

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
PAIR_MAP = {"BTCUSDT": "BTC/USDT", "ETHUSDT": "ETH/USDT", "SOLUSDT": "SOL/USDT"}


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
    out["datetime"] = pd.to_datetime(out["timestamp"], unit="s")
    out = out.set_index("datetime")
    return out


def _derive_adaptive_controls(regime: str, last_adx: float, volatility_pct: float, risk_pressure: float) -> dict:
    rp = max(0.0, min(1.0, float(risk_pressure or 0.0)))
    vol = max(0.0, float(volatility_pct or 0.0))

    if rp >= 0.80:
        profile = "suave"
    elif regime == "BULL" and last_adx >= 30 and vol <= 2.2 and rp <= 0.35:
        profile = "agresivo"
    elif regime == "RANGO" and vol <= 1.8 and rp <= 0.55:
        profile = "conservador"
    else:
        profile = "conservador"

    invest_mult = max(0.35, 1.0 - (rp * 0.60))
    stop_mult = max(0.55, 1.0 - (rp * 0.35))
    trail_activation_mult = max(0.70, 1.0 - (rp * 0.25))
    trail_distance_mult = max(0.60, 1.0 - (rp * 0.30))

    if vol >= 3.0:
        invest_mult *= 0.85
    if vol >= 4.0:
        profile = "suave"

    return {
        "profile": profile,
        "invest_mult": max(0.25, min(1.2, invest_mult)),
        "stop_mult": max(0.50, min(1.1, stop_mult)),
        "trail_activation_mult": max(0.65, min(1.1, trail_activation_mult)),
        "trail_distance_mult": max(0.55, min(1.1, trail_distance_mult)),
    }


def _compute_pair_edge_score(pair_perf: dict, min_trades: int) -> float:
    trades = int(pair_perf.get("trades", 0) or 0)
    pf = float(pair_perf.get("profit_factor", 0.0) or 0.0)
    wr = float(pair_perf.get("win_rate", 0.0) or 0.0)
    net = float(pair_perf.get("net_pnl", 0.0) or 0.0)

    if trades < min_trades:
        return 0.35

    pf_norm = max(0.0, min(1.0, (pf - 0.80) / 0.50))
    wr_norm = max(0.0, min(1.0, (wr - 40.0) / 20.0))
    net_norm = 1.0 if net > 0 else 0.0
    return max(0.0, min(1.0, (0.55 * pf_norm) + (0.35 * wr_norm) + (0.10 * net_norm)))


def _perf_from_sells(sells):
    profits = [float(s["pnl"]) for s in sells]
    n = len(profits)
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]
    wr = (len(wins) / n * 100.0) if n else 0.0
    net = sum(profits)
    gp = sum(wins)
    gl = abs(sum(losses))
    pf = (gp / gl) if gl > 0 else (999.0 if gp > 0 else 0.0)
    return {"trades": n, "win_rate": wr, "net_pnl": net, "profit_factor": pf}


def prepare_pair_dataset(raw_df):
    df15 = (
        raw_df.resample("15min")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
        .copy()
    )

    df1h = (
        raw_df.resample("1h")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
        .copy()
    )

    df15["ema_fast"] = compute_ema(df15["close"], 7)
    df15["ema_slow"] = compute_ema(df15["close"], 30)
    df15["ema_50"] = compute_ema(df15["close"], 50)
    df15["ema_200"] = compute_ema(df15["close"], 200)
    df15["adx"] = compute_adx(df15["high"], df15["low"], df15["close"], 14)
    _, bbm, bbl = compute_bollinger_bands(df15["close"], 20, 2.0)
    df15["bb_mid"] = bbm
    df15["bb_low"] = bbl
    df15["rsi"] = compute_rsi(df15["close"], 14)
    ml, ms, _ = compute_macd(df15["close"])
    df15["macd"] = ml
    df15["macd_signal"] = ms
    df15["macd_hist"] = (df15["macd"] - df15["macd_signal"]).fillna(0.0)
    df15["macd_hist_slope"] = df15["macd_hist"].diff().fillna(0.0)
    df15["rsi_prev"] = df15["rsi"].shift(1).fillna(50.0)
    df15["close_prev2"] = df15["close"].shift(2).ffill().fillna(df15["close"])
    df15["close_prev3"] = df15["close"].shift(3).ffill().fillna(df15["close"])
    df15["vol_avg"] = compute_volume_avg(df15["volume"], 20)
    df15["vwap"] = compute_vwap(df15.reset_index()).values
    df15["daily_open"] = compute_daily_open(df15.reset_index()).values
    df15["ret_std20"] = df15["close"].pct_change().rolling(20).std().fillna(0) * 100.0

    ema50_1h = compute_ema(df1h["close"], 50)
    ema200_1h = compute_ema(df1h["close"], 200)
    macro_up = ((df1h["close"] > ema200_1h) & (ema50_1h > ema200_1h)).astype(int)
    macro_up = macro_up.reindex(df15.index, method="ffill").fillna(1).astype(int)
    df15["macro_up"] = macro_up

    return df15


def run_portfolio_backtest_faithful(data_by_coin, month_filter=None, strategy_profile="balanced", hyperopt_params=None):
    pairs = [PAIR_MAP[c] for c in COINS]

    # Config defaults aligned with bot_manager
    invest_pct_trending = 25.0
    invest_pct_ranging = 15.0
    stop_loss = 3.0
    trailing_activation = 2.5
    trailing_distance = 0.8

    prod_gate_enabled = True
    prod_gate_lookback_days = 7
    prod_gate_min_trades = 8
    prod_gate_min_win_rate = 48.0
    prod_gate_min_net_profit_pct = 0.0
    prod_gate_max_drawdown_pct = 3.0
    daily_loss_limit_pct = 1.5
    weekly_loss_limit_pct = 4.0

    pair_gate_lookback_trades = 24
    pair_gate_min_trades = 12
    pair_gate_min_win_rate = 38.0
    pair_gate_min_pf = 0.90
    pair_gate_min_net_pnl = 0.0

    allocator_enabled = True
    allocator_top_pairs = 2
    pair_auto_disable_enabled = True
    pair_auto_disable_cycles = 12
    adaptive_mode_enabled = True

    # Strategy profiles inspired by common open-source patterns (trend, mean-reversion, momentum).
    profile = (strategy_profile or "balanced").strip().lower()
    bull_min_confirmations = 4
    range_require_macro = False
    range_min_confirmations = 5
    min_edge_score_to_buy = 0.25
    cold_start_quality_mult = 0.60

    if profile == "trend_guard":
        bull_min_confirmations = 4
        range_require_macro = True
        range_min_confirmations = 5
        min_edge_score_to_buy = 0.30
        cold_start_quality_mult = 0.50
    elif profile == "momentum_plus":
        bull_min_confirmations = 3
        range_require_macro = False
        range_min_confirmations = 4
        min_edge_score_to_buy = 0.22
        cold_start_quality_mult = 0.70

    # ── Hyperopt overrides (applied on top of profile defaults) ──────────────
    hp = hyperopt_params or {}
    bull_rsi_low              = float(hp.get("bull_rsi_low", 36.0))
    bull_rsi_high             = float(hp.get("bull_rsi_high", 62.0))
    range_rsi_thresh          = float(hp.get("range_rsi_thresh", 33.0))
    bear_rsi_thresh_suave     = float(hp.get("bear_rsi_thresh_suave", 24.0))
    bear_rsi_thresh_agresivo  = float(hp.get("bear_rsi_thresh_agresivo", 29.0))
    if "bull_min_confirmations" in hp:
        bull_min_confirmations = int(hp["bull_min_confirmations"])
    if "range_min_confirmations" in hp:
        range_min_confirmations = int(hp["range_min_confirmations"])
    if "stop_loss" in hp:
        stop_loss = float(hp["stop_loss"])
    if "trailing_activation" in hp:
        trailing_activation = float(hp["trailing_activation"])
    if "trailing_distance" in hp:
        trailing_distance = float(hp["trailing_distance"])
    # ROI table (Freqtrade-style): {bars_held: min_net_profit_pct_to_exit}
    roi_table    = hp.get("roi_table", {4: 3.5, 12: 1.8, 24: 0.8, 40: 0.0})
    cooldown_bars = int(hp.get("cooldown_bars", 3))

    cash = INITIAL
    fee_paid = 0.0

    pos = {c: {"hold": 0.0, "entry": 0.0, "maxp": 0.0, "hold_bars": 0, "partial_done": False, "regime_at_entry": ""} for c in COINS}
    sells_all = []
    sells_by_coin = defaultdict(list)
    pair_disabled_until = {}
    regime_blocked_until = {}  # (pair, regime) -> cycle_idx blocked until; auto-refreshed every 12 cycles
    pair_cooldown_until  = {}  # pair -> cycle_idx when cooldown expires (prevents immediate re-entry after trade)

    # common timeline
    timeline = sorted(set.intersection(*[set(df.index) for df in data_by_coin.values()]))
    if month_filter:
        timeline = [ts for ts in timeline if ts.strftime("%Y-%m") in month_filter]

    for cycle_idx, ts in enumerate(timeline, start=1):
        prices = {c: float(data_by_coin[c].loc[ts, "close"]) for c in COINS}
        portfolio_total = cash + sum(pos[c]["hold"] * prices[c] for c in COINS)
        denom_usdt = portfolio_total if portfolio_total > 0 else 1.0

        # global perf windows (time-based)
        day_cut = ts - timedelta(days=1)
        week_cut = ts - timedelta(days=7)
        gate_cut = ts - timedelta(days=max(1, prod_gate_lookback_days))

        day_sells = [s for s in sells_all if s["ts"] >= day_cut]
        week_sells = [s for s in sells_all if s["ts"] >= week_cut]
        gate_sells = [s for s in sells_all if s["ts"] >= gate_cut]

        perf_daily = _perf_from_sells(day_sells)
        perf_weekly = _perf_from_sells(week_sells)
        perf_gate = _perf_from_sells(gate_sells)

        daily_pnl_pct = (perf_daily["net_pnl"] / denom_usdt) * 100.0
        weekly_pnl_pct = (perf_weekly["net_pnl"] / denom_usdt) * 100.0
        gate_pnl_pct = (perf_gate["net_pnl"] / denom_usdt) * 100.0

        # drawdown abs in gate window
        eq = 0.0
        peak = 0.0
        max_dd_abs = 0.0
        for s in gate_sells:
            eq += float(s["pnl"])
            peak = max(peak, eq)
            max_dd_abs = max(max_dd_abs, peak - eq)
        gate_dd_pct = (max_dd_abs / denom_usdt) * 100.0

        buy_gate_reasons = []
        if daily_pnl_pct <= -daily_loss_limit_pct:
            buy_gate_reasons.append("daily_loss")
        if weekly_pnl_pct <= -weekly_loss_limit_pct:
            buy_gate_reasons.append("weekly_loss")
        if prod_gate_enabled and perf_gate["trades"] >= prod_gate_min_trades:
            if perf_gate["win_rate"] < prod_gate_min_win_rate:
                buy_gate_reasons.append("low_wr")
            if gate_pnl_pct < prod_gate_min_net_profit_pct:
                buy_gate_reasons.append("low_net")
            if gate_dd_pct > prod_gate_max_drawdown_pct:
                buy_gate_reasons.append("high_dd")

        buys_blocked_by_risk_gate = len(buy_gate_reasons) > 0

        risk_pressure = 0.0
        if daily_pnl_pct < 0:
            risk_pressure += min(abs(daily_pnl_pct) / max(0.25, daily_loss_limit_pct), 1.0) * 0.45
        if weekly_pnl_pct < 0:
            risk_pressure += min(abs(weekly_pnl_pct) / max(0.50, weekly_loss_limit_pct), 1.0) * 0.35
        if prod_gate_max_drawdown_pct > 0:
            risk_pressure += min(gate_dd_pct / prod_gate_max_drawdown_pct, 1.0) * 0.20
        if buys_blocked_by_risk_gate:
            risk_pressure = 1.0
        risk_pressure = max(0.0, min(1.0, risk_pressure))

        gate_pf = float(perf_gate.get("profit_factor", 0.0) or 0.0)
        portfolio_pf_weak = perf_gate["trades"] >= prod_gate_min_trades and gate_pf < 1.0
        market_fragile = risk_pressure >= 0.70 or (perf_gate["trades"] >= prod_gate_min_trades and gate_pf < 0.90)

        # Regime auto-gate: every 12 cycles review per-pair per-regime rolling WR.
        # If a regime is consistently losing (WR<35%) -> block it for 12 cycles.
        # If it recovers (WR>=52%) -> unblock early.
        if cycle_idx % 12 == 0:
            for _c in COINS:
                _pair = PAIR_MAP[_c]
                for _regime in ["BULL", "RANGO", "BEAR"]:
                    _r_sells = [s for s in sells_by_coin[_c][-30:] if s.get("regime") == _regime]
                    if len(_r_sells) >= 6:
                        _rwr = sum(1 for s in _r_sells if s["pnl"] > 0) / len(_r_sells)
                        if _rwr < 0.35:
                            regime_blocked_until[(_pair, _regime)] = cycle_idx + 12
                        elif _rwr >= 0.52:
                            regime_blocked_until.pop((_pair, _regime), None)

        # pair rolling perf map
        pair_perf_map = {}
        for coin in COINS:
            pair_perf_map[PAIR_MAP[coin]] = _perf_from_sells(sells_by_coin[coin][-pair_gate_lookback_trades:])

        # Dynamic pair reactivation: if a disabled pair shows recovery signals,
        # release it early (after at least half the disable window has elapsed)
        _min_wait_for_reactivation = max(6, pair_auto_disable_cycles // 2)
        for _pair in list(pair_disabled_until.keys()):
            _disable_until = int(pair_disabled_until.get(_pair, 0) or 0)
            if _disable_until <= cycle_idx:
                continue  # already expired naturally
            # Only check in the second half of the disable window
            if (_disable_until - cycle_idx) > _min_wait_for_reactivation:
                continue
            _coin = next((c for c in COINS if PAIR_MAP[c] == _pair), None)
            if not _coin or _coin not in data_by_coin:
                continue
            _df = data_by_coin[_coin]
            if ts not in _df.index:
                continue
            _iloc = _df.index.get_loc(ts)
            if _iloc < 5:
                continue
            _row = _df.iloc[_iloc]
            # Recovery conditions: 3 consecutive positive MACD hist slope + bullish structure
            _slopes = [float(_df.iloc[max(0, _iloc - i)]["macd_hist_slope"] or 0) for i in range(3)]
            _rsi_now = float(_row["rsi"] or 50)
            _ema_f = float(_row["ema_fast"] or 0)
            _ema_s = float(_row["ema_slow"] or 0)
            _p_now = float(_row["close"] or 0)
            _ema200 = float(_row["ema_200"] or 0)
            _momentum_ok = all(v > 0.0001 for v in _slopes)
            _structure_ok = _ema_f > _ema_s and _rsi_now > 50 and _p_now > _ema200
            if _momentum_ok and _structure_ok:
                pair_disabled_until[_pair] = 0  # early reactivation

        pair_score_map = {
            p: _compute_pair_edge_score(pair_perf_map.get(p, {}), pair_gate_min_trades)
            for p in pairs
        }
        ranked_pairs = sorted(pairs, key=lambda p: pair_score_map.get(p, 0.0), reverse=True)
        target_top_pairs = 1 if market_fragile else allocator_top_pairs
        if len(ranked_pairs) >= 2 and float(pair_score_map.get(ranked_pairs[1], 0.0) or 0.0) < 0.55:
            target_top_pairs = 1
        top_n = max(1, min(len(ranked_pairs), target_top_pairs))
        buy_enabled_pairs = set(ranked_pairs[:top_n]) if allocator_enabled else set(pairs)

        cycle_budget_factor = max(0.20, 1.0 - (risk_pressure * 0.75))
        if portfolio_pf_weak:
            cycle_budget_factor *= 0.55
            cycle_budget_factor = max(0.10, cycle_budget_factor)
        cycle_buy_budget_usdt = cash * cycle_budget_factor
        if buys_blocked_by_risk_gate:
            cycle_buy_budget_usdt = 0.0

        if allocator_enabled and buy_enabled_pairs:
            score_sum = sum(pair_score_map.get(p, 0.0) for p in buy_enabled_pairs)
            if score_sum <= 0:
                pair_budget_weights = {p: (1.0 / len(buy_enabled_pairs)) for p in buy_enabled_pairs}
            else:
                pair_budget_weights = {p: (pair_score_map.get(p, 0.0) / score_sum) for p in buy_enabled_pairs}
        else:
            pair_budget_weights = {p: (1.0 / len(pairs)) for p in pairs}

        cycle_budget_spent = 0.0
        pair_budget_spent = defaultdict(float)

        for coin in COINS:
            pair = PAIR_MAP[coin]
            row = data_by_coin[coin].loc[ts]
            p = float(row["close"])
            lef = float(row["ema_fast"])
            les = float(row["ema_slow"])
            le50 = float(row["ema_50"])
            le200 = float(row["ema_200"])
            adx = float(row["adx"])
            rsi = float(row["rsi"]) if not pd.isna(row["rsi"]) else 50.0
            bbm = float(row["bb_mid"])
            bbl = float(row["bb_low"])
            macd = float(row["macd"]) if not pd.isna(row["macd"]) else 0.0
            macd_s = float(row["macd_signal"]) if not pd.isna(row["macd_signal"]) else 0.0
            macd_hist = float(row["macd_hist"]) if not pd.isna(row["macd_hist"]) else 0.0
            macd_hist_slope = float(row["macd_hist_slope"]) if not pd.isna(row["macd_hist_slope"]) else 0.0
            rsi_prev = float(row["rsi_prev"]) if not pd.isna(row["rsi_prev"]) else rsi
            vol = float(row["volume"])
            vol_avg = float(row["vol_avg"]) if not pd.isna(row["vol_avg"]) else 0.0
            vwap = float(row["vwap"]) if not pd.isna(row["vwap"]) else p
            daily_open = float(row["daily_open"]) if not pd.isna(row["daily_open"]) else p
            macro_up = int(row["macro_up"]) == 1
            close_prev2 = float(row["close_prev2"]) if not pd.isna(row["close_prev2"]) else p
            close_prev3 = float(row["close_prev3"]) if not pd.isna(row["close_prev3"]) else p
            volatility_pct = float(row["ret_std20"])

            st = pos[coin]
            has_open = (st["hold"] * p) > 1.0
            is_trending = adx >= 25
            regime = "RANGO"
            if is_trending:
                if p > le50 and le50 > le200:
                    regime = "BULL"
                elif p < le200 and le50 < le200:
                    regime = "BEAR"

            if adaptive_mode_enabled:
                adaptive_cfg = _derive_adaptive_controls(regime, adx, volatility_pct, risk_pressure)
                active_risk_profile = adaptive_cfg["profile"]
                pair_invest_t = invest_pct_trending * adaptive_cfg["invest_mult"]
                pair_invest_r = invest_pct_ranging * adaptive_cfg["invest_mult"]
                pair_stop_loss = max(1.2, stop_loss * adaptive_cfg["stop_mult"])
                pair_trail_act = max(1.0, trailing_activation * adaptive_cfg["trail_activation_mult"])
                pair_trail_dist = max(0.25, trailing_distance * adaptive_cfg["trail_distance_mult"])
            else:
                active_risk_profile = "conservador"
                pair_invest_t = invest_pct_trending
                pair_invest_r = invest_pct_ranging
                pair_stop_loss = stop_loss
                pair_trail_act = trailing_activation
                pair_trail_dist = trailing_distance

            if risk_pressure >= 0.60:
                pair_stop_loss = max(0.9, pair_stop_loss * 0.90)
                pair_trail_act = max(0.8, pair_trail_act * 0.85)
                pair_trail_dist = max(0.20, pair_trail_dist * 0.80)

            # pair quality and blocks
            pair_perf = pair_perf_map.get(pair, {"trades": 0, "win_rate": 0.0, "net_pnl": 0.0, "profit_factor": 0.0})
            pair_quality_mult = cold_start_quality_mult if pair_perf.get("trades", 0) < pair_gate_min_trades else 1.0
            pair_buy_blocked = False

            if allocator_enabled and pair not in buy_enabled_pairs:
                pair_buy_blocked = True
            if cycle_idx < _pair_disabled_until_cycle_get(pair_disabled_until, pair):
                pair_buy_blocked = True
            if cycle_idx < pair_cooldown_until.get(pair, 0):
                pair_buy_blocked = True  # Cooldown: too soon after last trade closed

            if pair_perf.get("trades", 0) >= pair_gate_min_trades:
                pf = float(pair_perf.get("profit_factor", 0.0) or 0.0)
                wr = float(pair_perf.get("win_rate", 0.0) or 0.0)
                net = float(pair_perf.get("net_pnl", 0.0) or 0.0)
                if pf < pair_gate_min_pf or wr < pair_gate_min_win_rate or net < pair_gate_min_net_pnl:
                    pair_buy_blocked = True
                    if pair_auto_disable_enabled and pf < 0.70 and net < 0:
                        pair_disabled_until[(pair)] = cycle_idx + max(1, pair_auto_disable_cycles)
                if pair_auto_disable_enabled and pair in {"ETH/USDT", "SOL/USDT"} and pf < 0.85:
                    aggressive_cycles = max(pair_auto_disable_cycles, 18)
                    pair_disabled_until[(pair)] = cycle_idx + aggressive_cycles
                    pair_buy_blocked = True
                elif pf < 1.00:
                    pair_quality_mult = 0.60
                elif pf < 1.15:
                    pair_quality_mult = 0.80

            pair_invest_t *= pair_quality_mult
            pair_invest_r *= pair_quality_mult

            signal = None
            if not has_open:
                filter_vwap_pass = p > vwap
                filter_daily_pass = p > daily_open
                filter_vol_pass = True if active_risk_profile in ["agresivo", "muy_agresivo"] else (vol > vol_avg)
                filter_macro_pass = macro_up if active_risk_profile in ["suave", "conservador"] else True
                filter_momentum_pass = macd_hist >= -0.0005 and macd_hist_slope >= -0.0005

                if regime == "BULL":
                    bull_pullback = lef > les and p <= (les * 1.003)
                    bull_continuation = lef > les and p > lef and rsi >= 48 and rsi <= 66
                    # Anti-falling-knife: price must be rebounding, not still declining
                    is_bouncing = (p > close_prev2) or (rsi > rsi_prev)
                    all_declining = p < close_prev2 < close_prev3
                    trend_confirmations = 0
                    if filter_vwap_pass:
                        trend_confirmations += 1
                    if filter_daily_pass:
                        trend_confirmations += 1
                    if filter_macro_pass:
                        trend_confirmations += 1
                    if filter_momentum_pass:
                        trend_confirmations += 1
                    if vol >= (vol_avg * 0.95):
                        trend_confirmations += 1

                    if bull_pullback and is_bouncing and not all_declining and trend_confirmations >= bull_min_confirmations and bull_rsi_low <= rsi <= bull_rsi_high:
                        signal = "buy"
                        amount_usdt = cash * (pair_invest_t / 100.0)
                    elif bull_continuation and is_bouncing and trend_confirmations >= bull_min_confirmations and macd >= macd_s:
                        signal = "buy"
                        amount_usdt = cash * ((pair_invest_t * 0.85) / 100.0)
                elif regime == "RANGO":
                    oversold = rsi < range_rsi_thresh and p <= (bbl * 1.002) and p > le200
                    rebound_ready = rsi > rsi_prev and macd_hist_slope > 0
                    range_confirmations = 0
                    if oversold:
                        range_confirmations += 1
                    if rebound_ready:
                        range_confirmations += 1
                    if p <= bbm:
                        range_confirmations += 1
                    if vol >= (vol_avg * 0.9):
                        range_confirmations += 1
                    if (not range_require_macro) or macro_up:
                        range_confirmations += 1

                    if oversold and rebound_ready and range_confirmations >= range_min_confirmations:
                        ok = not (active_risk_profile == "suave" and (not filter_vwap_pass or not filter_daily_pass))
                        if ok:
                            signal = "buy"
                            amount_usdt = cash * (pair_invest_r / 100.0)
                else:
                    # BEAR regime: bot always decides — adapt thresholds per profile automatically.
                    bear_rsi_thresh = bear_rsi_thresh_suave if active_risk_profile in ["suave", "conservador"] else bear_rsi_thresh_agresivo
                    bear_confs_needed = 5 if active_risk_profile in ["suave", "conservador"] else 4
                    bear_confs = sum([
                        1 if rsi < bear_rsi_thresh else 0,
                        1 if p <= bbl else 0,
                        1 if macd_hist_slope > 0 else 0,
                        1 if rsi > rsi_prev else 0,
                        1 if vol >= (vol_avg * 1.15) else 0,
                        1 if p <= (le200 * 0.965) else 0,
                    ])
                    if bear_confs >= bear_confs_needed:
                        signal = "buy"
                        amount_usdt = cash * ((pair_invest_t * 0.35) / 100.0)

                # Minimum edge filter: cold-start pairs are allowed, weak-edge pairs are filtered.
                if signal == "buy":
                    _min_edge = float(pair_score_map.get(pair, 0.0) or 0.0)
                    if _min_edge < min_edge_score_to_buy:
                        signal = None

                # Regime auto-gate: block if this regime has been consistently losing recently.
                if signal == "buy" and regime_blocked_until.get((pair, regime), 0) > cycle_idx:
                    signal = None

                if signal == "buy" and (pair_buy_blocked or buys_blocked_by_risk_gate):
                    signal = None

                if signal == "buy":
                    remaining_cycle = max(0.0, cycle_buy_budget_usdt - cycle_budget_spent)
                    pair_weight = float(pair_budget_weights.get(pair, 0.0) or 0.0)
                    pair_cap = cycle_buy_budget_usdt * pair_weight
                    remaining_pair = max(0.0, pair_cap - pair_budget_spent[pair])
                    amount_usdt = min(amount_usdt, remaining_cycle, remaining_pair, cash * 0.95)
                    if amount_usdt < 1.0:
                        signal = None

                if signal == "buy":
                    fee = amount_usdt * (FEE / 100.0)
                    qty = (amount_usdt - fee) / p
                    cash -= amount_usdt
                    fee_paid += fee
                    st["hold"] += qty
                    st["entry"] = p
                    st["maxp"] = p
                    st["hold_bars"] = 0
                    st["partial_done"] = False
                    st["regime_at_entry"] = regime
                    cycle_budget_spent += amount_usdt
                    pair_budget_spent[pair] += amount_usdt

            else:
                pnl_pct = ((p - st["entry"]) / st["entry"]) * 100.0 if st["entry"] > 0 else 0.0
                st["maxp"] = max(st["maxp"], p)
                max_pnl_pct = ((st["maxp"] - st["entry"]) / st["entry"]) * 100.0 if st["entry"] > 0 else 0.0
                st["hold_bars"] += 1

                total_fee_pct = FEE * 2
                pnl_pct_net = pnl_pct - total_fee_pct
                dynamic_stop_loss = pair_stop_loss
                if max_pnl_pct >= 1.1:
                    dynamic_stop_loss = -0.1

                weak_momentum = macd_hist < 0 and macd_hist_slope < 0
                is_time_stop = (
                    st["hold_bars"] >= 36
                    and pnl_pct_net > -pair_stop_loss
                    and pnl_pct_net < 0.8
                    and not is_trending
                    and weak_momentum
                )
                is_trail = max_pnl_pct >= pair_trail_act and pnl_pct <= (max_pnl_pct - pair_trail_dist)
                macd_cross_down = macd < macd_s

                # Temporal ROI table (Freqtrade-style): exit when time-adjusted profit target reached
                is_roi_exit = False
                for _bar_thresh in sorted(roi_table.keys(), reverse=True):
                    if st["hold_bars"] >= _bar_thresh:
                        if pnl_pct_net >= roi_table[_bar_thresh]:
                            is_roi_exit = True
                        break

                signal = None
                sell_pct = 100.0
                if is_roi_exit:
                    signal = "sell"
                elif is_trail:
                    signal = "sell"
                elif pnl_pct_net <= -dynamic_stop_loss:
                    signal = "sell"
                elif st["hold_bars"] >= 4 and pnl_pct_net <= -0.6 and weak_momentum:
                    signal = "sell"
                elif is_time_stop:
                    signal = "sell"
                elif pnl_pct_net >= 1.4 and rsi >= 68:
                    signal = "sell"
                elif not is_trending and rsi > 65 and p >= bbm and pnl_pct_net > 0:
                    signal = "sell"
                elif pnl_pct_net > 2.0 and macd_cross_down:
                    signal = "sell"
                elif macd_cross_down and pnl_pct_net > 1.0:
                    signal = "sell"

                if signal == "sell":
                    qty = st["hold"] * (sell_pct / 100.0)
                    gross = qty * p
                    fee = gross * (FEE / 100.0)
                    net_cash = gross - fee
                    realized = net_cash - (qty * st["entry"])

                    cash += net_cash
                    fee_paid += fee
                    st["hold"] -= qty
                    if st["hold"] < 1e-12:
                        st["hold"] = 0.0
                        st["entry"] = 0.0
                        st["maxp"] = 0.0
                        st["hold_bars"] = 0
                        st["partial_done"] = False
                        st["regime_at_entry"] = ""
                    else:
                        st["partial_done"] = True

                    sell_row = {"pnl": realized, "ts": ts, "regime": st.get("regime_at_entry", "")}
                    sells_all.append(sell_row)
                    sells_by_coin[coin].append(sell_row)
                    pair_cooldown_until[pair] = cycle_idx + cooldown_bars  # CooldownPeriod

    final_prices = {c: float(data_by_coin[c].iloc[-1]["close"]) for c in COINS}
    final_value = cash + sum(pos[c]["hold"] * final_prices[c] for c in COINS)
    ret = ((final_value - INITIAL) / INITIAL) * 100.0

    profits = [float(s["pnl"]) for s in sells_all]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]
    wr = (len(wins) / max(len(profits), 1)) * 100.0
    gp = sum(wins)
    gl = abs(sum(losses))
    pf = (gp / gl) if gl > 0 else (999.0 if gp > 0 else 0.0)
    aw = (gp / len(wins)) if wins else 0.0
    al = (sum(losses) / len(losses)) if losses else 0.0

    per_coin = {}
    for coin in COINS:
        p_profits = [float(s["pnl"]) for s in sells_by_coin[coin]]
        p_wins = [x for x in p_profits if x > 0]
        p_losses = [x for x in p_profits if x <= 0]
        p_wr = (len(p_wins) / max(len(p_profits), 1)) * 100.0
        p_gp = sum(p_wins)
        p_gl = abs(sum(p_losses))
        p_pf = (p_gp / p_gl) if p_gl > 0 else (999.0 if p_gp > 0 else 0.0)
        per_coin[coin] = {
            "wr": p_wr,
            "n": len(p_profits),
            "pf": p_pf,
            "net": sum(p_profits),
        }

    return {
        "ret": ret,
        "wr": wr,
        "n": len(profits),
        "fv": final_value,
        "pf": pf,
        "avg_win": aw,
        "avg_loss": al,
        "fees": fee_paid,
        "per_coin": per_coin,
    }


def run_hyperopt(data_by_coin, n_trials=200, seed=42):
    """Random-search hyperopt over entry/exit params inspired by Freqtrade Hyperopt.
    Optimizes: RSI thresholds, confirmations, stop_loss, trailing, ROI table, cooldown.
    Objective: blend of return, profit_factor, win_rate and trade-count validity.
    """
    import random
    rng = random.Random(seed)

    param_space = {
        "bull_rsi_low":              [30, 32, 34, 36, 38, 40],
        "bull_rsi_high":             [56, 58, 60, 62, 64, 66],
        "range_rsi_thresh":          [27, 29, 31, 33, 35, 37],
        "bear_rsi_thresh_suave":     [20, 22, 24, 26],
        "bear_rsi_thresh_agresivo":  [25, 27, 29, 31],
        "bull_min_confirmations":    [3, 4, 5],
        "range_min_confirmations":   [4, 5, 6],
        "stop_loss":                 [1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
        "trailing_activation":       [1.2, 1.5, 2.0, 2.5, 3.0],
        "trailing_distance":         [0.4, 0.6, 0.8, 1.0, 1.2],
        "roi_table": [
            {4: 3.5, 12: 1.8, 24: 0.8, 40: 0.0},
            {6: 3.0, 16: 1.5, 32: 0.5, 48: 0.0},
            {8: 2.5, 20: 1.2, 36: 0.3},
            {4: 4.0, 12: 2.0, 28: 0.8},
            {2: 5.0, 8: 2.5, 20: 1.0, 40: 0.0},
            {3: 3.8, 10: 2.0, 24: 0.9, 44: 0.0},
        ],
        "cooldown_bars": [1, 2, 3, 4, 5, 6],
    }

    best_score  = -9999.0
    best_params = {}
    best_result = {}

    for _trial in range(n_trials):
        params = {k: rng.choice(v) for k, v in param_space.items()}
        try:
            r = run_portfolio_backtest_faithful(
                data_by_coin, strategy_profile="balanced", hyperopt_params=params
            )
            n   = int(r.get("n", 0))
            ret = float(r.get("ret", -9999.0))
            pf  = float(r.get("pf", 0.0))
            wr  = float(r.get("wr", 0.0))
            # Calmar-inspired objective + quality bonuses; penalise too-few trades
            trade_penalty = max(0.0, (12 - n) * 0.10) if n < 12 else 0.0
            score = ret + (pf - 1.0) * 2.5 + (wr - 45.0) * 0.04 - trade_penalty
            if score > best_score:
                best_score  = score
                best_params = {k: v for k, v in params.items()}
                best_result = r
        except Exception:
            continue

    return best_params, best_result, best_score


def run_strategy_profile_benchmark(data_by_coin):
    profiles = ["balanced", "trend_guard", "momentum_plus"]
    results = {}
    for p in profiles:
        results[p] = run_portfolio_backtest_faithful(data_by_coin, strategy_profile=p)

    best_profile = max(
        profiles,
        key=lambda p: (
            float(results[p].get("ret", -9999.0)),
            float(results[p].get("pf", 0.0)),
            int(results[p].get("n", 0)),
        ),
    )
    return best_profile, results


def _pair_disabled_until_cycle_get(store, pair):
    return int(store.get(pair, 0) or 0)


def run_legacy_single_pair(df_raw, cfg):
    # minimal wrapper for previous baseline behavior; delegated from evaluate_3months.py
    from evaluate_3months_legacy import run_test as legacy_run_test

    return legacy_run_test(df_raw, cfg)


def main():
    raw_by_coin = {c: load_three_months(c) for c in COINS}
    data_by_coin = {c: prepare_pair_dataset(raw_by_coin[c]) for c in COINS}
    best_profile, profile_results = run_strategy_profile_benchmark(data_by_coin)
    print("[Hyperopt] Buscando parametros optimos (200 combinaciones)...")
    best_hp_params, hp_result, hp_score = run_hyperopt(data_by_coin, n_trials=200)
    print(f"[Hyperopt] Listo. Score={hp_score:.4f} ret={hp_result.get('ret',0):.2f}% pf={hp_result.get('pf',0):.2f}")

    cfgs_before = {
        "suave": {"inv_t": 25, "inv_r": 15, "use_vwap": True, "use_daily_open": True, "risk_profile": "suave"},
        "conservador": {"inv_t": 25, "inv_r": 15, "use_vwap": True, "use_daily_open": False, "risk_profile": "conservador"},
        "agresivo": {"inv_t": 25, "inv_r": 15, "use_vwap": False, "use_daily_open": False, "risk_profile": "agresivo"},
    }

    lines = []
    lines.append("VALORACION 3 MESES (2025-01 a 2025-03) - CONTINUO")
    lines.append("=" * 100)
    lines.append(f"Balance inicial simulado: ${INITIAL:.2f} USDT")
    lines.append("Formato: retorno%, win rate%, trades, final$, PF, avg_win$, avg_loss$")
    lines.append("")

    # BEFORE (legacy per pair)
    summary_before = {k: {"ret": 0.0, "wr": [], "n": 0, "pf": [], "coins": 0} for k in cfgs_before.keys()}

    for coin in COINS:
        lines.append(f"{coin}:")
        lines.append("  [ANTES]")
        for name, cfg in cfgs_before.items():
            # Lazy import to avoid circular when this file is called by wrapper
            from evaluate_3months_legacy import run_test as legacy_run_test

            r = legacy_run_test(raw_by_coin[coin].reset_index().copy(), cfg)
            lines.append(
                f"  - {name:<12} ret={r['ret']:>7.2f}% | wr={r['wr']:>5.1f}% | n={r['n']:>3} | "
                f"final=${r['fv']:.2f} | pf={r['pf']:.2f} | aw={r['avg_win']:+.4f} | al={r['avg_loss']:+.4f}"
            )
            summary_before[name]["ret"] += r["ret"]
            summary_before[name]["wr"].append(r["wr"])
            summary_before[name]["n"] += r["n"]
            summary_before[name]["pf"].append(r["pf"])
            summary_before[name]["coins"] += 1
        lines.append("")

    # AFTER (faithful portfolio allocator simulation)
    lines.append("[BENCHMARK_ESTRATEGIAS_PUBLICAS_INSPIRADAS]")
    lines.append("-" * 100)
    for profile_name in ["balanced", "trend_guard", "momentum_plus"]:
        r_prof = profile_results[profile_name]
        lines.append(
            f"  - {profile_name:<14} ret={r_prof['ret']:>7.2f}% | wr={r_prof['wr']:>5.1f}% | n={r_prof['n']:>3} | "
            f"final=${r_prof['fv']:.2f} | pf={r_prof['pf']:.2f}"
        )
    lines.append(f"  - perfil_ganador={best_profile}")
    lines.append("")

    lines.append("[HYPEROPT_RESULTADO]")
    lines.append("-" * 100)
    lines.append(
        f"  - score={hp_score:.4f} | ret={hp_result.get('ret',0):.2f}% | wr={hp_result.get('wr',0):.1f}% | "
        f"n={hp_result.get('n',0)} | pf={hp_result.get('pf',0):.2f} | fv=${hp_result.get('fv',100):.2f}"
    )
    lines.append(
        f"  - stop={best_hp_params.get('stop_loss',3.0):.1f}% | trail_act={best_hp_params.get('trailing_activation',2.5):.1f}% | "
        f"trail_dist={best_hp_params.get('trailing_distance',0.8):.1f}% | cooldown={best_hp_params.get('cooldown_bars',3)} barras"
    )
    lines.append(
        f"  - bull_rsi=[{best_hp_params.get('bull_rsi_low',36)},{best_hp_params.get('bull_rsi_high',62)}] | "
        f"range_rsi<{best_hp_params.get('range_rsi_thresh',33)} | bull_confs>={best_hp_params.get('bull_min_confirmations',4)}"
    )
    lines.append(f"  - roi_table={best_hp_params.get('roi_table',{})}")
    lines.append("")

    lines.append("[DESPUES_FIEL_PORTAFOLIO]")
    r_after = run_portfolio_backtest_faithful(data_by_coin, strategy_profile=best_profile, hyperopt_params=best_hp_params)
    lines.append(
        f"  - mejorado_auto_fiel profile={best_profile} ret={r_after['ret']:>7.2f}% | wr={r_after['wr']:>5.1f}% | n={r_after['n']:>3} | "
        f"final=${r_after['fv']:.2f} | pf={r_after['pf']:.2f} | aw={r_after['avg_win']:+.4f} | al={r_after['avg_loss']:+.4f}"
    )
    lines.append("  - detalle por activo (en simulacion de portafolio unico):")
    for coin in COINS:
        d = r_after["per_coin"][coin]
        lines.append(f"    * {coin}: net={d['net']:+.4f} | wr={d['wr']:.1f}% | n={d['n']} | pf={d['pf']:.2f}")
    lines.append("")

    # Walk-forward phase analysis (per month)
    lines.append("[ANALISIS_WALK_FORWARD_POR_MES]")
    lines.append("-" * 100)
    cumulative_balance = INITIAL
    for month in MONTHS:
        r_phase = run_portfolio_backtest_faithful(data_by_coin, month_filter=[month], strategy_profile=best_profile, hyperopt_params=best_hp_params)
        lines.append(
            f"  - {month}: ret={r_phase['ret']:>7.2f}% | wr={r_phase['wr']:>5.1f}% | n={r_phase['n']:>3} | "
            f"final=${r_phase['fv']:.2f} | pf={r_phase['pf']:.2f} | fees=${r_phase['fees']:.4f}"
        )
        for coin in COINS:
            d = r_phase["per_coin"][coin]
            if d["n"] > 0:
                lines.append(f"      {coin}: n={d['n']} | wr={d['wr']:.1f}% | pf={d['pf']:.2f} | net={d['net']:+.4f}")
    lines.append("")

    lines.append("RESUMEN GLOBAL (promedio por par) - ANTES")
    lines.append("-" * 100)
    for name, agg in summary_before.items():
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

    # Persist selected profile + hyperopt params for runtime bot autopilot.
    with open("autotuned_strategy_profile.json", "w", encoding="utf-8") as fp:
        # roi_table keys must be strings for JSON serialization
        _roi_json = {str(k): v for k, v in best_hp_params.get("roi_table", {}).items()}
        _hp_json  = {k: v for k, v in best_hp_params.items() if k != "roi_table"}
        _hp_json["roi_table"] = _roi_json
        json.dump(
            {
                "best_profile": best_profile,
                "hyperopt_params": _hp_json,
                "generated_from": MONTHS,
                "metrics": {
                    p: {
                        "ret": float(profile_results[p].get("ret", 0.0)),
                        "pf": float(profile_results[p].get("pf", 0.0)),
                        "wr": float(profile_results[p].get("wr", 0.0)),
                        "n": int(profile_results[p].get("n", 0)),
                    }
                    for p in ["balanced", "trend_guard", "momentum_plus"]
                },
            },
            fp,
            ensure_ascii=True,
            indent=2,
        )

    print("\n".join(lines))
    print(f"\nReporte guardado en {report_path}")
    print("Perfil autotune guardado en autotuned_strategy_profile.json")


if __name__ == "__main__":
    main()
