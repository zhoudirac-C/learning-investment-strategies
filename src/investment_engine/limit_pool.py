"""涨停梯队：东财 push2ex 涨停池/炸板池拉取 + 跨日衍生指标 + 落盘。

用途（spec: docs/superpowers/specs/2026-08-11-morning-pipeline-fix.md P1-3）：
- 收盘后（cron 15:37）落盘当日涨停/炸板池，供 18:05 盲判包与次日早盘使用
- 跨日衍生：晋级率（今连板÷昨首板，口径见 framework/up-glossary.md）、
  反包名单（昨日炸板 ∩ 今日涨停）——UP"承接意愿恢复"判断的原始数据
- P1 特征（2026-08-12 起）：first_board_width（首板宽度：家数+日环比+20日分位）、
  regulatory_distance（龙头监管距离：最高板龙头 10/30 日偏离值距严重异动阈值的空间，
  口径见 knowledge/wiki/市场分析/A股严重异常波动规则.md）

接口实测（2026-08-11）：push2ex.eastmoney.com/getTopicZTPool|getTopicZBPool，
date=YYYYMMDD 支持历史；关键字段 c=代码 n=名称 p=价格(×1000) zdp=涨幅
lbc=连板数 fbt=首次封板时间(92500=竞价一字) fund=封单额(元) zbc=炸板次数 hybk=行业
zttj={days,ct}=N天M板。
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

API_BASE = "https://push2ex.eastmoney.com"
_UT = "7eea3edcaed734bea9cbfc24409ed989"  # 东财网页版公开静态 token
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
REQUEST_INTERVAL = 0.3
_AUCTION_TIME = "92500"  # fbt=92500 → 集合竞价封板（一字/准一字）


class LimitPoolError(Exception):
    """涨停池/炸板池拉取失败。"""


def _get_json(path: str, params: dict, timeout: float = 10.0, retries: int = 2) -> dict:
    url = API_BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    payload: dict | None = None
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            break
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
    if payload is None:
        raise LimitPoolError(f"GET {path} 重试{retries}次后仍失败: {last_err}")
    if payload.get("rc") != 0:
        raise LimitPoolError(f"{path} 返回 rc={payload.get('rc')}")
    return payload


def _fetch_pool(kind: str, day: str) -> list[dict]:
    """拉涨停池(kind=ZT)或炸板池(kind=ZB)原始行。day 格式 YYYYMMDD。"""
    path = {"ZT": "/getTopicZTPool", "ZB": "/getTopicZBPool"}[kind]
    rows: list[dict] = []
    page = 0
    while True:
        payload = _get_json(path, {
            "ut": _UT, "dpt": "wz.ztzt", "Pageindex": page,
            "pagesize": 500, "sort": "fbt:asc", "date": day,
        })
        data = payload.get("data") or {}
        pool = data.get("pool") or []
        rows.extend(pool)
        if len(rows) >= (data.get("tc") or 0) or not pool:
            break
        page += 1
        time.sleep(REQUEST_INTERVAL)
    return rows


def _zt_item(r: dict) -> dict:
    return {"code": r.get("c", ""), "name": r.get("n", ""),
            "pct": r.get("zdp"), "lbc": r.get("lbc") or 0,
            "fbt": str(r.get("fbt", "")), "fund": r.get("fund"),
            "zbc": r.get("zbc") or 0, "hybk": r.get("hybk", ""),
            "days_ct": f"{(r.get('zttj') or {}).get('days', '')}天"
                       f"{(r.get('zttj') or {}).get('ct', '')}板"}


def _zb_item(r: dict) -> dict:
    return {"code": r.get("c", ""), "name": r.get("n", ""),
            "pct": r.get("zdp"), "zbc": r.get("zbc") or 0,
            "hybk": r.get("hybk", ""), "amount": r.get("amount")}


def _ladder(items: list[dict]) -> dict:
    """连板梯队 {高度: [名称...]}，按连板数降序。"""
    out: dict[str, list[str]] = {}
    for it in sorted(items, key=lambda x: -x["lbc"]):
        if it["lbc"] >= 2:
            out.setdefault(f"{it['lbc']}板", []).append(it["name"])
    return dict(sorted(out.items(), key=lambda kv: -int(kv[0][:-1])))


# ---------- P1 特征（2026-08-12 起） ----------

# 板块 → 偏离值基准指数（口径：wiki/市场分析/A股严重异常波动规则.md）
# 注：缓存无上证A指/深证A指/科创板综指，用 IDX000001/IDX399001/IDX399006 近似
_BOARD_INDEX = {"60": "IDX000001", "68": "IDX000001",
                "00": "IDX399001", "30": "IDX399006"}


def _first_board_width(zt: list[dict], out_root: Path | None, day: str) -> dict:
    """首板宽度：首板家数 + 日环比 + 20 日分位（历史取自本地落盘序列）。

    分位定义：历史窗口内 首板家数 ≤ 今日值 的占比。样本不足 20 日时如实标注。
    """
    cur = sum(1 for it in zt if (it.get("lbc") or 0) == 1)
    out: dict = {"count": cur}
    hist: list[tuple[str, int]] = []
    if out_root:
        for p in sorted(Path(out_root).glob("*.json")):
            if not p.stem.isdigit() or p.stem >= day:
                continue
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            items = d.get("zt_items") or []
            hist.append((p.stem,
                         sum(1 for it in items if (it.get("lbc") or 0) == 1)))
    hist = hist[-20:]
    if not hist:
        out.update({"dod_delta": None, "pctile_20d": None, "sample_days": 0,
                    "note": "无历史落盘，日环比/20日分位未计算"})
        return out
    prev_day, prev_cnt = hist[-1]
    window = [c for _, c in hist]
    out.update({
        "prev_date": prev_day, "dod_delta": cur - prev_cnt,
        "pctile_20d": round(sum(1 for c in window if c <= cur) / len(window), 4),
        "sample_days": len(window),
    })
    if len(window) < 20:
        out["note"] = f"历史样本仅 {len(window)} 日（<20），分位仅供参考"
    return out


def _daily_pcts(bars: list[dict]) -> dict[str, float]:
    """由收盘价序列算日涨幅 {trade_date: pct%}（不依赖 pct_change 字段）。"""
    out: dict[str, float] = {}
    prev_close: float | None = None
    for b in bars:
        d = b.get("trade_date") or b.get("date")
        c = b.get("close")
        if prev_close and c:
            out[d] = (c / prev_close - 1) * 100.0
        if c:
            prev_close = c
    return out


def _regulatory_distance(zt: list[dict], day: str) -> dict | None:
    """龙头监管距离：最高板龙头的偏离值距严重异动阈值的空间（百分点）。

    口径（wiki/市场分析/A股严重异常波动规则.md）：偏离值=个股日涨幅−基准指数日涨幅；
    严重异动线 10 日累计 +100%、30 日累计 +200%。距离=阈值−当前累计，越小越危险。
    未扣除异常波动公告后的清零重置，为保守上限估计。
    """
    if not zt:
        return None
    leader = max(zt, key=lambda it: (it.get("lbc") or 0, it.get("fund") or 0))
    code = leader.get("code", "")
    base = {"leader_code": code, "leader_name": leader.get("name", ""),
            "leader_lbc": leader.get("lbc")}
    if code.startswith(("4", "8")):
        return {**base, "note": "北交所标的，偏离值口径不适用，未计算"}
    idx_code = _BOARD_INDEX.get(code[:2])
    if not idx_code:
        return {**base, "note": f"无法识别板块（代码 {code}），未计算"}
    try:
        from investment_engine.backtest.history import get_index_daily, get_klines_range
    except Exception as e:
        return {**base, "note": f"K线缓存接口不可用: {e}"}
    end = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    start = (datetime.strptime(day, "%Y%m%d") - timedelta(days=75)).strftime("%Y-%m-%d")
    stock_bars = get_klines_range(code, start, end)
    if len(stock_bars) < 11:
        # 龙头通常不在监控池、缓存未覆盖 → 按需拉取（tdx→腾讯→东财，回写缓存）
        try:
            from qing_investment.agent.tools.stock_data import fetch_stock_kline
            fetched = fetch_stock_kline(code, days=45)
            fetched = [b for b in fetched
                       if (b.get("date") or "") <= end]
            if len(fetched) > len(stock_bars):
                stock_bars = fetched
        except Exception:
            pass
    stock_pct = _daily_pcts(stock_bars)
    idx_pct = _daily_pcts(get_index_daily(idx_code, start, end))
    common = sorted(d for d in stock_pct if d in idx_pct)
    if len(common) < 10:
        return {**base, "index_proxy": idx_code,
                "note": f"K线缓存公共交易日不足（{len(common)}<10），未计算"}
    devs = [stock_pct[d] - idx_pct[d] for d in common]
    dev10 = sum(devs[-10:])
    out = {**base, "index_proxy": idx_code,
           "dev_10d": round(dev10, 2), "dist_10d": round(100.0 - dev10, 2),
           "threshold_10d": 100.0}
    if len(devs) >= 30:
        dev30 = sum(devs[-30:])
        out.update({"dev_30d": round(dev30, 2),
                    "dist_30d": round(200.0 - dev30, 2), "threshold_30d": 200.0})
    out["note"] = ("未扣除异常波动公告清零重置，为保守上限；"
                   "指数为近似代理（缓存无上证A指/深证A指/科创板综指）")
    return out


def build_limit_pool(day: str, out_root: Path | None = None,
                     *, prev_day: str | None = None) -> dict:
    """组装当日梯队数据。day 格式 YYYYMMDD。

    prev_day 给出且本地已有落盘时，计算晋级率与反包名单；否则如实标注缺省。
    """
    zt_raw = _fetch_pool("ZT", day)
    time.sleep(REQUEST_INTERVAL)
    zb_raw = _fetch_pool("ZB", day)
    zt = [_zt_item(r) for r in zt_raw]
    zb = [_zb_item(r) for r in zb_raw]

    data: dict = {
        "date": f"{day[:4]}-{day[4:6]}-{day[6:]}",
        "zt_count": len(zt), "zb_count": len(zb),
        "max_lbc": max((it["lbc"] for it in zt), default=0),
        "ladder": _ladder(zt),
        "auction_sealed": [it["name"] for it in zt
                           if it["fbt"] == _AUCTION_TIME and it["zbc"] == 0],
        "zt_items": zt, "zb_items": zb,
    }

    # 跨日衍生：晋级率 + 反包（需要前日落盘）
    compare: dict = {}
    if prev_day and out_root:
        prev_path = Path(out_root) / f"{prev_day}.json"
        if prev_path.exists():
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
            prev_first = sum(1 for it in prev.get("zt_items", []) if it.get("lbc") == 1)
            cur_lianban = sum(1 for it in zt if it["lbc"] >= 2)
            prev_zb_codes = {it["code"] for it in prev.get("zb_items", [])}
            fanbao = [it["name"] for it in zt if it["code"] in prev_zb_codes]
            compare = {"prev_date": prev.get("date", prev_day),
                       "prev_first_board": prev_first, "cur_lianban": cur_lianban,
                       "promotion_rate": round(cur_lianban / prev_first, 4) if prev_first else None,
                       "fanbao": fanbao}
        else:
            compare = {"note": f"前日({prev_day})落盘缺失，晋级率/反包未计算"}
    else:
        compare = {"note": "未提供前日落盘，晋级率/反包未计算"}
    data["compare"] = compare

    # P1 特征：首板宽度 + 龙头监管距离（失败不阻断落盘，如实标注）
    data["first_board_width"] = _first_board_width(zt, out_root, day)
    try:
        data["regulatory_distance"] = _regulatory_distance(zt, day)
    except Exception as e:
        data["regulatory_distance"] = {"note": f"计算失败: {e}"}
    return data


def save_limit_pool(data: dict, out_root: Path, day: str) -> Path:
    """写 <out_root>/<day>.json（day 为 YYYYMMDD）。"""
    out_dir = Path(out_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path
