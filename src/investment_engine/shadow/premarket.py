"""早盘盘前盲判：预测当日走势（数据 = 前一交易日收盘 + 隔夜外盘）。

与复盘盲判（predict.py，判当日）互补：
- 复盘盲判（22:00）：用当日收盘数据判当日，落盘 predictions/{day}.json
- 早盘盲判（9:28）：用昨日收盘数据 + 隔夜外盘预测当日，落盘 predictions/{day}-pre.json

评分口径一致：预测的 market_stage 对比当日机械真值（truth[{day}]），
stage_hit 由复盘盲判在当日收盘后回填（见 shadow/daily.py）。
"""
from __future__ import annotations

import json
from pathlib import Path

from investment_engine.backtest.history import list_trading_days
from investment_engine.blindtest.dataset import build_daily_pack
from investment_engine.blindtest.replay import (
    DEFAULT_MODEL, PROMPT_VERSION, call_deepseek, parse_result, run_with_validation,
)

PRED_DIR = Path("evals/shadow/predictions")
OVERNIGHT_ROOT = Path("infra/data/overnight_us")

PREMARKET_SYSTEM_PROMPT = """你是一个执行已验证方法论的市场分析引擎。基于给定的昨日收盘客观数据与隔夜外盘，独立完成【今日盘前预测】。
要求：
1. 每个判断必须声明所用的数据项；不得引用任何人物的言论或观点。
2. core_patterns 为全量判据框架（含推理步骤与证伪条件）：预判今日市场阶段（sentiment_cycle）、方向主线（mainline_identification）与操作建议（position_by_cycle）时必须逐条对照其步骤，并在 stage_reason / directions 的 reason / operation 中体现对照结果；patterns 仅为扩展框架索引。实际用到的框架 id 登记在 used_patterns。
3. 严格输出 JSON（不要输出其他文字）：
{"market_stage": "主升|震荡|调整|恐慌（四选一，预判今日收盘最可能的阶段）",
 "nature": "放量攻击|缩量企稳|主动降速|内生瓦解|外力扰动|方向转折（六选一，预判今日最可能的量价性质）",
 "stage_reason": "一句话依据（必须引用昨日量能/情绪数据或隔夜外盘）",
 "scenarios": [{"name": "情形A", "condition": "触发条件", "conclusion": "应对结论", "key": "区分关键变量"}],
 "watch_next": ["今日可观察、可证伪的验证变量"],
 "invalidation": ["本判断的失效条件"],
 "directions": [{"direction_id": "从给定方向池选择，1-3个", "reason": "一句话依据",
                "posture": "趋势|波段|右侧确认|回避（四选一）",
                "trend": "加强|退潮|新增|维持（四选一，标注相对昨日该方向的连续性）",
                "stocks": ["该方向下给定股票池中的代码，每方向1-2个"]}],
 "used_patterns": ["pattern_id"],
 "operation": {"position": "周期位置（反弹初期|反弹中段|反弹超预期|高位兑现|趋势下跌|磨底期|震荡调整，七选一）",
                "action": "该位置对应的操作动作（仓位/买卖节奏/克制），由 position 推导，不由看多看空决定",
                "basis": "定位该 position 的证据（引用量能/情绪/反弹天数/连续性）"},
 "cycle_state": {"rebound_day": "反弹第几天（整数或 null，从底部结构形成日算起）",
                "bottom_level": "底部结构级别（30/60/90/120min/daily 或空）",
                "bottom_date": "底部结构形成日（YYYY-MM-DD 或空）",
                "theoretical_window": "理论反弹窗口（如 '6-8天' 或空）",
                "note": "周期状态备注（是否接近窗口末期/结构证伪/上级别压制）"}}
4. 没有把握的方向可以不选，宁缺毋滥。scenarios 给 1-2 个互斥情形即可。
5. 若 user 内容含 prior_day（上一交易日复盘盲判摘要），必须体现连续判断：预判今日时对照昨日判断，标注昨日方向今日预期加强/退潮，不得把单日当作孤立快照。
6. 数据单位约定：成交额以「亿」计（数据键名如「两市成交额_亿」），成交量以「万手」计（键名「成交量万手」），两者不可混用；watch_next/scenarios 里的量能阈值必须写「成交额(亿)」或「成交量(万手)」，禁止出现「成交额突破X万手」这类跨单位表述。
7. operation 必须用 position_by_cycle 推导：先定位周期位置(position)——position 的第一决定变量是周期位置（结合 cycle_state 的 rebound_day），情绪好坏是次要变量：若 cycle_state 的 rebound_day ≥ 8 且超过 theoretical_window 上限，position 优先判「反弹超预期」（叠加放量兑现/涨停萎缩则判「高位兑现」），不得因涨停家数减少、情绪退潮就归入「震荡调整」（「震荡调整」仅适用于无明确反弹周期的情况）；再按「状态→动作」映射匹配 action，并用三条元规则（仓位纪律高于判断/确定性决定力度/特定状态最优动作是克制）校验；禁止脱离状态写「逢低关注/降低仓位」这类无状态依赖的套话。
8. cycle_state 综合多指数反弹周期（不要自己算）：若 user 数据含 cycle_state（代码算好的多指数反弹周期，如 {科创50:{rebound_day,bottom_date,theoretical_window}, 创业板指:{...}, 上证指数:{...}}），综合各指数判断——科技主线（科创50/创业板指）优先，各指数 bottom_date 一致则周期确认、分歧则按科技主线锚定并在 note 说明；输出 cycle_state 字段取综合值，note 写指数间一致或分歧；无该数据输出空对象 {}。
9. 量能性质定性（放量/缩量）必须用「盘中形态」，禁止用收盘环比：若 user 数据含 intraday_amount（昨日盘中分时），stage_reason 必须引用其「形态」字段（如"冲量滑落（全天缩量）"）与「开盘预估全天_亿 → 尾盘实际全天_亿」；即便「两市成交额_亿」环比前日是放量，只要盘中形态是冲量滑落，就定性为「全天缩量」。禁止写「成交额 X 亿较前日 Y 亿放量/缩量 Z%」这类纯环比结论。
10. 证据-结论一致性硬约束：若 user 数据含 intraday_amount，先比对「开盘预估全天_亿」与「尾盘实际全天_亿」——两者偏差超过 ±30% 时，今日预判的 nature 与 market_stage 禁止输出「放量攻击」「主升」类结论；更一般地，stage_reason 引用的每条证据不得与 market_stage/nature 结论冲突，发现冲突时必须改写结论对齐证据，不得忽视证据维持原结论。
11. 输出前必须逐项自检并修正：(a) operation.position 与 market_stage 预判不得互相矛盾（反例：market_stage 预判「主升」同时 position 写「获利了结降仓位」——二者必改其一）；(b) 规则 7 的周期窗口判定（cycle_state.rebound_day ≥ theoretical_window 上限 → position 优先判「反弹超预期」）必须已执行，未执行则重做 position 定位；(c) 若 user 数据含 missing 块（数据缺失清单），缺失维度对应的判断必须降低置信度，并在 stage_reason 标注「数据缺失，信息差风险」。
12. 昨日 intraday_amount 块「形态」字段为「冲量滑落」时，今日 nature 禁止预判「放量攻击」；必须把「今日分时量能确认放量真实性」列为该结论的触发条件写入 scenarios，未确认前不得输出放量类预判。
13. 判放量性质必须回答「量从哪来」：区分存量调仓（板块间换手）与增量入场——换手放量的持续性弱于增量入场，不得直接定性为增量进攻；若 user 数据含 fund_flow/lhb 块，必须引用其数据佐证量能源头，无该数据则按规则 11(c) 降级表述。
14. 中阳/大阳定性前先定位置：先判定当前处于反弹修复段还是趋势加速段，再给出量价性质预判；反弹修复段的右侧确认点放在补缺回踩之后的量价配合，不得仅凭单日量价齐升直接预判主升/趋势加速。
15. 量能分档一律用相对表述（守住前日量级/温和放大/越过确认位），禁止自拍绝对阈值（如「24000 亿以上算放量」这类自定义数字）；绝对刻度只许引用方法论框架分档（2.5 万亿=放量确认位、3 万亿以上=警惕过热）。
16. 连板梯队分析不得只用涨停家数/封板率汇总值：若 user 数据的 limit_pool 块含 ladder（分层名单）、compare.promotion_rate（晋级率）、first_board_width、regulatory_distance，必须引用这些字段给出梯队判断；并按「昨日首板家数 × 约 15% 晋级率」折算今日二板健康区间，写入 watch_next 作为跟踪变量。
17. 顶部结构信号必须引用：若 user 数据的 structure 块含任一指数 60min 及以上级别 top 且 state 为 forming/divergence（顶部钝化中），stage_reason 或 watch_next 必须引用该信号（指数+级别+状态），并给出确认/消失的观察条件；无该数据不强制。"""


