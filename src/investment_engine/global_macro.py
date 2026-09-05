"""全球宏观行情快照：Yahoo v8 chart（经 sakura 代理）→ 美债/美元/美股/亚太/商品收盘落盘。

提案：framework/proposals/2026-08-20-data-channel-global-macro.md
补齐复盘盲判「外力/内生」归因的外部数据缺口：美债长端 → 美股半导体/存储链
→ 亚太股指 → A股 传导链各环节的当日收盘位置。

通道选型（2026-08-20 实测，见提案处置建议 3 补充实测记录）：
- Yahoo v8 chart API 免费无 key；本机直连 403，经 sakura 代理（mihomo mixed
  127.0.0.1:7890）全部有数；CNBC restQuote 为备份；stooq（反爬 PoW）/
  FRED（代理下超时）弃用；
- 工程纪律：显式挂代理 + UA 头 + 串行限速；节点可能半死（mihomo 测速通但
  中继断），接口失败先切节点再下结论。

as-of 语义（防泄漏核心）：只保留「交易所收盘时刻 ≤ min(拉取时刻, day 当日
22:00 北京)」的 session bar——即复盘（22:00）可得边界。美股 session 当日
16:00 ET 收盘（= 次日 04:00 北京）→ A股日 D 的文件里美股只到 session D-1，
亚太（14:30/16:00 北京收盘）可到 session D。历史日用 --date 重算同一规则，
不会因后见之明混入未来 session。

落盘：infra/data/global_macro/{yyyymmdd}.json（cron 盘前 09:10 拉取供早盘盲判 +
盘后 16:35 --force 刷新补亚太当日收盘供复盘）；盲判数据包经 dataset._load_global_macro
入包（fetched_at 可能晚于回放日，不进包）。
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
# Yahoo 边缘按 UA 分桶限流（2026-08-20 实测：完整 Chrome UA → 429，
# "Mozilla/5.0" 短 UA → 200）；勿改回浏览器全长 UA。
USER_AGENT = "Mozilla/5.0"

# sakura 代理（mihomo mixed 端口）；可用 GLOBAL_MACRO_PROXY 覆盖，None=直连。
DEFAULT_PROXY = os.environ.get("GLOBAL_MACRO_PROXY", "http://127.0.0.1:7890")

DATA_ROOT = Path("infra/data/global_macro")

_BEIJING = timezone(timedelta(hours=8))
_REVIEW_CLOSE_UTC_H = 14  # 复盘可得边界：A股日 22:00 北京 = 14:00 UTC
_PERIOD_LOOKBACK_D = 40   # chart period1 回看窗口（覆盖假期，保证 ≥2 根完整 bar）

# group 输出顺序对齐提案字段顺序（商品组 2026-09-05 增补：08-26/08-27 data-channel 闭环）
GROUPS = ("美股三指数", "费城半导体", "存储链", "亚太股指", "美债收益率", "美元指数",
          "商品")

# close = 交易所收盘本地时刻（判定 bar 完整性的基准）；kind=yield 为收益率报价
# （% 数值，chg_bp 为基点变动），缺省 pct（收盘涨跌幅百分数）。
# 注：铠侠无美股 ADR，用东京上市 285A.T（亚太收盘时刻）。
# 2026-09-05 增补：13W 国库券（^IRX）作短端代理——Yahoo 无 2Y 符号，曲线形状以
# 10Y−13W 粗看；商品取 COMEX 黄金/铜期货（LME 无免费公开符号，口径差异如实注明，
# 闭环提案 08-26/08-27 data-channel 的商品价格检验需求）。
SYMBOLS: dict[str, dict] = {
    "^DJI":     {"name": "道指", "group": "美股三指数", "close": (16, 0)},
    "^IXIC":    {"name": "纳指", "group": "美股三指数", "close": (16, 0)},
    "^GSPC":    {"name": "标普", "group": "美股三指数", "close": (16, 0)},
    "^SOX":     {"name": "费城半导体", "group": "费城半导体", "close": (16, 0)},
    "MU":       {"name": "美光", "group": "存储链", "close": (16, 0)},
    "SNDK":     {"name": "闪迪", "group": "存储链", "close": (16, 0)},
    "STX":      {"name": "希捷", "group": "存储链", "close": (16, 0)},
    "WDC":      {"name": "西数", "group": "存储链", "close": (16, 0)},
    "285A.T":   {"name": "铠侠", "group": "存储链", "close": (15, 30)},
    "^KS11":    {"name": "KOSPI", "group": "亚太股指", "close": (15, 30)},
    "^N225":    {"name": "日经225", "group": "亚太股指", "close": (15, 30)},
    "^HSI":     {"name": "恒生", "group": "亚太股指", "close": (16, 0)},
    "^IRX":     {"name": "13W", "group": "美债收益率", "close": (16, 0), "kind": "yield"},
    "^TNX":     {"name": "10Y", "group": "美债收益率", "close": (16, 0), "kind": "yield"},
    "^TYX":     {"name": "30Y", "group": "美债收益率", "close": (16, 0), "kind": "yield"},
    "DX-Y.NYB": {"name": "美元指数", "group": "美元指数", "close": (16, 0)},
    "GC=F":     {"name": "黄金", "group": "商品", "close": (17, 0)},
    "HG=F":     {"name": "铜", "group": "商品", "close": (17, 0)},
}


class GlobalMacroError(Exception):
    """全球宏观行情拉取失败（网络重试耗尽 / 接口异常）。"""


def _fetch_chart(symbol: str, *, asof_ts: float, proxy: str | None = DEFAULT_PROXY,
                 timeout: float = 15.0, retries: int = 2) -> dict:
    """Yahoo v8 chart 日线 JSON，返回 result[0]（含 meta.gmtoffset/timestamp/close）。

    period2 取 asof 之后一天，窗口内过晚的 bar 由 _completed_bars 按收盘时刻过滤。
    """
    p1 = int(asof_ts - _PERIOD_LOOKBACK_D * 86400)
    p2 = int(asof_ts + 86400)
    url = (YAHOO_CHART.format(sym=urllib.parse.quote(symbol, safe=""))
           + f"?period1={p1}&period2={p2}&interval=1d")
    handler = urllib.request.ProxyHandler(
        {"http": proxy, "https": proxy} if proxy else {})
    opener = urllib.request.build_opener(handler)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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
        raise GlobalMacroError(f"GET {symbol} 重试{retries}次后仍失败: {last_err}")
    chart = json.loads(payload.decode("utf-8")).get("chart") or {}
    if chart.get("error"):
        raise GlobalMacroError(f"{symbol}: {chart['error']}")
    result = chart.get("result") or []
    if not result:
        raise GlobalMacroError(f"{symbol}: 空 result")
    return result[0]


def _session_date(ts: int, gmtoffset: int) -> str:
    """bar 时间戳 → 交易所本地 session 日期。"""
    return datetime.fromtimestamp(ts + gmtoffset, tz=timezone.utc).strftime("%Y-%m-%d")


def _completed_bars(result: dict, *, close_local: tuple[int, int],
                    asof_ts: float) -> list[tuple[str, float]]:
    """提取 (session_date, close)，只保留收盘时刻 ≤ asof 的完整 bar（时间正序）。"""
    meta = result.get("meta") or {}
    gmtoff = meta.get("gmtoffset", 0)
    ts_list = result.get("timestamp") or []
    closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    out: list[tuple[str, float]] = []
    for ts, c in zip(ts_list, closes):
        if c is None:
            continue
        d = _session_date(ts, gmtoff)
        y, m, dd = map(int, d.split("-"))
        close_utc = (datetime(y, m, dd, close_local[0], close_local[1],
                              tzinfo=timezone.utc) - timedelta(seconds=gmtoff))
        if close_utc.timestamp() <= asof_ts:
            out.append((d, float(c)))
    return out


def compute_global_macro(day: str | None = None, *, fetcher=None,
                         symbols: dict | None = None,
                         proxy: str | None = DEFAULT_PROXY,
                         now_ts: float | None = None,
                         throttle: float = 0.4) -> dict | None:
    """拉全部 SYMBOLS，按 as-of 规则取最新完整 session，算收盘涨跌/收益率变动。

    day: A股交易日 YYYY-MM-DD（None=今日北京日期）；asof = min(now, day 22:00 北京)。
    fetcher 可注入 fn(symbol) -> chart result[0]（测试免网络）；
    symbols 可注入子集（测试/调试）。
    单个品种失败记 errors 不阻断；全部失败返回 None（调用方不落盘）。
    """
    symbols = symbols or SYMBOLS
    day = day or datetime.now(_BEIJING).strftime("%Y-%m-%d")
    y, m, d = map(int, day.split("-"))
    cap_ts = datetime(y, m, d, _REVIEW_CLOSE_UTC_H, tzinfo=timezone.utc).timestamp()
    asof_ts = min(now_ts if now_ts is not None else time.time(), cap_ts)

    groups: dict[str, dict] = {g: {} for g in GROUPS}
    errors: list[str] = []
    for i, (sym, meta) in enumerate(symbols.items()):
        try:
            result = fetcher(sym) if fetcher else _fetch_chart(
                sym, asof_ts=asof_ts, proxy=proxy)
            bars = _completed_bars(
                result, close_local=meta["close"], asof_ts=asof_ts)
            if len(bars) < 2:
                raise GlobalMacroError("完整 bar 不足 2 根")
        except Exception as e:  # noqa: BLE001 - 单品种失败不阻断其余
            errors.append(f"{sym}: {e}")
            continue
        (d0, c0), (d1, c1) = bars[-2], bars[-1]
        if meta.get("kind") == "yield":
            entry = {"symbol": sym, "session": d1, "yield": round(c1, 3),
                     "chg_bp": round((c1 - c0) * 100, 1)}
        else:
            entry = {"symbol": sym, "session": d1, "close": round(c1, 2),
                     "pct": round((c1 / c0 - 1) * 100, 2)}
        groups[meta["group"]][meta["name"]] = entry
        if throttle and not fetcher and i < len(symbols) - 1:
            time.sleep(throttle)

    out = {g: rows for g, rows in groups.items() if rows}
    if not out:
        return None
    return {"date": day,
            "fetched_at": datetime.now(_BEIJING).isoformat(timespec="seconds"),
            **out,
            "errors": errors,
            "note": "各品种取最近完整 session 收盘（≤ 当日 22:00 北京复盘可得边界）；"
                    "pct 为百分数，chg_bp 为收益率基点变动；熔断/Sidecar 类事件无法"
                    "从行情推出，靠 news 通道补"}


def save_global_macro(data: dict, root: Path | str = DATA_ROOT) -> Path:
    """落盘 {root}/{yyyymmdd}.json（幂等由调用方判断）。"""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{data['date'].replace('-', '')}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_global_macro(day: str, root: Path | str = DATA_ROOT) -> dict | None:
    """读落盘（day='YYYY-MM-DD'）；无文件/坏文件返回 None。"""
    path = Path(root) / f"{day.replace('-', '')}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
