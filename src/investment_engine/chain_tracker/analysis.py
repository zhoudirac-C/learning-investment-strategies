"""LLM 5 步推理分析（T12）。

Prompt 按 docs/tasks/m0-chain-industry-tracking.md §3.4 的 UP 5 步推理框架：
确认真实性 → 供需结构 → 周期位置 → 受益标的 → 持续性/操作建议，
外加证伪条件检查与 verdict 归类（写入 processed_items.llm_verdict）。

Step 6（2026-08-31 演化能力）：顺带判断新信息是否给产业链【逻辑结构本身】
带来结构性增量（环节细化/新增节点/重心转移/thesis修正/证伪更新/跨链传导），
可选输出 logic_update 字段（默认 null）；语义校验与落账在
chain_tracker.evolution（提案制，人工 confirm 才应用，不自动改 chain.yaml）。
设计见 docs/superpowers/specs/2026-08-31-chain-logic-evolution-design.md。

LLM 通道优先级（2026-08-31 用户决策：跟随 Hermes 全局配置，不写死）：
1. CHAIN_TRACKER_LLM=glm 逃生口（配额故障时直走 GLM 省重试开销）
2. Hermes 全局模型配置——与 cron 调度器同一个 resolve_runtime_provider()
   解析 ~/.hermes/config.yaml，全局换模型本引擎自动跟随
3. .env sensenova 主通道（blindtest.replay.call_deepseek 默认）→ GLM 兜底
所有通道都经 call_deepseek（强制 JSON、重试、自动落账 log/llm_calls.jsonl）。
"""
from __future__ import annotations

import json

VERDICTS = ("confirmed", "strengthening", "weakening", "falsified", "irrelevant")
STAGE_CHANGES = ("unchanged", "forward", "backward")

_SYSTEM = (
    "你是产业链跟踪分析师，按 UP 的 5 步推理框架分析新信息对产业链的影响。"
    "只输出 JSON，不要输出任何其他内容。"
)

_USER_TMPL = """以下是产业链"{chain_name}"的当前状态和新信息。

【产业链当前状态】
产业逻辑：{thesis}
当前阶段：{current_stage}（置信度：{stage_confidence}）
阶段依据：{stage_evidence}
关键节点：{key_nodes}
时机建议：{timing}
证伪条件：{falsification}

【环节结构】（segment_id | 环节名 | 材料/产品）
{segments_text}

【标的映射】（已有标的，避免重复提议）
{mappings_text}

【新信息】（{n_items} 条）
{items_text}

请按 UP 的 5 步推理框架分析：

Step 1 - 确认真实性：
  这条信息是否确认/加强/削弱/证伪了产业链逻辑？
  至少两个独立来源同向才确认（如研报+公告同时指向）。

Step 2 - 分析供需结构：
  这条信息影响的是需求侧、供给侧还是技术升级？
  对产业链的哪个环节（上游/中游/下游）影响最大？

Step 3 - 对比历史周期位置：
  当前处于底部/启动/加速/见顶哪一阶段？
  与历史高点的差距有多大？（如价格/产能利用率/订单排期）

Step 4 - 筛选受益标的：
  按三条逻辑筛选：①高端承接（能吃下外溢需求）
  ②上游供货（面向大厂）③弹性最大（产能占比大、对涨价敏感）

Step 5 - 判断持续性并给出操作建议：
  当前阶段是否变化？（unchanged=不变/forward=推进/backward=回退）
  时机建议：现在该做哪个环节？
  - 阶段0-观察：不介入
  - 阶段1-启动期：可介入（右侧确认）
  - 阶段2-加速期：不追高，等分歧回踩
  - 阶段3-分歧期：等回踩确认
  - 阶段4-见顶期：退出
  同时检查证伪条件是否被触发；触发则 verdict=falsified 且 stage_change=backward。

  阶段变更硬约束（2026-08-31 回放校准加入）：
  - stage_change=forward 仅当新信息【直接命中本链关键节点】——即上面列出的
    关键节点/跟踪指标被新信息直接证实或推进（如本链跟踪"FR8价格"，新信息给出
    FR8 实际涨价）；泛化的行业情绪、同板块其他链条的利好、"业绩符合预期"类
    无增量表述，一律 unchanged。
  - stage_change=backward 仅当证伪条件被触发或关键节点明确恶化。

阶段枚举（new_stage 必须取其中之一）：
阶段0-观察 / 阶段1-启动期 / 阶段2-加速期 / 阶段3-分歧期 / 阶段4-见顶期

Step 6 - 产业链逻辑演化判断（可选，多数批次应输出 null）：
  这批信息是否给产业链【逻辑结构本身】带来结构性增量？（区别于 Step 5 的阶段变化）
  - refine_segment：某环节进一步细化/新增材料。detail: {{"segment_id": "上面环节结构的 id（新环节可自定 slug）", "segment_name": "新环节名（仅新环节必填）", "add_materials": [...]}}
  - add_node：出现本链未跟踪的新关键节点/新标的。detail: {{"metric": {{"metric": "...", "current": "...", "signal_direction": "..."}}, "stock": {{"code": "6位代码", "name": "...", "segment": "segment_id", "relation": "..."}}}}（metric/stock 至少其一）
  - focus_shift：受益重心在环节间结构性迁移（如上游→中游）。detail: {{"from_segment": "...", "to_segment": "...", "recommendation": "...", "next_trigger": "...", "risk": "..."}}
  - update_thesis：传导路径/产业逻辑本身被新证据修正。detail: {{"new_thesis": "..."}}
  - update_falsification：证伪条件需要新增。detail: {{"add": [...]}}
  - add_relation：发现与其他产业链的传导关系。detail: {{"target": "chain_id", "relation": "...", "note": "..."}}
  硬约束：
  - 只影响阶段/价格/进度判断的信息 → null（那是 Step 5 的输出）
  - 上述当前状态/环节结构/标的映射已包含的内容（重复已知逻辑）→ null
  - 单家公司孤立事件、无产业链结构含义 → null
  - 每批最多输出 1 条，取最重要的；没有结构性增量就输出 null

输出 JSON：
{{
  "step1_verification": {{"verified": true/false, "sources": [...], "confidence": "高/中/低"}},
  "step2_supply_demand": {{"driver": "需求/供给/技术", "affected_segment": "上游/中游/下游"}},
  "step3_cycle_position": {{"current_stage": "...", "distance_to_peak": "..."}},
  "step4_beneficiaries": [{{"code": "...", "name": "...", "logic": "高端承接/上游供货/弹性最大"}}],
  "step5_recommendation": {{"stage_change": "unchanged|forward|backward", "new_stage": "...", "timing": "...", "action": "..."}},
  "verdict": "confirmed|strengthening|weakening|falsified|irrelevant",
  "summary": "一句话结论（≤60字）",
  "logic_update": null 或 {{"change_type": "refine_segment|add_node|focus_shift|update_thesis|update_falsification|add_relation", "summary": "一句话（≤40字）", "detail": {{...按 change_type...}}, "rationale": "哪条信息推出（≤60字）", "confidence": "高/中/低"}}
}}

若这批信息与本产业链无关，verdict=irrelevant，stage_change=unchanged，logic_update=null，其余字段从简。
"""


