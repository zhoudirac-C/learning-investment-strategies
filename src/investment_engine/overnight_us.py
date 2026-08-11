"""隔夜外盘映射股行情：东财 push2 批量接口拉取 + 落盘。

用途：盘前（cron 08:20）拉取 us_map.yaml 映射股的隔夜涨跌，供早盘"外盘→A股映射"
推理（spec: docs/superpowers/specs/2026-08-11-morning-pipeline-fix.md P1-1）。

接口实测（2026-08-11）：push2.eastmoney.com/api/qt/ulist.np/get 批量报价，
secid 前缀 105=NASDAQ / 106=NYSE / 107=AMEX；f2=现价(×1000)、f18=昨收(×1000)、
f3=涨跌幅(×100)、f12=代码、f14=名称。单股接口（qt/stock/get）限流严重，
故批量一次提交"符号×三前缀"全部变体（45 个 secid 一次请求），按代码归并首个
有数据的变体——交易所前缀无需预知。
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

API_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_PREFIXES = ("105", "106", "107")  # NASDAQ / NYSE / AMEX
_FIELDS = "f12,f13,f14,f2,f3,f18"

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "stock_monitor" / "us_map.yaml"


class OvernightUsError(Exception):
    """外盘映射股拉取失败（网络重试耗尽 / 接口异常）。"""


def _get_json(params: dict, timeout: float = 10.0, retries: int = 2) -> dict:
    url = API_URL + "?" + urllib.parse.urlencode(params)
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
        raise OvernightUsError(f"GET ulist 重试{retries}次后仍失败: {last_err}")
    return payload


def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    """批量拉取映射股，返回 {代码: {symbol, name, price, prev_close, pct_change, secid}}。

    单请求提交全部"符号×105/106/107"变体；无效变体不进 diff，按代码归并。
    """
    if not symbols:
        return {}
    variants = [f"{p}.{s}" for s in symbols for p in _PREFIXES]
    payload = _get_json({"secids": ",".join(variants), "fields": _FIELDS})
    rows = (payload.get("data") or {}).get("diff") or []
    out: dict[str, dict] = {}
    for row in rows:
        code = row.get("f12")
        if not code or code in out:
            continue
        if row.get("f2") in (None, "-") or row.get("f3") in (None, "-"):
            continue
        out[code] = {"symbol": code,
                     "name": row.get("f14") or "",
                     "price": float(row["f2"]) / 1000.0,
                     "prev_close": float(row.get("f18") or 0) / 1000.0,
                     "pct_change": float(row["f3"]) / 100.0,
                     "secid": f"{row.get('f13')}.{code}"}
    return out


def load_config(config_path: Path | None = None) -> dict:
    path = config_path or CONFIG_PATH
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def fetch_overnight(config_path: Path | None = None) -> dict:
    """按 us_map.yaml 拉全部映射股（一次批量请求），缺失个股记 error 不阻断。"""
    cfg = load_config(config_path)
    all_symbols = [s["symbol"] for t in cfg.get("themes") or []
                   for s in t.get("symbols") or []]
    quotes = fetch_quotes(all_symbols)
    themes: list[dict] = []
    errors: list[str] = []
    for theme in cfg.get("themes") or []:
        stocks: list[dict] = []
        for s in theme.get("symbols") or []:
            q = quotes.get(s["symbol"])
            if q:
                stocks.append({**q, "earnings_note": s.get("earnings_note", "")})
            else:
                errors.append(s["symbol"])
                stocks.append({"symbol": s["symbol"], "name": s.get("name", ""),
                               "error": "批量接口无该代码数据",
                               "earnings_note": s.get("earnings_note", "")})
        themes.append({"id": theme.get("id", ""), "name": theme.get("name", ""),
                       "stocks": stocks})
    return {"date": datetime.now().strftime("%Y-%m-%d"),
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "themes": themes,
            "errors": errors,
            "note": "涨跌幅为昨夜美股收盘数据" if not errors else
                    f"{len(errors)} 只无数据: {','.join(errors)}"}


def save_overnight(data: dict, out_root: Path, day: str) -> Path:
    """写 <out_root>/<day>.json。"""
    out_dir = Path(out_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path
