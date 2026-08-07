import pandas as pd

files = ["temp/pcb_batch_hist_a.csv", "temp/pcb_batch_hist_b.csv", "temp/pcb_batch_hist_c.csv"]
df = pd.concat([pd.read_csv(f) for f in files])
df['time'] = df['time'].astype(str)
for code, g in df.groupby('thscode'):
    g = g.sort_values('time')
    name = g['thsname_cn'].iloc[0]
    closes = g['close']
    last = closes.iloc[-1]; dlast = g['time'].iloc[-1]
    ma20 = closes.tail(20).mean(); ma5 = closes.tail(5).mean()
    hi60 = g['high'].max(); lo60 = g['low'].min()
    hi20 = g['high'].tail(20).max(); lo20 = g['low'].tail(20).min()
    c5 = closes.iloc[-6] if len(closes) > 5 else closes.iloc[0]
    c20 = closes.iloc[-21] if len(closes) > 20 else closes.iloc[0]
    print(f"{code} {name}: last={last} ({dlast}), chg5d={last/c5-1:+.1%}, chg20d={last/c20-1:+.1%}, "
          f"MA5={ma5:.2f}, MA20={ma20:.2f}, vsMA20={last/ma20-1:+.1%}, "
          f"60d_hi={hi60} lo={lo60}, off_hi={last/hi60-1:+.1%}, 20d_hi={hi20} 20d_lo={lo20}")
    print("  last5:", list(g.tail(5)[['time', 'close', 'volume']].itertuples(index=False, name=None)))