def _fmt_key_nodes(chain: dict) -> str:
    lines = []
    for tm in chain.get("tracking_metrics") or []:
        lines.append(f"- {tm.get('metric')}: 当前 {tm.get('current')}"
                     f"（{tm.get('signal_direction')}）")
    return "\n".join(lines) or "（无）"


def _fmt_timing(chain: dict) -> str:
    t = chain.get("timing") or {}
    if isinstance(t, dict):
        return (f"当前建议={t.get('current_recommendation')}；"
                f"下一触发={t.get('next_trigger')}；风险={t.get('risk')}")
    return str(t)


def _fmt_segments(chain: dict) -> str:
    """环节结构一行一条：segment_id | 环节名 | 材料/产品（供 Step 6 引用 id）。"""
    lines = []
    for seg in chain.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        mats = "/".join(str(m) for m in seg.get("materials") or [])
        lines.append(f"- {seg.get('id')} | {seg.get('name')} | {mats or '-'}")
    return "\n".join(lines) or "（无）"


def _fmt_mappings(chain: dict) -> str:
    lines = []
    for m in chain.get("mappings") or []:
        if not isinstance(m, dict):
            continue
        lines.append(f"- {m.get('code')} {m.get('name')}"
                     f"（{m.get('segment') or '-'}，{m.get('relation') or '-'}）")
    return "\n".join(lines) or "（无）"


def format_items(items: list[dict], max_items: int) -> str:
    lines = []
    for it in items[:max_items]:
        src = {"report": "研报", "notice": "公告", "futures": "期货"}.get(
            it.get("source"), it.get("source"))
        meta = []
        if it.get("org"):
            meta.append(str(it["org"]))
        if it.get("stock_name"):
            meta.append(str(it["stock_name"]))
        if it.get("industry_name"):
            meta.append(str(it["industry_name"]))
        meta_s = f"（{'/'.join(meta)}）" if meta else ""
        lines.append(f"- [{src}] {it.get('title')}{meta_s} @ {it.get('published_at')}"
                     f" [info_id={it.get('info_id')}]")
    return "\n".join(lines)


