"""东财龙虎榜日榜：datacenter-web 公开接口拉取 + 落盘。

背景：KPL UserBusiness.GetDay 对本账号不返回席位明细（见
docs/design/kpl-api-inventory.md §5），龙虎榜数据源改用东财公开接口
（docs/superpowers/specs/2026-08-11-eastmoney-lhb.md，2026-08-11 实测可用，无需鉴权）。

- 日榜清单：RPT_DAILYBILLBOARD_DETAILS（上榜原因/买卖净额/换手率）
- 逐股席位：RPT_BILLBOARD_DAILYDETAILSBUY / ...SELL（营业部名称/买卖金额，各取前 5）
- 披露节奏：T 日 17:00-18:00 出齐；清单为空属"非交易日或披露未出"，note 标注不报错
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

API_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
REQUEST_INTERVAL = 0.15  # 请求间隔（秒），单股买卖两请求+股间节流
_SEAT_CAP = 5

EMPTY_NOTE = "当日无龙虎榜数据（非交易日或披露未出，可次日 --date 补拉）"


class EastmoneyError(Exception):
    """东财数据中心接口调用失败（网络重试耗尽 / success=false）。"""


def _get_json(params: dict, timeout: float = 10.0, retries: int = 2) -> dict:
    """GET datacenter API 并返回解析后的 payload；失败抛 EastmoneyError。"""
    url = API_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    payload: dict | None = None
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            break
        except Exception as e:  # 网络/HTTP/JSON 错误统一重试
            last_err = e
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
    if payload is None:
        raise EastmoneyError(f"GET {params.get('reportName')} 重试{retries}次后仍失败: {last_err}")
    if not payload.get("success"):
        raise EastmoneyError(f"{params.get('reportName')} 返回 success=false: "
                             f"{payload.get('message')!r}")
    return payload


def _rows(payload: dict) -> list[dict]:
    return (payload.get("result") or {}).get("data") or []


def fetch_daily_list(day: str) -> list[dict]:
    """日榜清单原始行（可能为空）。day 格式 YYYY-MM-DD。"""
    payload = _get_json({
        "reportName": "RPT_DAILYBILLBOARD_DETAILS",
        "columns": "ALL",
        "filter": f"(TRADE_DATE='{day}')",
        "pageNumber": 1, "pageSize": 500,
        "sortColumns": "BILLBOARD_NET_AMT", "sortTypes": -1,
    })
    return _rows(payload)


def _seat_row(r: dict) -> dict:
    return {"name": r.get("OPERATEDEPT_NAME", ""),
            "buy": r.get("BUY"), "sell": r.get("SELL"), "net": r.get("NET")}


def fetch_seats(day: str, code: str, *, sleep: float = REQUEST_INTERVAL) -> dict:
    """单股买卖席位 {buy: [...], sell: [...]}，各取前 _SEAT_CAP 席。"""
    flt = f"(TRADE_DATE='{day}')(SECURITY_CODE=\"{code}\")"
    out: dict[str, list[dict]] = {}
    for side, report in (("buy", "RPT_BILLBOARD_DAILYDETAILSBUY"),
                         ("sell", "RPT_BILLBOARD_DAILYDETAILSSELL")):
        payload = _get_json({
            "reportName": report, "columns": "ALL", "filter": flt,
            "pageNumber": 1, "pageSize": 10,
            "sortColumns": side.upper(), "sortTypes": -1,
        })
        out[side] = [_seat_row(r) for r in _rows(payload)[:_SEAT_CAP]]
        if sleep:
            time.sleep(sleep)
    return out


def _list_item(r: dict) -> dict:
    return {"code": r.get("SECURITY_CODE", ""),
            "name": r.get("SECURITY_NAME_ABBR", ""),
            "reason": r.get("EXPLANATION", ""),
            "close": r.get("CLOSE_PRICE"),
            "change_pct": r.get("CHANGE_RATE"),
            "net_amt": r.get("BILLBOARD_NET_AMT"),
            "buy_amt": r.get("BILLBOARD_BUY_AMT"),
            "sell_amt": r.get("BILLBOARD_SELL_AMT"),
            "turnover": r.get("TURNOVERRATE")}


def fetch_lhb(day: str, *, sleep: float = REQUEST_INTERVAL) -> dict:
    """组装当日龙虎榜 {source, trade_date, fetched_at, stock_count, items, note}。

    单股席位失败不阻断：该股记 seat_error 并继续；整体清单失败抛 EastmoneyError。
    """
    rows = fetch_daily_list(day)
    items: list[dict] = []
    seat_errors: list[str] = []
    for r in rows:
        item = _list_item(r)
        try:
            seats = fetch_seats(day, item["code"], sleep=sleep)
            item["buy_seats"] = seats["buy"]
            item["sell_seats"] = seats["sell"]
        except EastmoneyError as e:
            item["buy_seats"] = []
            item["sell_seats"] = []
            item["seat_error"] = str(e)
            seat_errors.append(item["code"])
        items.append(item)

    notes: list[str] = []
    if not items:
        notes.append(EMPTY_NOTE)
    elif str(rows[0].get("TRADE_DATE", ""))[:10] != day:
        notes.append(f"返回数据交易日({str(rows[0].get('TRADE_DATE', ''))[:10]})与目标日({day})不符")
    if seat_errors:
        notes.append(f"{len(seat_errors)} 只个股席位拉取失败: {','.join(seat_errors)}")
    return {"source": "eastmoney",
            "trade_date": day,
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "stock_count": len(items),
            "items": items,
            "note": "；".join(notes)}


def save_lhb(data: dict, out_root: Path, day: str) -> Path:
    """写 <out_root>/lhb/<day>.json。"""
    out_dir = Path(out_root) / "lhb"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path
