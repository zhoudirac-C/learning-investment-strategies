"""涨停梯队：东财 push2ex 涨停池/炸板池拉取 + 跨日衍生指标 + 落盘。

用途（spec: docs/superpowers/specs/2026-08-11-morning-pipeline-fix.md P1-3）：
- 收盘后（cron 15:37）落盘当日涨停/炸板池，供 18:05 盲判包与次日早盘使用
- 跨日衍生：晋级率（今连板÷昨首板，口径见 framework/up-glossary.md）、
  反包名单（昨日炸板 ∩ 今日涨停）——UP"承接意愿恢复"判断的原始数据

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
    return data


def save_limit_pool(data: dict, out_root: Path, day: str) -> Path:
    """写 <out_root>/<day>.json（day 为 YYYYMMDD）。"""
    out_dir = Path(out_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path
