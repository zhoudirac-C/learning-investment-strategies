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

DEFAULT_MODEL = os.environ.get("SHADOW_LLM_MODEL", "deepseek-v4-flash")
_BASE_URL = os.environ.get("SHADOW_LLM_BASE_URL", "https://token.sensenova.cn/v1")
# sensenova deepseek-v4-flash 是推理模型：默认输出上限 8192 会被 reasoning 吃满
# （盲判长 prompt 72K tokens 实测 content 变空）。
#  关闭 thinking（默认）: max_tokens 16384 即可, 延迟 ~15s
#  开启 thinking（SHADOW_LLM_THINKING=on）: reasoning 消耗大, max_tokens 须更大
_MAX_OUTPUT_TOKENS = int(os.environ.get("SHADOW_LLM_MAX_TOKENS", "16384"))
_THINKING_DISABLED = os.environ.get("SHADOW_LLM_THINKING", "off").lower() != "on"
# 推理模式专属预算：reasoning 动辄数千 tokens，需要远高于非推理的 16384
_MAX_OUTPUT_TOKENS_THINKING = int(os.environ.get("SHADOW_LLM_THINKING_MAX_TOKENS", "32768"))
# 单次 LLM 调用超时：thinking on 时盲判长 prompt 实测 208s，归因 31s，留足余量
_LLM_TIMEOUT = int(os.environ.get("SHADOW_LLM_TIMEOUT", "600"))
_MAX_DIRECTIONS = 3
_MAX_STOCKS_PER_DIR = 2
_POSTURES = ("趋势", "波段", "右侧确认", "回避")
# 性质定性（P1-1）：定性今日量价性质，区别于阶段二分（market_stage）
_NATURES = ("放量攻击", "缩量企稳", "主动降速", "内生瓦解", "外力扰动", "方向转折")
# 方向连续性（P0-3）：相对昨日该方向的加强/退潮/新增/维持
_TRENDS = ("加强", "退潮", "新增", "维持")
_MAX_SCENARIOS = 3
_MAX_LIST = 5

PROMPT_VERSION = "v15"

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

