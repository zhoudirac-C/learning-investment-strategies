"""隔夜外盘映射股行情：腾讯 qt.gtimg.cn 美股批量接口拉取 + 落盘。

用途：盘前（cron 08:20）拉取 us_map.yaml 映射股的隔夜涨跌，供早盘"外盘→A股映射"
推理（spec: docs/superpowers/specs/2026-08-11-morning-pipeline-fix.md P1-1）。

数据源：腾讯 qt.gtimg.cn 美股批量报价（q=usCOHR,usLITE,...，GBK 编码）。
东财 push2 原接口对云服务器 IP 段做反爬风控（TCP 层直接断开，走代理无效，
代理出口同为云厂商 IP），2026-08-13 起弃用，改腾讯——实测 13 只映射股全覆盖。

返回字段契约（对齐旧东财实现，消费方无需改）：
{symbol, name, price, prev_close, pct_change, secid}，pct_change 为百分数（如 -12.05）。
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

API_URL = "https://qt.gtimg.cn/q="
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# 隔夜异动扫描（2026-08-21）：Yahoo 预定义榜单，经 sakura 代理（mihomo mixed）。
# Yahoo 边缘按 UA 分桶限流——短 UA（对齐 global_macro 模块实测），勿改回浏览器全长 UA。
YAHOO_SCREENER = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
_YAHOO_UA = "Mozilla/5.0"
DEFAULT_PROXY = os.environ.get("OVERNIGHT_US_PROXY",
                               os.environ.get("GLOBAL_MACRO_PROXY",
                                              "http://127.0.0.1:7890"))
_MOVERS_MIN_MCAP = 2e9     # 市值下限 20 亿美元（滤小盘噪音）
_MOVERS_MIN_ABS_PCT = 8.0  # 异动阈值 |涨跌幅| ≥ 8%
_MOVERS_TOP_N = 5

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "stock_monitor" / "us_map.yaml"


class OvernightUsError(Exception):
    """外盘映射股拉取失败（网络重试耗尽 / 接口异常）。"""


def _get_tencent_raw(symbols: list[str], timeout: float = 10.0, retries: int = 2) -> str:
    """腾讯美股批量报价，返回原始 GBK 文本（每行 v_usXXX="..."）。"""
    q = ",".join(f"us{s}" for s in symbols)
    url = API_URL + urllib.parse.quote(q, safe=",")
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Referer": "https://finance.qq.com/"})
    payload: bytes | None = None
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = resp.read()
            break
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
    if payload is None:
        raise OvernightUsError(f"GET qt.gtimg.cn 重试{retries}次后仍失败: {last_err}")
    return payload.decode("gbk", "replace")


def _parse_tencent_line(symbol: str, payload: str) -> dict | None:
    """解析单行 v_usXXX="200~名称~代码~现价~昨收~...~涨跌幅~..." 为统一字段。

    腾讯美股字段（~ 分隔，实测 2026-08-13）：
      [1] 名称  [3] 现价  [4] 昨收  [32] 涨跌幅%（百分数，如 3.03）
    停牌/无数据时现价或涨跌幅为 '-'，返回 None（调用方跳过）。
    """
    fields = payload.split("~")
    if len(fields) < 33:
        return None
    price_s, pct_s = fields[3], fields[32]
    if price_s in ("", "-") or pct_s in ("", "-"):
        return None
    try:
        price = float(price_s)
        prev_close = float(fields[4] or 0)
        pct_change = float(pct_s)
    except ValueError:
        return None
    return {"symbol": symbol,
            "name": fields[1] or symbol,
            "price": price,
            "prev_close": prev_close,
            "pct_change": pct_change,
            "secid": f"us{symbol}"}


def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    """批量拉取映射股，返回 {代码: {symbol, name, price, prev_close, pct_change, secid}}。

    单请求提交全部 us 前缀代码；返回行按 symbol 归并，无数据/停牌跳过。
    """
    if not symbols:
        return {}
    raw = _get_tencent_raw(symbols)
    out: dict[str, dict] = {}
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or "=" not in line or '"' not in line:
            continue
        key, _, payload = line.partition("=")
        sym = key.strip().removeprefix("v_us").strip()
        if sym not in symbols:
            continue
        parsed = _parse_tencent_line(sym, payload.strip().strip('";'))
        if parsed:
            out[sym] = parsed
    return out


def load_config(config_path: Path | None = None) -> dict:
    path = config_path or CONFIG_PATH
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _screener_fetch(side: str, *, proxy: str | None, timeout: float = 15.0,
                    retries: int = 2) -> list[dict]:
    """Yahoo 预定义榜单原始 quotes（side=day_gainers/day_losers），经代理。"""
    url = f"{YAHOO_SCREENER}?scrIds={side}&count=25"
    handler = urllib.request.ProxyHandler(
        {"http": proxy, "https": proxy} if proxy else {})
    opener = urllib.request.build_opener(handler)
    req = urllib.request.Request(url, headers={"User-Agent": _YAHOO_UA})
    payload: bytes | None = None
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with opener.open(req, timeout=timeout) as resp:
                payload = resp.read()
            break
        except Exception as e:  # noqa: BLE001 - 如实重试后报错
            last_err = e
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
    if payload is None:
        raise OvernightUsError(f"screener {side} 重试{retries}次后仍失败: {last_err}")
    result = (json.loads(payload.decode("utf-8")).get("finance") or {}).get("result") or []
    if not result:
        raise OvernightUsError(f"screener {side}: 空 result")
    return result[0].get("quotes") or []


def _filter_movers(quotes: list[dict], side: str) -> list[dict]:
    """榜单过滤：市值 ≥20 亿美元且涨/跌幅 ≥8%，按幅度取 top5。

    side=gainers 取涨幅榜（pct ≥ +8% 降序），losers 取跌幅榜（pct ≤ -8% 升序）。
    """
    out = []
    for q in quotes or []:
        pct = q.get("regularMarketChangePercent")
        mcap = q.get("marketCap")
        if not isinstance(pct, (int, float)) or not isinstance(mcap, (int, float)):
            continue
        if mcap < _MOVERS_MIN_MCAP:
            continue
        if side == "gainers" and pct < _MOVERS_MIN_ABS_PCT:
            continue
        if side == "losers" and pct > -_MOVERS_MIN_ABS_PCT:
            continue
        out.append({"symbol": q.get("symbol"),
                    "name": q.get("shortName") or q.get("longName") or "",
                    "pct_change": round(float(pct), 2),
                    "price": q.get("regularMarketPrice"),
                    "mcap_亿美元": round(mcap / 1e8, 1)})
    out.sort(key=lambda m: -m["pct_change"] if side == "gainers" else m["pct_change"])
    return out[:_MOVERS_TOP_N]


def fetch_movers(*, fetch_fn=None, proxy: str | None = DEFAULT_PROXY) -> dict:
    """隔夜美股异动扫描：gainers/losers 双侧榜单（过滤口径见 note）。

    补 us_map.yaml 主题表覆盖不了的表外大异动（如 2026-08-19 MRNA +177%）。
    fetch_fn 可注入（side -> quotes，测试免网络）；失败抛 OvernightUsError。
    """
    fetch = fetch_fn or (lambda side, **kw: _screener_fetch(side, proxy=proxy, **kw))
    return {
        "gainers": _filter_movers(fetch("day_gainers"), "gainers"),
        "losers": _filter_movers(fetch("day_losers"), "losers"),
        "note": "异动口径：|涨跌幅|≥8% 且市值≥20亿美元（Yahoo 榜单，经代理）",
    }


def fetch_overnight(config_path: Path | None = None) -> dict:
    """按 us_map.yaml 拉全部映射股（一次批量请求），缺失个股记 error 不阻断。

    附 movers 异动扫描（best-effort）：代理故障等失败时 movers=None 并记
    movers_error，不影响主题映射与既有消费方。
    """
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
                               "error": "接口无该代码数据",
                               "earnings_note": s.get("earnings_note", "")})
        themes.append({"id": theme.get("id", ""), "name": theme.get("name", ""),
                       "stocks": stocks})
    out = {"date": datetime.now().strftime("%Y-%m-%d"),
           "fetched_at": datetime.now().isoformat(timespec="seconds"),
           "themes": themes,
           "errors": errors,
           "note": "涨跌幅为昨夜美股收盘数据" if not errors else
                   f"{len(errors)} 只无数据: {','.join(errors)}"}
    try:
        out["movers"] = fetch_movers()
    except Exception as e:  # noqa: BLE001 - 异动扫描失败不阻断主题映射
        out["movers"] = None
        out["movers_error"] = str(e)[:150]
    return out


def save_overnight(data: dict, out_root: Path, day: str) -> Path:
    """写 <out_root>/<day>.json。"""
    out_dir = Path(out_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path
