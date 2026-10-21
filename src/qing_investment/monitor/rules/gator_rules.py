"""鳄鱼派确定性规则引擎（gator school rules）。

来源：sources/third_party/gator-method/03-规则体系/（50 章提炼库，2026-10-15 落盘）
设计文档：docs/design/dual-school-architecture.md

设计原则：
- 只实现「带明确数字阈值」的可计算规则（章目标记 `[可计算]`），
  语义类规则留在 reasoning-patterns（gator school）走检索路线。
- 纯函数 + 注入数据，方便单测与回测（qing-strategy-backtest）。
- 输出 GatorSignal 列表，不直接产生买卖指令（与项目 output 契约一致）。

已实现（P2b 初版）：
  1. 止跌 / 强反弹 5 信号（第一章）  → 满足数 + 激进/保守档位
  2. 短期情绪冰点（第一章）          → 三条件与
  3. 剪刀差（第八章）                → 沪深300 vs 中证2000 分歧分级
  4. 护盘三力度分级（第十二章）      → 大金融/宽基ETF/全ETF 判定
  5. 指数共振（第一章信号1）         → 已并入 5 信号
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SignalLevel(str, Enum):
    """信号判定结果。"""

    MET = "met"          # 满足
    NOT_MET = "not_met"  # 不满足
    UNKNOWN = "unknown"  # 数据缺失，无法判定


@dataclass
class GatorSignal:
    """单条鳄鱼派信号判定。"""

    rule_id: str
    name: str
    level: SignalLevel
    detail: str = ""
    source_chapter: str = ""


@dataclass
class GatorAssessment:
    """鳄鱼派综合判定结果。"""

    signals: list[GatorSignal] = field(default_factory=list)
    met_count: int = 0
    total_count: int = 0
    stance: str = ""          # 无 / 激进可出手 / 保守可出手
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"止跌信号 {self.met_count}/{self.total_count} 满足"
            + (f" → {self.stance}" if self.stance else "")
        )


# ── 阈值常量（集中管理，便于回测校准）────────────────────────────

# 第一章「止跌 / 强反弹的 5 个信号」
THRESHOLD_AGGRESSIVE_ENTRY = 3  # 激进选手 ≥3 个信号可出手
THRESHOLD_CONSERVATIVE_ENTRY = 4  # 保守选手 ≥4 个信号可出手

# 指差收敛：上证 vs 创业板 / 沪深300 vs 中证2000 差距
CONVERGENCE_MAX_GAP_PCT = 1.0  # 差距 ≤1% 视为收敛

# 情绪冰点（2026-09-24《跌多少才会止跌？》）
ICE_WEIWANG_DROP_PCT = -3.0     # 微盘股跌幅 ≤ -3%
ICE_LIMIT_DOWN_COUNT = 30       # 跌停家数 > 30
ICE_INDEX_DROP_PCT = -2.0       # 上证跌幅 < -2%

# 剪刀差（第八章）
SCISSOR_DIVERGENCE_MIN = 0.5    # >0.5% 存在分歧
SCISSOR_DIVERGENCE_HEAVY = 1.0  # >1% 分歧较重
SCISSOR_DIVERGENCE_SEVERE = 2.0 # >2% 分歧严重

# 火车头板块（第一章信号 2）
LOCOMOTIVE_SECTOR_GAIN_MIN = 0.5   # 领涨板块涨幅 ≥0.5%
LOCOMOTIVE_RED_RATIO_MIN = 0.60    # 板块内上涨家数占比 ≥60%


# ── 第一章：止跌 5 信号 ────────────────────────────────────────

def _signal_convergence(market: dict) -> GatorSignal:
    """信号 1：指数共振（差距收敛）。"""
    need = ("sh_pct", "cyb_pct", "hs300_pct", "zz2000_pct")
    if any(market.get(k) is None for k in need):
        return GatorSignal(
            "gator-01-convergence", "指数共振（差距收敛）", SignalLevel.UNKNOWN,
            "缺少指数涨跌幅数据", source_chapter="第一章",
        )
    gap1 = abs(market["sh_pct"] - market["cyb_pct"])
    gap2 = abs(market["hs300_pct"] - market["zz2000_pct"])
    ok = gap1 <= CONVERGENCE_MAX_GAP_PCT and gap2 <= CONVERGENCE_MAX_GAP_PCT
    return GatorSignal(
        "gator-01-convergence", "指数共振（差距收敛）",
        SignalLevel.MET if ok else SignalLevel.NOT_MET,
        f"上证vs创业板差 {gap1:.2f}%，沪深300vs中证2000差 {gap2:.2f}%"
        f"（阈值 ≤{CONVERGENCE_MAX_GAP_PCT}%）",
        source_chapter="第一章",
    )


def _signal_locomotive(sector: dict | None) -> GatorSignal:
    """信号 2：出现火车头板块（有带动作用）。"""
    if not sector:
        return GatorSignal(
            "gator-01-locomotive", "火车头板块（有带动）", SignalLevel.UNKNOWN,
            "缺少板块强度数据", source_chapter="第一章",
        )
    gain = sector.get("top_sector_pct")
    red_ratio = sector.get("top_sector_red_ratio")
    if gain is None or red_ratio is None:
        return GatorSignal(
            "gator-01-locomotive", "火车头板块（有带动）", SignalLevel.UNKNOWN,
            "缺少领涨板块数据", source_chapter="第一章",
        )
    ok = gain >= LOCOMOTIVE_SECTOR_GAIN_MIN and red_ratio >= LOCOMOTIVE_RED_RATIO_MIN
    return GatorSignal(
        "gator-01-locomotive", "火车头板块（有带动）",
        SignalLevel.MET if ok else SignalLevel.NOT_MET,
        f"领涨板块 {sector.get('top_sector_name','?')} 涨 {gain:.2f}%，"
        f"板块内上涨占比 {red_ratio:.0%}（阈值 ≥{LOCOMOTIVE_SECTOR_GAIN_MIN}% / ≥{LOCOMOTIVE_RED_RATIO_MIN:.0%}）",
        source_chapter="第一章",
    )


def _signal_broker_limit_up(broker: dict | None) -> GatorSignal:
    """信号 3：气氛组证券走强（券商有无涨停板）。"""
    if not broker:
        return GatorSignal(
            "gator-01-broker", "券商涨停（气氛组）", SignalLevel.UNKNOWN,
            "缺少券商板块数据", source_chapter="第一章",
        )
    n = broker.get("limit_up_count")
    if n is None:
        return GatorSignal(
            "gator-01-broker", "券商涨停（气氛组）", SignalLevel.UNKNOWN,
            "缺少券商涨停家数", source_chapter="第一章",
        )
    ok = int(n) > 0
    return GatorSignal(
        "gator-01-broker", "券商涨停（气氛组）",
        SignalLevel.MET if ok else SignalLevel.NOT_MET,
        f"券商涨停 {n} 家（判定：{'合格' if ok else '不及格'}）",
        source_chapter="第一章",
    )


def _signal_incremental_fund(fund: dict | None) -> GatorSignal:
    """信号 4：短线增量资金进场。"""
    if not fund:
        return GatorSignal(
            "gator-01-incremental", "短线增量资金进场", SignalLevel.UNKNOWN,
            "缺少资金面数据", source_chapter="第一章",
        )
    vol_ratio = fund.get("volume_ratio")
    north = fund.get("north_net_inflow")
    if vol_ratio is None and north is None:
        return GatorSignal(
            "gator-01-incremental", "短线增量资金进场", SignalLevel.UNKNOWN,
            "缺少量比/北向数据", source_chapter="第一章",
        )
    parts = []
    ok = False
    if vol_ratio is not None:
        parts.append(f"量比 {vol_ratio:.2f}")
        if vol_ratio > 1.2:
            ok = True
    if north is not None:
        parts.append(f"北向净流入 {north:.1f} 亿")
        if north > 0:
            ok = True
    return GatorSignal(
        "gator-01-incremental", "短线增量资金进场",
        SignalLevel.MET if ok else SignalLevel.NOT_MET,
        "；".join(parts), source_chapter="第一章",
    )


def _signal_basis(basis: dict | None) -> GatorSignal:
    """信号 5：股指基差缩小（上涨途中缩小才算）。"""
    if not basis:
        return GatorSignal(
            "gator-01-basis", "股指基差缩小", SignalLevel.UNKNOWN,
            "缺少基差数据", source_chapter="第一章",
        )
    delta = basis.get("basis_delta")
    index_up = basis.get("index_up")
    if delta is None or index_up is None:
        return GatorSignal(
            "gator-01-basis", "股指基差缩小", SignalLevel.UNKNOWN,
            "缺少基差变化/指数方向", source_chapter="第一章",
        )
    # 基差缩小 = 贴水收窄（delta < 0 表示期货贴水，delta 上行收窄），且上涨途中
    # delta 是期货-现货的差值，负值=贴水，正值=升水
    # 基差缩小 = 贴水收窄 = delta 从更负值回升（但我们只有单点数据，无法判断趋势）
    # 简化：期货贴水（delta < 0）且指数上涨，视为「基差有收窄空间」
    ok = delta < 0 and bool(index_up)
    detail = (
        f"基差 {delta:+.2f}（期货{'贴水' if delta < 0 else '升水'}），指数{'上涨' if index_up else '下跌'}途中"
        + ("（下跌途中缩小不算）" if not index_up and delta < 0 else "")
    )
    return GatorSignal(
        "gator-01-basis", "股指基差缩小",
        SignalLevel.MET if ok else SignalLevel.NOT_MET,
        detail, source_chapter="第一章",
    )


def assess_stop_falling(
    market: dict | None = None,
    sector: dict | None = None,
    broker: dict | None = None,
    fund: dict | None = None,
    basis: dict | None = None,
) -> GatorAssessment:
    """止跌 / 强反弹 5 信号综合判定（第一章）。

    Args:
        market: {"sh_pct","cyb_pct","hs300_pct","zz2000_pct"}
        sector: {"top_sector_name","top_sector_pct","top_sector_red_ratio"}
        broker: {"limit_up_count"}
        fund:   {"volume_ratio","north_net_inflow"}
        basis:  {"basis_delta","index_up"}

    Returns:
        GatorAssessment（met_count / stance：激进 ≥3，保守 ≥4）
    """
    signals = [
        _signal_convergence(market or {}),
        _signal_locomotive(sector),
        _signal_broker_limit_up(broker),
        _signal_incremental_fund(fund),
        _signal_basis(basis),
    ]
    met = sum(1 for s in signals if s.level == SignalLevel.MET)
    unknown = sum(1 for s in signals if s.level == SignalLevel.UNKNOWN)
    total = len(signals)

    if met >= THRESHOLD_CONSERVATIVE_ENTRY:
        stance = "保守选手可出手"
    elif met >= THRESHOLD_AGGRESSIVE_ENTRY:
        stance = "激进选手可出手"
    else:
        stance = "继续观望"

    notes = []
    if unknown:
        notes.append(f"{unknown} 项因数据缺失未判定（不计入满足数）")
    notes.append(
        f"判定口径：激进 ≥{THRESHOLD_AGGRESSIVE_ENTRY}，保守 ≥{THRESHOLD_CONSERVATIVE_ENTRY}"
    )

    return GatorAssessment(
        signals=signals, met_count=met, total_count=total, stance=stance, notes=notes
    )


# ── 第一章：短期情绪冰点 ──────────────────────────────────────

def assess_emotion_ice(
    weiwang_drop_pct: float | None,
    limit_down_count: int | None,
    index_drop_pct: float | None,
) -> GatorSignal:
    """短期情绪冰点（2026-09-24《跌多少才会止跌？》）。

    IF 微盘股跌 ≥3% AND 跌停家数 >30 AND 上证跌 >2% THEN 视为短期情绪冰点
    """
    if weiwang_drop_pct is None or limit_down_count is None or index_drop_pct is None:
        return GatorSignal(
            "gator-01-ice", "短期情绪冰点", SignalLevel.UNKNOWN,
            "缺少微盘/跌停/指数数据", source_chapter="第一章",
        )
    ok = (
        weiwang_drop_pct <= ICE_WEIWANG_DROP_PCT
        and limit_down_count > ICE_LIMIT_DOWN_COUNT
        and index_drop_pct < ICE_INDEX_DROP_PCT
    )
    return GatorSignal(
        "gator-01-ice", "短期情绪冰点",
        SignalLevel.MET if ok else SignalLevel.NOT_MET,
        f"微盘 {weiwang_drop_pct:+.2f}%（≤{ICE_WEIWANG_DROP_PCT}%）、"
        f"跌停 {limit_down_count} 家（>{ICE_LIMIT_DOWN_COUNT}）、"
        f"上证 {index_drop_pct:+.2f}%（<{ICE_INDEX_DROP_PCT}%）",
        source_chapter="第一章",
    )


# ── 第八章：剪刀差 ────────────────────────────────────────────

def assess_scissors(
    hs300_pct: float | None, zz2000_pct: float | None
) -> GatorSignal:
    """剪刀差 = 沪深300 与 中证2000 涨跌幅之差（取正数）。

    >0.5% 存在分歧，>1% 分歧较重，>2% 分歧严重。分歧明显则涨跌不可持续。
    """
    if hs300_pct is None or zz2000_pct is None:
        return GatorSignal(
            "gator-08-scissors", "剪刀差（机构 vs 游资分歧）", SignalLevel.UNKNOWN,
            "缺少沪深300/中证2000 数据", source_chapter="第八章",
        )
    diff = abs(hs300_pct - zz2000_pct)
    if diff > SCISSOR_DIVERGENCE_SEVERE:
        level, label = SignalLevel.MET, "分歧严重"
    elif diff > SCISSOR_DIVERGENCE_HEAVY:
        level, label = SignalLevel.MET, "分歧较重"
    elif diff > SCISSOR_DIVERGENCE_MIN:
        level, label = SignalLevel.MET, "存在分歧"
    else:
        level, label = SignalLevel.NOT_MET, "无明显分歧"
    return GatorSignal(
        "gator-08-scissors", "剪刀差（机构 vs 游资分歧）", level,
        f"沪深300 {hs300_pct:+.2f}% vs 中证2000 {zz2000_pct:+.2f}%，"
        f"差 {diff:.2f}% → {label}",
        source_chapter="第八章",
    )


# ── 第十二章：护盘三力度 ──────────────────────────────────────

class HedgeLevel(str, Enum):
    NONE = "无护盘"
    SMALL = "小维护"
    MEDIUM = "中护盘"
    LARGE = "大救市"


def assess_hedge(
    big_finance_up: bool | None = None,
    broad_etf_up: bool | None = None,
    all_etf_up: bool | None = None,
    policy_meeting: bool | None = None,
) -> tuple[GatorSignal, HedgeLevel]:
    """护盘力度分级（第十二章）。

    小维护（大金融、巨型中字头）/ 中护盘（上证50、300、500 ETF）/
    大救市（全 ETF 轮番上阵 + 开会出利好）。出手顺序先权重后小票。

    注意（第十二章配套）：**上涨由护盘驱动 ≠ 止跌**。
    """
    if big_finance_up is None and broad_etf_up is None and all_etf_up is None:
        return (
            GatorSignal(
                "gator-12-hedge", "护盘力度分级", SignalLevel.UNKNOWN,
                "缺少护盘迹象数据", source_chapter="第十二章",
            ),
            HedgeLevel.NONE,
        )

    if all_etf_up and policy_meeting:
        level, hl = SignalLevel.MET, HedgeLevel.LARGE
        detail = "全 ETF 轮番上涨 + 政策会议 → 大救市"
    elif all_etf_up:
        level, hl = SignalLevel.MET, HedgeLevel.LARGE
        detail = "全 ETF 轮番上涨 → 大救市"
    elif broad_etf_up:
        level, hl = SignalLevel.MET, HedgeLevel.MEDIUM
        detail = "上证50/300/500 ETF 走强 → 中护盘"
    elif big_finance_up:
        level, hl = SignalLevel.MET, HedgeLevel.SMALL
        detail = "大金融/巨型中字头走强 → 小维护"
    else:
        level, hl = SignalLevel.NOT_MET, HedgeLevel.NONE
        detail = "未见明显护盘迹象"

    detail += "；提醒：上涨由护盘驱动 ≠ 止跌（第十二章）"
    return (
        GatorSignal("gator-12-hedge", "护盘力度分级", level, detail, "第十二章"),
        hl,
    )
