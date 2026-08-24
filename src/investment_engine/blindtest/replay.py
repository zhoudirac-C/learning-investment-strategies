"""盲测推理回放：逐日组装 prompt 调 DeepSeek，JSONL 落盘，断点续跑。"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from investment_engine.blindtest.dataset import build_daily_pack, pack_to_prompt
from investment_engine.blindtest.truth import STAGES

DEFAULT_MODEL = "deepseek-chat"
_BASE_URL = "https://api.deepseek.com"
_MAX_DIRECTIONS = 3
_MAX_STOCKS_PER_DIR = 2
_POSTURES = ("趋势", "波段", "右侧确认", "回避")
# 性质定性（P1-1）：定性今日量价性质，区别于阶段二分（market_stage）
_NATURES = ("放量攻击", "缩量企稳", "主动降速", "内生瓦解", "外力扰动", "方向转折")
# 方向连续性（P0-3）：相对昨日该方向的加强/退潮/新增/维持
_TRENDS = ("加强", "退潮", "新增", "维持")
_MAX_SCENARIOS = 3
_MAX_LIST = 5

PROMPT_VERSION = "v11"

_LLM_CALL_LOG = Path(__file__).resolve().parents[3] / "log" / "llm_calls.jsonl"


def _int_or_none(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _log_llm_call(entry: dict) -> None:
    """LLM 调用台账（log/llm_calls.jsonl）。尽力而为，永不阻断主流程。"""
    try:
        _LLM_CALL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _LLM_CALL_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - 台账失败不影响调用
        pass

SYSTEM_PROMPT = """你是一个执行已验证方法论的市场分析引擎。基于给定的当日客观数据，独立完成市场复盘判断。
要求：
1. 每个判断必须声明所用的数据项；不得引用任何人物的言论或观点。
2. core_patterns 为全量判据框架（含推理步骤与证伪条件）：判定市场阶段（sentiment_cycle）、方向主线（mainline_identification）与操作建议（position_by_cycle）时必须逐条对照其步骤，并在 stage_reason / directions 的 reason / operation 中体现对照结果；patterns 仅为扩展框架索引。实际用到的框架 id 登记在 used_patterns。
3. 严格输出 JSON（不要输出其他文字）：
{"market_stage": "主升|震荡|调整|恐慌（四选一）",
 "nature": "放量攻击|缩量企稳|主动降速|内生瓦解|外力扰动|方向转折（六选一，定性今日量价性质：放量攻击=放量上涨进攻；缩量企稳=缩量止跌；主动降速=放量阴线但主动换手消化浮盈、非方向转折；内生瓦解=高位抱团断板情绪内部瓦解；外力扰动=消息面/外部利空；方向转折=趋势反转）",
 "stage_reason": "一句话依据（必须引用当日量能/情绪数据）",
 "scenarios": [{"name": "情形A", "condition": "触发条件", "conclusion": "应对结论", "key": "区分关键变量"}],
 "watch_next": ["下一交易日可观察、可证伪的验证变量"],
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
5. 若 user 内容含 prior_day（上一交易日盲判摘要），必须体现连续判断：在 stage_reason 中对照昨日判断说明今日是否兑现/证伪昨日 watch_next，并在 directions 的 trend 字段标注方向加强/退潮；不得把单日当作孤立快照。
6. 数据单位约定：成交额以「亿」计（数据键名如「两市成交额_亿」），成交量以「万手」计（键名「成交量万手」），两者不可混用；watch_next/scenarios 里的量能阈值必须写「成交额(亿)」或「成交量(万手)」，禁止出现「成交额突破X万手」这类跨单位表述。
7. operation 必须用 position_by_cycle 推导：先定位周期位置(position)——position 的第一决定变量是周期位置（结合 cycle_state 的 rebound_day），情绪好坏是次要变量：若 cycle_state 的 rebound_day ≥ 8 且超过 theoretical_window 上限，position 优先判「反弹超预期」（叠加放量兑现/涨停萎缩则判「高位兑现」），不得因涨停家数减少、情绪退潮就归入「震荡调整」（「震荡调整」仅适用于无明确反弹周期的情况）；再按「状态→动作」映射匹配 action，并用三条元规则（仓位纪律高于判断/确定性决定力度/特定状态最优动作是克制）校验；禁止脱离状态写「逢低关注/降低仓位」这类无状态依赖的套话。
8. cycle_state 综合多指数反弹周期（不要自己算）：若 user 数据含 cycle_state（代码算好的多指数反弹周期，如 {科创50:{rebound_day,bottom_date,theoretical_window}, 创业板指:{...}, 上证指数:{...}}），综合各指数判断——科技主线（科创50/创业板指）优先，各指数 bottom_date 一致则周期确认、分歧则按科技主线锚定并在 note 说明；输出 cycle_state 字段取综合值，note 写指数间一致或分歧；无该数据输出空对象 {}。
9. 量能性质定性（放量/缩量）须并列引用盘中形态与环比口径：若 user 数据含 intraday_amount，stage_reason 必须引用其「形态」字段（如"冲量滑落（全天缩量）"）与「环比前日_pct」；两者冲突时（如形态=冲量滑落但环比放量）不得单一口径强制定性，须在 stage_reason 写明冲突并给出双向解读（如：冲量滑落=追涨意愿不足；环比放量=下跌有承接）。「开盘预估全天_亿 → 尾盘实际全天_亿」为历史同时段占比校准后的同口径对照，可并列引用。禁止写只有环比、不对照盘中形态的结论。
10. 证据-结论一致性硬约束：若 user 数据含 intraday_amount，先比对「开盘预估全天_亿」与「尾盘实际全天_亿」——两者偏差超过 ±15% 时（校准后正常偏差约 ±3%，±15% 对应盘中分布显著异常），nature 与 market_stage 禁止输出「放量攻击」「主升」类结论；更一般地，stage_reason 引用的每条证据不得与 market_stage/nature 结论冲突，发现冲突时必须改写结论对齐证据，不得忽视证据维持原结论。
11. 输出前必须逐项自检并修正：(a) operation.position 与 market_stage 不得互相矛盾（反例：market_stage 判「主升」同时 position 写「获利了结降仓位」——二者必改其一）；(b) 规则 7 的周期窗口判定（cycle_state.rebound_day ≥ theoretical_window 上限 → position 优先判「反弹超预期」）必须已执行，未执行则重做 position 定位；(c) 若 user 数据含 missing 块（数据缺失清单），缺失维度对应的判断必须降低置信度，并在 stage_reason 标注「数据缺失，信息差风险」。
12. intraday_amount 块「形态」字段为「冲量滑落」时，nature 禁止判「放量攻击」；必须结合分时量能（intraday_amount 的「分时」曲线）确认放量真实性后才能输出放量类结论。
13. 判放量性质必须回答「量从哪来」：区分存量调仓（板块间换手）与增量入场——换手放量的持续性弱于增量入场，不得直接定性为增量进攻；若 user 数据含 fund_flow/lhb 块，必须引用其数据佐证量能源头，无该数据则按规则 11(c) 降级表述。
14. 中阳/大阳定性前先定位置：先判定当日处于反弹修复段还是趋势加速段，再给出量价性质结论；反弹修复段的右侧确认点放在补缺回踩之后的量价配合，不得仅凭当日量价齐升直接判主升/趋势加速。
15. 量能分档一律用相对表述（守住前日量级/温和放大/越过确认位），禁止自拍绝对阈值（如「24000 亿以上算放量」这类自定义数字）；绝对刻度只许引用方法论框架分档（2.5 万亿=放量确认位、3 万亿以上=警惕过热）。
16. 连板梯队分析不得只用涨停家数/封板率汇总值：若 user 数据的 limit_pool 块含 ladder（分层名单）、compare.promotion_rate（晋级率）、first_board_width、regulatory_distance，必须引用这些字段给出梯队判断；并按「首板家数 × 约 15% 晋级率」折算次日二板健康区间，写入 watch_next 作为跟踪变量。
17. 顶部结构信号必须引用：若 user 数据的 structure 块含任一指数 60min 及以上级别 top 且 state 为 forming/divergence（顶部钝化中）或 invalidated（钝化消失），stage_reason 或 watch_next 必须引用该信号（指数+级别+状态），并给出确认/消失的观察条件；含 td9 计数≥5 的级别同理；无该数据不强制。
18. 情绪极端日反向检验（三信号见底清单）：判 market_stage=「调整」或 nature=「内生瓦解」前，若当日情绪呈极端值（跌停≥80家，或上涨家数≤1000家），stage_reason 必须先逐条回答三信号见底清单——①强势股是否补跌（核心连板高标同步跌停/风险提示）；②是否多杀多（跌停家数盘中反超涨停并飙升）；③流动性是否见底（缩量=抛压衰竭为见底，放量下跌=未见底）。仅缺「流动性见底」时禁止判「调整/内生瓦解」，基准情形按「接近极限但未出清、横向震荡磨窗口」构造 scenarios（很难比前一日更差，但也不直接反转）。无情绪极端值时不强制。
19. 普涨弱指数日的宽度/强度两步定性：上涨家数显著多于下跌家数（约2倍以上）但指数收跌或冲高回落时，禁止直接定性「情绪修复」——stage_reason 必须先分解「谁在涨（超跌/低位补涨）谁在压（权重/前期高位品种）」，再判定宽度修复或强度修复；缩量宽度修复按反抽处理（不构成调整结束信号，反而消耗调整时间），scenarios 确认线挂「守住当前量能台阶」而非「回升至上台阶」。「缩量企稳」只证明卖方衰竭、不证明买盘回来，选该 nature 时不得在 stage_reason 写增量入场类结论。
20.（规则15扩展）量能台阶锚定：写量能阈值前先定位当前量能所处台阶；优先引用当日/前日成交额量级的「守住/跌破」线或方法论分档（2.5万亿确认位/3万亿过热）；量能下台阶阶段，禁止把修复确认线挂在上一台阶（如「回升至X亿确认修复」）。
21. 弱市防御方向禁止顺延：directions 候选含前一交易日弱市中逆势净流入的防御方向（银行/煤炭/石油石化/农业等避险品种）时，禁止直接标「维持」——先答「次日修复概率」，修复情形下防御方向默认退潮（标「退潮」或不选）；并须回溯昨日所选方向的当日表现、在 trend 字段标注（规则5闭环）。
22. watch_next 首条为个股级验证节点：连板梯队有独苗（唯一高位活口）/断板换龙承接标的/控异动个股，或 lhb 机构席位 top 个股与该股当日情绪事件方向矛盾（如大额净买入+控异动失败）时，watch_next 第一条须点名标的并给出确认/证伪条件；不得只写汇总指标。
23. 方向判断必须做催化溯源：directions 所选方向（及 stage_reason 归因的当日领涨/领跌方向）若当日涨幅/净流入居前，必须先在 user 数据的 news_titles / research 块中检索对应催化并引用条目标题；检索不到显性催化时必须注明「无显性催化，按纯资金/轮动对待」并降低置信度（posture 不高于「波段」）。禁止只用「涨幅居前+资金流入」的描述性理由。
24. 外力/内生归因前置：判 market_stage/nature 前先答「本轮驱动来自内部还是外部」。若 user 数据含 global_macro/overnight_us 且外部链条成立（隔夜美股半导体/存储链大跌、亚太股指同步重挫、美债收益率异常变动等），nature 优先判「外力扰动」，不得仅凭内部情绪指标判「内生瓦解」；判「外力扰动」时 stage_reason 必须引用外盘数据，scenarios/invalidation 至少一条含外部变量锚（如今夜美股收盘位置、关键利率点位）。无论最终定性如何，stage_reason 必须注明外部链条检验结论（成立/不成立/平稳）。
25. 宏观三条件校验（宏观压制 vs AI证伪定性）：若 user 数据的 global_macro 块含美债收益率字段，stage_reason 必须做「宏观三条件」检验并给出定性质结论——三条前置条件：①美联储动向（不动=条件成立）②油价是否低于80美元 ③十年期美债收益率是否低于4.70%。三条均不成立时，本轮压制优先定性为「宏观扰动」而非「AI商业模式证伪」，科技主线的中期逻辑不被外盘下跌证伪；部分成立时写明哪条失效及对应含义。禁止只罗列外盘涨跌数字而不给宏观/AI归因结论。
23b. 催化兑现覆盖：directions 做催化溯源（规则23）时，若 overnight_us 中该方向的隔夜映射股出现大幅回落（利好兑现），隔夜反向数据优先于前日催化——reason 必须同时引用两者并解释矛盾（如「前日+X%催化 vs 隔夜-Y%兑现回落」），禁止只引用前日利好而忽略隔夜反向信号；此时 posture 不高于「波段」或直接不选该方向。
27. 方向同簇限选：directions 选出的多条方向不得属于同一相关簇（簇=共享同一核心催化、同涨同跌的方向群，非字面行业分类）。参考分簇——C1 AI硬件链：pcb_ai_chain、ccL_resin_upstream、copper_foil_hvlp4、tungsten_pcb_drill、cipb_power_substrate、mlcc_super_cycle、aramid_ai_fiber、optical_communication、switch_800g_domestic、computing_network_super_node、waic_supernode_catalyst、memory_nor、chip_specialty、semiconductor_silicon_wafer、electronic_gas_wf6、leadframe_upcycle、equipment_packaging_catchup、sk_hynix_adr、edge_ai_endpoint、aidc_power_supply；C2 能源电力：green_power_ai_electric、photovoltaic_low_recovery、lithium_battery_separator_upcycle；C3 大宗周期：coke_coal_upcycle、copper_aluminum_shortage、small_metal_chemical、upstream_scarce_price_rise、polyester_filament_refill、tire_offshore_transfer；C4 医药：pharmaceutical_innovation、ai4s_pharma；C5 金融：securities_bottom、broker_finance；C6 消费农业：pig_farming_hedge、cheese_domestic_sub；C7 主题事件/其他：commercial_aerospace、robot_observation、shipbuilding_boom、typhoon_drainage、film_industry_event、mid_report_performance、kcb_ai_policy、ai_applications_rotation、ai_equity_investment、cybersecurity_mapping。自由文本方向名按语义归簇（如「5G概念」「存储芯片」均属 C1）。两条候选同簇时保留 reason 证据更强的一条，第二条从其它簇选当日证据最强者；若其它簇无合格候选，允许只输出 1 条并在 reason 注明「同簇限选，无其它簇合格候选」。每条 direction 的 reason 中用一句话写明簇归属判断（如「同属C1 AI硬件簇，取证据更强者」）。"""


def build_messages(pack_text: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": pack_text},
    ]


def _default_client():
    from openai import OpenAI

    # 兼容仓库 .env 的小写命名（qing_investment Settings 用 deepseek_api_key）
    key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("deepseek_api_key")
    if not key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY 环境变量")
    return OpenAI(api_key=key, base_url=_BASE_URL)


def call_deepseek(messages: list[dict], *, model: str = DEFAULT_MODEL,
                  max_retries: int = 3, client=None, tag: str | None = None) -> str:
    client = client or _default_client()
    last_err: Exception | None = None
    prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
    for attempt in range(1, max_retries + 1):
        t0 = time.monotonic()
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=0,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content
            usage = getattr(resp, "usage", None)
            _log_llm_call({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "event": "ok", "tag": tag, "model": model, "attempt": attempt,
                "latency_s": round(time.monotonic() - t0, 2),
                "prompt_chars": prompt_chars,
                "prompt_tokens": _int_or_none(getattr(usage, "prompt_tokens", None)),
                "completion_tokens": _int_or_none(getattr(usage, "completion_tokens", None)),
                "reply_chars": len(content or ""),
            })
            return content
        except Exception as e:  # noqa: BLE001 - 重试后如实记录
            last_err = e
            _log_llm_call({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "event": "error", "tag": tag, "model": model, "attempt": attempt,
                "latency_s": round(time.monotonic() - t0, 2),
                "prompt_chars": prompt_chars,
                "error": str(e)[:200],
            })
            if attempt < max_retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"DeepSeek 调用失败（{max_retries} 次）: {last_err}")


def parse_result(raw: str) -> dict:
    """解析模型输出为规范结构；fence 容忍、字段校验、超限截断。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"输出非 JSON: {raw[:80]!r}") from e
    stage = data.get("market_stage")
    if stage not in STAGES:
        raise ValueError(f"market_stage 非法: {stage!r}")
    nature = str(data.get("nature", ""))
    if nature not in _NATURES:
        nature = ""  # nature 非评分字段，非法值清空（不阻断）
    directions = []
    for d in (data.get("directions") or [])[:_MAX_DIRECTIONS]:
        if not isinstance(d, dict) or not d.get("direction_id"):
            continue
        posture = str(d.get("posture", ""))
        trend = str(d.get("trend", ""))
        directions.append({
            "direction_id": str(d["direction_id"]),
            "reason": str(d.get("reason", "")),
            "posture": posture if posture in _POSTURES else "",
            "trend": trend if trend in _TRENDS else "",
            "stocks": [str(s).split(".")[0] for s in (d.get("stocks") or [])[:_MAX_STOCKS_PER_DIR]],
        })
    scenarios = []
    for s in (data.get("scenarios") or [])[:_MAX_SCENARIOS]:
        if not isinstance(s, dict):
            continue
        scenarios.append({
            "name": str(s.get("name", "")),
            "condition": str(s.get("condition", "")),
            "conclusion": str(s.get("conclusion", "")),
            "key": str(s.get("key", "")),
        })
    op = data.get("operation")
    if not isinstance(op, dict):
        op = {}
    operation = {
        "position": str(op.get("position", "")),
        "action": str(op.get("action", "")),
        "basis": str(op.get("basis", "")),
    }
    cs = data.get("cycle_state")
    if not isinstance(cs, dict):
        cs = {}
    cycle_state = {
        "rebound_day": cs.get("rebound_day"),
        "bottom_level": str(cs.get("bottom_level", "")),
        "bottom_date": str(cs.get("bottom_date", "")),
        "theoretical_window": str(cs.get("theoretical_window", "")),
        "note": str(cs.get("note", "")),
    }
    return {
        "market_stage": stage,
        "nature": nature,
        "stage_reason": str(data.get("stage_reason", "")),
        "scenarios": scenarios,
        "watch_next": [str(w) for w in (data.get("watch_next") or [])[:_MAX_LIST]],
        "invalidation": [str(w) for w in (data.get("invalidation") or [])[:_MAX_LIST]],
        "directions": directions,
        "used_patterns": [str(p) for p in (data.get("used_patterns") or [])],
        "operation": operation,
        "cycle_state": cycle_state,
    }


