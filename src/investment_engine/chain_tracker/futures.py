"""大宗商品期货异动检测（T15）。

数据源：新浪 hq.sinajs.cn 主力连续合约（nf_XX0）。
任务书原计划用东财期货行情，但东财 push2 在本机实测不可达
（含已知可用的 A 股 fs 也断连），新浪实测可用（2026-08-31 验证）。

字段位置（实测采样解析）：
  0=名称 2=今开 3=最高 4=最低 6=买价 7=卖价 8=最新价 10=昨结
  13=持仓量 14=成交量 15=交易所简称 16=品种 17=日期

异动判定：|（最新-昨结）/昨结| >= threshold_pct 触发；
防抖：同品种同日内仅当 |变动| 较上次告警扩大 >= realert_step_pct 才重复告警。
"""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

from investment_engine.chain_tracker.items import make_futures_item

# 品种 → (中文名, 关联产业链)。只列知识库中真实存在对应链的品种。
FUTURES_CHAIN_MAP: dict[str, tuple[str, list[str]]] = {
    "CU0": ("铜", ["copper-aluminum"]),
    "AL0": ("铝", ["copper-aluminum"]),
    "J0": ("焦炭", ["coal-coke"]),
    "JM0": ("焦煤", ["coal-coke"]),
    "RB0": ("螺纹钢", ["coal-coke"]),
    "SI0": ("工业硅", ["photovoltaic"]),
}

DEFAULT_THRESHOLD_PCT = 2.0
DEFAULT_REALERT_STEP_PCT = 1.0

_NF_URL = "https://hq.sinajs.cn/list="
_NF_LINE_RE = re.compile(r'var hq_str_nf_(\w+)="([^"]*)"')


def default_futures_state_path() -> Path:
    from investment_engine.chain_tracker.report import default_tracking_dir

    return default_tracking_dir() / "futures_state.json"


def parse_sina_nf(raw: str) -> dict[str, dict]:
    """解析新浪 nf_ 响应；昨结为 0（无数据）的品种跳过。"""
    quotes: dict[str, dict] = {}
    for m in _NF_LINE_RE.finditer(raw):
        symbol, body = m.group(1), m.group(2)
        f = body.split(",")
        if len(f) < 18:
            continue
        try:
            last = float(f[8])
            prev_settle = float(f[10])
        except (ValueError, IndexError):
            continue
        if prev_settle == 0 or last == 0:
            continue
        quotes[symbol] = {
            "name": f[0],
            "last": last,
            "prev_settle": prev_settle,
            "open": float(f[2] or 0),
            "high": float(f[3] or 0),
            "low": float(f[4] or 0),
            "volume": float(f[14] or 0),
            "date": f[17],
            "change_pct": round((last - prev_settle) / prev_settle * 100, 3),
        }
    return quotes


def _fetch_text(url: str) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0",
                      "Referer": "https://finance.sina.com.cn"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("gbk", errors="replace")


def fetch_quotes(symbols: list[str] | None = None, *, fetch_text=None) -> dict[str, dict]:
    """拉取主力连续合约快照；fetch_text 可注入（测试）。"""
    symbols = symbols or sorted(FUTURES_CHAIN_MAP)
    fetch = fetch_text or _fetch_text
    url = _NF_URL + ",".join(f"nf_{s}" for s in symbols)
    return parse_sina_nf(fetch(url))


def _load_state(state_path: Path) -> dict:
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def detect_anomalies(quotes: dict[str, dict], *,
                     threshold_pct: float = DEFAULT_THRESHOLD_PCT,
                     realert_step_pct: float = DEFAULT_REALERT_STEP_PCT,
                     state_path: Path | str | None = None,
                     date: str, window: str) -> list[dict]:
    """对快照做异动判定，返回期货 InfoItem 列表（已通过 chain_ids 预分配产业链）。"""
    state_path = Path(state_path) if state_path else None
    state = _load_state(state_path) if state_path else {}
    items: list[dict] = []
    state_dirty = False

    for symbol, q in sorted(quotes.items()):
        mapped = FUTURES_CHAIN_MAP.get(symbol)
        if not mapped:
            continue
        cname, chain_ids = mapped
        change = q.get("change_pct")
        if change is None:
            prev_settle = q.get("prev_settle") or 0
            if not prev_settle:
                continue
            change = round((q["last"] - prev_settle) / prev_settle * 100, 3)
        if abs(change) < threshold_pct:
            continue
        prev = state.get(symbol) or {}
        if prev.get("date") == date:
            last_alert = abs(float(prev.get("last_alert_change", 0)))
            if abs(change) < last_alert + realert_step_pct:
                continue  # 防抖：同日内幅度未显著扩大不重复告警
        items.append(make_futures_item(
            symbol=symbol, name=cname, change_pct=change,
            last=q["last"], prev_settle=q["prev_settle"],
            date=date, window=window, chain_ids=chain_ids))
        state[symbol] = {"date": date, "last_alert_change": change}
        state_dirty = True

    if state_path and state_dirty:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n",
                              encoding="utf-8")
    return items