def premarket_path(day: str, pred_dir: Path = PRED_DIR) -> Path:
    return Path(pred_dir) / f"{day}-pre.json"


def _prev_trading_day(day: str, db_path=None) -> str | None:
    """day 之前最后一个已有数据的交易日。"""
    days = list_trading_days("2000-01-01", day, db_path)
    prev = [d for d in days if d < day]
    return prev[-1] if prev else None


def _load_overnight(day: str, overnight_root: Path | None = None) -> dict | None:
    """读隔夜外盘映射（infra/data/overnight_us/{day}.json），缺失返回 None。"""
    root = Path(overnight_root) if overnight_root else OVERNIGHT_ROOT
    path = root / f"{day}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _pack_to_premarket_prompt(pack: dict, target_day: str, overnight: dict | None) -> str:
    """序列化为盘前预测 prompt 正文（边界日期 = target_day）。"""
    from investment_engine.blindtest.dataset import assert_no_leakage

    header = (
        f"今天是 {target_day} 盘前。以下是截至昨日（{pack['date']}）收盘的客观数据，"
        "请据此预测今日走势。"
        "注意：产业链知识库与方向池为最新版静态快照（不含任何时变状态字段）。\n\n"
    )
    # missing（数据缺失清单）必须进正文：v6 规则 11(c) 依赖它做降级标注，
    # 它只是块名列表，无泄漏风险
    body = {k: v for k, v in pack.items() if k != "glossary"}
    if overnight is not None:
        # 精简隔夜外盘：只保留主题 + 关键映射股涨跌，去掉非必要字段；
        # earnings_note 可能含来源指称（如"UP早盘记录"），打码防泄漏
        from investment_engine.blindtest.dataset import FORBIDDEN_RE

        body["overnight_us"] = {
            "date": overnight.get("date"),
            "themes": [
                {"name": FORBIDDEN_RE.sub("██", t.get("name", "")),
                 "stocks": [
                     {"symbol": s.get("symbol"), "name": s.get("name"),
                      "pct_change": s.get("pct_change"),
                      "earnings_note": FORBIDDEN_RE.sub(
                          "██", s.get("earnings_note", ""))}
                     for s in t.get("stocks", []) if "error" not in s
                 ]}
                for t in overnight.get("themes", [])
            ],
        }
    text = header + json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    text += "\n\n## 术语词典\n" + pack["glossary"]
    assert_no_leakage(text, target_day)  # 出厂自检（边界=预测日）
    return text


