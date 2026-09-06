"""盲测每日数据包构建：prompt 的唯一输入，只含当日可得的客观数据。

防泄漏：pack_to_prompt 产出必须过 assert_no_leakage（无未来日期、无 UP 指称）。
时变字段（direction_pool.current_stage 等）一律不进包。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import yaml

from investment_engine.backtest.history import get_index_daily, get_klines_range, list_trading_days

FORBIDDEN_RE = re.compile(r"UP|青枫浦|博主")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
INDEX_CODES = ("IDX000300", "IDX000001", "IDX399006", "IDX399001", "IDX000852",
               "IDX000932", "IDX880823")  # 中证2000/微盘股（2026-08-16 入包，contract-v2 D7 可选项）
# 2026-09-05 包瘦身 Round C：60→20 展示口径导致「震荡误判调整」净 -2 天
# （可视历史变短 → 现价显得接近波段低点 → 破位观感放大），已回滚回 60。
_INDEX_LOOKBACK = 60
_STOCK_ZONE_DAYS = 20
# 40 日复验（2026-09-06）：BLINDTEST_PACK_SLIM=0 关闭瘦身三刀，用于基线臂
# A/B；生产默认保持开启。
_PACK_SLIM = os.environ.get("BLINDTEST_PACK_SLIM", "1") != "0"
# 2026-09-05 包瘦身：每股板块标签上限（原每只约 20 个 TDX 板块名，占包 ~25%）
_SECTOR_CAP_PER_STOCK = 8 if _PACK_SLIM else None

_REPO = Path(__file__).resolve().parents[3]

# 噪音板块：成分标签而非投资方向，方向识别时排除
_SECTOR_NOISE = ("通达信88", "ST板块", "次新股", "含H股", "含B股", "含GDR", "含可转债")

KPL_ROOT = _REPO / "infra" / "data" / "kpl"
EM_ROOT = _REPO / "infra" / "data" / "eastmoney"
LP_ROOT = _REPO / "infra" / "data" / "limit_pool"
IC_ROOT = _REPO / "infra" / "data" / "intraday_changes"
FF_ROOT = _REPO / "infra" / "data" / "fund_flow"
SI_ROOT = _REPO / "infra" / "data" / "sector_intraday"
RESEARCH_ROOT = _REPO / "infra" / "data" / "research"
IA_ROOT = _REPO / "infra" / "data" / "intraday_amount"
GM_ROOT = _REPO / "infra" / "data" / "global_macro"
_NEWS_TITLE_CAP = 60
_LHB_ITEM_CAP = 12 if _PACK_SLIM else 20  # 2026-09-05 包瘦身：20→12
_LP_ITEM_CAP = 20
_LHB_SEAT_CAP = 3 if _PACK_SLIM else 5  # 2026-09-05 包瘦身：每股买卖席位各取前 3（原 5）
_IC_HIGHLIGHT_CAP = 30
_RESEARCH_ITEM_CAP = 30  # notices/reports 各封顶（C6）
_CATALYST_CAP = 60  # catalysts_since_prev_day 总量封顶（C2）
_FF_INSTANT_TOP = 10  # 即时窗口净流入/流出各 top10（C1/C4）
_FF_MULTI_TOP = 5  # 3/5/10日窗口净流入各 top5（持续性佐证）
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


def _active_chains(chains: list[dict], active_codes: set[str],
                   sector_names: set[str]) -> list[dict]:
    """只保留当日有行情的产业链（2026-09-05 包瘦身：26 条全量约 28K 字符）。

    保留条件：映射股与当日 active 股票有交集，或链名（去「产业链」后缀）与
    当日活跃板块名互含。无活跃链时返回空列表（如实，不算 missing）。
    """
    out = []
    for c in chains:
        codes = {str(m.get("code", "")).split(".")[0] for m in c.get("mappings") or []}
        if codes & active_codes:
            out.append(c)
            continue
        cname = str(c.get("name", "")).replace("产业链", "")
        if cname and any(cname in s or s in cname for s in sector_names):
            out.append(c)
    return out


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


_VOLUME_SERIES_MAX = 60  # 量能序列回溯上限（交易日）


def _load_volume_series(day: str, kpl_root: Path,
                        vh_path: Path | None = None) -> dict | None:
    """两市成交额近期序列（亿元），最多 60 个交易日，双源合并：

    - 长历史：infra/data/volume_history.json（TDX 上证+深证成指日K amount 合计，
      cron 回灌；与 KPL 口径实测逐位一致）；
    - 近期覆盖：kpl/emotion 本地文件（当日/最新值以此为准，日期冲突时覆盖）。
    峰值/谷值/均值均为「可用窗口」口径并如实标注。两源皆空返回 None（登记 missing）；
    只取日期 ≤ day 的点（防泄漏）；fetched_at 等元数据不进包。
    """
    by_date: dict[str, dict] = {}
    from investment_engine.volume_history import load_volume_history
    vh = load_volume_history(vh_path) if vh_path else load_volume_history()
    for p in (vh or {}).get("points") or []:
        if isinstance(p.get("成交额_亿"), (int, float)) and p.get("date", "") <= day:
            by_date[p["date"]] = {"date": p["date"], "成交额_亿": p["成交额_亿"]}
    em_dir = kpl_root / "emotion"
    if em_dir.exists():
        for p in sorted(em_dir.glob("*.json")):
            d = p.stem
            if d > day:
                continue
            try:
                daban = (json.loads(p.read_text(encoding="utf-8")).get("daban") or {})
            except json.JSONDecodeError:
                continue
            qscln = daban.get("qscln")
            if isinstance(qscln, (int, float)) and qscln:
                by_date[d] = {"date": d, "成交额_亿": round(qscln / 10000, 1)}
    if not by_date:
        return None
    points = [by_date[d] for d in sorted(by_date)][-_VOLUME_SERIES_MAX:]
    vals = [p["成交额_亿"] for p in points]
    # 地量分位（提案 2026-09-05 模式五/规则34 数据基础）：窗口内 ≤ 最新值的点占比，
    # 低分位=接近地量（做空动能衰竭识别的正向信号输入）
    latest = vals[-1]
    latest_rank_pct = round(100 * sum(1 for v in vals if v <= latest) / len(vals), 1)
    return {
        "points": points,
        "mean_亿": round(sum(vals) / len(vals), 1),
        "peak": max(points, key=lambda p: p["成交额_亿"]),
        "trough": min(points, key=lambda p: p["成交额_亿"]),
        "latest_rank_pct": latest_rank_pct,
        "coverage": f"{len(points)}/{_VOLUME_SERIES_MAX}",
        "note": "长历史=TDX 两指数合计（与 KPL 口径一致）、近期=KPL 情绪；峰值/谷值/均值为可用窗口口径，非全周期",
    }


def _news_stocks(it: dict) -> list[str]:
    """KPL 资讯条目的关联股票代码提取（_load_news_titles 与 catalysts 共用）。"""
    stocks = []
    for s in (it.get("stocks") or [])[:5]:
        if isinstance(s, dict):
            stocks.append(str(s.get("StockID") or s.get("Code") or s))
        else:
            stocks.append(str(s))
    return stocks


def _load_news_titles(day: str, kpl_root: Path) -> dict | None:
    """当日资讯标题列表（不含全文），封顶 _NEWS_TITLE_CAP 条。"""
    path = kpl_root / "news" / day / "index.json"
    if not path.exists():
        return None
    items = json.loads(path.read_text(encoding="utf-8"))
    titles = [{"t": str(it.get("title", "")), "stocks": _news_stocks(it)}
              for it in items[:_NEWS_TITLE_CAP]]
    out: dict = {"items": titles}
    if len(items) > _NEWS_TITLE_CAP:
        out["truncated"] = f"{_NEWS_TITLE_CAP}/{len(items)}"
    return out


def _cap_em_item(it: dict) -> dict:
    """东财条目封顶：每股买卖席位各取前 _LHB_SEAT_CAP（字段已是精简形态，其余透传）。"""
    out = dict(it)
    out["buy_seats"] = (it.get("buy_seats") or [])[:_LHB_SEAT_CAP]
    out["sell_seats"] = (it.get("sell_seats") or [])[:_LHB_SEAT_CAP]
    return out


def _summarize_jgmmtj(rows: list) -> dict | None:
    """机构买卖席位汇总（C3）：净买入/净卖出 top5 + 家数统计。

    jgmmtj 为 None（拉取失败）或空列表时返回 None，不影响 lhb 块其余部分。
    """
    if not isinstance(rows, list) or not rows:
        return None
    valid = [r for r in rows if isinstance(r.get("机构买入净额"), (int, float))]
    if not valid:
        return None

    def _row(r: dict) -> dict:
        ratio = r.get("机构净买额占总成交额比")
        return {"代码": r.get("代码"), "名称": r.get("名称"),
                "机构买入净额_亿": round(r["机构买入净额"] / 1e8, 2),
                "买方机构数": r.get("买方机构数"), "卖方机构数": r.get("卖方机构数"),
                "机构净买额占总成交额比": round(ratio, 2) if isinstance(ratio, (int, float)) else ratio}

    desc = sorted(valid, key=lambda r: r["机构买入净额"], reverse=True)
    asc = sorted(valid, key=lambda r: r["机构买入净额"])
    return {"净买入top5": [_row(r) for r in desc[:5]],
            "净卖出top5": [_row(r) for r in asc[:5]],
            "净买入家数": sum(1 for r in valid if r["机构买入净额"] > 0),
            "净卖出家数": sum(1 for r in valid if r["机构买入净额"] < 0)}


def _load_lhb(day: str, kpl_root: Path, em_root: Path | None = None) -> dict | None:
    """龙虎榜摘要：东财日榜（含席位）优先，缺失回退 KPL GetDay 落盘。

    东财条目按 |net_amt| 降序封顶 _LHB_ITEM_CAP 条；kpl 块 entry_count/list 透传。
    东财 payload 含 jgmmtj（机构买卖统计）时附加机构席位汇总（C3）。
    """
    if em_root is not None:
        em_path = em_root / "lhb" / f"{day}.json"
        if em_path.exists():
            d = json.loads(em_path.read_text(encoding="utf-8"))
            items = sorted(d.get("items") or [],
                           key=lambda x: abs(x.get("net_amt") or 0), reverse=True)
            out = {"source": "eastmoney",
                   "disclosure_day": d.get("trade_date", day),
                   "count": d.get("stock_count", len(items)),
                   "items": [_cap_em_item(it) for it in items[:_LHB_ITEM_CAP]],
                   "note": d.get("note", "")}
            jg = _summarize_jgmmtj(d.get("jgmmtj"))
            if jg is not None:
                out["jgmmtj"] = jg
            return out
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
    """涨停梯队摘要：梯队/晋级率/反包/竞价一字 + 涨停明细（按封单额封顶 _LP_ITEM_CAP 条）。

    payload 含 broken_boards（昨日连板今日断板名单，C5）时全量带进包（量小）；
    broken_boards 为 None（拉取失败）时不进包，note 如实透传。
    """
    path = lp_root / f"{day.replace('-', '')}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    items = sorted(d.get("zt_items") or [],
                   key=lambda x: x.get("fund") or 0, reverse=True)
    out = {"date": d.get("date", day),
           "zt_count": d.get("zt_count"), "zb_count": d.get("zb_count"),
           "max_lbc": d.get("max_lbc"), "ladder": d.get("ladder") or {},
           "auction_sealed": d.get("auction_sealed") or [],
           "compare": d.get("compare") or {},
           "first_board_width": d.get("first_board_width"),
           "regulatory_distance": d.get("regulatory_distance"),
           "zt_items": items[:_LP_ITEM_CAP],
           "zb_items": (d.get("zb_items") or [])[:_LP_ITEM_CAP]}
    if d.get("broken_boards") is not None:
        out["broken_boards"] = d["broken_boards"]
    if d.get("broken_boards_note"):
        out["broken_boards_note"] = d["broken_boards_note"]
    return out


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
_STRUCTURE_INDEXES = (
    ("sh000001", "上证指数"),
    ("sh000688", "科创50"),
    ("sz399006", "创业板指"),
)


def _load_structure(day: str, db_path=None) -> dict:
    """多指数（上证大盘 + 创业板指/科技主线）多级别顶底结构识别（截至 day）。

    读 index_klines 表各级别 K 线，自算 MACD 后调 detect_structure，只保留
    有结构（bottom/top/recent_* 非 None）的级别。供盲判定位「反弹第几天 / 顶部调整」。

    输出 {指数名: {级别: 结构}}。关键：UP 的「6-8天反弹」是科技类指数（科创/
    创业板）的 90 分钟底部结构，上证大盘同期只有低级别结构——故需多指数，
    创业板指作为科创的本地近似（本地无 sh000688 分钟数据）。

    注意：分钟级 bar_time 带时间（'2026-08-14 15:00'），daily 不带；查询上限
    分别用 day 与 day+' 23:59:59' 处理，避免字符串比较漏掉当日盘中数据。
    """
    import sqlite3
    from datetime import datetime, timedelta

    from investment_engine.structure import detect_structure

    db = Path(db_path) if db_path else _REPO / "infra" / "data" / "kline_cache.db"
    if not db.exists():
        return {}
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    # recent 结构只保留最近 60 天内形成的（过滤太早的历史结构，如 3 月前的底部）
    cutoff = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=60)).strftime("%Y-%m-%d")
    out: dict = {}
    for code, name in _STRUCTURE_INDEXES:
        per_idx: dict = {}
        for tf in _STRUCTURE_TFS:
            upper = day if tf == "daily" else f"{day} 23:59:59"
            rows = conn.execute(
                "SELECT bar_time, close, low, high FROM index_klines "
                "WHERE code=? AND timeframe=? AND bar_time <= ? ORDER BY bar_time",
                (code, tf, upper),
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
            rb = res.get("recent_bottom")
            if rb and str(rb.get("time", ""))[:10] >= cutoff:
                keep["recent_bottom"] = rb
            rt = res.get("recent_top")
            if rt and str(rt.get("time", ""))[:10] >= cutoff:
                keep["recent_top"] = rt
            td9 = res.get("td9")
            if td9 and (td9.get("count") or 0) >= 5:  # 计数≥5才值得提示（九转中段）
                keep["td9"] = td9
            if keep:
                per_idx[tf] = keep
        if per_idx:
            out[name] = per_idx
    conn.close()
    return out


def _load_intraday_amount(day: str, ia_root: Path | None = None) -> dict | None:
    """盘中量能形态（放量/缩量判断）：优先读 cron 落盘，无文件回退实时计算。

    落盘文件（infra/data/intraday_amount/{yyyymmdd}.json，15:35 cron 由
    intraday_amount 模块写入）使历史回放可用；无文件时回退 TDX 实时拉取
    （行为与接线前一致，仅当日盘中/盘后有效）。实时拉取得到的实际交易日
    与 day 不一致时视同缺失（防历史回放串入最新数据）。
    返回 None 或 {date, 分时[{时点,累计_亿,预估全天_亿}], 开盘预估全天_亿, 尾盘实际全天_亿,
    形态, 环比前日_pct, 占比中位数, 校准残差_pct}（后三者为 2026-08-20 校准新增）。
    """
    from investment_engine import intraday_amount

    data = intraday_amount.load_intraday_amount(
        day, data_dir=Path(ia_root) if ia_root else IA_ROOT)
    if data is not None:
        return data
    data = intraday_amount.compute_intraday_amount()
    if data and data.get("date") == day:
        return data
    return None


def _load_global_macro(day: str, gm_root: Path) -> dict | None:
    """全球宏观快照（美债/美元/美股/亚太收盘，global_macro 模块 cron 落盘）。

    回答「外力/内生」归因的外部链条位置（提案 2026-08-20-data-channel-global-macro）。
    文件缺失返回 None（调用方登记 missing）；fetched_at 可能晚于回放日，不进包。
    """
    from investment_engine.global_macro import load_global_macro

    d = load_global_macro(day, root=gm_root)
    if not d:
        return None
    return {k: v for k, v in d.items() if k != "fetched_at"}


def _load_research(day: str, research_root: Path) -> dict | None:
    """当日公告 + 研报标题摘要（C6），各封顶 _RESEARCH_ITEM_CAP 条。

    两个文件均缺失返回 None（调用方登记 missing）；单文件缺失只带现有部分。
    标题为自由文本，逐条过 assert_no_leakage（含来源指称/未来日期即拒绝）。
    只取标题与关联股票字段，不带 url/date 等冗余字段（控 prompt 体积）。
    """
    npath = research_root / "notices" / f"{day}.json"
    rpath = research_root / "reports" / f"{day}.json"
    if not npath.exists() and not rpath.exists():
        return None
    out: dict = {}
    if npath.exists():
        items = json.loads(npath.read_text(encoding="utf-8"))
        rows = []
        for n in items[:_RESEARCH_ITEM_CAP]:
            title = str(n.get("title", ""))
            assert_no_leakage(title, day)
            rows.append({"code": n.get("code"), "name": n.get("name"),
                         "title": title, "type": n.get("type")})
        out["notices"] = rows
        if len(items) > _RESEARCH_ITEM_CAP:
            out["notices_truncated"] = f"{_RESEARCH_ITEM_CAP}/{len(items)}"
    if rpath.exists():
        items = json.loads(rpath.read_text(encoding="utf-8"))
        rows = []
        for r in items[:_RESEARCH_ITEM_CAP]:
            title = str(r.get("title", ""))
            assert_no_leakage(title, day)
            rows.append({"title": title, "org": r.get("org"),
                         "qtype_name": r.get("qtype_name"),
                         "industry_name": r.get("industry_name"),
                         "stock_code": r.get("stock_code"),
                         "stock_name": r.get("stock_name"),
                         "rating": r.get("rating")})
        out["reports"] = rows
        if len(items) > _RESEARCH_ITEM_CAP:
            out["reports_truncated"] = f"{_RESEARCH_ITEM_CAP}/{len(items)}"
    return out or None


def _read_json_list(path: Path) -> list:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _load_catalysts(day: str, target_day: str, research_root: Path,
                    kpl_root: Path) -> list[dict]:
    """(day, target_day] 区间催化扫描（C2 周末/节假日催化通道）。

    逐日合并公告/研报/KPL 资讯标题（周末由 research_feed 覆盖），每条注明
    来源日期与来源类型，总量封顶 _CATALYST_CAP。封顶优先保留离 target_day
    最近的日期（盘前视角越近越相关），展示顺序恢复为时间正序。标题逐条过
    assert_no_leakage（边界 = target_day：盘前预测视角下区间内容当日可得）。
    无数据返回空列表（不算 missing——周末无催化是正常情形，不是数据缺口）。
    """
    from datetime import date, timedelta

    start = date.fromisoformat(day) + timedelta(days=1)
    end = date.fromisoformat(target_day)
    out: list[dict] = []
    cur = end
    while cur >= start:
        d = cur.isoformat()
        for n in _read_json_list(research_root / "notices" / f"{d}.json"):
            title = str(n.get("title", ""))
            assert_no_leakage(title, target_day)
            out.append({"date": d, "source": "公告", "code": n.get("code"),
                        "name": n.get("name"), "title": title})
        for r in _read_json_list(research_root / "reports" / f"{d}.json"):
            title = str(r.get("title", ""))
            assert_no_leakage(title, target_day)
            out.append({"date": d, "source": "研报", "org": r.get("org"),
                        "stock_code": r.get("stock_code"),
                        "stock_name": r.get("stock_name"), "title": title})
        for it in _read_json_list(kpl_root / "news" / d / "index.json"):
            title = str(it.get("title", ""))
            assert_no_leakage(title, target_day)
            out.append({"date": d, "source": "资讯", "title": title,
                        "stocks": _news_stocks(it)})
        cur -= timedelta(days=1)
    return out[:_CATALYST_CAP][::-1]


def _ff_top(rows: list, n: int, *, reverse: bool) -> list[dict]:
    """资金流窗口净额排序取 topN（净额单位亿元，akshare 原值）。"""
    valid = [r for r in rows if isinstance(r.get("净额"), (int, float))]
    valid.sort(key=lambda r: r["净额"], reverse=reverse)
    return valid[:n]


def _ff_instant_row(r: dict) -> dict:
    return {"行业": r.get("行业"), "净额": r.get("净额"),
            "行业-涨跌幅": r.get("行业-涨跌幅"), "领涨股": r.get("领涨股")}


def _ff_multi_row(r: dict) -> dict:
    return {"行业": r.get("行业"), "净额": r.get("净额"),
            "阶段涨跌幅": r.get("阶段涨跌幅")}


def _load_sector_intraday(day: str, si_root: Path) -> dict | None:
    """板块分时强度：防御/进攻阵营全日/上午/下午涨跌幅 + 拉升定性。

    回答「拉升发生在哪个时段、由哪类板块完成」（UP 8-18：下午拉升由银行完成
    = 避险资金抬指数，诱多嫌疑）。文件缺失/空板块返回 None（登记 missing）。
    """
    from investment_engine.sector_intraday import load_sector_intraday

    d = load_sector_intraday(day, root=si_root)
    if not d or not d.get("sectors"):
        return None
    return {"date": d.get("date", day),
            "pm_lead_camp": d.get("pm_lead_camp"),
            "sectors": d["sectors"]}


def _load_fund_flow(day: str, ff_root: Path) -> dict | None:
    """板块资金流摘要（C1/C4）：行业/概念即时 top10 双向 + 行业多日窗口 top5。

    回答「换手方向 + 持续性」（A3 量能源头判断）：即时窗口给当日板块间资金
    迁移方向，3/5/10日窗口给净流入持续性佐证。文件缺失或全部窗口拉取失败
    返回 None（调用方登记 missing）；部分窗口失败照常出包并记 errors_note。
    fetched_at 可能晚于回放日，不进包。
    """
    path = ff_root / f"{day.replace('-', '')}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    industry = d.get("industry") or {}
    concept = d.get("concept") or {}
    usable = any(isinstance(v, list) and v
                 for v in list(industry.values()) + list(concept.values()))
    if not usable:
        return None
    out: dict = {"date": d.get("date", day)}
    ind_now = industry.get("即时") or []
    if ind_now:
        out["行业即时"] = {
            "净流入top10": [_ff_instant_row(r)
                            for r in _ff_top(ind_now, _FF_INSTANT_TOP, reverse=True)],
            "净流出top10": [_ff_instant_row(r)
                            for r in _ff_top(ind_now, _FF_INSTANT_TOP, reverse=False)],
        }
    con_now = concept.get("即时") or []
    if con_now:
        out["概念即时"] = {
            "净流入top10": [_ff_instant_row(r)
                            for r in _ff_top(con_now, _FF_INSTANT_TOP, reverse=True)],
            "净流出top10": [_ff_instant_row(r)
                            for r in _ff_top(con_now, _FF_INSTANT_TOP, reverse=False)],
        }
    multi = {}
    for w in ("3日排行", "5日排行", "10日排行"):
        rows = industry.get(w) or []
        if rows:
            multi[w] = {"净流入top5": [_ff_multi_row(r)
                                       for r in _ff_top(rows, _FF_MULTI_TOP, reverse=True)]}
    if multi:
        out["行业多日"] = multi
    if d.get("errors"):
        out["errors_note"] = f"{len(d['errors'])} 个窗口拉取失败"
    return out


_CYCLE_INDEXES = (
    ("科创50", "sh000688", "90min"),
    ("创业板指", "sz399006", "90min"),
    ("上证指数", "sh000001", "90min"),
)


def _compute_cycle_states(day: str, db_path=None) -> dict:
    """代码确定性算多指数的 cycle_state 候选，供大模型综合判断。

    每个指数优先 90min 底部结构（recent_bottom），无则回退 60min。
    返回 {指数名: {rebound_day, bottom_level, bottom_date, theoretical_window}}，
    无结构的指数不出现。交易日计数用 daily bar（bottom_date 当天计第 1 天）。
    """
    import sqlite3

    from investment_engine.structure import detect_structure

    db = Path(db_path) if db_path else _REPO / "infra" / "data" / "kline_cache.db"
    if not db.exists():
        return {}
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    out: dict = {}
    for name, code, tf in _CYCLE_INDEXES:
        rb = None
        tf_used = tf
        for t in (tf, "60min"):
            upper = day if t == "daily" else f"{day} 23:59:59"
            rows = conn.execute(
                "SELECT bar_time, close, low, high FROM index_klines "
                "WHERE code=? AND timeframe=? AND bar_time <= ? ORDER BY bar_time",
                (code, t, upper),
            ).fetchall()
            if len(rows) < 30:
                continue
            klines = [dict(r) for r in rows]
            rb = detect_structure(klines, window=4, timeframe=t).get("recent_bottom")
            if rb and rb.get("time"):
                tf_used = t
                break
        if not rb or not rb.get("time"):
            continue
        bottom_date = str(rb["time"])[:10]
        td = rb.get("theoretical_days")
        if td and td != (None, None) and td[0] is not None:
            window = f"{td[0]}天" if td[0] == td[1] else f"{td[0]}-{td[1]}天"
        else:
            window = ""
        daily_cnt = conn.execute(
            "SELECT COUNT(*) FROM index_klines WHERE code='sh000001' AND timeframe='daily' "
            "AND bar_time >= ? AND bar_time <= ?",
            (bottom_date, day),
        ).fetchone()[0]
        out[name] = {
            "rebound_day": daily_cnt,
            "bottom_level": tf_used,
            "bottom_date": bottom_date,
            "theoretical_window": window,
        }
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


def _load_direction_track(day: str, pred_dir: Path | None = None,
                          db_path=None) -> dict | None:
    """候选方向历史 T+5 超额命中率块（提案 2026-09-05 数据缺口 3）。

    模型选方向时看不到自身历史战绩（稀缺资源 0/4、存储芯片 0/6 仍被反复选）；
    本块聚合 predictions 目录里已 scored 记录的 due_scores.direction_details。
    防泄漏：只聚合「截至 day 已满 5 个交易日」的记录（与 shadow/maturity
    .due_predictions 同口径；交易日以沪深300指数缓存为准，免个股表依赖）；
    未来日期/未到期/pending 记录一律跳过。无合格记录返回 None（不出块、
    不登记 missing）。
    """
    root = Path(pred_dir) if pred_dir else _REPO / "evals" / "shadow" / "predictions"
    if not root.exists():
        return None
    stats: dict[str, dict] = {}
    for path in sorted(root.glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if rec.get("status") != "scored":
            continue
        pred_day = str(rec.get("date") or "")
        if not pred_day or pred_day >= day:
            continue
        # 到期口径：pred_day 与 day 之间（含两端）须 ≥6 个交易日
        # （maturity.due_predictions: len(days_between)-1 >= 5）
        days_between = [b["date"] for b in
                        get_index_daily("IDX000300", pred_day, day, db_path)]
        if len(days_between) - 1 < 5:
            continue
        details = ((rec.get("due_scores") or {}).get("direction_details")) or []
        for d in details:
            did = str(d.get("direction_id") or "")
            if not did:
                continue
            s = stats.setdefault(did, {"命中": 0, "样本": 0, "_excess": []})
            s["样本"] += 1
            if d.get("hit"):
                s["命中"] += 1
            dr, br = d.get("dir_ret"), d.get("bench_ret")
            if isinstance(dr, (int, float)) and isinstance(br, (int, float)):
                s["_excess"].append(dr - br)
    if not stats:
        return None
    directions = {}
    for did in sorted(stats):
        s = stats[did]
        n = s["样本"]
        directions[did] = {
            "命中": s["命中"],
            "样本": n,
            "命中率": round(s["命中"] / n, 2),
            "平均超额_pct": round(sum(s["_excess"]) / len(s["_excess"]), 1)
            if s["_excess"] else None,
        }
    return {"directions": directions,
            "口径": "T+5 到期方向超额（方向均值-沪深300），截至当日已满5个交易日"}


def _range_anchors(index: dict) -> dict | None:
    """复合区间双锚（提案 2026-09-05 模式六/规则35 数据基础，收盘价口径）。

    指数分化僵持期用区间高/低做双锚，区间内摆动不升级破位/瓦解定性。
    输入为 pack 的 index 块（_compact_bars 口径，键含 d/c）。序列不足 20 根
    的指数跳过；全部不足返回 None（不出块）。
    """
    out = {}
    for code, bars in (index or {}).items():
        closes = [float(b["c"]) for b in bars
                  if isinstance(b, dict) and isinstance(b.get("c"), (int, float))]
        if len(closes) < 5:
            continue
        window = closes[-60:]
        out[code] = {
            "区间高_60d": max(window),
            "区间低_60d": min(window),
            "近20日低": min(closes[-20:]),
            "最新收盘": closes[-1],
        }
    return out or None


def build_daily_pack(day: str, *, config_dir: Path, db_path=None,
                     kpl_root=None, em_root=None, lp_root=None,
                     ic_root=None, research_root=None, ff_root=None,
                     ia_root=None, si_root=None, gm_root=None, vh_path=None,
                     pred_dir=None,
                     target_day: str | None = None) -> dict:
    """组装某日数据包（只含截至当日的数据）。

    target_day（盘前预测目标日）提供时，额外扫描 (day, target_day] 区间的
    公告/研报/KPL 资讯合成 catalysts_since_prev_day（C2）；默认 None 不扫
    （盘后复盘/历史回放路径无此块，防泄漏边界保持 = day）。
    """
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
        # TDX 板块归属（多板块，已滤噪音，上限 _SECTOR_CAP_PER_STOCK）；无板块归属时回退本地 stock_pool direction
        sectors = [b for b in code_to_sectors.get(bare, [])
                   if b not in _SECTOR_NOISE][:_SECTOR_CAP_PER_STOCK]
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
        # 精选方向池静态快照（id+打码 name，无时变字段）：directions 块切到 TDX
        # 板块后池 id 在包内不可见，模型只能选当日热点中文名（2026-09-05 A/B 归因：
        # v15 靠 prompt 内嵌分簇表看到池 id，其池 id 方向 5/6 命中、TDX 热点 3/6）。
        # direction_track 战绩也用池 id 词汇，本块是两词汇表的桥。
        "direction_pool": _load_directions(config_dir),
        "structure": _load_structure(day, db_path),
        "intraday_amount": _load_intraday_amount(day, ia_root),
        "cycle_state": _compute_cycle_states(day, db_path),
        # 只进当日有行情的产业链（瘦身；空列表=当日无活跃链，如实）
        "chains": (_active_chains(_load_chains(), active_codes,
                                  {str(d.get("name", "")) for d in directions})
                   if _PACK_SLIM else _load_chains()),
        "glossary": _load_glossary(),
        "patterns": _load_patterns_index(),
        "core_patterns": _load_core_patterns(),
    }
    root = Path(kpl_root) if kpl_root else KPL_ROOT
    em = Path(em_root) if em_root else EM_ROOT
    lp = Path(lp_root) if lp_root else LP_ROOT
    ic = Path(ic_root) if ic_root else IC_ROOT
    research = Path(research_root) if research_root else RESEARCH_ROOT
    ff = Path(ff_root) if ff_root else FF_ROOT
    blocks = {"emotion": _load_emotion(day, root),
              "news_titles": _load_news_titles(day, root),
              "lhb": _load_lhb(day, root, em),
              "volume_series": _load_volume_series(day, root, vh_path=vh_path)}
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
    research_block = _load_research(day, research)
    if research_block is None:
        missing.append("research")
    else:
        blocks["research"] = research_block
    fund_flow = _load_fund_flow(day, ff)
    if fund_flow is None:
        missing.append("fund_flow")
    else:
        blocks["fund_flow"] = fund_flow
    si = Path(si_root) if si_root else SI_ROOT
    sector_intraday = _load_sector_intraday(day, si)
    if sector_intraday is None:
        missing.append("sector_intraday")
    else:
        blocks["sector_intraday"] = sector_intraday
    gm = Path(gm_root) if gm_root else GM_ROOT
    global_macro = _load_global_macro(day, gm)
    if global_macro is None:
        missing.append("global_macro")
    else:
        blocks["global_macro"] = global_macro
    for k, v in blocks.items():
        if v is not None:
            pack[k] = v
    # 复合区间双锚（规则35 数据基础）：从 pack index 块推导，收盘价口径
    anchors = _range_anchors(index)
    if anchors is not None:
        pack["range_anchors"] = anchors
    # 候选方向历史 T+5 超额命中率（提案 2026-09-05 数据缺口 3）：
    # 无已到期 scored 记录时不出块、不登记 missing
    track = _load_direction_track(day, pred_dir=pred_dir, db_path=db_path)
    if track is not None:
        pack["direction_track"] = track
    if target_day is not None:
        pack["catalysts_since_prev_day"] = _load_catalysts(
            day, target_day, research, root)
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