# ---------------------------------------------------------------------------
# 输出确定性校验层（proposal: 2026-08-18-fix-deterministic-output-validation）
# 规则遵守不依赖模型自觉：违规则打回重写一次，仍违规则标 failed 如实落盘。
# ---------------------------------------------------------------------------

# 规则15 白名单：方法论框架量能分档（数值 → 同句必需关键词）
_FRAMEWORK_BANDS = {25000: ("确认位",), 30000: ("过热", "警惕")}
_RELATIVE_ANCHORS = ("前日量级", "昨日量级", "前一交易日", "昨日成交", "前日成交")
# v9 规则20：当前台阶锚定语境词（数值 ≈ pack 当日/前日成交额 ±7% 时豁免自拍阈值）
_STEP_HOLD_WORDS = ("守住", "站稳", "跌破", "失守", "萎缩", "缩量至", "缩至")
_AMOUNT_RE = re.compile(r"成交额[\(（]?亿?[\)）]?[^\d]{0,15}?(\d{4,5})\s*亿?")

# 规则18：三信号见底清单引用词
_THREE_SIGNAL_HINTS = ("补跌", "多杀多", "流动性")
_THREE_SIGNAL_NAMED = ("三信号", "见底判据", "见底清单")

# 规则24：外部链条引用词（外力/内生归因前置）
_EXTERNAL_HINTS = ("外盘", "美股", "隔夜", "美债", "费半", "费城", "纳指", "道指",
                   "标普", "SOX", "KOSPI", "日经", "恒生", "美元指数", "收益率",
                   "存储链", "亚太", "外部")