def run_predict_premarket(day: str, *, config_dir, db_path=None,
                          pred_dir: Path = PRED_DIR, overnight_root=None,
                          model: str = DEFAULT_MODEL, client=None) -> dict:
    """对某日做盘前盲判（预测当日）。已完成日跳过；error 日重跑覆盖。"""
    path = premarket_path(day, pred_dir)
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old = {}
        if old.get("status") not in (None, "error"):
            return {"status": "skipped", "date": day}

    try:
        prev_day = _prev_trading_day(day, db_path=db_path)
        if prev_day is None:
            return {"date": day, "status": "no_data",
                    "error": "无前一交易日数据"}
        pack = build_daily_pack(prev_day, config_dir=Path(config_dir), db_path=db_path,
                                target_day=day)  # 盘前路径：扫 (prev_day, day] 区间催化（C2）
        # P0-3 连续状态：注入前一交易日复盘盲判摘要（predictions/{prev_day}.json）
        from investment_engine.shadow.predict import _load_prior_summary
        prior = _load_prior_summary(day, pred_dir=pred_dir, db_path=db_path)
        if prior:
            pack["prior_day"] = prior
        overnight = _load_overnight(day, overnight_root)
        text = _pack_to_premarket_prompt(pack, day, overnight)
        messages = [{"role": "system", "content": PREMARKET_SYSTEM_PROMPT},
                    {"role": "user", "content": text}]
        raw, result, validation = run_with_validation(
            messages, pack, model=model, client=client, tag="shadow_premarket",
            call_fn=call_deepseek)
        rec = {"date": day, "result": result, "raw": raw,
               "prompt_version": PROMPT_VERSION,
               "stage_hit": None, "due_scores": None, "status": "pending_maturity",
               "validation": validation,
               "meta": {"prev_day": prev_day,
                        "overnight_date": (overnight or {}).get("date")}}
    except Exception as e:  # noqa: BLE001 - 失败留 error 记录，次日重跑
        rec = {"date": day, "status": "error", "error": str(e)[:200]}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec
