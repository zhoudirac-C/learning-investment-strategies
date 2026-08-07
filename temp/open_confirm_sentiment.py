#!/usr/bin/env python3
"""开盘确认 - 情绪 + 板块数据采集"""
import sys, os, json, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# 1. 市场情绪
from qing_investment.agent.tools.market_sentiment import fetch_market_sentiment
try:
    sent = fetch_market_sentiment()
    print("=== 市场情绪 ===")
    for k, v in sent.items():
        print(f"{k}: {v}")
except Exception as e:
    print(f"情绪获取失败: {e}")

# 2. 板块数据
from qing_investment.agent.tools.sector_data import get_sector_strength_snapshot
try:
    snap = get_sector_strength_snapshot()
    print("\n=== 板块强度快照 ===")
    print(json.dumps(snap, ensure_ascii=False, default=str)[:3000])
except Exception as e:
    print(f"板块获取失败: {e}")

# 3. 两市成交额（东财）
import urllib.request, json as _json
def fetch_amount():
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&fields=f12,f14,f2,f3,f6&secids=1.000001,0.399001"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = _json.loads(resp.read().decode("utf-8", errors="ignore"))
    for q in (data.get("data") or {}).get("diff", []):
        print(f"指数 {q.get('f14')}: 最新={q.get('f2')} 涨跌={q.get('f3')}% 成交额={q.get('f6')}")
fetch_amount()