# v15 原样冻结（A/B 对照臂；37 条经验补丁规则，编号 1-25/23b/27-37 为历史形态）
SYSTEM_PROMPT_V15 = """你是一个执行已验证方法论的市场分析引擎。基于给定的当日客观数据，独立完成市场复盘判断。
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
5. 若 user 内容含 prior_day（上一交易日盲判摘要），必须体现连续判断：在 stage_reason 中对照昨日判断说明今日是否兑现/证伪昨日 watch_next，并在 directions 的 trend 字段标注方向加强/退潮；不得把单日当作孤立快照。若 user 内容含 premarket_today（当日盘前预判），收盘结论与盘前预判的 market_stage 不一致时，stage_reason 必须写明推翻理由（当日哪项数据证伪了盘前预判）；一致时注明「盘前预判兑现」。
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
27. 方向同簇限选：directions 选出的多条方向不得属于同一相关簇（簇=共享同一核心催化、同涨同跌的方向群，非字面行业分类）。参考分簇——C1 AI硬件链：pcb_ai_chain、ccL_resin_upstream、copper_foil_hvlp4、tungsten_pcb_drill、cipb_power_substrate、mlcc_super_cycle、aramid_ai_fiber、optical_communication、switch_800g_domestic、computing_network_super_node、waic_supernode_catalyst、memory_nor、chip_specialty、semiconductor_silicon_wafer、electronic_gas_wf6、leadframe_upcycle、equipment_packaging_catchup、sk_hynix_adr、edge_ai_endpoint、aidc_power_supply；C2 能源电力：green_power_ai_electric、photovoltaic_low_recovery、lithium_battery_separator_upcycle；C3 大宗周期：coke_coal_upcycle、copper_aluminum_shortage、small_metal_chemical、upstream_scarce_price_rise、polyester_filament_refill、tire_offshore_transfer；C4 医药：pharmaceutical_innovation、ai4s_pharma；C5 金融：securities_bottom、broker_finance；C6 消费农业：pig_farming_hedge、cheese_domestic_sub；C7 主题事件/其他：commercial_aerospace、robot_observation、shipbuilding_boom、typhoon_drainage、film_industry_event、mid_report_performance、kcb_ai_policy、ai_applications_rotation、ai_equity_investment、cybersecurity_mapping。自由文本方向名按语义归簇（如「5G概念」「存储芯片」均属 C1）。两条候选同簇时保留 reason 证据更强的一条，第二条从其它簇选当日证据最强者；若其它簇无合格候选，允许只输出 1 条并在 reason 注明「同簇限选，无其它簇合格候选」。每条 direction 的 reason 中用一句话写明簇归属判断（如「同属C1 AI硬件簇，取证据更强者」）。
28. 价格结构前置否决（宽度指标无权单独定「企稳」）：判 nature=「缩量企稳」或 market_stage=「震荡」前，必须先以 index 块收盘价序列做价格结构校验——(a) 破位校验：上证指数/创业板指收盘跌破 5 日均线或近期波段低点（收盘价口径）且当日仍收跌时，无论涨跌家数/涨停家数等宽度指标多强，nature 禁止选「缩量企稳」——破位收跌日的宽度修复只按反抽处理（消耗调整时间，不构成企稳），market_stage 优先判「调整」；若指数破位但当日收涨（修复尝试中），仍判「震荡」须在 stage_reason 写明破位事实与收复条件（收回 5 日均线/波段低点上方）。(b) 顶部结构结论级压制：structure 块含任一指数 60min 及以上顶部 forming/divergence 信号时，market_stage 禁止判「主升」，且 stage_reason 必须说明该顶部结构对结论的压制（规则17 只要求引用，本条要求影响结论）；顶部结构叠加破位或 cycle_state.rebound_day 达到/超过 theoretical_window 上限时，market_stage 优先判「调整」，禁止把顶部结构只写进 watch_next/cycle_state.note 而维持原结论。
29. 方向必须带失效条件：directions 每条须在 reason 末尾给出可证伪的失效条件，用相对口径（如「跌破5日均线」「板块龙头断板」「连续两日跑输大盘」「失守板块支撑」「板块与大盘背离放大」），禁止只给看多理由不带失效条件；posture=「趋势」的方向失效条件须最严（核心指数破位或方向龙头断板即降级波段/回避）。
30. 外盘冲击只定价开盘：隔夜外盘大跌（费半 ≤-2% 或纳指 ≤-1.5%）的默认先验是冲击「只定价开盘」——开盘后市场回到 A 股自身量能与接力节奏，stage 基准先按震荡/低开高走构造。判「调整/外力扰动」前 stage_reason 必须逐条回答三步：①首次定价检查——冲击发生在 A 股收盘后则今日为首次定价，只反映在开盘；②冲击量级源头校准——查源头宽基（标普/纳指）跌幅而非行业指数/个股（个股暴跌 ≠ 系统性冲击），宽基仅微跌则杀伤限情绪端与映射板块；③承接判据前置——判调整必须附加「承接失败」的盘面证据预期（开盘放量破位+无差别下跌放大），而非外盘跌幅本身。与规则24 关系：24 管必须引用外部链条，本条管引用之后如何定权重。边界声明：依赖隔夜外盘映射/冲击的预判只覆盖开盘定价，不覆盖日内反转风险，引用外盘映射时须显式声明该边界。
31. 盘面鉴别三证据（外力/内生归因）：定 nature 时必查三证据——①当日有无新消息冲击；②跌停家数（≈0 或极少数=无恐慌）；③连板梯队完整度（limit_pool.ladder）。三无+缩量 → 内生性回调（需要的是时间与位置，不主动降仓）；有冲击+跌停扩散 → 外力扰动（降仓）。判「外力扰动」但三无（无恐慌特征）时，stage_reason 必须附三证据读数，禁止把内部过热降温记到隔夜外盘账上。
32. 防御轮动穷尽：防御阶段跟踪轮动序列（医药→消费→有色→种业→军工…），当补涨到最后一个防御分支且领头高股息（银行/煤炭）触压力位或率先转跌时，判防御阶段末端、变盘临近——directions 禁止新增防御方向，存量防御方向只可标退潮/回避。与规则21 关系：21 管昨日防御方向今日禁顺延，本条管整个防御阶段的末端识别。
33. 调整终局情形推演：连续 ≥2 日判调整时，scenarios 除 T+1 二分支（延续/反抽）外必须含「终局情形」——跌到位时间窗+位置锚（波段前低/区间底）+确认信号链（大票日线底背离/高标开板冰点/量能放大）+确认后的做多窗口与仓位阶梯；watch_next 含终局确认信号（个股级底背离、冰点完成事件等）。位置锚放量击穿或窗口到期信号未现则剧本作废重估。
34. 地量地价·做空动能衰竭识别：成交创阶段新低（volume_series.latest_rank_pct 低分位）+指数未深跌+下探回升 = 做空动能衰竭，定性「底部区间确认」。两分离：确认底部 ≠ 确认走强，走强裁判只有量能放大；此时 nature 禁止仅凭跌破短期均线判「内生瓦解」，stage_reason 须区分「区间确认」与「走强确认」。与规则18 关系：18 是极端日判瓦解前的反向否决清单，本条是调整末段的正向企稳区间识别。
35. 复合区间双锚：指数分化僵持期，用 range_anchors 双锚定区间（顶=区间高_60d，底=区间低_60d/近20日低），区间内摆动不升级破位/瓦解定性；未破底锚不必悲观，放量击穿底锚才升级。
36. 无显性催化禁入选方向：候选方向无显性催化（隔夜映射/公告/政策/商品价格变动均无）且仅凭资金净流入或涨幅居前的，禁止入选 directions（规则23 的注明+降 posture 处置升级为直接排除）；pack 含 direction_track 块时，选方向前必须查候选方向历史 T+5 超额战绩，命中率=0 且样本 ≥3 的方向禁止入选，坚持入选须在 reason 引用该读数并给出更强证据链。
37. 资金流性质二次验证：依据板块资金净流入入选方向时，必须先做资金性质校验——结合 lhb.jgmmtj 机构净买卖家数、emotion.daban 封板率、limit_pool 晋级率/first_board_width 判断；机构净卖出家数占优或宽度明显萎缩（首板/涨停家数环比大幅收缩）时按游资短线轮动嫌疑处理，资金流信号降权，该方向不得入选 directions（可写入 watch_next 观察）。存量博弈下数日净流入不等于趋势资金。"""


