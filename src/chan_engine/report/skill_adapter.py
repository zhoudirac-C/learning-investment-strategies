"""M7-5 Skill 接入层：MultiTimeframeChart → skill 输出惯例翻译（设计 §8.2/§8.3）。

输出七项 + 级别三问自检：
- 防守线（日线最近一买低点 / 次级别最近买入点低点，级别标签并列）
- 反转确认位（日线前高=最近顶分型高）
- 仓位性质（**仅日线**可定：trend_div 一买→反转仓，consolidation_div→反弹仓，
  无日线一买→观察；60m/30m 信号永不改变日线仓位性质——级别错配硬防线）
- 失效条件（破防守线→买点失败；破日线前低→反弹终结）
- 入场点（当前日线笔内的次级别买卖点，价位=买卖点 bar 收盘价，与 spike
  "价1.864"口径一致）
- 背驰类型（最近背驰信号的 backchi_type 强制标注，防盘整背驰误报反转）
- 数据基准日 asof + 分钟窗口能力边界声明（设计 §4.2 写进报告头）
"""
from __future__ import annotations

from chan_engine.multi_tf.model import MultiTimeframeChart
from chan_engine.spec.model import Bar, BSPoint, Direction, NormalizedChart

BSP_NAMES = {(1, Direction.UP): "一买", (1, Direction.DOWN): "一卖",
             (2, Direction.UP): "二买", (2, Direction.DOWN): "二卖",
             (3, Direction.UP): "三买", (3, Direction.DOWN): "三卖"}

WINDOW_NOTE = ("分钟数据为 260 根滑动窗口快照（60m≈2.6 个月 / 30m≈1.4 个月），"
               "仅支撑近期次级别确认，不做历史回填；日线管级别定性，分钟管近期时机"
               "（chanlun-m7-multitimeframe-skill.md §4.2 能力边界）")


def bsp_name(b: BSPoint) -> str:
    """买卖点中文名（一买/二卖/三买…）。"""
    return BSP_NAMES[(b.bstype, b.dir)]


def _latest(items, pred):
    hit = [x for x in items if pred(x)]
    return hit[-1] if hit else None


def _premise_note(backchi_type: str) -> str:
    """背驰前提结论（G3 显式化，L15/L24 '没有趋势没有背驰'）。

    trend_div → 当前中枢之前存在同级别同向不重叠中枢（趋势成立，前提满足）；
    consolidation_div → 无同级别前中枢（仅中枢内力度减弱，趋势前提不满足，
    报告必须标注防误报为反转信号）；空 → 该信号未走 G3 校验。
    """
    return {
        "trend_div": "前提满足：存在同级别同向不重叠前中枢（趋势成立）",
        "consolidation_div": "前提不满足：无同级别前中枢（仅盘整背驰，趋势前提缺失）",
        "未标注": "前提未校验（无 G3 标注）",
    }.get(backchi_type, f"前提未校验（backchi_type={backchi_type}）")


