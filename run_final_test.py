import pandas as pd, numpy as np, sys, glob, os
sys.path.insert(0, r"D:\10-Cripto\Bot Tradding con IA - API 2")
from indicators import compute_ema, compute_adx, compute_bollinger_bands, compute_rsi, compute_macd, compute_volume_avg, compute_vwap, compute_daily_open

FILES = glob.glob(r"D:\01-Descargas\Historicos\*.csv")
INITIAL = 66.0; FEE = 0.1

def run_test(df_raw, config):
    df_raw["datetime"] = pd.to_datetime(df_raw["timestamp"], unit="s")
    df_raw = df_raw.sort_values("datetime").reset_index(drop=True)
    df_raw.set_index("datetime", inplace=True)

    df = df_raw.resample("15min").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna().reset_index()
    df_1h = df_raw.resample("1h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna().reset_index()

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

    ema50_1h = compute_ema(df_1h["close"], 50)
    ema200_1h = compute_ema(df_1h["close"], 200)

    def get_macro_uptrend(dt):
        mask = df_1h["datetime"] <= dt
        if mask.sum() == 0: return True
        idx = mask.sum() - 1
        return float(df_1h["close"].iloc[idx]) > float(ema200_1h.iloc[idx]) and float(ema50_1h.iloc[idx]) > float(ema200_1h.iloc[idx])

    cap = INITIAL; hold = 0.0; ep = 0.0; mp = 0.0; fees = 0.0; trades = []
    sl = config.get("sl", 3.0); tp = config.get("tp", 2.5); prev = config.get("prev", 1.0)
    trail_act = config.get("trail_act", 1.5); trail_dist = config.get("trail_dist", 0.5)
    inv_t = config.get("inv_t", 25); inv_r = config.get("inv_r", 15)
    use_ema200 = config.get("use_ema200", True)
    use_vol_filter = config.get("use_vol_filter", True)
    use_macro = config.get("use_macro", True)
    use_vwap = config.get("use_vwap", False)
    use_daily_open = config.get("use_daily_open", False)
    rsi_max_buy = 65
    
    for i in range(200, len(df)):
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
        lvwap = float(vwap.iloc[i]); ldaily = float(daily_open.iloc[i])
        lg=lef-les; pg=pef-pes; itr=la>25; hp=(hold*p)>1.0; mcd=lm<lms
        macro_ok = get_macro_uptrend(dt) if use_macro else True
        
        sig=None; st=""
        if not hp:
            if itr:
                if lef>les and p<=(lef*1.005):
                    blocked = False
                    if use_ema200 and p < le200: blocked = True
                    if lr > rsi_max_buy: blocked = True
                    if use_vol_filter and lv < lva: blocked = True
                    if use_macro and not macro_ok: blocked = True
                    if use_vwap and p < lvwap: blocked = True
                    if use_daily_open and p < ldaily: blocked = True
                    if not blocked and cap*(inv_t/100)>1.0: sig="buy"; st="EMA"
            else:
                if lr<35 and p<=lbl_v*1.002:
                    blocked = False
                    if use_vol_filter and lv < lva * 0.5: blocked = True
                    if use_vwap and p < lvwap: blocked = True
                    if use_daily_open and p < ldaily: blocked = True
                    if not blocked and cap*(inv_r/100)>1.0: sig="buy"; st="MR"
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
            cap+=sv-f
            trades.append(dict(side="sell",pnl=pu,pnl_pct=pp,strat="?",pv=cap,date=str(dt)[:16],price=p))
            hold=0; ep=0; mp=0
    
    fv=cap+hold*float(df["close"].iloc[-1])
    ret=((fv-INITIAL)/INITIAL)*100
    sells=[t for t in trades if t["side"]=="sell"]
    wins=[t for t in sells if t.get("pnl",0)>0]
    return {"ret": ret, "wr": len(wins)/max(len(sells),1)*100, "n": len(sells), "fv": fv}

L = []
L.append("RESUMEN DE ESTRATEGIA: Conservador vs Conservador + Filtros Diarios (Diciembre 2025)")
L.append("="*80)

# Configuraciones
cfg_base = {"inv_t": 25, "inv_r": 15, "use_macro": True, "use_ema200": True, "use_vol_filter": True, "use_vwap": False, "use_daily_open": False}
cfg_diario = {"inv_t": 25, "inv_r": 15, "use_macro": True, "use_ema200": True, "use_vol_filter": True, "use_vwap": True, "use_daily_open": True}

for f in FILES:
    coin = os.path.basename(f).split("-")[0]
    df_raw = pd.read_csv(f)
    print(f"Evaluando {coin}...")
    
    res_base = run_test(df_raw.copy(), cfg_base)
    res_diario = run_test(df_raw.copy(), cfg_diario)
    
    L.append(f"\n🪙 {coin} - Mercado bajista/alta volatilidad")
    L.append(f"  > Conservador Clásico:")
    L.append(f"    {'Retorno:':<10} {res_base['ret']:>7.2f}% | Win Rate: {res_base['wr']:>5.1f}% | Trades: {res_base['n']:>3} | Final: ${res_base['fv']:.2f}")
    L.append(f"  > Conservador + VWAP + Daily Open (PRODUCCIÓN):")
    L.append(f"    {'Retorno:':<10} {res_diario['ret']:>7.2f}% | Win Rate: {res_diario['wr']:>5.1f}% | Trades: {res_diario['n']:>3} | Final: ${res_diario['fv']:.2f}")

with open("resumen_final_diciembre.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(L))
print("Finalizado. Resultado en resumen_final_diciembre.txt")
