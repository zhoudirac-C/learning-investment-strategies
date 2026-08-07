#!/usr/bin/env python3
"""探测可用数据源：腾讯 / 东财 clist / 新浪"""
import sys, os, json, urllib.request, warnings
warnings.filterwarnings("ignore")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

def http_get(url, timeout=15, headers=None):
    req = urllib.request.Request(url, headers=headers or HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")

# 1. 腾讯指数行情（含成交量额）
print("=== 腾讯 qt.gtimg.cn 指数 ===")
try:
    raw = http_get("https://qt.gtimg.cn/q=sh000001,sz399001,sz399006,sh000016,sh000852,sz399303,sh000905",
                   encoding=None) if False else urllib.request.urlopen(
        urllib.request.Request("https://qt.gtimg.cn/q=sh000001,sz399001,sz399006,sh000016,sh000852,sz399303,sh000905",
                               headers=HEADERS), timeout=15).read().decode("gbk", errors="ignore")
    for line in raw.strip().split(";"):
        line = line.strip()
        if "=" not in line:
            continue
        val = line.split("=", 1)[1].strip('"')
        parts = val.split("~")
        if len(parts) > 40:
            # 腾讯指数格式: 1名称 2代码 3当前 4昨收 5开盘 6成交量(手) ... 37成交额(万) 38... 
            print(f"{parts[1]}: 现价={parts[3]} 昨收={parts[4]} 开={parts[5]} 涨跌%={parts[32]} 成交额(亿)={float(parts[37])/10000:.1f} 量比={parts[49] if len(parts)>49 else 'N/A'}")
except Exception as e:
    print(f"腾讯失败: {e}")

# 2. 腾讯涨跌家数（用市场总览接口）
print("\n=== 腾讯涨跌家数 (sh000001 市场统计) ===")
try:
    # 腾讯有 market 统计接口: https://proxy.finance.qq.com/ifzqgtimg/appstock/app/mktHs/rank
    raw = http_get("https://qt.gtimg.cn/q=s_sh000001")
    print(f"s_sh000001: {raw[:200]}")
except Exception as e:
    print(f"失败: {e}")

# 3. 东财 clist 板块测试
print("\n=== 东财 clist 概念板块 ===")
try:
    url = ("https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fltt=2&invt=2&fid=f3"
           "&fs=m:90+t:3+f:!50&fields=f12,f14,f2,f3,f6")
    data = json.loads(http_get(url, headers={**HEADERS, "Referer": "https://quote.eastmoney.com/"}))
    for q in (data.get("data") or {}).get("diff", []):
        print(f"{q.get('f14')}: {q.get('f3')}% 成交额={q.get('f6')}")
except Exception as e:
    print(f"东财 clist 失败: {e}")

# 4. 东财涨跌家数（clist 全市场统计）
print("\n=== 东财涨跌家数（统计接口） ===")
try:
    # 用 clist 接口拿全市场统计不现实，改用统计接口
    url = "https://push2.eastmoney.com/api/qt/stock/get?secid=1.000001&fields=f104,f105,f106"
    data = json.loads(http_get(url, headers={**HEADERS, "Referer": "https://quote.eastmoney.com/"}))
    print(f"上证 涨跌平: {data.get('data')}")
except Exception as e:
    print(f"失败: {e}")
