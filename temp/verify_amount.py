#!/usr/bin/env python3
"""验证成交额 + 涨跌家数"""
import sys, os, json, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from qing_investment.tdx_market import TdxMarket

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

# 1. TDX 交叉验证指数成交额
mkt = TdxMarket()
idx = mkt.get_quotes(["999999", "399001", "399006"])
print("=== TDX 指数（含 amount） ===")
for q in idx:
    print(f"{q.get('name') or q.get('code')}: price={q.get('price')} pct={q.get('pct_change')} amount={q.get('amount')} volume={q.get('volume')}")

# 2. 腾讯涨跌家数接口（appstock dayzj）
print("\n=== 腾讯 涨跌家数 ===")
for code in ["sh000001", "sz399001"]:
    try:
        url = f"https://web.ifzq.gtimg.cn/appstock/app/dayzj/query?code={code}"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        print(f"{code}: {json.dumps(data.get('data', {}), ensure_ascii=False)[:400]}")
    except Exception as e:
        print(f"{code} 失败: {e}")

# 3. 腾讯 全市场涨跌统计（沪深A股 通过板块接口）
print("\n=== 新浪 涨跌家数 ===")
try:
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCountSimple?node=hs_a"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("gbk", errors="ignore")
    print(f"hs_a count: {raw[:200]}")
except Exception as e:
    print(f"失败: {e}")

# 4. 涨停家数近似：腾讯市场统计
print("\n=== 腾讯 涨停统计（clist 替代：用涨跌分布） ===")
try:
    url = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/mktHs/rank?l=5&p=1&t=01/averatio"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    print(raw[:300])
except Exception as e:
    print(f"失败: {e}")
