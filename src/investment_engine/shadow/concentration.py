"""全市场成交集中度计算（提案 2026-10-13-pack-enhancement-turnover-concentration）。

UP 004-f 筹码出清锚的本地复算口径：
    全A个股按当日成交额降序，top N% 个股成交额合计 / 全市场成交额合计。

数据源：东财 push2 clist 全A快照（scripts/fetch_turnover_concentration.py，
收盘后拉取），落盘 infra/data/turnover_concentration/YYYY-MM-DD.json。
"""
from __future__ import annotations


def compute_concentration(rows: list[dict], top_pct: float = 0.05) -> dict | None:
    """从东财 clist 行（f12=代码, f6=成交额/元）计算集中度。

    返回 {n_stocks, top_n, top_amount_yi, total_amount_yi, concentration_pct}；
    无有效行返回 None。成交额 <=0 / 缺失 / 非数值的行剔除。
    """
    amounts = []
    for r in rows:
        a = r.get("f6")
        if isinstance(a, (int, float)) and a > 0:
            amounts.append(float(a))
    if not amounts:
        return None
    amounts.sort(reverse=True)
    n = len(amounts)
    top_n = max(1, int(n * top_pct))
    total = sum(amounts)
    top = sum(amounts[:top_n])
    return {
        "n_stocks": n,
        "top_n": top_n,
        "top_amount_yi": round(top / 1e8, 1),
        "total_amount_yi": round(total / 1e8, 1),
        "concentration_pct": round(top / total * 100, 2),
    }
