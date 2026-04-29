import random
from evaluate_3months import COINS, load_three_months, run_test

random.seed(42)

datasets = {c: load_three_months(c) for c in COINS}

best = []
for i in range(30):
    cfg = {
        "risk_profile": "conservador",
        "inv_t": random.choice([8, 10, 12, 15, 18, 20]),
        "inv_r": random.choice([5, 8, 10, 12]),
        "sl": random.choice([1.8, 2.0, 2.2, 2.5, 3.0]),
        "tp": random.choice([1.2, 1.5, 1.8, 2.0, 2.5]),
        "prev": random.choice([0.6, 0.8, 1.0, 1.2]),
        "trail_act": random.choice([1.0, 1.2, 1.5, 1.8, 2.2]),
        "trail_dist": random.choice([0.25, 0.35, 0.5, 0.65, 0.8]),
        "use_vwap": random.choice([True, False]),
        "use_daily_open": random.choice([True, False]),
    }

    rets = []
    wrs = []
    trades = 0
    pfs = []
    for coin, df in datasets.items():
        r = run_test(df, cfg)
        rets.append(r["ret"])
        wrs.append(r["wr"])
        trades += r["n"]
        pfs.append(r["pf"])

    score = sum(rets) / len(rets)
    best.append((score, sum(wrs) / len(wrs), trades, sum(pfs) / len(pfs), cfg))

best.sort(key=lambda x: x[0], reverse=True)

print("TOP 10 CONFIGS (3M avg return across BTC/ETH/SOL)")
for rank, row in enumerate(best[:10], 1):
    score, wr, n, pf, cfg = row
    print(f"{rank:02d}. ret_prom={score:+.2f}% | wr_prom={wr:.1f}% | trades={n} | pf_prom={pf:.2f} | cfg={cfg}")