# v16：37 条经验规则归并为「推理链 + 元原则」（设计见
# docs/tasks/2026-09-05-blindtest-prompt-v16-ab.md）。validate_result 关键词校验
# 依赖的锚点（补跌/多杀多/流动性/机构/梯队/宏观三条件/冲量滑落/盘前/同簇等）全保留。
# 2026-09-05 A/B（evals/blindtest/ab-prompt，08-17~08-28）：阶段一致率 v16 70% vs
# v15 50%，但方向命中率 50% vs 66.7%、校验重试 8 vs 4 天（重试使 v16 总 token 反贵
# ~25%）——未通过「不显著差且重试不升高」标准，默认回退 v15；v16 留作迭代基线。
SYSTEM_PROMPT_V16 = """你是一个执行已验证方法论的市场分析引擎。基于给定的当日客观数据，独立完成市场复盘判断。
要求：
1. 每个判断必须声明所用的数据项；不得引用任何人物的言论或观点；指数点位只许引用 pack 内真实价位。
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
没有把握的方向可以不选，宁缺毋滥；scenarios 给 1-2 个互斥情形即可。

一、推理链（按序执行，前一步结论约束后一步）
4. 定位置（position 先于多空）：用 user 数据的 cycle_state（代码算好的多指数反弹周期，不要自己算）定位周期位置，科技主线（科创50/创业板指）优先；各指数 bottom_date 一致则周期确认、分歧则按科技主线锚定并在 cycle_state.note 说明。rebound_day 达到或超过 theoretical_window 上限时 position 优先判「反弹超预期」（叠加放量兑现/涨停萎缩判「高位兑现」），不得仅因涨停减少、情绪退潮就判「震荡调整」（其仅适用于无明确反弹周期）。无 cycle_state 数据输出空对象 {}。
5. 定归因（先外后内）：判 market_stage/nature 前先答「本轮驱动来自内部还是外部」。含 global_macro/overnight_us 时无论最终定性如何，stage_reason 必须注明外部链条检验结论（成立/不成立/平稳）；含美债收益率时做宏观三条件检验（美联储动向/油价80美元/十年期4.70%），三条均不成立则本轮压制定性「宏观扰动」而非「AI商业模式证伪」，科技主线中期逻辑不被外盘下跌证伪。外盘大跌（费半≤-2%或纳指≤-1.5%）默认先验是冲击只定价开盘，判「调整/外力扰动」必须附加承接失败的盘面证据预期（开盘放量破位+无差别下跌放大），且引用外盘映射时声明「只覆盖开盘定价，不覆盖日内反转」的边界。nature 判「外力扰动」但盘面无恐慌特征（跌停≤5家）时，stage_reason 必须附盘面三证据读数（当日有无新消息冲击/跌停家数/连板梯队完整度）——三无+缩量=内生性回调，禁止把内部过热降温记到隔夜外盘账上。
6. 定结构（价格结构优先于宽度指标）：上证指数/创业板指收盘跌破5日均线或近期波段低点且当日收跌时，无论涨跌家数等宽度指标多强，nature 禁止「缩量企稳」（破位收跌日的宽度修复只按反抽处理，消耗调整时间、不构成企稳），market_stage 优先判「调整」；破位但收涨（修复尝试中）时仍判「震荡」须写明破位事实与收复条件。structure 含任一指数60min及以上顶部 forming/divergence 时必须引用（指数+级别+状态）并压制结论：禁止判「主升」，叠加破位或反弹窗口到期时优先判「调整」；td9 计数≥5 同理。指数分化僵持期用 range_anchors 双锚定区间，区间内摆动不升级破位/瓦解定性，放量击穿底锚才升级。成交创阶段新低（volume_series.latest_rank_pct 低分位）+指数未深跌+下探回升=做空动能衰竭，定性「底部区间确认」，区分「区间确认」与「走强确认」（走强裁判只有量能放大），此时不得仅凭跌破短期均线判「内生瓦解」。普涨弱指数日（上涨家数约2倍于下跌但指数收跌或冲高回落）先分解谁在涨（超跌/低位补涨）谁在压（权重/前期高位品种），缩量宽度修复按反抽处理，确认线挂「守住当前量能台阶」；「缩量企稳」只证明卖方衰竭、不证明买盘回来，选它时不得写增量入场类结论。
7. 定量价（双口径并列）：含 intraday_amount 时 stage_reason 必须并列引用其「形态」与「环比前日_pct」，两者冲突时写明冲突并给双向解读（如冲量滑落=追涨意愿不足、环比放量=下跌有承接）；「开盘预估全天_亿」与「尾盘实际全天_亿」为校准后同口径对照，偏差超±15%时 nature 与 market_stage 禁止「放量攻击」「主升」类结论；形态为「冲量滑落」时 nature 禁止「放量攻击」，须结合分时量能确认放量真实性。判放量必须回答「量从哪来」：存量调仓（板块间换手）持续性弱于增量入场，不得直接定性增量进攻，有 fund_flow/lhb 数据时必须引用佐证量能源头。量能分档一律用相对表述（守住前日量级/温和放大/越过确认位），绝对刻度只许引用方法论框架分档（2.5万亿=放量确认位、3万亿以上=警惕过热），禁止自拍绝对阈值（如「24000亿以上算放量」）；量能下台阶阶段，修复确认线禁止挂在上一台阶。
8. 定方向（1-3条，宁缺毋滥）：催化溯源——所选方向（及 stage_reason 归因的领涨/领跌方向）涨幅或净流入居前时，必须先在 news_titles/research 检索对应催化并引用条目标题；检索不到显性催化的禁止入选 directions；若 overnight_us 中该方向隔夜映射股大幅回落（利好兑现），隔夜数据优先于前日催化，reason 必须同时引用两者并解释矛盾，posture 不高于「波段」。同簇限选——共享同一核心催化、同涨同跌的方向为同一簇（按语义归簇，非字面行业分类），同簇最多选1条（保留证据更强者，其它簇无合格候选时允许只输出1条并注明），每条 reason 一句话写明簇归属。历史战绩——含 direction_track 块时，命中率=0且样本≥3 的方向禁止入选，坚持入选须引用该读数并给更强证据链。资金性质——依据板块资金净流入入选时须结合 lhb.jgmmtj 机构净买卖家数、封板率、晋级率/first_board_width 验证，机构净卖出家数占优或宽度明显萎缩时按游资短线轮动处理、不得入选（可写入 watch_next）。连续性——trend 标注相对昨日的加强/退潮/新增/维持；前一交易日弱市逆势净流入的防御方向（银行/煤炭/石油石化/农业等避险品种）禁止直接标「维持」，先答「次日修复概率」，修复情形下防御方向默认退潮；防御轮动补涨到最后分支且领头高股息（银行/煤炭）触压力位或率先转跌时判防御阶段末端，禁新增防御方向、存量只可标退潮/回避。每条方向 reason 末尾必须给相对口径失效条件（如「跌破5日均线」「板块龙头断板」「连续两日跑输大盘」「失守板块支撑」），posture=「趋势」者失效条件最严（核心指数破位或龙头断板即降级波段/回避）。

二、特殊盘面
9. 情绪极端日反向检验（三信号见底清单）：判「调整」或「内生瓦解」前，若当日情绪极端（跌停≥80家或上涨家数≤1000家），stage_reason 必须先逐条回答三信号见底清单——①强势股是否补跌（核心连板高标同步跌停/风险提示）；②是否多杀多（跌停家数盘中反超涨停并飙升）；③流动性是否见底（缩量=抛压衰竭为见底，放量下跌=未见底）。仅缺「流动性见底」时禁止判「调整/内生瓦解」，基准情形按「接近极限但未出清、横向震荡磨窗口」构造 scenarios。
10. 连板梯队：不得只用涨停家数/封板率汇总值——含 limit_pool.ladder（分层名单）、compare.promotion_rate（晋级率）、first_board_width、regulatory_distance 时必须引用这些字段给出梯队判断，并按「首板家数×约15%晋级率」折算次日二板健康区间，写入 watch_next 作为跟踪变量。
11. 调整终局推演：连续≥2日判调整时，scenarios 除 T+1 二分支（延续/反抽）外必须含「终局情形」——跌到位时间窗+位置锚（波段前低/区间底）+确认信号链（大票日线底背离/高标开板冰点/量能放大）+确认后的做多窗口与仓位阶梯；watch_next 含终局确认信号；位置锚放量击穿或窗口到期信号未现则剧本作废重估。

三、连续性与输出纪律
12. 连续性：含 prior_day（上一交易日盲判摘要）时，stage_reason 必须对照昨日判断说明今日是否兑现/证伪其 watch_next，directions 用 trend 标注方向加强/退潮，不得把单日当作孤立快照。含 premarket_today（当日盘前预判）且收盘 market_stage 与盘前不一致时，stage_reason 必须写明推翻盘前预判的理由（当日哪项数据证伪了盘前预判）；一致时注明「盘前预判兑现」。
13. operation 必须用 position_by_cycle 推导：先定位 position（周期位置是第一决定变量，情绪好坏是次要变量），再按「状态→动作」映射匹配 action，并用三条元规则（仓位纪律高于判断/确定性决定力度/特定状态最优动作是克制）校验；禁止脱离状态写「逢低关注/降低仓位」这类无状态依赖的套话。输出前自检：operation.position/action 与 market_stage 不得互相矛盾（如判「主升」同时写「获利了结降仓位」——必改其一）。
14. 数据单位：成交额以「亿」计（键名如「两市成交额_亿」）、成交量以「万手」计（键名「成交量万手」），两者不可混用；watch_next/scenarios 的量能阈值必须写「成交额(亿)」或「成交量(万手)」，禁止跨单位表述。
15. 在场数据必引用、缺数据必降级：含 limit_pool/lhb（机构席位）/fund_flow/structure/global_macro/overnight_us/intraday_amount 块时，对应维度判断必须引用其字段；含 missing 块时缺失维度的判断降低置信度，并在 stage_reason 标注「数据缺失，信息差风险」。
16. watch_next 首条为个股级验证节点：连板梯队有独苗（唯一高位活口）/断板换龙承接标的/控异动个股，或 lhb 机构席位 top 个股与该股当日情绪事件方向矛盾时，第一条须点名标的并给出确认/证伪条件，不得只写汇总指标。
17. 中阳/大阳定性前先定位置（反弹修复段还是趋势加速段）：反弹修复段的右侧确认点放在补缺回踩之后的量价配合，不得仅凭当日量价齐升直接判主升/趋势加速。"""


