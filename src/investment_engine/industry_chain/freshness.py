"""产业链知识库保鲜巡检（M5 提前项，v2.2 §16.6）。

扫描 knowledge/industry-chains/*/chain.yaml 的 last_verified（链/环节/标的映射三级），
超过阈值（默认 90 天）或从未核实的字段列入"待核实"清单。

口径说明：巡检只出报告，不回写 chain.yaml——"标注待核实"落在报告消费侧
（plan §5.3：超保鲜期字段在报告中自动标注），避免机器改知识库与人冲突。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

CHAINS_DIR = Path("knowledge/industry-chains")
DEFAULT_STALE_DAYS = 90
REPORT_PATH = Path("logs/industry-chain-freshness.md")


def _age(day_str: str | None, today: date) -> int | None:
    """last_verified 距今天数；None/非法 → None（从未核实）。"""
    if not day_str:
        return None
    try:
        return (today - date.fromisoformat(str(day_str)[:10])).days
    except ValueError:
        return None


def inspect_chains(chains_dir: Path = CHAINS_DIR, *, today: date | None = None,
                   stale_days: int = DEFAULT_STALE_DAYS) -> dict:
    """返回 {chain_id: {"name", "age", "stale": [条目...]}}；age 单位天，None=从未核实。

    环节/标的的 last_verified 为空时继承链级日期（迁移存量普遍如此）；
    两者皆空才记"从未核实"。
    """
    today = today or date.today()
    chains = {}
    for path in sorted(Path(chains_dir).glob("*/chain.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        cid = data.get("chain_id") or path.parent.name
        chain_lv = data.get("last_verified")
        entries = []

        def _add(where: str, label: str, lv):
            effective = lv or chain_lv
            age = _age(effective, today)
            if age is None or age > stale_days:
                entries.append({"where": where, "label": label,
                                "last_verified": effective or None, "age_days": age,
                                "inherited": not bool(lv)})

        for seg in data.get("segments") or []:
            _add("segment", seg.get("name") or seg.get("id") or "?", seg.get("last_verified"))
        for m in data.get("mappings") or []:
            _add("mapping", f"{m.get('name')}({m.get('code')})", m.get("last_verified"))
        chains[cid] = {
            "name": data.get("name", cid),
            "last_verified": chain_lv,
            "age_days": _age(chain_lv, today),
            "stale": entries,
            "counts": {"segments": len(data.get("segments") or []),
                       "mappings": len(data.get("mappings") or [])},
        }
    return chains


def render_report(chains: dict, *, today: date | None = None,
                  stale_days: int = DEFAULT_STALE_DAYS) -> str:
    today = today or date.today()
    total_stale = sum(len(c["stale"]) for c in chains.values())
    lines = [
        f"# 产业链知识库保鲜巡检（{today:%Y-%m-%d}）",
        "",
        f"- 阈值：last_verified 超 {stale_days} 天或从未核实 → 待核实；只出报告，不回写 chain.yaml",
        f"- 链数：{len(chains)}；待核实条目：{total_stale}",
        "",
        "| 链 | 链级 last_verified | 龄期（天） | 环节/标的 | 待核实 |",
        "|---|---|---|---|---|",
    ]
    for cid, c in chains.items():
        age = c["age_days"]
        lines.append(f"| {c['name']} | {c['last_verified'] or '从未'} "
                     f"| {age if age is not None else '-'} "
                     f"| {c['counts']['segments']}环节/{c['counts']['mappings']}标的 "
                     f"| {len(c['stale'])} |")
    for cid, c in chains.items():
        if not c["stale"]:
            continue
        lines += ["", f"## {c['name']} 待核实清单", ""]
        for e in c["stale"]:
            age = f"{e['age_days']} 天" if e["age_days"] is not None else "从未核实"
            lines.append(f"- [{e['where']}] {e['label']}：last_verified="
                         f"{e['last_verified'] or '无'}（{age}）")
    lines.append("")
    return "\n".join(lines)


def run(chains_dir: Path = CHAINS_DIR, *, stale_days: int = DEFAULT_STALE_DAYS,
        report_path: Path = REPORT_PATH) -> Path:
    chains = inspect_chains(chains_dir, stale_days=stale_days)
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(chains, stale_days=stale_days), encoding="utf-8")
    return report_path
