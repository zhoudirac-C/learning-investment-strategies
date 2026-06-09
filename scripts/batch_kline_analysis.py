#!/usr/bin/env python3
"""批量拉取指定标的的60日K线+技术分析，输出JSON供 Qing-Agent 消费。"""
import json, sys, time, importlib.util
from pathlib import Path

_repo = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo / "src"))

# 直接加载 scan_all_stocks.py
spec = importlib.util.spec_from_file_location("scan_all_stocks", _repo / "scripts" / "scan_all_stocks.py")
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)
fetch_realtime_quotes = scan.fetch_realtime_quotes
fetch_history_kline = scan.fetch_history_kline
analyze_technical = scan.analyze_technical

STOCKS = {
    # 工程机械
    "600031": "三一重工", "000425": "徐工机械", "000157": "中联重科",
    "000528": "柳工", "601100": "恒立液压",
    # 蓝筹
    "600188": "兖矿能源", "600893": "航发动力", "603259": "药明康德",
    "600276": "恒瑞医药", "002027": "分众传媒",
    # 燃气轮机
    "002353": "杰瑞股份", "600482": "中国动力", "002126": "银轮股份",
    "605060": "联德股份",
    # 商业航天
    "600118": "中国卫星", "600879": "航天电子",
    # 已有持仓
    "000534": "万泽股份", "002709": "天赐材料",
}

codes = list(STOCKS.keys())
print(f"拉取 {len(codes)} 只标的数据...")

# 1. 实时行情
quotes = fetch_realtime_quotes(codes)

results = []
for code in codes:
    name = STOCKS[code]
    q = quotes.get(code, {})
    latest = q.get("latest", 0)
    pct = q.get("pct_change", 0)

    # 2. 60日K线
    klines = fetch_history_kline(code, days=60)

    # 3. 技术分析
    tech = analyze_technical(code, q, klines) if klines else {}

    # 4. 计算60日回撤
    if klines and len(klines) >= 40:
        high_60d = max(k["high"] for k in klines)
        low_60d = min(k["low"] for k in klines)
        drawdown = round((latest - high_60d) / high_60d * 100, 1)
    else:
        high_60d = low_60d = drawdown = None

    results.append({
        "code": code, "name": name, "latest": latest, "pct_change": pct,
        "high_60d": high_60d, "low_60d": low_60d, "drawdown_60d_pct": drawdown,
        "ma5": tech.get("ma5"), "ma10": tech.get("ma10"), "ma20": tech.get("ma20"),
        "avg_vol_20": tech.get("avg_vol_20"),
        "trend": tech.get("trend", "unknown"),  # bullish/bearish/sideways
        "candle_pattern": tech.get("candle_pattern", "unknown"),
        "candle_score": tech.get("candle_score", 0),
        "support_20d": tech.get("recent_low"),
        "resistance_20d": tech.get("recent_high"),
    })
    sys.stdout.write(".")
    sys.stdout.flush()
    time.sleep(0.3)  # 频率控制

print(f"\n完成 {len(results)} 只")
print(json.dumps(results, ensure_ascii=False, indent=2))
