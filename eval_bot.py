import pandas as pd, numpy as np, sys, glob, os
sys.path.insert(0, r"d:\10-Cripto\Bot Tradding con IA - API 2")
from indicators import compute_ema, compute_adx, compute_bollinger_bands, compute_rsi, compute_macd, compute_vwap

INITIAL = 100.0
FEE = 0.2  # 0.2% comision del exchange

csvs = glob.glob(r"D:\01-Descargas\Historicos\*.csv")
print(f"Ejecutando simulador en {len(csvs)} mercados historicos (Enero 2025)...")

def run_simulation(csv_path):
    print(f"\n---------------------------------------------")
    print(f"Testeando: {os.path.basename(csv_path)}")
    df_raw = pd.read_csv(csv_path)
    df_raw["datetime"] = pd.to_datetime(df_raw["timestamp"], unit="s")
    df_raw = df_raw.sort_values("datetime").reset_index(drop=True)
    df_raw.set_index("datetime", inplace=True)
    
    # Velas de 15m
    df = df_raw.resample("15min").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna().reset_index()
    
    # Indicadores
    ef7 = compute_ema(df["close"], 7)
    ef30 = compute_ema(df["close"], 30)
    ema50 = compute_ema(df["close"], 50)
    ema200 = compute_ema(df["close"], 200)
    ema800 = compute_ema(df["close"], 800) # Proxy para EMA200 de 1 Hora
    adx = compute_adx(df["high"], df["low"], df["close"], 14)
    bbu, bbm, bbl = compute_bollinger_bands(df["close"], 20, 2.0)
    rsi = compute_rsi(df["close"], 14)
    ml, ms_s, _ = compute_macd(df["close"])
    vwap = compute_vwap(df)
    
    cap = INITIAL; hold = 0.0; ep = 0.0; mp = 0.0; trades = []
    inv = 50.0  # Usar 50% de la cuenta (Perfil Agresivo)
    
    for i in range(800, len(df)):
        p = float(df["close"].iloc[i]); dt = df["datetime"].iloc[i]
        lef=float(ef7.iloc[i]); les=float(ef30.iloc[i])
        le50=float(ema50.iloc[i]); le200=float(ema200.iloc[i]); le800=float(ema800.iloc[i])
        la=float(adx.iloc[i])
        lr=float(rsi.iloc[i]) if not pd.isna(rsi.iloc[i]) else 50.0
        lbl_v=float(bbl.iloc[i]); lbm_v=float(bbm.iloc[i])
        lm=float(ml.iloc[i]) if not pd.isna(ml.iloc[i]) else 0; lms=float(ms_s.iloc[i]) if not pd.isna(ms_s.iloc[i]) else 0
        lvwap=float(vwap.iloc[i])
        
        lg=lef-les; itr=la>25; mcd=lm<lms; hp=(hold*p)>1.0
        is_bull = p > le200 and le50 > le200
        is_bear = p < le200 and le50 < le200
        macro_pass = p > le800 and le200 > le800
        
        sig=None
        if not hp:
            if itr:
                # Comprar retrocesos a la EMA Lenta (30) con FILTRO MACRO
                if is_bull and lef>les and p<=(les*1.002) and macro_pass and cap*(inv/100)>1.0: sig="buy"
                elif is_bear and lr<15 and p<=lbl_v and cap*(inv/100)>1.0: sig="buy" # Rebote pánico extremo
            else:
                if lr<25 and p<=lbl_v*0.998 and p<lvwap and cap*(inv/100)>1.0: sig="buy"
        else:
            pnl=((p-ep)/ep)*100; mp=max(mp,p); mpnl=((mp-ep)/ep)*100
            
            # Filtro Panico
            tstop = False; t_reason = ""
            if pnl <= -1.0:
                if itr and p < le50: tstop = True; t_reason = "PANICO_TENDENCIA"
                elif not itr and p < (lbl_v * 0.995): tstop = True; t_reason = "PANICO_RANGO"
                
            # Break-Even
            dynamic_sl = 4.0
            if mpnl >= 1.5: dynamic_sl = -0.1
            
            if mpnl >= 2.5 and pnl <= (mpnl - 0.8): sig="sell"; st="TRAILING"
            elif tstop: sig="sell"; st=t_reason
            elif pnl <= -dynamic_sl: sig="sell"; st="EMERGENCIA_SL_O_BE"
            elif not itr and lr > 65 and p >= lbm_v and pnl > 0.5: sig="sell"; st="EXITO_RANGO"
            elif pnl > 2.5 and mcd: sig="sell"; st="EXITO_TENDENCIA"
            elif mcd and pnl > 1.5: sig="sell"; st="PREVENTIVO_EXITO"
            
        if sig=="buy":
            ia=cap*(inv/100); f=ia*(FEE/100); hold=(ia-f)/p; cap-=ia; ep=p; mp=p
        elif sig=="sell":
            sv=hold*p; f=sv*(FEE/100) 
            cap+=sv-f; pu=(sv-f)-(hold*ep); pp=((sv-f - hold*ep)/(hold*ep))*100
            trades.append(dict(side="sell",pnl=pu,pnl_pct=pp,date=str(dt)[:16],price=p,reason=st))
            hold=0; ep=0; mp=0
            
    fv=cap+hold*float(df["close"].iloc[-1])
    ret=((fv-INITIAL)/INITIAL)*100
    wins=[t for t in trades if t.get("pnl",0)>0]
    losses=[t for t in trades if t.get("pnl",0)<=0]
    aw = np.mean([t["pnl_pct"] for t in wins]) if wins else 0
    al = np.mean([t["pnl_pct"] for t in losses]) if losses else 0
    wr = len(wins)/max(len(trades),1)*100
    
    print(f"Rentabilidad Neta: {ret:+.2f}%")
    print(f"Total Trades: {len(trades)}")
    if len(trades) > 0:
        print(f"WinRate (Acierto): {wr:.1f}%")
        print(f"Ganancia Promedio: +{aw:.2f}%")
        print(f"Perdida Promedio: {al:.2f}%")
        
    return ret, fv

overall = 0
for c in csvs:
    r, fv = run_simulation(c)
    overall += r

print(f"\n===========================================")
if len(csvs) > 0:
    print(f"RENTABILIDAD PROMEDIO GLOBAL PERIODO: {overall/len(csvs):+.2f}% MENSUAL (Enero 2025)")
    print(f"===========================================")
