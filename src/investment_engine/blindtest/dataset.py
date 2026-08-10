"""盲测每日数据包构建：prompt 的唯一输入，只含当日可得的客观数据。

防泄漏：pack_to_prompt 产出必须过 assert_no_leakage（无未来日期、无 UP 指称）。
时变字段（direction_pool.current_stage 等）一律不进包。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from investment_engine.backtest.history import get_klines_range, list_trading_days

FORBIDDEN_RE = re.compile(r"UP|青枫浦|博主")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
INDEX_CODES = ("IDX000300", "IDX000001", "IDX399006", "IDX399001", "IDX000852")
_INDEX_LOOKBACK = 60
_STOCK_ZONE_DAYS = 20

_REPO = Path(__file__).resolve().parents[3]

KPL_ROOT = _REPO / "infra" / "data" / "kpl"
_NEWS_TITLE_CAP = 60
_LHB_ITEM_CAP = 20


class LeakageError(ValueError):
    """数据包含未来信息或来源指称，禁止送入盲测 prompt。"""


def assert_no_leakage(text: str, day: str) -> None:
    m = FORBIDDEN_RE.search(text)
    if m:
        raise LeakageError(f"prompt 含来源指称 {m.group(0)!r}")
    for d in DATE_RE.findall(text):
        if d > day:
            raise LeakageError(f"prompt 含未来日期 {d}（当日 {day}）")


def trading_days(start: str, end: str, db_path=None) -> list[str]:
    return list_trading_days(start, end, db_path)


def _pos20(klines: list[dict]) -> float | None:
    if len(klines) < _STOCK_ZONE_DAYS:
        return None
    window = klines[-_STOCK_ZONE_DAYS:]
    hi = max(k["high"] for k in window)
    lo = min(k["low"] for k in window)
    if hi <= lo:
        return 0.5
    return round((window[-1]["close"] - lo) / (hi - lo), 4)


def _compact_bars(klines: list[dict], n: int) -> list[dict]:
    return [
        {"d": k["date"], "c": k["close"], "pct": k.get("pct_change"), "vol": k.get("volume")}
        for k in klines[-n:]
    ]


def _load_directions(config_dir: Path) -> list[dict]:
    raw = yaml.safe_load((config_dir / "direction_pool.yaml").read_text(encoding="utf-8")) or {}
    return [
        # name 可能含来源指称（如"7/2UP强call"），打码处理；id 保持不变
        {"id": d.get("id"), "name": FORBIDDEN_RE.sub("██", str(d.get("name", "")))}
        for d in raw.get("directions", []) or []
        if d.get("id")
    ]


def _load_chains() -> list[dict]:
    from investment_engine.industry_chain.store import list_chains, load_chain

    chains = []
    for cid in list_chains():
        c = load_chain(cid)
        # last_verified 等日期字段可能晚于回放日 → 泄漏断言会拦截，一律剔除
        chains.append({
            "chain_id": c["chain_id"], "name": c["name"], "thesis": c["thesis"],
            "segments": [{"id": s["id"], "name": s["name"]} for s in c["segments"]],
            "mappings": [
                {"code": m["code"], "name": m["name"], "segment": m["segment"],
                 "elasticity": m["elasticity"], "cert_status": m.get("cert_status")}
                for m in c["mappings"]
            ],
        })
    return chains


def _load_patterns_index() -> list[dict]:
    raw = yaml.safe_load((_REPO / "framework" / "reasoning-patterns.yaml").read_text(encoding="utf-8"))
    return [
        {"pattern_id": p["pattern_id"], "name": p["name"], "trigger": p.get("trigger", [])}
        for p in raw.get("patterns", [])
    ]


def _load_glossary() -> str:
    """术语词典正文。标题/引言行含"UP"指称（如"UP 术语词典"），逐行剔除——
    术语定义表本身无来源指称，过滤后仍完整。"""
    raw = (_REPO / "framework" / "up-glossary.md").read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if not FORBIDDEN_RE.search(ln)]
    return "\n".join(lines)


def _load_emotion(day: str, kpl_root: Path) -> dict | None:
    """KPL 情绪快照精选块；当日文件缺失返回 None。"""
    path = kpl_root / "emotion" / f"{day}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    out: dict = {}
    if d.get("daban"):
        out["daban"] = d["daban"]
    if d.get("lianban"):
        out["lianban"] = d["lianban"]
    fengkou = [f["StockName"] for f in (d.get("fengkou") or [])
               if isinstance(f, dict) and f.get("StockName")]
    if fengkou:
        out["fengkou_stocks"] = fengkou
    bankuai = [[b[0], b[1]] for b in (d.get("bankuai") or [])
               if isinstance(b, (list, tuple)) and len(b) >= 2]
    if bankuai:
        out["bankuai"] = bankuai
    return out or None


def _load_news_titles(day: str, kpl_root: Path) -> dict | None:
    """当日资讯标题列表（不含全文），封顶 _NEWS_TITLE_CAP 条。"""
    path = kpl_root / "news" / day / "index.json"
    if not path.exists():
        return None
    items = json.loads(path.read_text(encoding="utf-8"))
    titles = []
    for it in items[:_NEWS_TITLE_CAP]:
        stocks = []
        for s in (it.get("stocks") or [])[:5]:
            if isinstance(s, dict):
                stocks.append(str(s.get("StockID") or s.get("Code") or s))
            else:
                stocks.append(str(s))
        titles.append({"t": str(it.get("title", "")), "stocks": stocks})
    out: dict = {"items": titles}
    if len(items) > _NEWS_TITLE_CAP:
        out["truncated"] = f"{_NEWS_TITLE_CAP}/{len(items)}"
    return out


def _load_lhb(day: str, kpl_root: Path) -> dict | None:
    """龙虎榜摘要：披露日 + 上榜明细（封顶 _LHB_ITEM_CAP 条，字段透传）。"""
    path = kpl_root / "lhb" / f"{day}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    return {"disclosure_day": d.get("disclosure_day", ""),
            "count": len(d.get("list") or []),
            "items": (d.get("list") or [])[:_LHB_ITEM_CAP],
            "note": d.get("note", "")}


def build_daily_pack(day: str, *, config_dir: Path, db_path=None, kpl_root=None) -> dict:
    """组装某日数据包（只含截至当日的数据）。"""
    index = {}
    for code in INDEX_CODES:
        bars = get_klines_range(code, "2000-01-01", day, db_path=db_path)
        index[code] = _compact_bars(bars, _INDEX_LOOKBACK)

    from qing_investment.monitor.context import load_monitor_config

    cfg = load_monitor_config(config_dir)
    stocks = []
    for s in (cfg.stock_pool or {}).get("stocks", []):
        code = s.get("code")
        if not code:
            continue
        bars = get_klines_range(code, "2000-01-01", day, db_path=db_path)
        if not bars or bars[-1]["date"] != day:
            continue
        last = bars[-1]
        stocks.append({
            "code": code.split(".")[0], "name": s.get("name", ""),
            "direction": s.get("direction", ""),
            "close": last["close"], "pct": last.get("pct_change"),
            "turnover": last.get("turnover"), "pos20": _pos20(bars),
        })

    pack = {
        "date": day,
        "index": index,
        "stocks": stocks,
        "directions": _load_directions(config_dir),
        "chains": _load_chains(),
        "glossary": _load_glossary(),
        "patterns": _load_patterns_index(),
    }
    root = Path(kpl_root) if kpl_root else KPL_ROOT
    blocks = {"emotion": _load_emotion(day, root),
              "news_titles": _load_news_titles(day, root),
              "lhb": _load_lhb(day, root)}
    missing = [f"kpl_{k}" for k, v in blocks.items() if v is None]
    for k, v in blocks.items():
        if v is not None:
            pack[k] = v
    if missing:
        pack["missing"] = missing
    return pack


def pack_to_prompt(pack: dict) -> str:
    """序列化为 prompt 正文。产出必须能过 assert_no_leakage。"""
    header = (
        f"今天是 {pack['date']}。以下是截至今日收盘的客观数据。"
        "注意：产业链知识库与方向池为最新版静态快照（不含任何时变状态字段）。\n\n"
    )
    body = json.dumps(
        {k: v for k, v in pack.items() if k != "glossary"},
        ensure_ascii=False, separators=(",", ":"),
    )
    text = header + body + "\n\n## 术语词典\n" + pack["glossary"]
    assert_no_leakage(text, pack["date"])  # 出厂自检
    return text
