"""
Backtest v2 - Testing strategy improvements
Key additions:
1. EMA 200 macro filter on 15m (no buy below EMA200)
2. RSI overbought filter (no buy when RSI > 65 for EMA)
3. Volume confirmation (only buy when volume > avg)
4. Simulated 1h macro filter (EMA50 > EMA200 on hourly)
"""
import pandas as pd, numpy as np, sys
sys.path.insert(0, r"D:\10-Cripto\Bot Tradding con IA - API 2")
from indicators import compute_ema, compute_adx, compute_bollinger_bands, compute_rsi, compute_macd, compute_volume_avg, compute_vwap, compute_daily_open

CSV = r"D:\01-Descargas\Historicos\BTCUSDT-Kline-MINUTE-Spot-2025-12.csv"
INITIAL = 66.0; FEE = 0.1

# Load and resample
df_raw = pd.read_csv(CSV)
df_raw["datetime"] = pd.to_datetime(df_raw["timestamp"], unit="s")
df_raw = df_raw.sort_values("datetime").reset_index(drop=True)
df_raw.set_index("datetime", inplace=True)

# 15m candles for trading
df = df_raw.resample("15min").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna().reset_index()
# 1h candles for macro filter
df_1h = df_raw.resample("1h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna().reset_index()

# Indicators on 15m
ef7 = compute_ema(df["close"], 7)
ef30 = compute_ema(df["close"], 30)
ema200 = compute_ema(df["close"], 200)
adx = compute_adx(df["high"], df["low"], df["close"], 14)
bbu, bbm, bbl = compute_bollinger_bands(df["close"], 20, 2.0)
rsi = compute_rsi(df["close"], 14)
ml, ms_s, _ = compute_macd(df["close"])
vol_avg = compute_volume_avg(df["volume"], 20)
vwap = compute_vwap(df)
daily_open = compute_daily_open(df)

# Macro indicators on 1h
ema50_1h = compute_ema(df_1h["close"], 50)
ema200_1h = compute_ema(df_1h["close"], 200)

def get_macro_uptrend(dt):
    """Check if the 1h macro filter says uptrend at a given time."""
    mask = df_1h["datetime"] <= dt
    if mask.sum() == 0:
        return True
    idx = mask.sum() - 1
    c = float(df_1h["close"].iloc[idx])
    e50 = float(ema50_1h.iloc[idx])
    e200 = float(ema200_1h.iloc[idx])
    return c > e200 and e50 > e200

def run(config):
    """Run backtest with given config dict."""
    cap = INITIAL; hold = 0.0; ep = 0.0; mp = 0.0; fees = 0.0; trades = []
    sl = config.get("sl", 3.0)
    tp = config.get("tp", 2.5)
    prev = config.get("prev", 1.0)
    trail_act = config.get("trail_act", 1.5)
    trail_dist = config.get("trail_dist", 0.5)
    inv_t = config.get("inv_t", 25)
    inv_r = config.get("inv_r", 15)
    use_ema200 = config.get("use_ema200", False)
    use_rsi_guard = config.get("use_rsi_guard", False)
    use_vol_filter = config.get("use_vol_filter", False)
    use_macro = config.get("use_macro", False)
    use_vwap = config.get("use_vwap", False)
    use_daily_open = config.get("use_daily_open", False)
    rsi_max_buy = config.get("rsi_max_buy", 65)
    
    for i in range(200, len(df)):  # Start at 200 for EMA200                
        p = float(df["close"].iloc[i])
        dt = df["datetime"].iloc[i]
        lef=float(ef7.iloc[i]); pef=float(ef7.iloc[i-1])
        les=float(ef30.iloc[i]); pes=float(ef30.iloc[i-1])
        le200=float(ema200.iloc[i])
        la=float(adx.iloc[i]); lr=float(rsi.iloc[i]) if not pd.isna(rsi.iloc[i]) else 50.0
        lbm_v=float(bbm.iloc[i]); lbl_v=float(bbl.iloc[i])
        lm=float(ml.iloc[i]) if not pd.isna(ml.iloc[i]) else 0
        lms=float(ms_s.iloc[i]) if not pd.isna(ms_s.iloc[i]) else 0
        lv=float(df["volume"].iloc[i]); lva=float(vol_avg.iloc[i])
        lvwap = float(vwap.iloc[i])
        ldaily = float(daily_open.iloc[i])
        lg=lef-les; pg=pef-pes; itr=la>25; hp=(hold*p)>1.0; mcd=lm<lms
        
        # Macro check
        macro_ok = True
        if use_macro:
            macro_ok = get_macro_uptrend(dt)
        
        sig=None; st=""
        if not hp:
            if itr:
                # EMA Crossover buy
                if lef>les and p<=(lef*1.005):
                    blocked = False
                    if use_ema200 and p < le200:
                        blocked = True
                    if use_rsi_guard and lr > rsi_max_buy:
                        blocked = True
                    if use_vol_filter and lv < lva:
                        blocked = True
                    if use_macro and not macro_ok:
                        blocked = True
                    if use_vwap and p < lvwap:
                        blocked = True
                    if use_daily_open and p < ldaily:
                        blocked = True
                    if not blocked and cap*(inv_t/100)>1.0:
                        sig="buy"; st="EMA"
            else:
                # Mean Reversion buy
                if lr<35 and p<=lbl_v*1.002:
                    blocked = False
                    if use_vol_filter and lv < lva * 0.5:  # Relaxed for MR
                        blocked = True
                    if use_vwap and p < lvwap:
                        blocked = True
                    if use_daily_open and p < ldaily:
                        blocked = True
                    if not blocked and cap*(inv_r/100)>1.0:
                        sig="buy"; st="MR"
        else:
            pnl=((p-ep)/ep)*100; mp=max(mp,p); mpnl=((mp-ep)/ep)*100
            if mpnl>=trail_act and pnl<=(mpnl-trail_dist): sig="sell"
            elif pnl<=-sl: sig="sell"
            elif not itr and lr>65 and p>=lbm_v and pnl>0: sig="sell"
            elif pnl>tp and (lg<pg or mcd): sig="sell"
            elif mcd and pnl>prev: sig="sell"
        
        if sig=="buy":
            ip=inv_t if itr else inv_r; ia=cap*(ip/100); f=ia*(FEE/100); fees+=f
            hold=(ia-f)/p; cap-=ia; ep=p; mp=p
            trades.append(dict(side="buy",strat=st,pv=cap+hold*p,date=str(dt)[:16],price=p))
        elif sig=="sell":
            sv=hold*p; f=sv*(FEE/100); fees+=f; pu=(sv-f)-(hold*ep); pp=((p-ep)/ep)*100
            cap+=sv-f; ls=trades[-1]["strat"] if trades else "?"
            trades.append(dict(side="sell",pnl=pu,pnl_pct=pp,strat=ls,pv=cap,date=str(dt)[:16],price=p))
            hold=0; ep=0; mp=0
    
    fv=cap+hold*float(df["close"].iloc[-1])
    ret=((fv-INITIAL)/INITIAL)*100
    sells=[t for t in trades if t["side"]=="sell"]
    wins=[t for t in sells if t.get("pnl",0)>0]
    losses=[t for t in sells if t.get("pnl",0)<=0]
    ema_t=[t for t in sells if t.get("strat")=="EMA"]
    mr_t=[t for t in sells if t.get("strat")=="MR"]
    pvs=[INITIAL]+[t["pv"] for t in trades]; peak=pvs[0]; mdd=0
    for v in pvs:
        if v>peak: peak=v
        dd=(peak-v)/peak*100
        if dd>mdd: mdd=dd
    
    aw = np.mean([t["pnl"] for t in wins]) if wins else 0
    al = np.mean([t["pnl"] for t in losses]) if losses else 0
    return dict(ret=ret, wr=len(wins)/max(len(sells),1)*100, n=len(sells), fv=fv, fees=fees, mdd=mdd,
                wins=len(wins), losses=len(losses), aw=aw, al=al,
                ema_n=len(ema_t), ema_w=len([t for t in ema_t if t.get("pnl",0)>0]), ema_pnl=sum(t.get("pnl",0) for t in ema_t),
                mr_n=len(mr_t), mr_w=len([t for t in mr_t if t.get("pnl",0)>0]), mr_pnl=sum(t.get("pnl",0) for t in mr_t),
                trades=trades)

# Test configurations
configs = {
    "ORIGINAL (sin mejoras)": dict(tp=2.5, prev=1.0),
    "+ EMA200 filter": dict(tp=2.5, prev=1.0, use_ema200=True),
    "EMA200 + Macro": dict(tp=2.5, prev=1.0, use_ema200=True, use_macro=True),
    "EMA200 + Macro + Vol + RSI": dict(tp=2.5, prev=1.0, use_ema200=True, use_macro=True, use_vol_filter=True, use_rsi_guard=True),
    "=== INTRADAY FILTERS ===": dict(tp=2.5, prev=1.0),
    "Macro + Daily Open": dict(tp=2.5, prev=1.0, use_macro=True, use_daily_open=True, use_ema200=True),
    "Macro + VWAP": dict(tp=2.5, prev=1.0, use_macro=True, use_vwap=True, use_ema200=True),
    "Macro + VWAP + Daily Open": dict(tp=2.5, prev=1.0, use_macro=True, use_vwap=True, use_daily_open=True, use_ema200=True),
    "ALL FILTERS (MAX SAFEST)": dict(tp=2.5, prev=1.0, use_ema200=True, use_macro=True, use_vwap=True, use_daily_open=True, use_vol_filter=True, use_rsi_guard=True),
}

L = []
L.append("BTC/USDT DAY-TRADING FILTERS BACKTEST - January 2026")
L.append("Period: %s to %s" % (df["datetime"].iloc[0], df["datetime"].iloc[-1]))
L.append("Candles: %d (15m) | Price: $%.0f - $%.0f" % (len(df), df["close"].min(), df["close"].max()))
L.append("BTC bajando en enero: Probando VWAP y Daily Open")
L.append("="*100)
L.append("")
L.append("%-25s %8s %7s %6s %8s %7s %8s %8s %10s %10s" % 
    ("Config", "Return", "WinR", "Trades", "Final$", "MaxDD", "AvgWin", "AvgLoss", "EMA P&L", "MR P&L"))
L.append("-"*100)

for name, cfg in configs.items():
    r = run(cfg)
    L.append("%-25s %+7.2f%% %5.1f%% %5d  $%6.2f %5.2f%%  $%+.4f $%+.4f  $%+.4f  $%+.4f" %
        (name, r["ret"], r["wr"], r["n"], r["fv"], r["mdd"], r["aw"], r["al"], r["ema_pnl"], r["mr_pnl"]))

# Show details for the best
best_name = max(configs.keys(), key=lambda k: run(configs[k])["ret"])
best_r = run(configs[best_name])
L.append("")
L.append("MEJOR CONFIG: %s" % best_name)
L.append("  Return: %+.2f%% | Win Rate: %.1f%% | Trades: %d" % (best_r["ret"], best_r["wr"], best_r["n"]))
L.append("  EMA: %d trades (W:%d) PnL=$%+.4f" % (best_r["ema_n"], best_r["ema_w"], best_r["ema_pnl"]))
L.append("  MR:  %d trades (W:%d) PnL=$%+.4f" % (best_r["mr_n"], best_r["mr_w"], best_r["mr_pnl"]))
L.append("")
L.append("--- Last 15 trades (best config) ---")
for t in best_r["trades"][-15:]:
    s="BUY " if t["side"]=="buy" else "SELL"
    pstr=" PnL=$%+.4f(%+.1f%%)" % (t.get("pnl",0), t.get("pnl_pct",0)) if t["side"]=="sell" else ""
    L.append("  %s | %s @$%.0f [%s]%s PV=$%.2f" % (t["date"], s, t["price"], t.get("strat","?"), pstr, t["pv"]))

out = "\n".join(L)
with open(r"D:\10-Cripto\Bot Tradding con IA - API 2\intraday_filters_backtest.txt", "w", encoding="utf-8") as f:
    f.write(out)
print("DONE - results in intraday_filters_backtest.txt")