# 规则25：宏观三条件校验引用词（宏观压制 vs AI证伪定性）
_MACRO_CHECK_HINTS = ("宏观三条件", "三条件", "美联储", "油价", "4.70", "4.7%", "十年期", "10Y")

_LADDER_HINTS = ("梯队", "连板", "首板", "晋级", "二板", "断板", "高度", "宽度", "抱团")
_STRUCTURE_HINTS = ("钝化", "顶部结构", "背离", "MACD", "绿柱", "高9", "DIF")
_REDUCE_RE = re.compile(r"降仓|减仓|获利了结|兑现|清仓|卖出")

# 规则27：方向同簇限选——池内 direction_id → 簇（proposal:
# 2026-08-24-pattern-direction-cluster-limit；与 SYSTEM_PROMPT 规则27 分簇保持一致）
_DIRECTION_CLUSTERS = {
    "C1": ("pcb_ai_chain", "ccL_resin_upstream", "copper_foil_hvlp4",
           "tungsten_pcb_drill", "cipb_power_substrate", "mlcc_super_cycle",
           "aramid_ai_fiber", "optical_communication", "switch_800g_domestic",
           "computing_network_super_node", "waic_supernode_catalyst",
           "memory_nor", "chip_specialty", "semiconductor_silicon_wafer",
           "electronic_gas_wf6", "leadframe_upcycle", "equipment_packaging_catchup",
           "sk_hynix_adr", "edge_ai_endpoint", "aidc_power_supply"),
    "C2": ("green_power_ai_electric", "photovoltaic_low_recovery",
           "lithium_battery_separator_upcycle"),
    "C3": ("coke_coal_upcycle", "copper_aluminum_shortage", "small_metal_chemical",
           "upstream_scarce_price_rise", "polyester_filament_refill",
           "tire_offshore_transfer"),
    "C4": ("pharmaceutical_innovation", "ai4s_pharma"),
    "C5": ("securities_bottom", "broker_finance"),
    "C6": ("pig_farming_hedge", "cheese_domestic_sub"),
    "C7": ("commercial_aerospace", "robot_observation", "shipbuilding_boom",
           "typhoon_drainage", "film_industry_event", "mid_report_performance",
           "kcb_ai_policy", "ai_applications_rotation", "ai_equity_investment",
           "cybersecurity_mapping"),
}
_DIRECTION_CLUSTER_OF = {d: c for c, ids in _DIRECTION_CLUSTERS.items() for d in ids}
# 自由文本方向名归簇别名（只收高精度关键词；长词优先，避免「铜箔」被「铜」截胡）
_DIRECTION_CLUSTER_ALIASES = {
    "C1": ("存储", "芯片", "半导体", "PCB", "覆铜板", "铜箔", "光通信", "光模块",
           "CPO", "算力", "MLCC", "被动元件", "5G", "服务器", "液冷"),
    "C2": ("绿电", "电力", "光伏", "锂电"),
    "C3": ("焦炭", "煤", "铜", "铝", "小金属", "化工", "涤纶", "轮胎"),
    "C4": ("创新药", "医药", "疫苗"),
    "C5": ("证券", "券商", "银行"),
    "C6": ("猪", "养殖", "奶酪", "食品"),
}
_ALIAS_KEYS = sorted(
    ((k, c) for c, ks in _DIRECTION_CLUSTER_ALIASES.items() for k in ks),
    key=lambda x: -len(x[0]))


