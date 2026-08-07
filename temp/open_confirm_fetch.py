#!/usr/bin/env python3
"""开盘15分钟确认 - 实时数据采集"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from qing_investment.tdx_market import TdxMarket

mkt = TdxMarket()

# 1. 指数实时行情
index_codes = ["999999", "399001", "399006", "000016", "000852", "399303", "000688", "000905"]
idx = mkt.get_quotes(index_codes)
print("=== 指数行情 ===")
for q in idx:
    print(f"{q.get('code')} {q.get('name')}: price={q.get('price')} open={q.get('open')} prev={q.get('prev_close')} pct={q.get('pct_change')}%")

# 2. 持仓/关注个股
watch = ["002812", "603259", "002821", "688387", "688702", "603978", "000060", "600111", "601857", "000938"]
quotes = mkt.get_quotes(watch)
print("\n=== 个股行情 ===")
for q in quotes:
    if q:
        print(f"{q.get('code')} {q.get('name')}: price={q.get('price')} open={q.get('open')} prev={q.get('prev_close')} pct={q.get('pct_change')}% amount={q.get('amount')}")

# 3. 指数15分钟K线（判断开盘15分钟走势）
print("\n=== 上证指数 15min K线（今日） ===")
kl = mkt.get_index_kline("999999", category="15min", count=10)
if kl:
    for k in kl:
        print(f"{k.get('date')} O={k.get('open')} C={k.get('close')} H={k.get('high')} L={k.get('low')} V={k.get('volume')}")

print("\n=== 创业板指 15min K线（今日） ===")
kl2 = mkt.get_index_kline("399006", category="15min", count=10)
if kl2:
    for k in kl2:
        print(f"{k.get('date')} O={k.get('open')} C={k.get('close')} H={k.get('high')} L={k.get('low')} V={k.get('volume')}")
