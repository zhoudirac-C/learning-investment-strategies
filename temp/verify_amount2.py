#!/usr/bin/env python3
"""核实成交额口径 + 今日是否放量"""
import sys, os, json, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from qing_investment.tdx_market import TdxMarket

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

# 1. 腾讯原始字段打印
print("=== 腾讯 上证指数 原始字段 ===")
try:
    req = urllib.request.Request("https://qt.gtimg.cn/q=sh000001,sz399001", headers=HEADERS)
    raw = urllib.request.urlopen(req, timeout=15).read().decode("gbk", errors="ignore")
    for line in raw.strip().split(";"):
        line = line.strip()
        if "=" not in line:
            continue
        val = line.split("=", 1)[1].strip('"')
        parts = val.split("~")
        print(f"name={parts[1]} 现价={parts[3]} 昨收={parts[4]} 开={parts[5]} 量(手)={parts[6]} 额={parts[37]} 涨跌%={parts[32]} 最高={parts[33]} 最低={parts[34]}")
except Exception as e:
    print(f"失败: {e}")

# 2. 新浪交叉验证
print("\n=== 新浪 上证指数 ===")
try:
    req = urllib.request.Request("https://hq.sinajs.cn/list=s_sh000001,s_sz399001", headers={**HEADERS, "Referer": "https://finance.sina.com.cn/"})
    raw = urllib.request.urlopen(req, timeout=15).read().decode("gbk", errors="ignore")
    print(raw[:600])
except Exception as e:
    print(f"失败: {e}")

# 3. TDX 前一日上证成交额对比（昨日 vs 今日）
print("\n=== TDX 上证指数 日K 最近3日（验证今日量能放大） ===")
mkt = TdxMarket()
kl = mkt.get_index_kline("999999", category="daily", count=5)
for k in kl:
    print(f"{k.get('date')} C={k.get('close')} V={k.get('volume')} amount={k.get('amount')} pct={k.get('pct_change')}")

print("\n=== TDX 创业板指 日K 最近3日 ===")
kl2 = mkt.get_index_kline("399006", category="daily", count=5)
for k in kl2:
    print(f"{k.get('date')} C={k.get('close')} V={k.get('volume')} amount={k.get('amount')} pct={k.get('pct_change')}")