def _direction_cluster(direction_id: str) -> str | None:
    """direction_id → 簇编号；池内 id 精确匹配，自由文本按别名归簇，无法归类返回 None。"""
    if direction_id in _DIRECTION_CLUSTER_OF:
        return _DIRECTION_CLUSTER_OF[direction_id]
    low = direction_id.lower()
    for k, c in _ALIAS_KEYS:
        if k.lower() in low:
            return c
    return None


def _result_text(result: dict) -> str:
    """拼接输出全部文本字段，供引用类校验检索。"""
    parts = [result.get("stage_reason")]
    for s in result.get("scenarios") or []:
        parts += [s.get("condition"), s.get("conclusion"), s.get("key")]
    parts += list(result.get("watch_next") or [])
    parts += list(result.get("invalidation") or [])
    for d in result.get("directions") or []:
        parts.append(d.get("reason"))
    op = result.get("operation") or {}
    parts += [op.get("action"), op.get("basis")]
    parts.append((result.get("cycle_state") or {}).get("note"))
    return " ".join(str(p or "") for p in parts)


def _iter_top_signals(structure, ref_date: str | None = None) -> list[tuple[str, str, str]]:
    """structure 块中的顶部 forming/divergence/invalidated 信号 → (指数, 级别, 状态)。

    ref_date 提供时只保留近 10 个自然日内的信号：低级别信号快速轮换，
    但 daily 级 invalidated 可能滞留数月（2026-08-18 实测创业板指 daily
    残留 2026-06-25 invalidated），不设时效会让规则17 每天强制引用陈旧信号。
    """
    out = []
    if not isinstance(structure, dict):
        return out
    for idx, levels in structure.items():
        if not isinstance(levels, dict):
            continue
        for level, lv in levels.items():
            if not isinstance(lv, dict):
                continue
            top = lv.get("top")
            if not isinstance(top, dict) or \
                    top.get("state") not in ("forming", "divergence", "invalidated"):
                continue
            if ref_date:
                t = str(top.get("time") or "")[:10]
                if t and t < _shift_days(ref_date, -10):
                    continue  # 陈旧信号，不强制引用（数据仍留在包内供模型参考）
            out.append((str(idx), str(level), str(top.get("state"))))
    return out