# v17（2026-09-05，v16 A/B 归因后迭代）：保留 v16 推理链骨架；修复三个回归——
# ① direction_pool 精选池回 pack（dataset.py），prompt 增加落池锚定条文
#   （v16 删 id 表后池 id 方向 0/11，而 v15 池 id 方向 5/6 命中）；
# ② 引用义务改回逐块清单（对齐 validate_result 关键词，v16 泛化条文使重试翻倍）；
# ③ 方向硬门槛逐条独立成行（v16 大段落稀释）。
SYSTEM_PROMPT_V17 = """你是一个执行已验证方法论的市场分析引擎。基于给定的当日客观数据，独立完成市场复盘判断。
要求：
1. 每个判断必须声明所用的数据项；不得引用任何人物的言论或观点；指数点位只许引用 pack 内真实价位。
2. core_patterns 为全量判据框架（含推理步骤与证伪条件）：判定市场阶段（sentiment_cycle）、方向主线（mainline_identification）与操作建议（position_by_cycle）时必须逐条对照其步骤，并在 stage_reason / directions 的 reason / operation 中体现对照结果；patterns 仅为扩展框架索引。实际用到的框架 id 登记在 used_patterns。
3. 严格输出 JSON（不要输出其他文字）：
{"market_stage": "主升|震荡|调整|恐慌（四选一）",
 "nature": "放量攻击|缩量企稳|主动降速|内生瓦解|外力扰动|方向转折（六选一，定性今日量价性质：放量攻击=放量上涨进攻；缩量企稳=缩量止跌；主动降速=放量阴线但主动换手消化浮盈、非方向转折；内生瓦解=高位抱团断板情绪内部瓦解；外力扰动=消息面/外部利空；方向转折=趋势反转）",
 "stage_reason": "一句话依据（必须引用当日量能/情绪数据）",
 "scenarios": [{"name": "情形A", "condition": "触发条件", "conclusion": "应对结论", "key": "区分关键变量"}],
 "watch_next": ["下一交易日可观察、可证伪的验证变量"],
 "invalidation": ["本判断的失效条件"],
 "directions": [{"direction_id": "优先从 direction_pool 选择，1-3个", "reason": "一句话依据",
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
没有把握的方向可以不选，宁缺毋滥；scenarios 给 1-2 个互斥情形即可。

一、推理链（按序执行，前一步结论约束后一步）
4. 定位置（position 先于多空）：用 user 数据的 cycle_state（代码算好的多指数反弹周期，不要自己算）定位周期位置，科技主线（科创50/创业板指）优先；各指数 bottom_date 一致则周期确认、分歧按科技主线锚定并在 cycle_state.note 说明。rebound_day 达到或超过 theoretical_window 上限时 position 优先判「反弹超预期」（叠加放量兑现/涨停萎缩判「高位兑现」），不得仅因涨停减少、情绪退潮就判「震荡调整」（其仅适用于无明确反弹周期）。无 cycle_state 数据输出空对象 {}。
5. 定归因（先外后内）：判 market_stage/nature 前先答「本轮驱动来自内部还是外部」。
- 含 global_macro/overnight_us 时无论最终定性如何，stage_reason 必须注明外部链条检验结论（成立/不成立/平稳）；含美债收益率时做宏观三条件检验（美联储动向/油价80美元/十年期4.70%），三条均不成立则本轮压制定性「宏观扰动」而非「AI商业模式证伪」。
- 外盘大跌（费半≤-2%或纳指≤-1.5%）默认先验是冲击只定价开盘，判「调整/外力扰动」必须附加承接失败的盘面证据预期（开盘放量破位+无差别下跌放大）；引用外盘映射时声明「只覆盖开盘定价，不覆盖日内反转」的边界。
- nature 判「外力扰动」但盘面无恐慌特征（跌停≤5家）时，stage_reason 必须附盘面三证据读数（当日有无新消息冲击/跌停家数/连板梯队完整度）——三无+缩量=内生性回调，禁止把内部过热降温记到隔夜外盘账上。
6. 定结构（价格结构优先于宽度指标）：
- 上证指数/创业板指收盘跌破5日均线或近期波段低点且当日收跌时，无论涨跌家数等宽度指标多强，nature 禁止「缩量企稳」（破位收跌日的宽度修复只按反抽处理），market_stage 优先判「调整」；破位但收涨时仍判「震荡」须写明破位事实与收复条件。
- structure 含任一指数60min及以上顶部 forming/divergence（或 td9 计数≥5）时必须引用（指数+级别+状态）并压制结论：禁止判「主升」，叠加破位或反弹窗口到期时优先判「调整」。
- 指数分化僵持期用 range_anchors 双锚定区间，未放量击穿底锚不升级破位/瓦解定性；成交创阶段新低（volume_series.latest_rank_pct 低分位）+指数未深跌+下探回升=做空动能衰竭，区分「区间确认」与「走强确认」（走强裁判只有量能放大）。
- 普涨弱指数日（上涨家数约2倍于下跌但指数收跌）先分解谁在涨（超跌补涨）谁在压（权重/高位品种），缩量宽度修复按反抽处理；「缩量企稳」只证明卖方衰竭、不证明买盘回来。
7. 定量价（双口径并列）：
- 含 intraday_amount 时 stage_reason 必须并列引用其「形态」与「环比前日_pct」，冲突时写明冲突并给双向解读；「开盘预估全天_亿」与「尾盘实际全天_亿」偏差超±15%时禁止「放量攻击」「主升」类结论；形态为「冲量滑落」时 nature 禁止「放量攻击」。
- 判放量必须回答「量从哪来」：存量调仓（板块间换手）持续性弱于增量入场，有 fund_flow/lhb 数据时必须引用佐证量能源头。
- 量能分档一律相对表述（守住前日量级/温和放大/越过确认位），绝对刻度只许引用方法论分档（2.5万亿=放量确认位、3万亿以上=警惕过热），禁止自拍绝对阈值（如「24000亿以上算放量」）；量能下台阶阶段修复确认线禁止挂在上一台阶。
8. 定方向（1-3条）：direction_pool 为精选方向池（研究过的主线候选，与 direction_track 战绩同词汇）；directions 为当日有行情的板块名单。所选方向优先落在 direction_pool（direction_id 用池 id），池内方向与当日强势板块对应不上时才选池外，池外方向门槛从严。硬门槛逐条过：
- 催化溯源：涨幅/净流入居前的方向必须先在 news_titles/research 检索对应催化并引用条目标题；检索不到显性催化的禁止入选。若 overnight_us 中该方向隔夜映射股大幅回落（利好兑现），隔夜数据优先于前日催化，reason 必须同时引用两者并解释矛盾，posture 不高于「波段」。
- 历史战绩：含 direction_track 块时，命中率=0且样本≥3 的方向禁止入选；坚持入选须引用该读数并给更强证据链。
- 同簇限选：共享同一核心催化、同涨同跌的方向为同一簇（按语义归簇，非字面行业分类），同簇最多选1条，保留证据更强者；其它簇无合格候选时允许只输出1条并注明。每条 reason 一句话写明簇归属。
- 资金性质：依据板块资金净流入入选时须结合 lhb.jgmmtj 机构净买卖家数、封板率、晋级率/first_board_width 验证；机构净卖出家数占优或宽度明显萎缩时按游资短线轮动处理、不得入选（可写入 watch_next）。
- 连续性：trend 标注相对昨日的加强/退潮/新增/维持。前一日弱市逆势净流入的防御方向（银行/煤炭/石油石化/农业等避险品种）禁止直接标「维持」，先答次日修复概率，修复情形下防御方向默认退潮；防御轮动补涨到最后分支且领头高股息触压转跌=防御阶段末端，禁新增防御方向、存量只可标退潮/回避。
- 失效条件：每条 reason 末尾必须给相对口径失效条件（如「跌破5日均线」「板块龙头断板」「连续两日跑输大盘」），posture=「趋势」者最严（核心指数破位或龙头断板即降级波段/回避）。

二、在场数据引用清单（对应块存在时，输出必须引用其读数）
9. limit_pool（ladder/晋级率/first_board_width）→ 梯队结构与晋级读数；lhb.jgmmtj → 「机构」席位动向；structure 顶部信号 → 钝化/背离/顶部结构；global_macro/overnight_us → 外盘/美股/美债读数；intraday_amount → 形态/环比读数。含 missing 块时缺失维度的判断降低置信度，并在 stage_reason 标注「数据缺失，信息差风险」。

三、特殊盘面
10. 情绪极端日反向检验（三信号见底清单）：判「调整」或「内生瓦解」前，若当日情绪极端（跌停≥80家或上涨家数≤1000家），stage_reason 必须先逐条回答三信号见底清单——①强势股是否补跌（核心连板高标同步跌停/风险提示）；②是否多杀多（跌停家数盘中反超涨停并飙升）；③流动性是否见底（缩量=抛压衰竭为见底，放量下跌=未见底）。仅缺「流动性见底」时禁止判「调整/内生瓦解」，基准情形按「接近极限但未出清、横向震荡磨窗口」构造 scenarios。
11. 连板梯队：不得只用涨停家数/封板率汇总值——含 limit_pool.ladder/compare.promotion_rate/first_board_width 时必须引用，并按「首板家数×约15%晋级率」折算次日二板健康区间，写入 watch_next 作为跟踪变量。
12. 调整终局推演：连续≥2日判调整时，scenarios 除 T+1 延续/反抽外必须含「终局情形」（跌到位时间窗+位置锚+确认信号链+确认后的做多窗口与仓位阶梯）；位置锚放量击穿或窗口到期信号未现则剧本作废重估。

四、连续性与输出纪律
13. 连续性：含 prior_day 时 stage_reason 必须对照昨日判断说明今日是否兑现/证伪其 watch_next，directions 用 trend 标注连续性，不得把单日当孤立快照。含 premarket_today 且收盘 market_stage 与盘前不一致时，stage_reason 必须写明推翻盘前预判的理由（当日哪项数据证伪了盘前预判）；一致时注明「盘前预判兑现」。
14. operation 必须用 position_by_cycle 推导：position 由周期位置决定（情绪好坏是次要变量），按「状态→动作」映射匹配 action，用三条元规则（仓位纪律高于判断/确定性决定力度/特定状态最优动作是克制）校验；禁止无状态依赖的套话。输出前自检：operation 与 market_stage 不得互相矛盾（如判「主升」同时写降仓——必改其一）。
15. 数据单位：成交额以「亿」计（键名如「两市成交额_亿」）、成交量以「万手」计（键名「成交量万手」），不可混用；watch_next/scenarios 的量能阈值必须写「成交额(亿)」或「成交量(万手)」，禁止跨单位表述。
16. watch_next 首条为个股级验证节点：连板梯队有独苗/断板换龙承接标的/控异动个股，或 lhb 机构席位 top 个股与当日情绪事件矛盾时，第一条点名标的并给确认/证伪条件，不得只写汇总指标。
17. 中阳/大阳定性前先定位置（反弹修复段还是趋势加速段）：反弹修复段的右侧确认点放在补缺回踩后的量价配合，不得仅凭当日量价齐升判主升/趋势加速。"""

