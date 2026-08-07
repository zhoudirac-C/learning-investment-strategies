import pandas as pd
for f in ["/home/ubuntu/.kimi-code/plugins/managed/kimi-datasource/temp/batch_hist_chip_a.csv","/home/ubuntu/.kimi-code/plugins/managed/kimi-datasource/temp/batch_hist_chip_b.csv"]:
    df = pd.read_csv(f)
    for code, g in df.groupby("thscode"):
        g = g.sort_values("time")
        name = g["thsname_cn"].iloc[0]
        last = g.tail(15)
        ma20 = g["close"].tail(20).mean()
        ma60 = g["close"].tail(60).mean()
        print(f"{code} {name} last_close={g['close'].iloc[-1]:.2f} date={g['time'].iloc[-1]}")
        print(f"  15d: high={last['high'].max():.2f} low={last['low'].min():.2f}  ma20={ma20:.2f} ma60={ma60:.2f}")
        print("  last10:", ", ".join(f"{r.time}:{r.close:.2f}" for r in g.tail(10).itertuples()))
