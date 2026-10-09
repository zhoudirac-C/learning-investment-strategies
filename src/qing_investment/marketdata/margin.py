"""融资融券（两融）市场合计数据 — 东方财富数据中心（唯一源，2026-10-09 新增）。

背景：crash_loop_attribution 框架（暴跌互爆归因与救市需求判断，2026-10-09 人审入库）
的第一数据锚点——「暴跌中融资余额仍在增加=散户还在加仓→排除融资盘互爆；余额骤降
=杠杆平仓螺旋进行中」。UP 本人用的就是东财融资融券数据中心页面（data.eastmoney.com/rzrq/），
本模块数据与 UP 截图口径完全一致（2026-10-09 实测：10-08 融资余额 25445.87 亿、
融资买入 1391.25 亿与 UP 图 OCR 逐项吻合）。

接口：datacenter-web.eastmoney.com reportName=RPTA_WEB_MARGIN_DAILYTRADE
（两融账户统计，日频，T 日数据 T 日晚间披露）。

fail-fast 纪律（对齐 macro.py）：success=false / result 为空 / 行数不足都抛错，
绝不静默返回 [] 让调用方当成"当天没数据"。

注意：接口不直接给融资偿还额/融资净买入；融资净买入 = 融资余额日差值（本模块计算，
与 UP 图的「净买入」列口径一致——10-08 实测 +41.39 亿 vs 余额差 25445.87-25404.55=+41.32 亿，
尾差来自四舍五入与口径微调，量级一致）。
"""

from __future__ import annotations

from urllib.parse import urlencode

from qing_investment.marketdata import ratelimit
from qing_investment.marketdata.errors import MarketDataError
from qing_investment.marketdata.http import http_get_json

_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_SOURCE = "eastmoney"
_HEADERS = {"Referer": "https://data.eastmoney.com/rzrq/"}


def get_margin_balance(days: int = 10) -> list[dict]:
    """两融市场合计日度数据，返回升序 list[dict]，单位：亿元。

    字段：
      date                交易日 "2026-10-08"
      fin_balance         融资余额
      loan_balance        融券余额
      margin_balance      两融余额（融资+融券）
      balance_ratio       两融余额占流通市值比（%）
      fin_buy_amt         融资买入额
      loan_sell_amt       融券卖出额
      fin_net_buy         融资净买入（= 融资余额日差值，首日无前值为 None）
      avg_guarantee_ratio 平均维持担保比例（%，240% 以下为预警密集区）
      sh_close            上证指数收盘（接口附带，便于对照）

    days 为返回行数（实际多拉 1 行用于算首日净买入）。全链路失败抛 MarketDataError。
    """
    if days < 2:
        raise ValueError("days 至少为 2（净买入需要前一日余额差值）")
    ratelimit.acquire(_SOURCE)
    qs = urlencode({
        "reportName": "RPTA_WEB_MARGIN_DAILYTRADE",
        "columns": "ALL",
        "pageNumber": 1,
        "pageSize": days + 1,
        "sortColumns": "STATISTICS_DATE",
        "sortTypes": "-1",
    })
    data = http_get_json(f"{_URL}?{qs}", headers=_HEADERS, timeout=20)
    if not isinstance(data, dict) or not data.get("success"):
        raise MarketDataError(
            f"eastmoney margin: 接口返回失败 success={data.get('success') if isinstance(data, dict) else '非JSON'} "
            f"message={data.get('message') if isinstance(data, dict) else ''}"
        )
    rows = (data.get("result") or {}).get("data") or []
    if len(rows) < 2:
        raise MarketDataError(f"eastmoney margin: 返回行数不足（{len(rows)}），接口结构可能已变更")

    def _f(v):
        return round(float(v), 2) if v is not None else None

    out = []
    prev_fin = None
    for row in reversed(rows):  # 接口倒序 → 转升序
        fin = row.get("FIN_BALANCE")
        rec = {
            "date": str(row.get("STATISTICS_DATE", ""))[:10],
            "fin_balance": _f(fin),
            "loan_balance": _f(row.get("LOAN_BALANCE")),
            "margin_balance": _f(row.get("MARGIN_BALANCE")),
            "balance_ratio": _f(row.get("BALANCE_RATIO")),
            "fin_buy_amt": _f(row.get("FIN_BUY_AMT")),
            "loan_sell_amt": _f(row.get("LOAN_SELL_AMT")),
            "fin_net_buy": _f(fin - prev_fin) if (fin is not None and prev_fin is not None) else None,
            "avg_guarantee_ratio": _f(row.get("AVG_GUARANTEE_RATIO")),
            "sh_close": _f(row.get("SCI_CLOSE_PRICE")),
        }
        prev_fin = fin
        out.append(rec)
    return out[-days:]