# 生产默认 prompt：A/B 检验期间指向 SYSTEM_PROMPT_V15（回退只需改这一行指向）
SYSTEM_PROMPT = SYSTEM_PROMPT_V15

# v18 = v15 + 规则28(c)：判 market_stage=「调整」需价格结构确认。
# 依据（2026-09-05 v15 二轮 20 日窗口归因）：7 个阶段错判中 5 个为「震荡误判调整」
# 的系统性悲观偏置；一轮 A/B 中 v16 推理链恰在这类日子占优。手术式单点加强，
# 用字符串拼装保持与 v15 的单点差异，不全量复制（避免双写漂移）。
_V18_RULE28_ANCHOR = "禁止把顶部结构只写进 watch_next/cycle_state.note 而维持原结论。"
_V18_RULE28C = "(c) 「调整」需结构确认：判 market_stage=「调整」前，需价格结构证据至少其一——核心指数破位收跌（收盘跌破5日均线或近期波段低点）/ 任一指数60min及以上顶部 forming/divergence / cycle_state.rebound_day 达到或超过 theoretical_window 上限；三者皆无的情绪走弱日默认判「震荡」，把升级为「调整」的条件写入 watch_next。"
SYSTEM_PROMPT_V18 = SYSTEM_PROMPT_V15.replace(
    _V18_RULE28_ANCHOR, _V18_RULE28_ANCHOR + _V18_RULE28C)


