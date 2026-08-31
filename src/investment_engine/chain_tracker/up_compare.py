"""「管线判断 vs UP 判断」每日对比（M0-Chain Phase 4 T23）。

两条判断线的口径：
- 管线判断：knowledge/industry-chains/<chain_id>/chain.yaml 的阶段/时机
  （current_stage / stage_confidence / timing.current_recommendation）
- UP 判断：knowledge/claims/claim-YYYYMMDD-NNN.yaml 拍平后的结构化 claim

本模块只做三件事：把当日 UP claim 匹配到链（match）、生成人工对比草稿
（collect）、把人工结论落账并统计重合度（log/stats）。agree/partial/disagree
由人工判断填写，工具不调 LLM、不自动下结论。

产物（infra/data/chain_tracking/，gitignored）：
- up_compare_<date>.md   每日对比草稿（人工填结论）
- up_comparison.jsonl    结论正本（每行一条 JSON，供 stats 统计）
"""
from __future__ import annotations

import json
from datetime import date as date_type
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from investment_engine.chain_tracker.matching import extract_chain_signals
from investment_engine.chain_tracker.report import default_tracking_dir

# 人工结论的合法取值：方向一致 / 部分一致 / 方向冲突
AGREEMENT_LEVELS = ("agree", "partial", "disagree")

# UP 侧 statement 在草稿中的截断长度（完整陈述可查原 claim 文件）
_STATEMENT_MAX = 200


def default_claims_dir() -> Path:
    from qing_investment.paths import repo_root

    return repo_root() / "knowledge" / "claims"


def default_log_path() -> Path:
    """结论正本：up_comparison.jsonl。"""
    return default_tracking_dir() / "up_comparison.jsonl"


def default_draft_path(date: str) -> Path:
    return default_tracking_dir() / f"up_compare_{date}.md"