def build_report(
    mtc: MultiTimeframeChart,
    code: str,
    daily_bars: list[Bar],
    daily_dates: list[str],
    sub_bars: dict[str, list[Bar]],
    sub_stamps: dict[str, list[str]],
) -> dict:
    """多周期结构 → skill 输出惯例报告（结构化 dict，控制台渲染在 CLI 层）。"""
    daily = mtc.daily
    report: dict = {"code": code, "window_note": WINDOW_NOTE}

    # ── 数据基准日（skill 纪律：报告必须标基准日） ──
    report["asof"] = {"daily": daily_dates[-1] if daily_dates else None}
    for tf, stamps in sorted(sub_stamps.items()):
        report["asof"][tf] = stamps[-1] if stamps else None

    # ── 防守线：日线最近一买低点 + 各次级别最近买入点低点（级别标签并列） ──
    defense: list[dict] = []
    d1 = _latest(daily.bsp, lambda b: b.bstype == 1 and b.dir is Direction.UP)
    if d1 is not None:
        defense.append({"price": float(daily_bars[d1.idx].l), "level": "日线",
                        "ref": f"一买低点@{daily_dates[d1.idx]}"})
    for tf in sorted(sub_bars):
        chart = mtc.sub.get(tf)
        if chart is None:
            continue
        b = _latest(chart.bsp, lambda x: x.dir is Direction.UP)
        if b is not None:
            defense.append({"price": float(sub_bars[tf][b.idx].l), "level": tf,
                            "ref": f"{bsp_name(b)}低点@{sub_stamps[tf][b.idx]}"})
    report["defense_lines"] = defense

    # ── 反转确认位：日线前高（最近顶分型高） ──
    top = _latest(daily.fx, lambda f: f.type is Direction.UP)
    report["reversal_confirm"] = (
        {"price": float(daily_bars[top.idx].h), "level": "日线",
         "ref": f"前高@{daily_dates[top.idx]}"} if top is not None else None)

    # ── 仓位性质：仅日线（级别错配硬防线） ──
    trend = daily.trend
    if d1 is not None:
        label = "反转仓" if d1.backchi_type == "trend_div" else "反弹仓"
        reason = f"日线一买@{daily_dates[d1.idx]}（{d1.backchi_type}）"
    else:
        label = "观察"
        reason = "日线无一买"
    if trend is not None:
        reason += f"；走势类型={trend.walk_type}"
    report["position_nature"] = {"label": label, "basis": "日线", "reason": reason}

    # ── 入场点：当前日线笔内的次级别买点（区间套精确定位） ──
    entry_points: list[dict] = []
    since = daily_dates[daily.bi[-1].start_idx] if daily.bi else ""
    for tf in sorted(sub_bars):
        chart = mtc.sub.get(tf)
        if chart is None:
            continue
        for b in chart.bsp:
            if b.dir is not Direction.UP:
                continue
            if sub_stamps[tf][b.idx] < since:
                continue  # 只取当前日线笔内的买点
            entry_points.append({
                "price": float(sub_bars[tf][b.idx].c), "dt": sub_stamps[tf][b.idx],
                "type": bsp_name(b), "level": tf, "level_n": b.level, "sure": b.sure,
            })
    report["entry_points"] = entry_points

    # ── 背驰类型：各级别最近背驰信号逐级别标注（级别归属纪律，不跨级取唯一） ──
    # 前提字段（M7-3 G3 结论显式化）：backchi_type=trend_div → 存在同级别同向
    # 不重叠前中枢（趋势前提满足）；consolidation_div → 仅盘整背驰（趋势前提
    # 不满足，防误报为反转）。报告必须带前提标注，强制检查"没有趋势没有背驰"。
    backchi: dict = {}
    d_div = _latest(daily.bsp, lambda b: b.bstype == 1)
    if d_div is not None:
        backchi["日线"] = {
            "backchi_type": d_div.backchi_type or "未标注",
            "ref": f"{bsp_name(d_div)}@{daily_dates[d_div.idx]}",
            "premise": _premise_note(d_div.backchi_type),
        }
    for tf in sorted(sub_bars):
        chart = mtc.sub.get(tf)
        if chart is None:
            continue
        b = _latest(chart.bsp, lambda x: x.bstype == 1)
        if b is not None:
            backchi[tf] = {
                "backchi_type": b.backchi_type or "未标注",
                "ref": f"{bsp_name(b)}@{sub_stamps[tf][b.idx]}",
                "premise": _premise_note(b.backchi_type),
            }
    report["backchi"] = backchi

    # ── 失效条件 ──
    invalidation = [
        f"破 {d['price']}（{d['level']} 防守线，{d['ref']}）→ 买点失败，停止买入并止损"
        for d in defense
    ]
    bottom = _latest(daily.fx, lambda f: f.type is Direction.DOWN)
    if bottom is not None:
        invalidation.append(
            f"破 {float(daily_bars[bottom.idx].l)}（日线前低@{daily_dates[bottom.idx]}）"
            f"→ 反弹彻底终结，退出等新结构")
    report["invalidation"] = invalidation

    # ── 级别归属三问自检（信号/防守/目标各属哪张图，必须同图可答） ──
    report["level_check"] = {
        "signal": "60m（主判断）/30m（辅助精细入场）",
        "defense": defense[-1]["level"] if defense else None,
        "target": "日线",
        "position_nature": "日线",
    }

    # ── 小转大候选提示（课 43 + L44 两步走，G10 必要条件检查） ──
    report["small_to_large_alerts"] = [
        {"bi_ref": c.bi_ref, "tf": c.tf, "premise": c.s2l_premise}
        for c in mtc.confirmations if c.small_to_large
    ]

    # ── G9 分类状态→预案（逐级别：日线 + 各次级别） ──
    state_plan: dict = {}
    if daily_bars:
        state_plan["日线"] = classify_state_plan(daily, float(daily_bars[-1].c), "日线")
    for tf in sorted(sub_bars):
        chart = mtc.sub.get(tf)
        if chart is not None and sub_bars[tf]:
            state_plan[tf] = classify_state_plan(chart, float(sub_bars[tf][-1].c), tf)
    report["state_plan"] = state_plan
    return report