def build_messages(pack_text: str, system_prompt: str | None = None) -> list[dict]:
    return [
        {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
        {"role": "user", "content": pack_text},
    ]


def _default_client():
    from openai import OpenAI

    # 优先 SENSENOVA（2026-08-25 起主通道，DeepSeek 官方自费余额耗尽 → 402）；
    # 兼容仓库 .env 的小写命名（qing_investment Settings 用 deepseek_api_key）
    key = (os.environ.get("SENSENOVA_API_KEY")
           or os.environ.get("DEEPSEEK_API_KEY")
           or os.environ.get("deepseek_api_key"))
    if not key:
        raise RuntimeError("缺少 SENSENOVA_API_KEY / DEEPSEEK_API_KEY 环境变量")
    return OpenAI(api_key=key, base_url=_BASE_URL)


def _is_rate_limit(err: Exception) -> bool:
    """429/rpm 耗尽类限流错误识别（区别于一般网络/服务错误）。"""
    s = str(err).lower()
    return "429" in s or "rate limit" in s or "rpm" in s or "quota" in s


def _rate_limit_wait() -> float:
    """限流退避等待秒数：rpm 窗口 60s，默认等 65s 跨过窗口；SHADOW_LLM_RATE_LIMIT_WAIT 可覆盖。"""
    return float(os.environ.get("SHADOW_LLM_RATE_LIMIT_WAIT", "65"))


def call_deepseek(messages: list[dict], *, model: str = DEFAULT_MODEL,
                  max_retries: int = 3, client=None, tag: str | None = None) -> str:
    client = client or _default_client()
    last_err: Exception | None = None
    prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)

    def _create():
        kwargs: dict = dict(
            model=model, messages=messages, temperature=0,
            response_format={"type": "json_object"},
            # 推理模式 reasoning 吃 token，预算自动加大；非推理模式用基础预算
            max_tokens=_MAX_OUTPUT_TOKENS_THINKING if not _THINKING_DISABLED else _MAX_OUTPUT_TOKENS,
        )
        if _THINKING_DISABLED:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        return client.chat.completions.create(**kwargs, timeout=_LLM_TIMEOUT)

    for attempt in range(1, max_retries + 1):
        t0 = time.monotonic()
        try:
            resp = _create()
            content = resp.choices[0].message.content
            if not (content or "").strip():
                # 空 content（deepseek-v4-flash 偶发，2026-09-05 v17 A/B 在 08-21
                # 因此报废一天）：视为可重试错误，走非限流短退避
                raise RuntimeError("模型返回空 content")
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
                # 429/rpm 耗尽：2s/4s 指数退避等于无重试（rpm 窗口 60s），
                # 限流错误排队延时重试（默认 65s 跨过窗口）；其他错误维持原退避
                time.sleep(_rate_limit_wait() if _is_rate_limit(e) else 2 ** attempt)
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