def _shift_days(day: str, delta: int) -> str:
    from datetime import datetime, timedelta
    return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=delta)).strftime("%Y-%m-%d")


def validate_result(result: dict, pack: dict | None = None) -> list[str]:
    """确定性校验：返回违规说明列表，空列表 = 通过。不调 LLM。

    四类校验（对应 prompt v9 规则）：
    - 规则15/20：scenarios/watch_next/invalidation 禁止自拍绝对成交额阈值
      （当前台阶锚定——守住/跌破 pack 当日或前日成交额量级 ±7%——豁免）；
    - 规则11a + 10/12：结论-证据一致性（主升 vs 降仓类动作；冲量滑落 vs 放量结论）；
    - 规则13/16/17：pack 在场数据（ladder/jgmmtj/顶部结构信号）必须引用；
    - 规则18：情绪极端日判「调整/内生瓦解」必须引用三信号见底清单；
    - 规则24：pack 含外盘数据（global_macro/overnight_us）时必须引用外部链条；
    - 规则27：directions 同簇多选（池内 id 精确归簇，自由文本按别名归簇）。
    """
    if not isinstance(result, dict):
        return ["输出结构非法"]
    violations: list[str] = []

    # 规则15：绝对成交额阈值（相对口径锚点 / 框架分档 + 关键词 / 当前台阶锚定豁免）
    daban = ((pack or {}).get("emotion") or {}).get("daban") or {}
    step_anchors: list[float] = []
    for _k in ("两市成交额_亿", "昨日两市成交额_亿"):
        _v = daban.get(_k)
        if isinstance(_v, (int, float)) and _v:
            step_anchors.append(float(_v))
    fields = [("scenarios.condition", str(s.get("condition") or ""))
              for s in result.get("scenarios") or [] if isinstance(s, dict)]
    fields += [("watch_next", str(w or "")) for w in result.get("watch_next") or []]
    fields += [("invalidation", str(w or "")) for w in result.get("invalidation") or []]
    for src, text in fields:
        if any(a in text for a in _RELATIVE_ANCHORS):
            continue
        m = _AMOUNT_RE.search(text)
        if m:
            num = int(m.group(1))
            keys = _FRAMEWORK_BANDS.get(num)
            if keys and any(k in text for k in keys):
                continue
            if step_anchors and any(w in text for w in _STEP_HOLD_WORDS) and \
                    any(abs(num - a) / a <= 0.07 for a in step_anchors):
                continue  # 守住/跌破当前量能台阶（pack 锚点 ±7%）为规则20 合法表述
            violations.append(
                f"规则15: {src} 含自拍绝对成交额阈值「{num}亿」"
                "（量能只写方向/相对口径，或引用 2.5万亿确认位 / 3万亿过热 分档）")

    # 规则11a：market_stage 与 operation.action 不得矛盾
    stage = result.get("market_stage")
    action = str((result.get("operation") or {}).get("action") or "")
    if stage == "主升" and _REDUCE_RE.search(action):
        violations.append(
            f"规则11: market_stage=主升 与 operation.action「{action[:20]}」自相矛盾")

    # 规则27：方向同簇限选——同簇双选即违规（合规出口只有「只输出1条并注明」）
    cluster_hits: dict[str, list[str]] = {}
    for d in result.get("directions") or []:
        if not isinstance(d, dict):
            continue
        c = _direction_cluster(str(d.get("direction_id") or ""))
        if c:
            cluster_hits.setdefault(c, []).append(str(d.get("direction_id")))
    for c, ids in cluster_hits.items():
        if len(ids) > 1:
            violations.append(
                f"规则27: directions 同簇多选（{c}：{'、'.join(ids)}）——"
                "同簇限选：保留证据更强者，另一条从其它簇递补；"
                "其它簇无合格候选时应只输出 1 条并注明")

    # 规则10/12：盘中形态冲量滑落时禁止放量类结论
    shape = str(((pack or {}).get("intraday_amount") or {}).get("形态") or "")
    if "冲量滑落" in shape and (result.get("nature") == "放量攻击" or stage == "主升"):
        violations.append(
            "规则10/12: intraday 形态为冲量滑落，禁止 nature=放量攻击 / market_stage=主升")

    # 规则13/16/17：在场数据必须引用（pack 缺块则跳过对应校验）
    if pack:
        text_all = _result_text(result)
        ladder = (pack.get("limit_pool") or {}).get("ladder")
        has_ladder = (isinstance(ladder, dict) and any(ladder.values())) or \
                     (isinstance(ladder, list) and bool(ladder))
        if has_ladder and not any(h in text_all for h in _LADDER_HINTS):
            violations.append(
                "规则16: pack 含 limit_pool.ladder 梯队数据，输出未引用梯队结构字段")
        jg = (pack.get("lhb") or {}).get("jgmmtj") or {}
        names = []
        if isinstance(jg, dict):
            for key in ("净买入top5", "净卖出top5"):
                for row in jg.get(key) or []:
                    if isinstance(row, dict) and row.get("名称"):
                        names.append(str(row["名称"]))
        if names and "机构" not in text_all and not any(n in text_all for n in names):
            violations.append("规则13: pack 含 lhb.jgmmtj 机构席位数据，输出未引用")
        tops = _iter_top_signals(pack.get("structure"), ref_date=pack.get("date"))
        if tops and not any(h in text_all for h in _STRUCTURE_HINTS):
            idx, level, state = tops[0]
            violations.append(
                f"规则17: pack 含 {idx} {level} 顶部{state}信号，输出未引用")

        # 规则18：情绪极端日判「调整/内生瓦解」必须先过三信号见底清单
        die, up = daban.get("跌停"), daban.get("上涨家数")
        extreme = (isinstance(die, (int, float)) and die >= 80) or \
                  (isinstance(up, (int, float)) and up <= 1000)
        if extreme and (stage == "调整" or result.get("nature") == "内生瓦解"):
            sr = str(result.get("stage_reason") or "")
            named = any(k in sr for k in _THREE_SIGNAL_NAMED)
            hits = sum(1 for h in _THREE_SIGNAL_HINTS if h in sr)
            if not named and hits < 2:
                violations.append(
                    "规则18: 情绪极端日判「调整/内生瓦解」，stage_reason 未逐条检验"
                    "三信号见底清单（强势股补跌/多杀多/流动性见底）")

        # 规则25：宏观三条件校验——global_macro 含美债收益率时必须做宏观/AI归因
        gm = pack.get("global_macro") or {}
        has_yield = isinstance(gm.get("美债收益率"), dict) and bool(gm["美债收益率"])
        if has_yield and not any(h in text_all for h in _MACRO_CHECK_HINTS):
            violations.append(
                "规则25: pack 含 global_macro 美债收益率数据，stage_reason 未做宏观三条件"
                "检验（美联储/油价80美元/十年期4.70%）——须给出宏观压制 vs AI证伪的定性质结论")

        # 规则26：指数点位须落在 pack 主要指数当日收盘价 ±10% 内
        # （2026-08-21 实测幻觉：「跌破前低4588.7」vs 上证实际 3883-3905）
        index_pack = (pack or {}).get("index")
        if isinstance(index_pack, dict) and index_pack:
            closes = []
            for _code, bars in index_pack.items():
                if isinstance(bars, list) and bars and \
                        isinstance(bars[-1], dict) and bars[-1].get("c"):
                    try:
                        closes.append(float(bars[-1]["c"]))
                    except (TypeError, ValueError):
                        continue
            if closes:
                # 只扫千位级点位（1000-99999），排除量能语境（亿/万/家/%）
                for src, txt in fields:
                    if any(w in txt for w in ("亿", "万手", "家", "%")):
                        continue
                    for m in re.finditer(r"\d{4,5}(?:\.\d+)?", txt):
                        num = float(m.group())
                        if num < 1000:
                            continue
                        if not any(abs(num - c) / c <= 0.10 for c in closes):
                            violations.append(
                                f"规则26: {src} 指数点位「{num}」偏离 pack 全部主要指数"
                                f"当日收盘价（{', '.join(f'{c:.0f}' for c in closes)}）±10%"
                                "以上，疑似幻觉数字——指数点位须引用 pack 内真实价位")

        # 规则24：外力/内生归因前置——外盘数据在场时必须引用外部链条
        # （无论最终定性；判非外力也须注明外部检验结论）
        has_external = bool(pack.get("global_macro")) or \
            bool((pack.get("overnight_us") or {}).get("themes"))
        if has_external and not any(h in text_all for h in _EXTERNAL_HINTS):
            violations.append(
                "规则24: pack 含外盘数据（global_macro/overnight_us），输出未引用"
                "外部链条——外力/内生归因前置：须注明外部检验结论（成立/不成立/平稳）")

    return violations


