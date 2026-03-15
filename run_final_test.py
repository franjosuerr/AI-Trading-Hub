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
    ema50 = compute_ema(df["close"], 50)
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
    hold_time_candles = 0
    sl = config.get("sl", 3.0); tp = config.get("tp", 2.5); prev = config.get("prev", 1.0)
    trail_act = config.get("trail_act", 2.5); trail_dist = config.get("trail_dist", 0.8)
    inv_t = config.get("inv_t", 25); inv_r = config.get("inv_r", 15)
    use_vwap = config.get("use_vwap", False)
    use_daily_open = config.get("use_daily_open", False)
    risk_profile = config.get("risk_profile", "conservador")
    
    for i in range(200, len(df)):
        p = float(df["close"].iloc[i])
        dt = df["datetime"].iloc[i]
        lef=float(ef7.iloc[i]); pef=float(ef7.iloc[i-1])
        les=float(ef30.iloc[i]); pes=float(ef30.iloc[i-1])
        le50=float(ema50.iloc[i])
        le200=float(ema200.iloc[i])
        la=float(adx.iloc[i]); lr=float(rsi.iloc[i]) if not pd.isna(rsi.iloc[i]) else 50.0
        lbm_v=float(bbm.iloc[i]); lbl_v=float(bbl.iloc[i])
        lm=float(ml.iloc[i]) if not pd.isna(ml.iloc[i]) else 0
        lms=float(ms_s.iloc[i]) if not pd.isna(ms_s.iloc[i]) else 0
        lv=float(df["volume"].iloc[i]); lva=float(vol_avg.iloc[i])
        lvwap = float(vwap.iloc[i]); ldaily = float(daily_open.iloc[i])
        lg=lef-les; pg=pef-pes; hp=(hold*p)>1.0; mcd=lm<lms
        macro_ok = get_macro_uptrend(dt)
        volume_ok = lv > lva
        
        # Detector de Régimen
        is_trending = la >= 25
        regime = "RANGO"
        if is_trending:
            if p > le200 and le50 > le200:
                regime = "BULL"
            elif p < le200 and le50 < le200:
                regime = "BEAR"
            
        sig=None; st=""
        if not hp:
            filter_vwap_pass = True if not use_vwap else (p > lvwap)
            filter_daily_pass = True if not use_daily_open else (p > ldaily)
            filter_vol_pass = True if risk_profile in ["muy_agresivo", "agresivo"] else volume_ok
            filter_macro_pass = True if risk_profile in ["muy_agresivo", "agresivo"] else macro_ok

            rsi_rango_threshold = 25
            if risk_profile == "suave": rsi_rango_threshold = 20
            elif risk_profile == "agresivo": rsi_rango_threshold = 28
            elif risk_profile == "muy_agresivo": rsi_rango_threshold = 30
            
            if regime == "BULL":
                is_uptrend_local = lef > les
                is_pullback = p <= (lef * 1.005)
                
                if is_uptrend_local and is_pullback:
                    if risk_profile == "suave" and (not filter_vwap_pass or not filter_daily_pass or not filter_vol_pass or not filter_macro_pass):
                        pass
                    elif risk_profile == "conservador" and (not filter_vwap_pass or not filter_macro_pass):
                        pass
                    else:
                        if cap*(inv_t/100)>1.0: sig="buy"; st="BULL-TF"
                        
            elif regime == "BEAR":
                if risk_profile not in ["suave", "conservador"]:
                    rsi_rebote_extremo = 15 if risk_profile == "agresivo" else 20
                    is_oversold_brutal = lr < rsi_rebote_extremo
                    is_at_bb_lower = p <= lbl_v
                    
                    if is_oversold_brutal and is_at_bb_lower:
                        if cap*(inv_t/100)>1.0: sig="buy"; st="BEAR-REV"

            elif regime == "RANGO":
                is_oversold = lr < rsi_rango_threshold
                is_at_bb_lower = p <= lbl_v * 1.002
                
                if is_oversold and is_at_bb_lower:
                    if risk_profile == "suave" and (not filter_vwap_pass or not filter_daily_pass):
                        pass
                    else:
                        if cap*(inv_r/100)>1.0: sig="buy"; st="RANGO-MR"
        else:
            pnl=((p-ep)/ep)*100; mp=max(mp,p); mpnl=((mp-ep)/ep)*100
            
            # Evaluar Break-Even Dinámico
            dynamic_stop_loss = sl
            if mpnl >= 1.2:
                dynamic_stop_loss = -0.1

            # Calcular Hold Time (velas) y Evaluar Time-Stop
            time_stop = False
            hold_time_candles += 1
            if hold_time_candles >= 24 and pnl > -sl and pnl < 1.0 and not is_trending: # 6 horas en velas de 15m
                time_stop = True

            if mpnl>=trail_act and pnl<=(mpnl-trail_dist): sig="sell"
            elif pnl<=-dynamic_stop_loss: sig="sell"
            elif time_stop: sig="sell"
            elif not is_trending and lr>65 and p>=lbm_v and pnl>0: sig="sell"
            elif pnl>tp and (lg<pg or mcd): sig="sell"
            elif mcd and pnl>prev: sig="sell"
        
        if sig=="buy":
            ip=inv_t if is_trending else inv_r; ia=cap*(ip/100); f=ia*(FEE/100); fees+=f
            hold=(ia-f)/p; cap-=ia; ep=p; mp=p; hold_time_candles=0
            trades.append(dict(side="buy",strat=st,pv=cap+hold*p,date=str(dt)[:16],price=p))
        elif sig=="sell":
            sv=hold*p; f=sv*(FEE/100); fees+=f; pu=(sv-f)-(hold*ep); pp=((p-ep)/ep)*100
            cap+=sv-f
            trades.append(dict(side="sell",pnl=pu,pnl_pct=pp,strat="?",pv=cap,date=str(dt)[:16],price=p))
            hold=0; ep=0; mp=0; hold_time_candles=0
    
    fv=cap+hold*float(df["close"].iloc[-1])
    ret=((fv-INITIAL)/INITIAL)*100
    sells=[t for t in trades if t["side"]=="sell"]
    wins=[t for t in sells if t.get("pnl",0)>0]
    return {"ret": ret, "wr": len(wins)/max(len(sells),1)*100, "n": len(sells), "fv": fv}