# ── G8/G9（设计 §8.3，L38/39 + P3 既定演进） ──

def _zs_position(zd: float, zg: float, close: float) -> str:
    if zd <= close <= zg:
        return "中枢内"
    return "中枢上方" if close > zg else "中枢下方"


def build_decomp(chart: NormalizedChart, level: str, last_close: float) -> dict:
    """G8 同级别分解视角（--decomp）：当前中枢 + 上一段/当前段 + 位置 + 段序列重排。

    机械化"只做上涨+盘整段、回避下跌段"视角（L38/39）：当前段 dir/sure
    直接可操作（下跌段回避，上涨/盘整段参与）。
    ``segment_sequence``（G8 补全，2026-08-29）：全段序列逐段重排 +
    参与/回避标签——上涨段=参与、下跌段=回避、未确认段加"(待确认)"后缀；
    这就是同级别分解的操作化输出（把走势按段重排，机械化只做可参与段）。
    """
    z = chart.zs[-1] if chart.zs else None
    segs = chart.seg

    def _action(s_dir: Direction, sure: bool) -> str:
        base = "参与" if s_dir is Direction.UP else "回避"
        return base if sure else f"{base}(待确认)"

    return {
        "level": level,
        "current_zs": {"zd": z.zd, "zg": z.zg} if z is not None else None,
        "prev_segment": ({"dir": segs[-2].dir.value, "sure": segs[-2].sure}
                         if len(segs) >= 2 else None),
        "current_segment": ({"dir": segs[-1].dir.value, "sure": segs[-1].sure}
                            if segs else None),
        "position": _zs_position(z.zd, z.zg, last_close) if z is not None else "无中枢",
        "segment_sequence": [
            {"dir": s.dir.value, "sure": s.sure, "action": _action(s.dir, s.sure)}
            for s in segs
        ],
    }


def classify_state_plan(chart: NormalizedChart, last_close: float, level: str) -> dict:
    """G9 分类状态→预案（课 17"理论不预测，只提供分类框架" + L18 定理三）。

    状态机：中枢位置（内/上/下）× 破坏判定（三买/三卖须落在中枢结束之后）：
    - 破坏确认：三买/三卖已出 → 持有到新高 / 退出回避；
    - 新生候选：中枢外未确认 → 等回试（上）/ 不抄底等一买（下）；
    - 延伸：中枢内 → 中枢内无该级别买卖点，等方向选择。
    """
    if not chart.zs:
        return {"level": level, "position": "无中枢", "state": "无结构",
                "plan": "等结构（无中枢无从定性）"}
    z = chart.zs[-1]
    position = _zs_position(z.zd, z.zg, last_close)
    # L18 定理三：破坏确认 = 中枢结束之后出现三类买卖点
    broken_up = any(b.bstype == 3 and b.dir is Direction.UP and b.idx >= z.end_idx
                    for b in chart.bsp)
    broken_down = any(b.bstype == 3 and b.dir is Direction.DOWN and b.idx >= z.end_idx
                      for b in chart.bsp)
    if position == "中枢上方" and broken_up:
        state, plan = "破坏确认", (
            f"三买成立（{level}）：持有到新高；回抽跌回中枢内（破 {z.zg}）"
            "→ 破坏不成立，退回中枢内处理")
    elif position == "中枢下方" and broken_down:
        state, plan = "破坏确认", (
            f"三卖成立（{level}）：回避/退出；反弹回中枢内（上破 {z.zd}）"
            "→ 破坏不成立，重新评估")
    elif position == "中枢上方":
        state, plan = "新生候选", (
            f"突破 {z.zg} 待回试确认：回试不破 {z.zg} → 三买；"
            "跌回中枢内 → 延伸继续，不追")
    elif position == "中枢下方":
        state, plan = "新生候选", (
            f"跌破 {z.zd} 向下离开：不抄底，等次级别一买/底背驰确认；"
            f"反弹回 {z.zd} 上方 → 延伸继续")
    else:
        state, plan = "延伸", (
            f"中枢内（[{z.zd}, {z.zg}]）：中枢内无该级别买卖点，"
            "只做次级别波动，等方向选择")
    return {"level": level, "position": position, "zs": {"zd": z.zd, "zg": z.zg},
            "state": state, "plan": plan}
