"""收盘差异归因：判错日 → DeepSeek 四型分类 → 归因记录 + 处置提案（提案制闭环）。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from investment_engine.blindtest.replay import DEFAULT_MODEL, call_deepseek

ATTR_DIR = Path("evals/shadow/attributions")
PROPOSAL_DIR = Path("framework/proposals")

ATTRIBUTION_TYPES = ("数据缺", "步骤缺", "概念误用", "信息差")
PROPOSAL_TYPES = ("data-channel", "pattern-patch", "glossary-patch", "capability-boundary")
_TYPE_TO_PROPOSAL = {"数据缺": "data-channel", "步骤缺": "pattern-patch",
                     "概念误用": "glossary-patch", "信息差": "capability-boundary"}

# 盲判数据包当前结构性缺失的通道（M1 spec 已如实标注）
KNOWN_DATA_GAPS = ["板块资金流", "分时数据", "公告流"]

ATTR_PROMPT = """你是方法论复盘归因员。AI 在没有参考任何人物言论的情况下独立做出了市场判断，事后证明判错了。
请做差异归因，严格输出 JSON：
{{"types": ["数据缺", "步骤缺", "概念误用", "信息差"],
  "analysis": "错因分析（必须引用具体数据项或推理步骤）",
  "proposals": [{{"type": "data-channel|pattern-patch|glossary-patch|capability-boundary",
                "title": "一句话", "action": "具体处置建议"}}]}}
归因口径：数据缺=推理所需数据没有采集通道；步骤缺=方法论缺环节；概念误用=术语/框架用错场景；信息差=依赖非公开渠道信息（不强求，标注能力边界即可）。
types 可多选；proposals 可为空列表。只输出 JSON。

【判错类型】{trigger}
【AI 判断】{ai_result}
【事后真值/评分】{score_info}
【当日在场数据】指数与个股 K 线量价、产业链知识库、术语词典、推理框架索引
【当日缺席数据（已知缺口）】{gaps}
"""


def parse_attribution(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"归因输出非 JSON: {raw[:80]!r}") from e
    types = [t for t in (data.get("types") or []) if t in ATTRIBUTION_TYPES]
    if not types:
        raise ValueError(f"types 必须含四型之一: {data.get('types')!r}")
    proposals = []
    for p in (data.get("proposals") or []):
        if not isinstance(p, dict):
            continue
        ptype = p.get("type")
        if ptype not in PROPOSAL_TYPES:
            ptype = _TYPE_TO_PROPOSAL.get(types[0], "capability-boundary")
        proposals.append({"type": ptype, "title": str(p.get("title", ""))[:80],
                          "action": str(p.get("action", ""))[:500]})
    return {"types": types, "analysis": str(data.get("analysis", "")), "proposals": proposals}


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "note"


def _write_proposals(day: str, attr: dict, proposal_dir: Path) -> list[str]:
    refs = []
    Path(proposal_dir).mkdir(parents=True, exist_ok=True)
    for p in attr["proposals"]:
        path = Path(proposal_dir) / f"{day}-{p['type']}-{_slug(p['title'])}.md"
        path.write_text(
            f"---\ndate: {day}\ntype: {p['type']}\nstatus: open\n"
            f"source: evals/shadow/attributions/{day}.json\n---\n\n"
            f"# {p['title']}\n\n## 分析\n\n{attr['analysis']}\n\n## 处置建议\n\n{p['action']}\n",
            encoding="utf-8",
        )
        refs.append(str(path))
    return refs


def run_attribution(day: str, *, trigger: str, pred: dict, score_info: dict,
                    attr_dir: Path = ATTR_DIR, proposal_dir: Path = PROPOSAL_DIR,
                    model: str = DEFAULT_MODEL, client=None) -> dict:
    """对判错日跑归因。同日消息合并 triggers；提案每次重新生成引用。

    旧归因已被预测重跑作废（superseded）时不合并其 triggers，按新记录重新开始。
    """
    prompt = ATTR_PROMPT.format(
        trigger=trigger,
        ai_result=json.dumps(pred.get("result", {}), ensure_ascii=False),
        score_info=json.dumps(score_info, ensure_ascii=False),
        gaps="、".join(KNOWN_DATA_GAPS),
    )
    raw = call_deepseek([{"role": "user", "content": prompt}], model=model, client=client,
                        tag="shadow_attribute")
    attr = parse_attribution(raw)

    path = Path(attr_dir) / f"{day}.json"
    triggers = [trigger]
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if not old.get("superseded"):
                triggers = list(dict.fromkeys(old.get("triggers", []) + [trigger]))
        except json.JSONDecodeError:
            pass
    refs = _write_proposals(day, attr, proposal_dir)
    rec = {"date": day, "triggers": triggers, "types": attr["types"],
           "analysis": attr["analysis"], "proposal_refs": refs}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec


def supersede_attribution(day: str, *, attr_dir: Path = ATTR_DIR,
                          proposal_dir: Path = PROPOSAL_DIR,
                          reason: str = "prediction_rerun") -> dict | None:
    """预测重跑覆盖时作废旧归因：归因标 superseded，其 open 提案改 retracted。

    返回作废后的归因记录；无归因或已作废返回 None。幂等。
    """
    path = Path(attr_dir) / f"{day}.json"
    if not path.exists():
        return None
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if rec.get("superseded"):
        return None
    rec["superseded"] = True
    rec["superseded_reason"] = reason
    retracted = []
    for ref in rec.get("proposal_refs") or []:
        p = Path(ref)
        if not p.exists():
            p = Path(proposal_dir) / p.name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        if not re.search(r"status:\s*open\b", text):
            continue  # 已 applied/rejected/retracted 的不动
        text = re.sub(r"status:\s*open\b", "status: retracted", text, count=1)
        text += (f"\n> retracted {day}：归因记录已被预测重跑作废（{reason}），"
                 "本提案证据基础失效；如议题仍成立请人工重开。\n")
        p.write_text(text, encoding="utf-8")
        retracted.append(p.name)
    rec["retracted_proposals"] = retracted
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec
