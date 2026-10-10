#!/usr/bin/env python3
"""板块估值-业绩快照拉取（产业链阶段判断的第三腿：估值腿）。

2026-10-11 用户拍板：信息面看到产业利润增长+预期增长（实际利好）且板块低位
低估值（PE/PEG/PB）= 潜在机会区（opportunity_zone），作为正交标签叠加在
0-4 阶段上，不加新阶段。估值工具按 methodology/f10-fundamental-analysis.md
公司类型路由：高成长链用动态PE/PEG（一致预期），强周期链用PB历史分位。

数据源（均实测可用）：
- 东财 datacenter RPT_VALUEANALYSIS_DET：个股 PE_TTM/PB_MRQ/PS_TTM 日频历史
- 东财 datacenter RPT_WEB_RESPREDICT：一致预期 EPS1-4 + 机构覆盖数
口径纪律（a-share-valuation-data skill）：
- 中位数汇总（市值加权会被极端值污染）；PEG 除以增速百分数值；
  EPS1<=0（亏损）剔除出增速统计；机构覆盖<5 家剔除出一致预期统计。

用法: .venv/bin/python scripts/fetch_board_valuation.py [--only CHAIN_ID ...]
输出: infra/data/board_valuation/<chain_id>.json
调度: cron 每周一/四 16:00（估值慢变量，用户拍板 D4）
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
MAP_PATH = REPO / "config" / "stock_monitor" / "chain_board_map.yaml"
CHAINS_DIR = REPO / "knowledge" / "industry-chains"
OUT_DIR = REPO / "infra" / "data" / "board_valuation"

EM_BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EM_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}

# 机会区阈值（2026-10-11 用户拍板 D2）
PEG_THRESHOLD = 1.0          # 成长链：PEG 中位数上限
GROWTH_MIN = 25.0            # 成长链：预期增速中位数下限（%）
PB_PERCENTILE_MAX = 20.0     # 周期链：PB 中位数 3 年分位上限（%）
BOARD_DRAWDOWN_MIN = 20.0    # 通用：板块指数距 120 日高点回撤下限（%，绝对值）
MIN_COVERAGE = 5             # 一致预期低置信门槛（机构覆盖数）
PB_HISTORY_DAYS = 3 * 365    # 周期链 PB 分位的历史窗口


def _em_get(report: str, filter_str: str, *, page_size: int = 1,
            page: int = 1, sort: str = "") -> list[dict]:
    qs = {
        "reportName": report, "columns": "ALL",
        "filter": filter_str, "pageNumber": str(page), "pageSize": str(page_size),
    }
    if sort:
        qs["sortColumns"], qs["sortTypes"] = sort, "-1"
    url = EM_BASE + "?" + urllib.parse.urlencode(qs)
    req = urllib.request.Request(url, headers=EM_HEADERS)
    d = json.loads(urllib.request.urlopen(req, timeout=20).read())
    return (d.get("result") or {}).get("data") or []


def fetch_valuation_latest(code: str) -> dict | None:
    rows = _em_get("RPT_VALUEANALYSIS_DET", f'(SECURITY_CODE="{code}")',
                   page_size=1, sort="TRADE_DATE")
    return rows[0] if rows else None


def fetch_pb_history(code: str, days: int = PB_HISTORY_DAYS) -> list[float]:
    start = (datetime.now().timestamp() - days * 86400)
    start_s = datetime.fromtimestamp(start).strftime("%Y-%m-%d")
    out: list[float] = []
    page = 1
    while True:
        rows = _em_get(
            "RPT_VALUEANALYSIS_DET",
            f'(SECURITY_CODE="{code}")(TRADE_DATE>=\'{start_s}\')',
            page_size=500, page=page, sort="TRADE_DATE")
        if not rows:
            break
        out.extend(float(r["PB_MRQ"]) for r in rows
                   if r.get("PB_MRQ") and float(r["PB_MRQ"]) > 0)
        if len(rows) < 500:
            break
        page += 1
        time.sleep(0.3)
    return out


def fetch_consensus(code: str) -> dict | None:
    rows = _em_get("RPT_WEB_RESPREDICT", f'(SECURITY_CODE="{code}")', page_size=1)
    return rows[0] if rows else None


def _pct(cur: float, hist: list[float]) -> float:
    return round(sum(1 for v in hist if v < cur) / len(hist) * 100, 1) if hist else -1


def analyze_chain(chain_id: str, cfg: dict) -> dict:
    chain_yaml = CHAINS_DIR / chain_id / "chain.yaml"
    stocks = []
    if chain_yaml.exists():
        with open(chain_yaml, encoding="utf-8") as f:
            c = yaml.safe_load(f)
        for m in (c or {}).get("mappings") or []:
            code = str(m.get("code") or "").zfill(6)
            if code:
                stocks.append({"code": code, "name": m.get("name")})
    method = cfg.get("valuation_method") or "pe_peg"
    recs = []
    for s in stocks:
        rec = dict(s)
        try:
            v = fetch_valuation_latest(s["code"])
            if v:
                rec.update(price=v.get("CLOSE_PRICE"), pe_ttm=v.get("PE_TTM"),
                           pb=v.get("PB_MRQ"), ps_ttm=v.get("PS_TTM"),
                           val_date=str(v.get("TRADE_DATE") or "")[:10])
            if method == "pe_peg":
                p = fetch_consensus(s["code"])
                if p and p.get("EPS1") and p.get("EPS2"):
                    eps1, eps2 = float(p["EPS1"]), float(p["EPS2"])
                    rec["eps1"], rec["eps2"] = eps1, eps2
                    rec["org_num"] = p.get("RATING_ORG_NUM")
                    if eps1 > 0 and v and v.get("CLOSE_PRICE"):
                        growth = (eps2 / eps1 - 1) * 100
                        dyn_pe = float(v["CLOSE_PRICE"]) / eps2
                        rec["growth_pct"] = round(growth, 1)
                        rec["dyn_pe"] = round(dyn_pe, 1)
                        if growth > 0:
                            rec["peg"] = round(dyn_pe / growth, 2)
            else:  # pb_cycle: PB 历史分位
                if v and v.get("PB_MRQ") and float(v["PB_MRQ"]) > 0:
                    hist = fetch_pb_history(s["code"])
                    rec["pb_percentile_3y"] = _pct(float(v["PB_MRQ"]), hist)
            recs.append(rec)
        except Exception as e:  # noqa: BLE001 - 单股失败不阻断
            rec["error"] = f"{type(e).__name__}"
            recs.append(rec)
        time.sleep(0.3)

    # ── 中位数汇总（剔除亏损/低覆盖，防极端值污染）──
    def _med(key, pred=lambda r: True):
        vals = [r[key] for r in recs if r.get(key) is not None and pred(r)]
        return round(statistics.median(vals), 2) if vals else None

    agg: dict = {"stocks_total": len(recs),
                 "stocks_ok": sum(1 for r in recs if "error" not in r)}
    agg["pe_ttm_median"] = _med("pe_ttm", lambda r: (r.get("pe_ttm") or 0) > 0)
    if method == "pe_peg":
        trusted = lambda r: (r.get("org_num") or 0) >= MIN_COVERAGE  # noqa: E731
        agg["dyn_pe_median"] = _med("dyn_pe", trusted)
        agg["growth_pct_median"] = _med("growth_pct", trusted)
        agg["peg_median"] = _med("peg", trusted)
        agg["org_coverage_median"] = _med("org_num")
        agg["loss_excluded"] = sum(1 for r in recs
                                   if r.get("eps1") is not None and r["eps1"] <= 0)
    else:
        agg["pb_median"] = _med("pb", lambda r: (r.get("pb") or 0) > 0)
        agg["pb_percentile_3y_median"] = _med("pb_percentile_3y",
                                              lambda r: (r.get("pb_percentile_3y") or -1) >= 0)
    return {"chain_id": chain_id, "valuation_method": method,
            "board": cfg.get("board"), "as_of": datetime.now().strftime("%Y-%m-%d"),
            "aggregate": agg, "stocks": recs}


def judge_opportunity(snapshot: dict, board_metrics: dict | None) -> dict:
    """机会区判定（硬规则不走 LLM，宁可漏不可错）。返回 {opportunity_zone, reasons}。"""
    agg = snapshot["aggregate"]
    reasons: list[str] = []
    dd = (board_metrics or {}).get("drawdown_from_120d_high_pct")
    dd_ok = dd is not None and dd <= -BOARD_DRAWDOWN_MIN
    reasons.append(f"板块回撤{dd}% {'≥20%✓' if dd_ok else '<20%✗'}"
                   if dd is not None else "板块回撤无数据✗")
    if snapshot["valuation_method"] == "pe_peg":
        peg, gr = agg.get("peg_median"), agg.get("growth_pct_median")
        cov = agg.get("org_coverage_median")
        peg_ok = peg is not None and peg < PEG_THRESHOLD
        gr_ok = gr is not None and gr > GROWTH_MIN
        cov_ok = cov is not None and cov >= MIN_COVERAGE
        reasons.append(f"PEG中位{peg} {'<1✓' if peg_ok else '✗'}")
        reasons.append(f"预期增速中位{gr}% {'>25%✓' if gr_ok else '✗'}")
        reasons.append(f"机构覆盖中位{cov}家 {'≥5✓' if cov_ok else '<5✗(低置信)'}")
        ok = dd_ok and peg_ok and gr_ok and cov_ok
    else:
        pp = agg.get("pb_percentile_3y_median")
        pp_ok = pp is not None and pp < PB_PERCENTILE_MAX
        reasons.append(f"PB三年分位中位{pp}% {'<20%✓' if pp_ok else '✗'}")
        # 周期链"产品价企稳"由引擎期货腿另行确认，此处只判估值位置
        ok = dd_ok and pp_ok
    return {"opportunity_zone": bool(ok), "reasons": reasons}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()

    import sys
    sys.path.insert(0, str(REPO / "src"))
    from investment_engine.chain_tracker.board_context import (
        board_metrics, load_board_map)

    board_map = load_board_map()
    targets = {k: v for k, v in board_map.items()
               if not args.only or k in args.only}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ok = 0
    for cid, cfg in targets.items():
        try:
            snap = analyze_chain(cid, cfg)
            snap["opportunity"] = judge_opportunity(snap, board_metrics(cid))
            with open(OUT_DIR / f"{cid}.json", "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=1)
            oz = "🎯机会区" if snap["opportunity"]["opportunity_zone"] else "—"
            print(f"[ok] {cid} ({snap['valuation_method']}) {oz} "
                  f"{snap['aggregate']}")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {cid} 失败 {type(e).__name__}: {e}")
    print(f"[done] 成功 {ok}/{len(targets)}")


if __name__ == "__main__":
    main()