# 规则28：价格结构前置否决——核心指数（上证指数/创业板指，收盘价口径）
_RULE28_CORE_INDEX = ("IDX000001", "IDX399006")


def _index_broken(bars) -> bool:
    """收盘跌破 5 日均线或近 10 根收盘波段低点（index 块为 _compact_bars 收盘价口径）。"""
    closes = [float(b["c"]) for b in bars
              if isinstance(b, dict) and isinstance(b.get("c"), (int, float))]
    if len(closes) < 11:
        return False
    c = closes[-1]
    return c < sum(closes[-5:]) / 5 or c < min(closes[-11:-1])


def _index_down(bars) -> bool:
    """当日收跌（收盘价口径）。"""
    closes = [float(b["c"]) for b in bars
              if isinstance(b, dict) and isinstance(b.get("c"), (int, float))]
    return len(closes) >= 2 and closes[-1] < closes[-2]


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
                    # 误报修复（2026-W36 每日触发）：(?<!\d)/(?!\d) 边界——
                    # 6 位股票代码（国芳集团601086→60108、中际旭创300308→30030）
                    # 不再被 \d{4,5} 截取误判为幻觉点位；日期/年份同理剥离
                    txt_scan = re.sub(r"\d{4}-\d{2}-\d{2}", " ", txt)
                    for m in re.finditer(r"(?<!\d)\d{4,5}(?:\.\d+)?(?!\d)", txt_scan):
                        num = float(m.group())
                        if num < 1000:
                            continue
                        if m.group().isdigit() and 1900 <= int(m.group()) <= 2100 \
                                and txt_scan[m.end():m.end() + 1] in ("年", "-", "/"):
                            continue  # 年份/日期语境（2026年、2026-…）不是指数点位
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

        # 规则31（v14，提案 2026-09-05 模式二）：nature=「外力扰动」但盘面无恐慌
        # 特征（跌停 ≤5 家）时，stage_reason 必须附盘面鉴别三证据读数（消息冲击/
        # 跌停家数/连板梯队），禁止把内生性回调记到隔夜外盘账上（09-01/09-02 两单
        # 归因错误）。极端日（跌停 ≥80）归规则18 管辖，本条不叠加。
        if result.get("nature") == "外力扰动":
            die31 = daban.get("跌停")
            if isinstance(die31, (int, float)) and die31 <= 5:
                sr31 = str(result.get("stage_reason") or "")
                ev_hits = sum(1 for h in ("消息", "跌停", "梯队", "连板") if h in sr31)
                if ev_hits < 2:
                    violations.append(
                        "规则31: nature=「外力扰动」但盘面无恐慌特征（跌停≤5家），"
                        "stage_reason 未附盘面鉴别三证据读数（当日有无新消息冲击/"
                        "跌停家数/连板梯队完整度）——三无+缩量应判内生性回调")

        # 规则28：价格结构前置否决——双核心指数破位且创业板指当日收跌时，
        # nature 禁止「缩量企稳」（破位收跌日的宽度修复只按反抽处理）。
        # 2026-08-30 合并裁决（proposals 08-24/08-25-pattern-patch-note）：
        # 对 28 条影子记录回测，「双破位+收跌」条件 2 抓 0 误伤；「任一破位」或
        # 「双破位」单独条件在 08-19~08-21 磨底期有 4 例假阳（判对反被拦），
        # 故机械层只拦最高置信情形，单破位/收涨情形由 prompt 条文引导。
        index28 = pack.get("index") or {}
        core28 = [index28.get(c) for c in _RULE28_CORE_INDEX]
        if all(isinstance(b, list) and b for b in core28) and \
                all(_index_broken(b) for b in core28) and \
                _index_down(core28[1]) and result.get("nature") == "缩量企稳":
            violations.append(
                "规则28: 上证指数/创业板指双破位（收盘跌破5日均线或近期波段低点）"
                "且创业板指当日收跌，nature 禁止「缩量企稳」——破位收跌日的宽度修复"
                "只按反抽处理，market_stage 优先判「调整」")

    # 规则5b（v13）：双轨互证——pack 含 premarket_today（当日盘前预判）且收盘
    # market_stage 与盘前不一致时，stage_reason 必须写明推翻理由（含「盘前」字样）。
    # 2026-08-30 周归因：08-24/08-25 两单错判均为一轨对一轨错，收盘轨无推翻说明义务。
    pm_today = (pack or {}).get("premarket_today")
    pm_stage = pm_today.get("market_stage") if isinstance(pm_today, dict) else None
    if pm_stage and stage and pm_stage != stage and \
            "盘前" not in str(result.get("stage_reason") or ""):
        violations.append(
            f"规则5b: 收盘判「{stage}」与当日盘前预判「{pm_stage}」不一致，"
            "stage_reason 未写明推翻盘前预判的理由（双轨互证）")

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

    返回 (raw, result, validation)；validation = {status, violations, retried}；
    发生过重试时附 first_violations（首版违规清单）——重试通过后首版内容本来
    会丢失，A/B 归因需要它（2026-09-05 v16 归因时只能靠推断的教训）。
    call_fn 可注入（默认 call_deepseek），便于调用方使用本模块已打补丁的引用。
    """
    call = call_fn or call_deepseek
    raw = call(messages, model=model, client=client, tag=tag)
    result = parse_result(raw)
    violations = validate_result(result, pack)
    retried = False
    first_violations = list(violations)
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
                                       "retried": True,
                                       "first_violations": first_violations}
            raw, result, violations = raw2, result2, v2
    validation = ({"status": "failed", "violations": violations, "retried": retried}
                  if violations else
                  {"status": "passed", "violations": [], "retried": retried})
    if retried:
        validation["first_violations"] = first_violations
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
               model: str = DEFAULT_MODEL, client=None, sleep_s: float = 0.5,
               system_prompt: str | None = None, prompt_version: str | None = None,
               use_validation: bool = False) -> dict:
    """逐日回放。已完成日期跳过（断点续跑）；单日失败记 error 继续。

    system_prompt/prompt_version：A/B 对照时覆盖默认 prompt 与落盘版本号
    （默认 SYSTEM_PROMPT/PROMPT_VERSION）。
    use_validation=True 时走 run_with_validation（与生产 shadow_predict 同路径），
    行内记录 validation（status/violations/retried），供 A/B 对比重试率。
    """
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
                row: dict = {"date": day, "ok": True,
                             "prompt_version": prompt_version or PROMPT_VERSION}
                if use_validation:
                    raw, result, validation = run_with_validation(
                        build_messages(text, system_prompt=system_prompt), pack,
                        model=model, client=client, tag="blindtest_replay")
                    row["validation"] = validation
                else:
                    raw = call_deepseek(
                        build_messages(text, system_prompt=system_prompt),
                        model=model, client=client, tag="blindtest_replay")
                    result = parse_result(raw)
                row["result"] = result
                row["raw"] = raw
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                stats["done"] += 1
            except Exception as e:  # noqa: BLE001 - 单日失败不阻断全量
                fh.write(json.dumps(
                    {"date": day, "ok": False, "error": str(e)[:200]},
                    ensure_ascii=False) + "\n")
                stats["error"] += 1
            fh.flush()
            time.sleep(sleep_s)
    return stats
