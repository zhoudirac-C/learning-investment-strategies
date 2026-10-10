"""板块量价快照（2026-10-10 用户拍板：阶段判断补板块级量价数据腿）。

背景：跟踪引擎此前只消费研报/公告/期货行情，不看量价，导致"叙事还在加速、
股价已腰斩"时阶段判断失真（ai-pcb-ccl/mlcc-passive 2026-10-10 人工校准事件）。
用户明确口径：不用个股，用同花顺板块指数（板块联动/退潮本来就该看板块）。

数据源：config/stock_monitor/chain_board_map.yaml 映射 →
infra/data/board_klines/*.json 本地缓存（由 scripts/fetch_board_klines.py
每日 15:40 cron 更新；本模块只读缓存，不联网）。

两处消费：
1. analysis.build_tracking_messages —— 注入【板块量价快照】prompt 段
2. state.apply_chain_update —— 硬护栏：板块回撤超阈值且处启动/加速期，
   禁止 stage_change=forward（不走 LLM，宁可漏不可错）
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
MAP_PATH = ROOT / "config" / "stock_monitor" / "chain_board_map.yaml"
CACHE_DIR = ROOT / "infra" / "data" / "board_klines"

#: 硬护栏阈值：板块距120日高点回撤超过该幅度（%），且当前阶段处于
#: 启动/加速期时，禁止阶段前进（2026-10-10 D2 拍板 30%）
FORWARD_BLOCK_DRAWDOWN_PCT = -30.0
FORWARD_BLOCK_STAGES = ("阶段1-启动期", "阶段2-加速期")

_MAP_CACHE: dict | None = None


def _load_map() -> dict:
    global _MAP_CACHE
    if _MAP_CACHE is None:
        with open(MAP_PATH, encoding="utf-8") as f:
            _MAP_CACHE = yaml.safe_load(f).get("chains") or {}
    assert _MAP_CACHE is not None
    return _MAP_CACHE


def _cache_path(board_type: str, board: str) -> Path:
    safe = board.replace("/", "_").replace("(", "_").replace(")", "_")
    return CACHE_DIR / f"{board_type}_{safe}.json"


def board_metrics(chain_id: str) -> dict | None:
    """返回链映射板块的量价快照；无映射或无缓存返回 None。

    字段: board/board_type/proxy_strength/as_of/drawdown_from_120d_high_pct/
    change_20d_pct/volume_ratio_5_60/vs_ma60_pct
    """
    m = _load_map().get(chain_id)
    if not m:
        return None
    p = _cache_path(m["type"], m["board"])
    if not p.exists():
        return None
    bars = json.loads(p.read_text(encoding="utf-8"))
    if len(bars) < 25:
        return None
    closes = [b["close"] for b in bars]
    vols = [b.get("volume") or 0 for b in bars]
    last = closes[-1]
    hi = max(closes[-120:])
    ma60 = statistics.mean(closes[-60:])
    v5 = statistics.mean(vols[-5:])
    v60 = statistics.mean(vols[-60:]) or 1.0
    return {
        "board": m["board"],
        "board_type": m["type"],
        "proxy_strength": m.get("proxy_strength") or "exact",
        "proxy_note": m.get("note") or "",
        "as_of": bars[-1]["date"],
        "drawdown_from_120d_high_pct": round((last / hi - 1) * 100, 1),
        "change_20d_pct": round((last / closes[-21] - 1) * 100, 1),
        "volume_ratio_5_60": round(v5 / v60, 2),
        "vs_ma60_pct": round((last / ma60 - 1) * 100, 1),
    }


def format_board_context(chain_id: str) -> str:
    """prompt 注入文本；无数据返回空串（调用方拼段时跳过）。"""
    s = board_metrics(chain_id)
    if not s:
        return ""
    lines = [
        f"板块指数：{s['board']}（同花顺{'概念' if s['board_type'] == 'concept' else '行业'}，"
        f"数据截止 {s['as_of']}）",
        f"- 距120日高点回撤：{s['drawdown_from_120d_high_pct']}%",
        f"- 20日涨跌幅：{s['change_20d_pct']}%",
        f"- 量能比（5日均量/60日均量）：{s['volume_ratio_5_60']}",
        f"- 现价 vs 60日均线：{s['vs_ma60_pct']}%",
    ]
    if s["proxy_strength"] != "exact":
        lines.append(f"（注意：该板块是本链的弱代理——{s['proxy_note']}，权重放低）")
    return "\n".join(lines)


def forward_blocked(chain_id: str, current_stage: str) -> tuple[bool, str]:
    """硬护栏：板块深度回撤时禁止阶段前进。返回 (是否拦截, 原因)。"""
    if current_stage not in FORWARD_BLOCK_STAGES:
        return False, ""
    s = board_metrics(chain_id)
    if not s:
        return False, ""
    if s["drawdown_from_120d_high_pct"] <= FORWARD_BLOCK_DRAWDOWN_PCT:
        reason = (f"板块{s['board']}距高点回撤{s['drawdown_from_120d_high_pct']}%"
                  f"≤{FORWARD_BLOCK_DRAWDOWN_PCT}%，当前{current_stage}，禁止forward"
                  f"（量价护栏 2026-10-10）")
        return True, reason
    return False, ""