def _violation_note(violations: list[str]) -> str:
    items = "\n".join(f"- {v}" for v in violations)
    return ("上一版输出违反以下硬性规则：\n" + items +
            "\n请只修正违规部分（量能改相对口径 / 补充引用在场数据字段 / 消除结论矛盾），"
            "严格按原 JSON 契约重新输出完整结果。")


def run_with_validation(messages: list[dict], pack: dict | None = None, *,
                        model: str = DEFAULT_MODEL, client=None,
                        tag: str | None = None, call_fn=None) -> tuple[str, dict, dict]:
    """调 LLM + 确定性校验：违规则带说明重试一次；仍违规则标 failed 如实返回。

    返回 (raw, result, validation)；validation = {status, violations, retried}。
    call_fn 可注入（默认 call_deepseek），便于调用方使用本模块已打补丁的引用。
    """
    call = call_fn or call_deepseek
    raw = call(messages, model=model, client=client, tag=tag)
    result = parse_result(raw)
    violations = validate_result(result, pack)
    retried = False
    if violations:
        retried = True
        retry_msgs = list(messages) + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": _violation_note(violations)},
        ]
        retry_tag = f"{tag}_retry" if tag else None
        raw2 = call(retry_msgs, model=model, client=client, tag=retry_tag)
        try:
            result2 = parse_result(raw2)
        except ValueError:
            result2 = None
        if result2 is not None:
            v2 = validate_result(result2, pack)
            if not v2:
                return raw2, result2, {"status": "passed", "violations": [],
                                       "retried": True}
            raw, result, violations = raw2, result2, v2
    validation = ({"status": "failed", "violations": violations, "retried": retried}
                  if violations else
                  {"status": "passed", "violations": [], "retried": retried})
    return raw, result, validation