def load_claims_for_date(date: str, *, claims_dir: Path | None = None) -> list[dict]:
    """读取 claim-{date 去横线}-*.yaml 全部文件，拍平 claims 列表返回。"""
    base = Path(claims_dir) if claims_dir is not None else default_claims_dir()
    compact = date.replace("-", "")
    claims: list[dict] = []
    for path in sorted(base.glob(f"claim-{compact}-*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for c in data.get("claims") or []:
            if isinstance(c, dict):
                claims.append(c)
    return claims


def _claim_hits(sig: dict, *, codes: set[str], names: set[str],
                subject: str, tags: set[str]) -> bool:
    """单条 claim 是否命中某链的信号（任一规则即中）。"""
    if codes & sig["codes"]:
        return True
    if names & sig["names"]:
        return True
    if subject and any(n in subject for n in sig["names"]):
        return True
    # keywords 里拉丁 token 已是大写（matching.py），中文碎片 upper 后不变
    if tags & {k.upper() for k in sig["keywords"]}:
        return True
    return False


def match_claims_to_chains(claims: list[dict],
                           chains: list[dict]) -> dict[str, list[dict]]:
    """UP claim → 链匹配：返回 {chain_id: [claim, ...]}，无命中的链不出现。

    命中规则（任一即中）：
    1. claim.related_stocks 任一 code 在链信号 codes 中
    2. claim.related_stocks 任一 name 在链信号 names 中
    3. 链信号 names 任一名称出现在 claim.subject 中
    4. claim.tags 任一项（upper 后）出现在链信号 keywords 中
    """
    index = {c["chain_id"]: extract_chain_signals(c) for c in chains}
    matched: dict[str, list[dict]] = {}
    for claim in claims:
        stocks = [s for s in claim.get("related_stocks") or []
                  if isinstance(s, dict)]
        codes = {str(s.get("code") or "").strip() for s in stocks} - {""}
        names = {str(s.get("name") or "").strip() for s in stocks} - {""}
        subject = str(claim.get("subject") or "")
        tags = {str(t).strip().upper() for t in claim.get("tags") or []} - {""}
        for chain_id, sig in index.items():
            if _claim_hits(sig, codes=codes, names=names,
                           subject=subject, tags=tags):
                matched.setdefault(chain_id, []).append(claim)
    return matched


def render_compare_draft(date: str, matched: dict[str, list[dict]],
                         chains: dict[str, dict]) -> str:
    """生成每日对比草稿 markdown；无命中时只写头部说明（复盘留痕）。"""
    lines = [
        f"# 管线判断 vs UP 判断 每日对比 {date}",
        "",
        "> 填写说明：对比管线侧（chain.yaml 阶段/时机）与 UP 侧（当日 claim）判断，",
        "> 在每节末尾留白行填 agree（方向一致）/ partial（部分一致）/ "
        "disagree（方向冲突）与备注，",
        "> 然后用 `python scripts/chain_up_compare.py log` 落账。",
        "",
    ]
    if not matched:
        lines.append("当日无 UP 判断命中任何链。")
        lines.append("")
        return "\n".join(lines)

    for chain_id, claims in matched.items():
        chain = chains.get(chain_id) or {}
        timing = chain.get("timing")
        timing = timing if isinstance(timing, dict) else {}
        lines.append(f"## {chain.get('name') or chain_id}（{chain_id}）")
        lines.append("")
        lines.append(f"- 管线阶段：{chain.get('current_stage') or '-'}"
                     f"（置信度 {chain.get('stage_confidence') or '-'}）")
        lines.append(f"- 管线时机：{timing.get('current_recommendation') or '-'}")
        lines.append("- UP 判断：")
        for c in claims:
            statement = str(c.get("statement") or "")
            if len(statement) > _STATEMENT_MAX:
                statement = statement[:_STATEMENT_MAX] + "…"
            lines.append(f"  - 【{c.get('claim_type') or '-'}/"
                         f"{c.get('confidence') or '-'}】{c.get('subject') or '-'}")
            lines.append(f"    {statement}")
        lines.append("")
        lines.append("> 对比结论（agree/partial/disagree）：___  备注：___")
        lines.append("")
    return "\n".join(lines)


def collect_compare_draft(date: str, *, claims_dir: Path | None = None,
                          base_dir: Path | None = None,
                          out_path: Path | None = None
                          ) -> tuple[Path, dict[str, list[dict]]]:
    """加载全部链 + 当日 UP claims → 匹配 → 写对比草稿。

    返回 (草稿路径, 命中结果)。无命中也写草稿（头部注明），便于复盘留痕。
    """
    from investment_engine.industry_chain import store

    chain_list = [store.load_chain(cid, base_dir=base_dir)
                  for cid in store.list_chains(base_dir=base_dir)]
    claims = load_claims_for_date(date, claims_dir=claims_dir)
    matched = match_claims_to_chains(claims, chain_list)
    draft = render_compare_draft(date, matched,
                                 {c["chain_id"]: c for c in chain_list})
    path = Path(out_path) if out_path is not None else default_draft_path(date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(draft, encoding="utf-8")
    return path, matched


def log_comparison(*, date: str, chain_id: str, agreement: str, note: str = "",
                   path: Path | None = None,
                   base_dir: Path | None = None) -> dict:
    """把人工对比结论 append 到 up_comparison.jsonl；返回写入的 entry。

    若 chain.yaml 存在，顺带记录当时的 pipeline_stage / pipeline_timing
    （timing.current_recommendation），供事后核对"管线当时说了什么"；
    链不存在也允许落账（如复盘已删除的链），两字段记 None。
    """
    if agreement not in AGREEMENT_LEVELS:
        raise ValueError(f"agreement 必须 ∈ {AGREEMENT_LEVELS}，得到 {agreement!r}")

    from investment_engine.industry_chain import store

    stage = timing_rec = None
    try:
        chain = store.load_chain(chain_id, base_dir=base_dir)
    except FileNotFoundError:
        pass
    else:
        stage = chain.get("current_stage")
        timing = chain.get("timing")
        if isinstance(timing, dict):
            timing_rec = timing.get("current_recommendation")

    entry = {
        "date": date,
        "chain_id": chain_id,
        "agreement": agreement,
        "note": note,
        "pipeline_stage": stage,
        "pipeline_timing": timing_rec,
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    out = Path(path) if path is not None else default_log_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _summarize(entries: list[dict]) -> dict:
    """一组结论的细分统计；n=0 时两项比率为 None。"""
    n = len(entries)
    agree = sum(1 for e in entries if e.get("agreement") == "agree")
    partial = sum(1 for e in entries if e.get("agreement") == "partial")
    disagree = sum(1 for e in entries if e.get("agreement") == "disagree")
    return {
        "total": n,
        "agree": agree,
        "partial": partial,
        "disagree": disagree,
        # 重合度口径：partial 按半条计入
        "overlap_rate": (agree + 0.5 * partial) / n if n else None,
        "full_rate": agree / n if n else None,
    }


def agreement_stats(*, days: int = 30, today: str | None = None,
                    path: Path | None = None) -> dict:
    """统计最近 days 天（含今天）内的对比结论重合度。

    返回 {"days", "total", "agree", "partial", "disagree", "overlap_rate",
    "full_rate", "by_chain", "dates"}；窗口内无数据时比率为 None。
    """
    log = Path(path) if path is not None else default_log_path()
    end = date_type.fromisoformat(today) if today else datetime.now().date()
    cutoff = end - timedelta(days=days)

    entries: list[dict] = []
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                ed = date_type.fromisoformat(str(e.get("date") or ""))
            except (json.JSONDecodeError, ValueError):
                continue  # 坏行/坏日期跳过，不阻断统计
            if ed >= cutoff:
                entries.append(e)

    by_chain: dict[str, list[dict]] = {}
    for e in entries:
        by_chain.setdefault(str(e.get("chain_id") or ""), []).append(e)

    return {
        "days": days,
        **_summarize(entries),
        "by_chain": {cid: _summarize(es)
                     for cid, es in sorted(by_chain.items())},
        "dates": sorted({str(e.get("date")) for e in entries}),
    }