L = []
L.append("RESUMEN DE ESTRATEGIA: Evaluación de Enero 2025 (Tendencia y Rango)")
L.append("="*80)

# Configuraciones
cfg_suave = {"inv_t": 25, "inv_r": 15, "use_vwap": True, "use_daily_open": True, "risk_profile": "suave"}
cfg_cons = {"inv_t": 25, "inv_r": 15, "use_vwap": True, "use_daily_open": False, "risk_profile": "conservador"}
cfg_agres = {"inv_t": 25, "inv_r": 15, "use_vwap": False, "use_daily_open": False, "risk_profile": "agresivo"}

for f in FILES:
    coin = os.path.basename(f).split("-")[0]
    df_raw = pd.read_csv(f)
    print(f"Evaluando {coin}...")
    
    res_suave = run_test(df_raw.copy(), cfg_suave)
    res_cons = run_test(df_raw.copy(), cfg_cons)
    res_agr = run_test(df_raw.copy(), cfg_agres)
    
    L.append(f"\n🪙 {coin} - Evaluación de Perfiles de Riesgo")
    L.append(f"  > Perfil SUAVE (Bloqueo Extremo):")
    L.append(f"    {'Retorno:':<10} {res_suave['ret']:>7.2f}% | Win Rate: {res_suave['wr']:>5.1f}% | Trades: {res_suave['n']:>3} | Final: ${res_suave['fv']:.2f}")
    L.append(f"  > Perfil CONSERVADOR (Default Recomendado):")
    L.append(f"    {'Retorno:':<10} {res_cons['ret']:>7.2f}% | Win Rate: {res_cons['wr']:>5.1f}% | Trades: {res_cons['n']:>3} | Final: ${res_cons['fv']:.2f}")
    L.append(f"  > Perfil AGRESIVO (Actividad Elevada):")
    L.append(f"    {'Retorno:':<10} {res_agr['ret']:>7.2f}% | Win Rate: {res_agr['wr']:>5.1f}% | Trades: {res_agr['n']:>3} | Final: ${res_agr['fv']:.2f}")

with open("resumen_final_enero.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(L))
print("Finalizado. Resultado en resumen_final_enero.txt")
