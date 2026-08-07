#!/usr/bin/env python3
"""轻量情绪+板块采集：东财 push2 API 直取"""
import sys, os, json, urllib.request

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
           "Referer": "https://quote.eastmoney.com/"}

def http_get(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")

# 1. 涨跌家数（沪深京A股 实时统计，用 clist 接口分页统计太重，改用市场统计接口）
#    东财行情中心接口：clist fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048
#    用 ulist 接口取全市场统计更轻 —— 实际用 push2 的 "市场涨跌分布" 接口
def fetch_market_stat():
    # 上证/深证/创业板 市场统计接口 f104=f105 等
    url = ("https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2"
           "&fields=f12,f14,f2,f3,f104,f105,f106,f6"
           "&secids=1.000001,0.399001,0.399006")
    data = json.loads(http_get(url))
    print("=== 指数+市场统计 ===")
    for q in (data.get("data") or {}).get("diff", []):
        print(f"{q.get('f14')}: 最新={q.get('f2')} 涨跌={q.get('f3')}% 上涨={q.get('f104')} 下跌={q.get('f105')} 平={q.get('f106')} 成交额(亿)={round((q.get('f6') or 0)/1e8,1)}")

fetch_market_stat()

# 2. 涨停池/跌停池统计 —— 用 clist 接口限制条件：涨幅>=9.8 且非ST近似统计
def fetch_limit_stats():
    # 沪深A股涨停（涨幅>9.9 近似）
    for name, fs, cond in [
        ("涨停", "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048", "f3>=9.9"),
        ("跌停", "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048", "f3<=-9.9"),
    ]:
        url = (f"https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=500&po=1&np=1&fltt=2&invt=2"
               f"&fid=f3&fs={fs}&fields=f12,f14,f2,f3&{cond}")
        try:
            data = json.loads(http_get(url))
            total = (data.get("data") or {}).get("total") or 0
            print(f"=== {name}数(涨幅>9.9%近似): {total} ===")
            diff = (data.get("data") or {}).get("diff") or []
            if isinstance(diff, list):
                for q in diff[:8]:
                    print(f"  {q.get('f12')} {q.get('f14')}: {q.get('f3')}%")
        except Exception as e:
            print(f"{name}统计失败: {e}")

fetch_limit_stats()

# 3. 板块强度（东财概念板块 top15 + 行业板块 top10）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from qing_investment.agent.tools.sector_data import fetch_eastmoney_boards
try:
    concepts = fetch_eastmoney_boards("concept", top_n=15)
    print("\n=== 概念板块 TOP15 ===")
    for b in concepts:
        print(f"{b.rank:>2}. {b.name}: {b.pct_change}% amount={b.amount}")
except Exception as e:
    print(f"概念板块失败: {e}")
try:
    inds = fetch_eastmoney_boards("industry", top_n=10)
    print("\n=== 行业板块 TOP10 ===")
    for b in inds:
        print(f"{b.rank:>2}. {b.name}: {b.pct_change}% amount={b.amount}")
except Exception as e:
    print(f"行业板块失败: {e}")