def _done_dates(out_path: Path) -> set[str]:
    """断点续跑：只把成功（ok=True）的日期视为已完成；error 日期会重跑。"""
    if not out_path.exists():
        return set()
    done = set()
    for line in out_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("ok"):
            done.add(row["date"])
    return done


def run_replay(days: list[str], *, config_dir, out_path: Path, db_path=None,
               model: str = DEFAULT_MODEL, client=None, sleep_s: float = 0.5) -> dict:
    """逐日回放。已完成日期跳过（断点续跑）；单日失败记 error 继续。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = _done_dates(out_path)
    stats = {"done": 0, "skipped": 0, "error": 0}
    with out_path.open("a", encoding="utf-8") as fh:
        for day in days:
            if day in done:
                stats["skipped"] += 1
                continue
            try:
                pack = build_daily_pack(day, config_dir=Path(config_dir), db_path=db_path)
                text = pack_to_prompt(pack)  # 内含防泄漏断言
                raw = call_deepseek(build_messages(text), model=model, client=client,
                                    tag="blindtest_replay")
                result = parse_result(raw)
                fh.write(json.dumps(
                    {"date": day, "ok": True, "result": result, "raw": raw,
                     "prompt_version": PROMPT_VERSION},
                    ensure_ascii=False) + "\n")
                stats["done"] += 1
            except Exception as e:  # noqa: BLE001 - 单日失败不阻断全量
                fh.write(json.dumps(
                    {"date": day, "ok": False, "error": str(e)[:200]},
                    ensure_ascii=False) + "\n")
                stats["error"] += 1
            fh.flush()
            time.sleep(sleep_s)
    return stats