def build_tracking_messages(chain: dict, items: list[dict],
                            *, max_items: int = 30) -> list[dict]:
    falsification = chain.get("falsification") or []
    user = _USER_TMPL.format(
        chain_name=chain.get("name"),
        thesis=chain.get("thesis"),
        current_stage=chain.get("current_stage") or "阶段0-观察",
        stage_confidence=chain.get("stage_confidence") or "中",
        stage_evidence=chain.get("stage_evidence") or "（无）",
        key_nodes=_fmt_key_nodes(chain),
        timing=_fmt_timing(chain),
        falsification="\n".join(f"- {f}" for f in falsification) or "（无）",
        segments_text=_fmt_segments(chain),
        mappings_text=_fmt_mappings(chain),
        n_items=len(items),
        items_text=format_items(items, max_items),
    )
    return [{"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user}]


def parse_analysis(raw: str) -> dict:
    """解析 LLM 输出；fence 容忍、枚举归一、非法 stage 变更拒绝。"""
    from investment_engine.industry_chain.schema import STAGE_LEVELS

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
    if not isinstance(data, dict):
        raise ValueError(f"输出非 JSON object: {raw[:80]!r}")

    if data.get("verdict") not in VERDICTS:
        data["verdict"] = "irrelevant"

    step5 = data.get("step5_recommendation")
    if not isinstance(step5, dict):
        step5 = {}
        data["step5_recommendation"] = step5
    if step5.get("stage_change") not in STAGE_CHANGES:
        step5["stage_change"] = "unchanged"
    if step5["stage_change"] != "unchanged" and step5.get("new_stage") not in STAGE_LEVELS:
        raise ValueError(f"阶段变更但 new_stage 非法: {step5.get('new_stage')!r}")
    return data


def _zhipu_client():
    """GLM fallback 通道（任务书 cheapest 档即 GLM-flash 级模型）。"""
    import os

    from openai import OpenAI

    key = os.environ.get("ZHIPU_API_KEY")
    if not key:
        raise RuntimeError("缺少 ZHIPU_API_KEY 环境变量")
    return OpenAI(api_key=key, base_url="https://open.bigmodel.cn/api/paas/v4")


_HERMES_CACHE: dict | None = None
_HERMES_TRIED = False


def _hermes_global() -> dict | None:
    """解析 Hermes 全局模型配置，返回 {api_key, base_url, model, source}。

    与 cron 调度器用同一个 resolve_runtime_provider()，全局换模型自动跟随。
    非 Hermes 环境或解析失败返回 None（调用方落 .env 通道）。
    进程内只解析一次（tick 进程短命，配置漂移由下一次 tick 感知）。
    """
    global _HERMES_CACHE, _HERMES_TRIED
    if _HERMES_TRIED:
        return _HERMES_CACHE
    _HERMES_TRIED = True
    import sys
    from pathlib import Path

    agent_pkg = Path.home() / ".hermes" / "hermes-agent"
    if not agent_pkg.is_dir():
        return None
    if str(agent_pkg) not in sys.path:
        sys.path.insert(0, str(agent_pkg))
    try:
        from hermes_cli.config import load_config
        from hermes_cli.runtime_provider import resolve_runtime_provider

        runtime = resolve_runtime_provider()
        model = (load_config().get("model") or {}).get("default")
    except Exception:  # noqa: BLE001 - Hermes 配置不可用不算错误
        return None
    if not runtime.get("api_key") or not runtime.get("base_url") or not model:
        return None
    _HERMES_CACHE = {"api_key": runtime["api_key"],
                     "base_url": runtime["base_url"], "model": str(model),
                     "source": runtime.get("source")}
    return _HERMES_CACHE


def default_llm_call(messages: list[dict], *, tag: str = "chain_tracker", **kw) -> str:
    import os

    from investment_engine.blindtest.replay import call_deepseek

    # CHAIN_TRACKER_LLM=glm 逃生口：跳过全部通道直走 GLM
    # （配额已知耗尽时省去每链 3 次失败重试的 ~14s 开销）
    if os.environ.get("CHAIN_TRACKER_LLM", "").lower() == "glm":
        return call_deepseek(messages, model="glm-4.7-flash",
                             client=_zhipu_client(), tag=f"{tag}:glm", **kw)

    # 主通道：Hermes 全局模型配置（跟随全局，不写死）
    g = _hermes_global()
    if g:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=g["api_key"], base_url=g["base_url"])
            return call_deepseek(messages, model=g["model"], client=client,
                                 tag=f"{tag}:hermes:{g['model']}", **kw)
        except RuntimeError:
            pass  # 全局通道故障 → 落 .env 通道

    # 兜底：.env sensenova → GLM（2026-08-31 前的主通道）
    try:
        return call_deepseek(messages, tag=tag, **kw)
    except RuntimeError:
        # sensenova 主通道 429/配额耗尽时回落 GLM（2026-08-31 实测 rpm exhausted）
        return call_deepseek(messages, model="glm-4.7-flash",
                             client=_zhipu_client(), tag=f"{tag}:glm", **kw)


def analyze_chain(chain: dict, items: list[dict], *, call_fn=None,
                  max_items: int = 30) -> dict:
    """对单条产业链跑 5 步分析；call_fn 可注入（测试/复用 client）。"""
    call = call_fn or default_llm_call
    messages = build_tracking_messages(chain, items, max_items=max_items)
    raw = call(messages)
    return parse_analysis(raw)
