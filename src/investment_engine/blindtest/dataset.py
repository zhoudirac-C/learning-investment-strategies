"""盲测每日数据包构建：prompt 的唯一输入，只含当日可得的客观数据。

防泄漏：pack_to_prompt 产出必须过 assert_no_leakage（无未来日期、无 UP 指称）。
时变字段（direction_pool.current_stage 等）一律不进包。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from investment_engine.backtest.history import get_index_daily, get_klines_range, list_trading_days

FORBIDDEN_RE = re.compile(r"UP|青枫浦|博主")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
INDEX_CODES = ("IDX000300", "IDX000001", "IDX399006", "IDX399001", "IDX000852")
_INDEX_LOOKBACK = 60
_STOCK_ZONE_DAYS = 20

_REPO = Path(__file__).resolve().parents[3]

# 噪音板块：成分标签而非投资方向，方向识别时排除
_SECTOR_NOISE = ("通达信88", "ST板块", "次新股", "含H股", "含B股", "含GDR", "含可转债")

KPL_ROOT = _REPO / "infra" / "data" / "kpl"
EM_ROOT = _REPO / "infra" / "data" / "eastmoney"
LP_ROOT = _REPO / "infra" / "data" / "limit_pool"
IC_ROOT = _REPO / "infra" / "data" / "intraday_changes"
_NEWS_TITLE_CAP = 60
_LHB_ITEM_CAP = 20
_LP_ITEM_CAP = 20
_IC_HIGHLIGHT_CAP = 30
# 盘中异动 highlights 优先抽取的类型（最具操作意义）
_IC_KEY_TYPES = ("封涨停板", "打开涨停板", "大笔买入", "火箭发射",
                 "快速反弹", "60日新高")


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
    # 腾讯指数 K 线只有成交量（手），无成交额；键名必须写「成交量」，否则 LLM
    # 会把 volume 误读成「成交额」（2026-08-13 盲判实测出现过该误读）。
    # 真正的两市成交额由 KPL 情绪块的 emotion.daban.两市成交额_亿 提供。
    out = []
    for k in klines[-n:]:
        vol = k.get("volume")
        out.append({
            "d": k["date"], "c": k["close"], "pct": k.get("pct_change"),
            "成交量万手": round(vol / 1e4, 1) if isinstance(vol, (int, float)) else None,
        })
    return out


def _load_directions(config_dir: Path) -> list[dict]:
    raw = yaml.safe_load((config_dir / "direction_pool.yaml").read_text(encoding="utf-8")) or {}
    return [
        # name 可能含来源指称（如"7/2UP强call"），打码处理；id 保持不变
        {"id": d.get("id"), "name": FORBIDDEN_RE.sub("██", str(d.get("name", "")))}
        for d in raw.get("directions", []) or []
        if d.get("id")
    ]


def _load_sector_members() -> dict[str, list[str]]:
    """读 TDX 概念板块成分股（{板块名: [裸码,...]}）。

    数据源 config/stock_monitor/sector_members.json（由
    scripts/fetch_tdx_sector_members.py 从通达信 block_gn.dat 落盘，
    269 个概念板块 / 41054 条成分股映射）。
    """
    path = _REPO / "config" / "stock_monitor" / "sector_members.json"
    if not path.exists():
        return {}
    d = json.loads(path.read_text(encoding="utf-8"))
    return {k: list(v) for k, v in (d.get("concept") or {}).items()}


def _sector_directions(sector_members: dict[str, list[str]],
                       active_codes: set[str]) -> list[dict]:
    """由 TDX 板块成分股反推「当日有行情的板块」作为方向池。

    只保留 active_codes（本地有 K 线且当日有数据的股票）中 ≥1 只成分股的
    板块，按成分股数降序，避免方向池里出现无行情的空板块。
    """
    rows = []
    for name, codes in sector_members.items():
        if name in _SECTOR_NOISE:
            continue
        hit = sorted(c for c in codes if c in active_codes)
        if hit:
            rows.append({"id": name, "name": name, "member_count": len(codes),
                         "local_count": len(hit)})
    rows.sort(key=lambda r: (-r["local_count"], -r["member_count"]))
    return rows


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


def _semanticize_lianban(rows: list) -> list[dict]:
    """连板梯队/二板池裸数组 → 带字段名的结构（供 LLM 直接理解）。

    KPL PHBList/ErBanList 结构：[[代码, 名称, 涨幅, 连板数, "N连板", 板块, "板块;天数"], ...]。
    连板股断板后标签会变成「昨N连板」、连板数归 0（兑现日特征），原样透传，不做归一。
    """
    out = []
    for r in rows:
        if not isinstance(r, (list, tuple)) or len(r) < 5:
            continue
        out.append({
            "code": str(r[0]), "name": str(r[1]), "pct": r[2],
            "连板数": r[3], "标签": str(r[4]),
            "板块": str(r[5]) if len(r) > 5 else "",
        })
    return out


def _load_emotion(day: str, kpl_root: Path) -> dict | None:
    """KPL 情绪快照精选块；当日文件缺失返回 None。

    产出带中文语义键的情绪结构（供 LLM 直接理解），关键补充：
    - 两市成交额（亿元）：源自 daban.qscln（当日成交额，单位万元），
      这是腾讯指数 K 线不提供的量能口径（UP 全程用「两市成交额」判断量能）。
    - 昨日两市成交额（亿元）：daban.q_zrtj（zr=昨日），供环比放量判断。
      （2026-08-13 实测：q_zrtj 是「昨日」、qscln 才是「当日」，早先误用
      q_zrtj 当当日成交额，导致盲判拿到的是 T-1 成交额。）
    """
    path = kpl_root / "emotion" / f"{day}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    out: dict = {}
    daban = d.get("daban") or {}
    if daban:
        yi = lambda w: round(w / 10000, 1) if isinstance(w, (int, float)) else None  # noqa: E731
        out["daban"] = {
            "昨日涨停": daban.get("lZhangTing"),
            "今日涨停": daban.get("tZhangTing"),
            "封板率_pct": daban.get("tFengBan"),
            "昨日封板率_pct": daban.get("lFengBan"),
            "跌停": daban.get("tDieTing"),
            "上涨家数": daban.get("SZJS"),
            "下跌家数": daban.get("XDJS"),
            "炸板家数": daban.get("PPJS"),
            "昨日涨停今收益_pct": daban.get("ZRZTJ"),
            "昨日连板今收益_pct": daban.get("ZRLBJ"),
            "两市成交额_亿": yi(daban.get("qscln") or daban.get("q_zrtj")),
            "昨日两市成交额_亿": yi(daban.get("q_zrtj")),
            "沪市成交额_亿": yi(daban.get("s_zrtj")),
        }
    lianban = d.get("lianban") or []
    if lianban:
        out["连板梯队"] = _semanticize_lianban(lianban)
    erban = d.get("erban") or []
    if erban:
        out["二板池"] = _semanticize_lianban(erban)
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


def _cap_em_item(it: dict) -> dict:
    """东财条目封顶：每股买卖席位各取前 5（字段已是精简形态，其余透传）。"""
    out = dict(it)
    out["buy_seats"] = (it.get("buy_seats") or [])[:5]
    out["sell_seats"] = (it.get("sell_seats") or [])[:5]
    return out


def _load_lhb(day: str, kpl_root: Path, em_root: Path | None = None) -> dict | None:
    """龙虎榜摘要：东财日榜（含席位）优先，缺失回退 KPL GetDay 落盘。

    东财条目按 |net_amt| 降序封顶 _LHB_ITEM_CAP 条；kpl 块 entry_count/list 透传。
    """
    if em_root is not None:
        em_path = em_root / "lhb" / f"{day}.json"
        if em_path.exists():
            d = json.loads(em_path.read_text(encoding="utf-8"))
            items = sorted(d.get("items") or [],
                           key=lambda x: abs(x.get("net_amt") or 0), reverse=True)
            return {"source": "eastmoney",
                    "disclosure_day": d.get("trade_date", day),
                    "count": d.get("stock_count", len(items)),
                    "items": [_cap_em_item(it) for it in items[:_LHB_ITEM_CAP]],
                    "note": d.get("note", "")}
    path = kpl_root / "lhb" / f"{day}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    raw = d.get("list") or {}
    if isinstance(raw, dict):  # 真实形态：{分类ID: [明细...]}
        items = [it for entries in raw.values() for it in entries]
    else:  # 兼容早期扁平数组落盘
        items = list(raw)
    count = d.get("entry_count")
    if count is None:
        count = len(items)
    return {"source": "kpl",
            "disclosure_day": d.get("disclosure_day", ""),
            "count": count,
            "items": items[:_LHB_ITEM_CAP],
            "note": d.get("note", "")}


def _load_limit_pool(day: str, lp_root: Path) -> dict | None:
    """涨停梯队摘要：梯队/晋级率/反包/竞价一字 + 涨停明细（按封单额封顶 _LP_ITEM_CAP 条）。"""
    path = lp_root / f"{day.replace('-', '')}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    items = sorted(d.get("zt_items") or [],
                   key=lambda x: x.get("fund") or 0, reverse=True)
    return {"date": d.get("date", day),
            "zt_count": d.get("zt_count"), "zb_count": d.get("zb_count"),
            "max_lbc": d.get("max_lbc"), "ladder": d.get("ladder") or {},
            "auction_sealed": d.get("auction_sealed") or [],
            "compare": d.get("compare") or {},
            "first_board_width": d.get("first_board_width"),
            "regulatory_distance": d.get("regulatory_distance"),
            "zt_items": items[:_LP_ITEM_CAP],
            "zb_items": (d.get("zb_items") or [])[:_LP_ITEM_CAP]}


def _load_intraday_changes(day: str, ic_root: Path) -> dict | None:
    """盘中异动摘要：22 类计数 + 关键类型 highlights（compact，控 prompt 体积）。

    全量明细在 infra/data/intraday_changes/<date>.json，这里只送计数与少量高亮。
    """
    path = ic_root / f"{day.replace('-', '')}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    counts = d.get("counts") or {}
    types_data = d.get("types") or {}
    highlights: list[dict] = []
    for t in _IC_KEY_TYPES:
        items = types_data.get(t)
        if not isinstance(items, list):
            continue
        for it in items[:8]:
            highlights.append({
                "type": t, "time": it.get("time", ""),
                "code": it.get("code", ""), "name": it.get("name", ""),
                "pct": _ic_parse_pct(it.get("info", "")),
            })
        if len(highlights) >= _IC_HIGHLIGHT_CAP:
            break
    return {"date": d.get("date", day),
            "counts": counts, "total": d.get("total"),
            "highlights": highlights[:_IC_HIGHLIGHT_CAP]}


def _ic_parse_pct(info: str) -> str:
    parts = info.split(",")
    return parts[-1].strip() if parts else ""


_STRUCTURE_TFS = ("daily", "120min", "90min", "60min", "30min")


def _load_structure(day: str, db_path=None) -> dict:
    """上证指数（sh000001）多级别顶底结构识别（截至 day）。

    读 index_klines 表各级别 K 线，自算 MACD 后调 detect_structure，只保留
    有结构（bottom/top 非 None）的级别。供盲判定位「反弹第几天 / 顶部调整」。

    注意：分钟级 bar_time 带时间（'2026-08-14 15:00'），daily 不带；查询上限
    分别用 day 与 day+' 23:59:59' 处理，避免字符串比较漏掉当日盘中数据。
    """
    import sqlite3

    from investment_engine.structure import detect_structure

    db = Path(db_path) if db_path else _REPO / "infra" / "data" / "kline_cache.db"
    if not db.exists():
        return {}
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    out: dict = {}
    for tf in _STRUCTURE_TFS:
        upper = day if tf == "daily" else f"{day} 23:59:59"
        rows = conn.execute(
            "SELECT bar_time, close, low, high FROM index_klines "
            "WHERE code='sh000001' AND timeframe=? AND bar_time <= ? ORDER BY bar_time",
            (tf, upper),
        ).fetchall()
        if len(rows) < 30:  # MACD 需要足够历史
            continue
        klines = [dict(r) for r in rows]
        res = detect_structure(klines, window=4, timeframe=tf)
        keep = {}
        if res.get("bottom"):
            keep["bottom"] = res["bottom"]
        if res.get("top"):
            keep["top"] = res["top"]
        if res.get("recent_bottom"):
            keep["recent_bottom"] = res["recent_bottom"]
        if res.get("recent_top"):
            keep["recent_top"] = res["recent_top"]
        if keep:
            out[tf] = keep
    conn.close()
    return out


_CORE_PATTERN_IDS = ("sentiment_cycle", "mainline_identification", "position_by_cycle")


def _load_core_patterns() -> list[dict]:
    """每篇复盘必用的核心模式正文：判据步骤 + 证伪条件。

    防泄漏：只取 steps(name/action)/falsification，不取 source_raw 等来源字段；
    出厂前由 pack_to_prompt 的 assert_no_leakage 终检。
    """
    raw = yaml.safe_load((_REPO / "framework" / "reasoning-patterns.yaml").read_text(encoding="utf-8"))
    by_id = {p["pattern_id"]: p for p in raw.get("patterns", [])}
    out = []
    for pid in _CORE_PATTERN_IDS:
        p = by_id.get(pid)
        if not p:
            continue
        out.append({
            "pattern_id": pid,
            "name": p.get("name", ""),
            "steps": [{"name": s.get("name", ""), "action": s.get("action", "")}
                      for s in (p.get("steps") or [])],
            "falsification": [str(f) for f in (p.get("falsification") or [])],
        })
    return out


def build_daily_pack(day: str, *, config_dir: Path, db_path=None,
                     kpl_root=None, em_root=None, lp_root=None,
                     ic_root=None) -> dict:
    """组装某日数据包（只含截至当日的数据）。"""
    index = {}
    for code in INDEX_CODES:
        bars = get_index_daily(code, "2000-01-01", day, db_path=db_path)
        index[code] = _compact_bars(bars, _INDEX_LOOKBACK)

    from qing_investment.monitor.context import load_monitor_config

    cfg = load_monitor_config(config_dir)
    sector_members = _load_sector_members()
    # 反向索引：股票裸码 → 所属 TDX 板块列表
    code_to_sectors: dict[str, list[str]] = {}
    for sname, codes in sector_members.items():
        for c in codes:
            code_to_sectors.setdefault(c, []).append(sname)

    stocks = []
    active_codes: set[str] = set()
    for s in (cfg.stock_pool or {}).get("stocks", []):
        code = s.get("code")
        if not code:
            continue
        bars = get_klines_range(code, "2000-01-01", day, db_path=db_path)
        if not bars or bars[-1]["date"] != day:
            continue
        last = bars[-1]
        bare = code.split(".")[0]
        active_codes.add(bare)
        sectors = [b for b in code_to_sectors.get(bare, []) if b not in _SECTOR_NOISE]
        stocks.append({
            "code": bare, "name": s.get("name", ""),
            # TDX 板块归属（多板块，已滤噪音）；无板块归属时回退本地 stock_pool direction
            "sectors": sectors,
            "direction": sectors[0] if sectors else s.get("direction", ""),
            "close": last["close"], "pct": last.get("pct_change"),
            "turnover": last.get("turnover"), "pos20": _pos20(bars),
        })

    # 方向池：TDX 概念板块（当日有行情的），回退本地 direction_pool
    directions = _sector_directions(sector_members, active_codes) if sector_members \
        else _load_directions(config_dir)

    pack = {
        "date": day,
        "index": index,
        "stocks": stocks,
        "directions": directions,
        "structure": _load_structure(day, db_path),
        "chains": _load_chains(),
        "glossary": _load_glossary(),
        "patterns": _load_patterns_index(),
        "core_patterns": _load_core_patterns(),
    }
    root = Path(kpl_root) if kpl_root else KPL_ROOT
    em = Path(em_root) if em_root else EM_ROOT
    lp = Path(lp_root) if lp_root else LP_ROOT
    ic = Path(ic_root) if ic_root else IC_ROOT
    blocks = {"emotion": _load_emotion(day, root),
              "news_titles": _load_news_titles(day, root),
              "lhb": _load_lhb(day, root, em)}
    missing = [f"kpl_{k}" for k, v in blocks.items() if v is None]
    limit_pool = _load_limit_pool(day, lp)
    if limit_pool is None:
        missing.append("limit_pool")
    else:
        blocks["limit_pool"] = limit_pool
    intraday_changes = _load_intraday_changes(day, ic)
    if intraday_changes is None:
        missing.append("intraday_changes")
    else:
        blocks["intraday_changes"] = intraday_changes
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
