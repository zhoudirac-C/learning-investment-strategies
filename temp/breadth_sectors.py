#!/usr/bin/env python3
"""涨跌家数 + 板块数据（多源容错）"""
import sys, os, json, urllib.request, warnings, time
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

def http_get(url, timeout=20, headers=None, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers or HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last

# 1. 涨跌家数：akshare 新浪源（轻量）
print("=== 涨跌家数 (akshare 新浪) ===")
try:
    import akshare as ak
    df = ak.stock_zh_a_spot()  # 新浪源
    pct = df["涨跌幅"].dropna()
    up = int((pct > 0).sum()); down = int((pct < 0).sum()); flat = int((pct == 0).sum())
    print(f"上涨={up} 下跌={down} 平={flat} 总数={len(df)}")
except Exception as e:
    print(f"akshare 失败: {e}")

# 2. 板块：同花顺（akshare 封装）
print("\n=== 概念板块 TOP (同花顺) ===")
try:
    from qing_investment.agent.tools.sector_data import fetch_ths_change_boards
    boards = fetch_ths_change_boards("concept", top_n=15)
    for b in boards:
        print(f"{b.rank:>2}. {b.name}: {b.pct_change}%")
except Exception as e:
    print(f"同花顺失败: {e}")

print("\n=== 行业板块 TOP (同花顺) ===")
try:
    from qing_investment.agent.tools.sector_data import fetch_ths_change_boards
    boards = fetch_ths_change_boards("industry", top_n=10)
    for b in boards:
        print(f"{b.rank:>2}. {b.name}: {b.pct_change}%")
except Exception as e:
    print(f"同花顺行业失败: {e}")

# 3. 涨停/跌停家数（新浪涨停池 or 东财clist 重试）
print("\n=== 涨停/跌停 (东财 clist 重试) ===")
for name, cond in [("涨停(≥9.8%)", "f3>=9.8"), ("跌停(≤-9.8%)", "f3<=-9.8")]:
    try:
        url = (f"https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=600&po=1&np=1&fltt=2&invt=2"
               f"&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
               f"&fields=f12,f14,f2,f3&{cond}")
        data = json.loads(http_get(url, headers={**HEADERS, "Referer": "https://quote.eastmoney.com/"}))
        total = (data.get("data") or {}).get("total") or 0
        print(f"{name}: {total}")
        diff = (data.get("data") or {}).get("diff") or []
        if isinstance(diff, list):
            for q in diff[:6]:
                print(f"  {q.get('f12')} {q.get('f14')}: {q.get('f3')}%")
    except Exception as e:
        print(f"{name} 失败: {e}")

# 4. CXO/创新药、医药消费 前排个股实时（观察锚点）
print("\n=== 医药/CXO 前排 ===")
from qing_investment.tdx_market import TdxMarket
mkt = TdxMarket()
meds = mkt.get_quotes(["603259", "002821", "300347", "603127", "688180", "600276", "300759"])
for q in meds:
    if q:
        print(f"{q.get('code')} {q.get('name')}: price={q.get('price')} pct={q.get('pct_change')}%")

print("\n=== 连板/情绪龙头（昨日涨停今日表现） ===")
hots = mkt.get_quotes(["301366", "600732", "002459", "688387", "000938"])
for q in hots:
    if q:
        print(f"{q.get('code')} {q.get('name')}: price={q.get('price')} open={q.get('open')} pct={q.get('pct_change')}%")
