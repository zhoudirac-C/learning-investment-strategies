from __future__ import annotations

import copy
import hashlib
import logging
import os
import re
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from fastapi import FastAPI

# ── 日志配置（Phase 8 新增：按天轮转日志，保留30天）──
_log_dir = Path(__file__).resolve().parents[3] / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)
_log_file = _log_dir / "qing-agent.log"

_handler = TimedRotatingFileHandler(
    str(_log_file),
    when="midnight",
    interval=1,
    backupCount=30,
    encoding="utf-8",
)

# 自定义 namer：将 qing-agent.log → qing-agent.YYYY-MM-DD.log
def _log_namer(default_name: str) -> str:
    # default_name = "qing-agent.log.2026-06-12" → "qing-agent.2026-06-12.log"
    base = _log_file.stem  # "qing-agent"
    ext = _log_file.suffix  # ".log"
    date_part = Path(default_name).suffix.lstrip(".")  # "2026-06-12"
    return str(_log_dir / f"{base}.{date_part}{ext}")

_handler.namer = _log_namer
_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))

# Clear default handlers and add file handler
_root_logger = logging.getLogger()
_root_logger.setLevel(logging.DEBUG if os.environ.get("QING_AGENT_LOG_LEVEL", "").upper() == "DEBUG" else logging.INFO)
# Remove existing handlers to avoid duplicate logs
for h in _root_logger.handlers[:]:
    _root_logger.removeHandler(h)
_root_logger.addHandler(_handler)

# Also log to stderr for docker/k8s environments
_console = logging.StreamHandler()
_console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_root_logger.addHandler(_console)

# Set module-specific loggers
for mod_name in [
    "qing_investment.agent.graph.nodes",
    "qing_investment.agent.graph.builder",
    "qing_investment.agent.tools.llm_client",
    "qing_investment.agent.tools.neo4j_client",
    "qing_investment.agent.tools.qdrant_client",
]:
    logging.getLogger(mod_name).setLevel(logging.DEBUG if os.environ.get("QING_AGENT_LOG_LEVEL", "").upper() == "DEBUG" else logging.INFO)

logger = logging.getLogger(__name__)
logger.info(f"日志初始化完成，路径={_log_file}")

from qing_investment.agent.graph.builder import build_graph
from qing_investment.agent.models.schemas import (
    ChatRequest,
    ChatResponse,
    TriggerRequest,
    TriggerResponse,
)
from qing_investment.agent.tools.llm_client import (
    format_provider_usage_summary,
    get_embedding_model,
    get_llm_client,
    reset_provider_usage,
)
from qing_investment.agent.tools.mem0_client import Mem0ClientWrapper
from qing_investment.agent.tools.neo4j_client import Neo4jClient
from qing_investment.agent.tools.qdrant_client import QdrantClientWrapper
from qing_investment.agent.tools.claim_freshness import apply_claim_freshness

app = FastAPI(title="Qing-Agent", version="0.1.0")
graph = build_graph()


# ── 轻量级关键词提取（用于 /chat 的 Neo4j claims 检索） ──
_STOP_WORDS: set[str] = {
    "什么是", "怎么", "如何", "分析一下", "告诉我", "请问",
    "一下", "的", "了", "吗", "呢", "啊", "吧", "吗",
}
_SECTOR_KEYWORDS: dict[str, list[str]] = {
    "光互连": ["光互连", "光互联", "光模块", "CPO", "光纤", "光通信", "光芯片"],
    "半导体": ["半导体", "芯片", "存储", "封测", "光刻", "设备", "材料"],
    "AI": ["AI", "算力", "大模型", "智能体", "Agent", "AIPC"],
    "机器人": ["机器人", "具身智能", "人形机器人", "特斯拉", "Optimus"],
    "电力": ["电力", "煤炭", "红利", "高股息", "绿电"],
    "新能源": ["新能源", "光伏", "锂电", "储能", "风电"],
    "资源": ["铜", "铝", "锂", "稀土", "黄金", "煤炭", "硫磺"],
}


def _claim_school(claim: dict) -> str:
    school = str(claim.get("school") or "").strip().lower()
    if school:
        return school
    up_id = str(claim.get("up_id") or "")
    if up_id:
        from qing_investment.schools import school_of_up

        return school_of_up(up_id) or "unknown"
    return "unknown"


def _format_claim_line(c: dict) -> str:
    """把 claim 格式化为带日期和学派的历史材料，而非当前观点。"""
    claim_id = c.get("id", "N/A")
    parts = [f"[{claim_id}]", f" [{_claim_school(c)}]"]
    parts.append(f" ({c.get('source_date','') or '日期未知'})")
    if c.get("claim_type"):
        parts.append(f" [{c.get('claim_type')}]")
    parts.append(" [历史证据]")
    intensity = c.get("intensity", "medium")
    intensity_tag = {"high": "🔴", "medium": "🟡", "low": "⚪"}.get(intensity, "⚪")
    parts.append(f" [历史材料强度:{intensity_tag}]")
    parts.append(f": {c.get('statement', '')[:200]}")
    if c.get("superseded_by"):
        parts.append(f" [已被 {', '.join(c['superseded_by'][:2])} 取代]")
    if c.get("contradicts"):
        parts.append(f" [与 {', '.join(c['contradicts'][:2])} 矛盾]")
    return "".join(parts)


def _extract_keywords(text: str) -> list[str]:
    """从用户查询中提取可用于 Neo4j claims 检索的关键词。"""
    # 去掉常见疑问前缀
    cleaned = text.strip()
    for sw in sorted(_STOP_WORDS, key=len, reverse=True):
        cleaned = cleaned.replace(sw, "")
    cleaned = cleaned.strip()
    # 去掉标点和数字
    cleaned = re.sub(r"[^\u4e00-\u9fa5a-zA-Z]", " ", cleaned)
    tokens = [t for t in cleaned.split() if len(t) >= 2]
    # 去重保留
    seen: set[str] = set()
    result: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


def _aggregate_cost(cost_tracking: list[dict]) -> dict:
    """从 Annotated 合并的 cost_tracking 列表中提取总成本快照。

    cost_tracking 格式: [{"llm_calls": int, "total_cost_usd": str}]
    """
    from decimal import Decimal

    total_calls = 0
    total_cost = Decimal("0")
    for entry in cost_tracking:
        total_calls += entry.get("llm_calls", 0)
        try:
            total_cost += Decimal(entry.get("total_cost_usd", "0"))
        except Exception:
            pass
    result = {"llm_calls": total_calls, "total_cost_usd": str(total_cost)}
    logger.info("[_aggregate_cost] entries=%d total_calls=%d total_cost_usd=%s", len(cost_tracking), total_calls, result["total_cost_usd"])
    return result


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


def _final_validation_summary(result: dict) -> dict:
    return result.get("market_context") or result.get("market_summary_context") or {}


def _trigger_input_availability(req: TriggerRequest) -> tuple[bool, bool]:
    from qing_investment.agent.tools.sector_data import (
        boards_have_market_data,
        quotes_have_market_data,
        sentiment_has_market_data,
    )

    snapshot = req.market_snapshot or {}
    snapshot_usable = quotes_have_market_data(
        snapshot.get("quotes")
    ) or sentiment_has_market_data(snapshot.get("sentiment"))
    boards = req.external_sector_boards or {}
    boards_usable = boards.get("available") is True and boards_have_market_data(boards)
    return snapshot_usable, boards_usable


def _trigger_record_status(req: TriggerRequest, result: dict, final_output: str) -> str:
    from qing_investment.agent.validators.output_guard import is_hallucinated_output

    data_as_of = req.data_as_of or str(req.market_snapshot.get("timestamp") or "")
    snapshot_usable, boards_usable = _trigger_input_availability(req)
    if not data_as_of or not (snapshot_usable or boards_usable):
        return "missing"
    if not final_output:
        return "error"
    summary = _final_validation_summary(result)
    if (
        summary.get("_fallback_reason")
        or summary.get("_validation_contract_errors")
        or summary.get("_scan_failed")
        or result.get("_style_writer_failed")
        or result.get("_stock_analysis_failed")
        or result.get("_reviewer_error")
    ):
        return "error"
    if is_hallucinated_output(final_output):
        return "error"
    return "pending_maturity"


def _trigger_record_error(
    status: str, result: dict, final_output: str
) -> dict | None:
    summary = _final_validation_summary(result)
    if status == "missing":
        return {"type": "missing_input", "message": "数据时点或实时输入快照缺失"}
    if not final_output:
        return {"type": "empty_output", "message": "Qing-Agent returned empty output"}
    if summary.get("_fallback_reason"):
        return {
            "type": "generation_fallback",
            "message": summary["_fallback_reason"],
        }
    if summary.get("_scan_failed"):
        return {"type": "generation_fallback", "message": "stock_scanner_failed"}
    if result.get("_style_writer_failed"):
        return {"type": "generation_fallback", "message": "style_writer_failed"}
    if result.get("_stock_analysis_failed"):
        return {"type": "generation_fallback", "message": "stock_analysis_failed"}
    if result.get("_reviewer_error"):
        return {"type": "generation_fallback", "message": "reviewer_llm_failed"}
    if summary.get("_validation_contract_errors"):
        return {
            "type": "validation_contract_error",
            "message": "; ".join(summary["_validation_contract_errors"]),
        }
    if status == "error":
        return {"type": "output_rejected", "message": "输出未通过幻觉验收"}
    return None


def _content_version(value: object) -> str:
    import json

    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _pipeline_versions(summary: dict) -> tuple[str, str]:
    repo_root = Path(__file__).resolve().parents[3]
    prompt_dir = Path(__file__).resolve().parent / "prompts" / "system"
    prompt_files = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(prompt_dir.glob("*.txt"))
    }
    prompt_version = _content_version(
        {"files": prompt_files, "market_summary": summary.get("prompt_version")}
    )
    code_paths = [
        "src/qing_investment/agent/graph/nodes.py",
        "src/qing_investment/agent/tools/pattern_policy.py",
        "src/qing_investment/monitor/rules/gator_rules.py",
    ]
    code_versions = {}
    for relative in code_paths:
        path = repo_root / relative
        code_versions[relative] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"
        )
    rules_version = _content_version(
        {"market_summary": summary.get("rules_version"), "code": code_versions}
    )
    return prompt_version, rules_version


def _freeze_trigger_result(
    req: TriggerRequest, result: dict, final_output: str
) -> Path | None:
    from investment_engine.qing_validation import records as validation_records

    try:
        data_as_of = req.data_as_of or str(req.market_snapshot.get("timestamp") or "")
        summary = _final_validation_summary(result)
        status = _trigger_record_status(req, result, final_output)
        snapshot_usable, boards_usable = _trigger_input_availability(req)
        prompt_version, rules_version = _pipeline_versions(summary)
        gaps = []
        if not data_as_of:
            gaps.append("data_as_of")
        if result.get("_data_missing_note"):
            gaps.append(result["_data_missing_note"])
        if summary.get("_fallback_reason"):
            gaps.append(f"market_summary:{summary['_fallback_reason']}")
        raw_judgment = summary.get("final_judgment")
        judgment = copy.deepcopy(raw_judgment) if isinstance(raw_judgment, dict) else {}
        judgment.setdefault("data_as_of", data_as_of)
        judgment["view"] = final_output
        for key in ("position_plans", "opportunity_scan"):
            judgment[key] = copy.deepcopy(summary.get(key) or [])
        if result.get("stock_analysis"):
            judgment["stock_analysis"] = copy.deepcopy(result["stock_analysis"])
        record = validation_records.build_record(
            trigger=req.trigger,
            data_as_of=data_as_of,
            input_payload=req.model_dump(),
            final_judgment=judgment,
            directions=summary.get("directions") or [],
            expert_views=summary.get("expert_views") or [],
            raw_output=final_output,
            status=status,
            input_availability={
                "market_snapshot": snapshot_usable,
                "external_sector_boards": boards_usable,
                "positions_provided": bool(req.positions),
                "position_snapshot_stored": False,
                "watchlist_count": len(req.watchlist),
                "gaps": gaps,
            },
            data_version=data_as_of or None,
            rules_version=rules_version,
            prompt_version=prompt_version,
            review={
                "passed": result.get("review_passed", False),
                "notes": result.get("review_notes", []),
            },
            citations=result.get("citation_report") or summary.get("citations") or [],
            error=_trigger_record_error(status, result, final_output),
            supersedes_record_id=req.trigger.get("supersedes_record_id"),
        )
        record["pattern_refs"] = copy.deepcopy(summary.get("pattern_refs") or [])
        record["gator_rules_snapshot"] = copy.deepcopy(
            summary.get("gator_rules_snapshot") or {}
        )
        return validation_records.save_record(record)
    except Exception as exc:
        logger.error("Qing-Agent 留痕失败: %s", exc, exc_info=True)
        return None


@app.post("/analyze/trigger", response_model=TriggerResponse)
async def analyze_trigger(req: TriggerRequest):
    shard_size = req.shard_size
    if shard_size is None:
        shard_size = int(os.environ.get("WATCHLIST_SHARD_SIZE", "8"))

    core_only = req.core_only
    if core_only is None:
        core_only = os.environ.get("WATCHLIST_CORE_ONLY", "0").lower() in ("1", "true", "yes", "on")

    state = {
        "query": req.query or f"{req.trigger.get('title', '')}：{req.trigger.get('reason', '')}",
        "session_id": req.session_id,
        "data_as_of": req.data_as_of or str(req.market_snapshot.get("timestamp") or ""),
        "trigger": req.trigger,
        "alerts": req.alerts,
        "market_snapshot": req.market_snapshot,
        "positions": req.positions,
        "watchlist": req.watchlist,
        "watchlist_shard": req.watchlist_shard,
        "sector_strengths": req.sector_strengths,
        "shard_size": shard_size,
        "core_only": core_only,
        "external_sector_boards": req.external_sector_boards,
        "external_market": req.external_market,
        "buy_signal_candidates": req.buy_signal_candidates,
        "sector_context": [],
        "claims": [],
        "wiki_snippets": [],
        "knowledge_graph": {},
        "memories": [],
        "few_shot_examples": [],
        "market_context": {},
        "stock_analysis": {},
        "draft_analysis": "",
        "styled_output": "",
        "review_notes": [],
        "final_output": "",
        "claims_cited": [],
        "data_sources": [],
        "confidence": "medium",
        "review_passed": False,
        "reasoning_steps": [],
        "_explicit_analysis_type": "analysis_type" in req.model_fields_set,
        "parsed_intent": {
            "analysis_type": req.analysis_type,
            "stock_code": req.stock_code or req.market_snapshot.get("stock_code", ""),
        },
    }

    import logging, time, traceback
    _req_logger = logging.getLogger("qing_investment.agent.main")
    _req_t0 = time.time()
    _req_logger.info(f"analyze_trigger start: type={req.analysis_type} trigger={req.trigger.get('title','')}")

    # 每个请求开始时重置 provider 使用轨迹
    reset_provider_usage()

    try:
        result = await graph.ainvoke(state)
    except Exception as e:
        _req_dur = time.time() - _req_t0
        _req_logger.error(
            f"analyze_trigger error after {_req_dur:.1f}s: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise

    _req_dur = time.time() - _req_t0
    provider_summary = format_provider_usage_summary()
    _req_logger.info(
        f"analyze_trigger end: duration={_req_dur:.1f}s "
        f"passed={result.get('review_passed')} "
        f"output_len={len(result.get('final_output', ''))} "
        f"claims_cited={len(result.get('claims_cited', []))} "
        f"provider_usage={provider_summary}"
    )

    # 在最终输出顶部附加模型路由说明
    final_output = result.get("final_output", "")
    if final_output:
        final_output = f"[{provider_summary}]\n\n{final_output}"

    record_path = _freeze_trigger_result(req, result, final_output)

    return TriggerResponse(
        final_output=final_output,
        claims_cited=result.get("claims_cited", []),
        data_sources=result.get("data_sources", []),
        confidence=result.get("confidence", "medium"),
        review_passed=result.get("review_passed", False),
        citation_report=result.get("citation_report"),
        reasoning_steps=result.get("reasoning_steps", []),
        cost_info=_aggregate_cost(result.get("cost_tracking", [])),
        record_id=record_path.stem if record_path else None,
        record_status=(
            _trigger_record_status(req, result, final_output) if record_path else None
        ),
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Chat endpoint with memory + knowledge-base retrieval + real-time data fetching."""
    mem0 = Mem0ClientWrapper()
    memories = mem0.search(req.message, user_id=req.session_id)

    # ── 知识库检索 ──
    wiki_snippets: list[dict] = []
    claims: list[dict] = []

    try:
        qdrant = QdrantClientWrapper()
        emb_model = get_embedding_model()
        if emb_model:
            vec = emb_model.encode(req.message)
            
            # 检索wiki和raw文档
            results = qdrant.search(vec, collection="qing_knowledge", limit=8)
            wiki_snippets = [
                {
                    "text": r.get("payload", {}).get("text", ""),
                    "source": r.get("payload", {}).get("source_path", ""),
                    "source_type": r.get("payload", {}).get("source_type", ""),
                }
                for r in results
            ]
            
            # 检索结构化claims
            claim_results = qdrant.search(vec, collection="qing_claims", limit=8)
            for r in claim_results:
                payload = r.get("payload", {})
                claims.append({
                    "id": payload.get("claim_id", ""),
                    "statement": payload.get("statement", ""),
                    "subject": payload.get("subject", ""),
                    "source_date": payload.get("source_date", ""),
                    "confidence": payload.get("confidence", ""),
                    "claim_type": payload.get("claim_type", ""),
                    "intensity": payload.get("intensity", "medium"),
                    "status": payload.get("status", ""),
                    "school": payload.get("school", ""),
                    "up_id": payload.get("up_id", ""),
                    "score": r.get("score", 0),
                })
    except Exception as e:
        print(f"Knowledge retrieval error: {e}")

    seen_ids: set[str] = set(c.get("id") or "" for c in claims)

    # ── 股票代码提取（先于 Neo4j 检索，供后续复用）──
    fetched_stock_code: str | None = None
    try:
        import re
        stock_code_match = re.search(r'(\d{6})', req.message)
        if stock_code_match:
            fetched_stock_code = stock_code_match.group(1)
    except Exception:
        pass

    # ── Neo4j 检索（单次连接，合并图遍历补充）──
    try:
        neo4j = Neo4jClient()

        # 若未提取到股票代码，尝试按名称从 Neo4j 模糊匹配
        if not fetched_stock_code:
            try:
                name_matches = neo4j.get_stock_by_name(req.message)
                if name_matches:
                    fetched_stock_code = name_matches[0]["code"]
            except Exception:
                pass
        
        # 如果提取到股票代码，使用图遍历获取相关 claims（包括演化关系）
        if fetched_stock_code:
            stock_claims = neo4j.get_claims_with_evolution(fetched_stock_code, limit=8)
            for c in stock_claims:
                c["source"] = "neo4j_graph"  # 标记来源
                claims.append(c)
        else:
            # 否则使用关键词匹配
            keywords = _extract_keywords(req.message)
            for cluster_kws in _SECTOR_KEYWORDS.values():
                for kw in cluster_kws:
                    if kw in req.message and kw not in keywords:
                        keywords.append(kw)
            for kw in keywords[:3]:
                batch = neo4j.get_claims_by_keyword(kw, limit=5)
                for c in batch:
                    cid = c.get("id")
                    if cid and cid not in seen_ids:
                        seen_ids.add(cid)
                        c["source"] = "neo4j_keyword"
                        claims.append(c)
                if len(claims) >= 15:
                    break

        # ── 图遍历补充：通过共享实体发现相关 claims（方案1）──
        if claims:
            graph_related_ids: set[str] = set()
            for c in claims[:3]:
                cid = c.get("id", "")
                if cid:
                    related = neo4j.get_related_claims(cid, limit=5)
                    for rc in related:
                        rid = rc.get("id", "")
                        if rid and rid not in seen_ids:
                            graph_related_ids.add(rid)
            for rid in graph_related_ids:
                rc = neo4j.get_claim_evolution(rid)
                if rc:
                    first = rc[0] if isinstance(rc, list) else rc
                    if first and first.get("id"):
                        first["source"] = "graph_traversal"
                        claims.append(first)
                        seen_ids.add(rid)

        neo4j.close()
    except Exception:
        pass


    market_snapshot: dict = {"quotes": []}
    external_sector_boards: dict = {"available": False}
    external_market = getattr(req, "external_market", {}) or {}

    # 1. 检测查询类型（同时尊重 trigger.analysis_type）
    query_lower = req.message.lower()
    is_market_query = (
        any(kw in query_lower for kw in ["大盘", "市场", "行情", "指数", "上证", "创业板", "科创"])
        or getattr(req, "analysis_type", None) == "market"
    )
    is_sector_query = (
        any(kw in query_lower for kw in ["板块", "行业", "概念"])
        or getattr(req, "analysis_type", None) == "sector"
    )
    is_stock_query = (
        any(kw in query_lower for kw in ["股", "走势", "分析", "低点", "高点", "买入", "卖出", "抄底", "减仓", "加仓", "持仓", "套牢", "解套", "止损", "止盈", "目标价", "支撑", "压力"])
        or getattr(req, "analysis_type", None) == "stock"
    )
    
    # 2. 如果没有提取到代码，从持仓配置中匹配股票名称
    if not fetched_stock_code:
        try:
            import yaml
            positions_path = "/home/ubuntu/learning-investment-strategies/config/stock_monitor/positions.yaml"
            with open(positions_path, "r", encoding="utf-8") as f:
                positions_data = yaml.safe_load(f)
            
            for account in positions_data.get("accounts", []):
                for pos in account.get("positions", []):
                    name = pos.get("name", "")
                    code = pos.get("code", "")
                    if name and code and isinstance(code, str) and name in req.message:
                        fetched_stock_code = code.replace(".SZ", "").replace(".SH", "").replace(".sz", "").replace(".sh", "")
                        break
                if fetched_stock_code:
                    break
        except Exception:
            pass
    
    def _format_macd_multi_tf_report(tech_signals: dict) -> str:
        """把 tech_signals 格式化成 prompt 里要的 macd_multi_tf_report。"""
        lines = ["📊 多级别 MACD 快照", ""]
        for code, sigs in tech_signals.items():
            macd = sigs.get("macd", {})
            tfs = macd.get("timeframes", {})
            if not tfs:
                continue
            lines.append(f"【{code}】")
            for tf in ["daily", "120min", "90min", "60min", "30min"]:
                if tf not in tfs:
                    continue
                d = tfs[tf]
                trend = d.get("hist_trend", "")
                cross = d.get("dif_cross", "")
                parts = [f"{tf}: close={d.get('close')} DIF={d.get('dif')} DEA={d.get('dea')} MACD={d.get('macd_hist')}"]
                if trend:
                    parts.append(f"柱趋势={trend}")
                if cross:
                    parts.append(f"交叉={cross}")
                lines.append("  " + " | ".join(parts))
            lines.append("")
        return "\n".join(lines)

    def _format_td_report(tech_signals: dict) -> str:
        """格式化九转报告。"""
        lines = ["🔄 神奇九转序列", ""]
        for code, sigs in tech_signals.items():
            td = sigs.get("td_daily", "")
            if td:
                lines.append(f"【{code} 日线】")
                lines.append(td)
                lines.append("")
        return "\n".join(lines)

    def _format_fibonacci_report(tech_signals: dict) -> str:
        """格式化斐波那契时间窗口报告。"""
        lines = ["⏰ 斐波那契时间窗口", ""]
        for code, sigs in tech_signals.items():
            fib = sigs.get("fibonacci", "")
            if fib:
                lines.append(f"【{code}】")
                lines.append(fib)
                lines.append("")
        return "\n".join(lines)

    # 3. 获取指数/大盘数据（如果是市场相关查询 或 个股查询也需要大盘环境）
    if is_market_query or is_sector_query or is_stock_query or not fetched_stock_code:
        try:
            from qing_investment.agent.tools.stock_data import fetch_index_quotes
            index_quotes = fetch_index_quotes()
            market_snapshot["quotes"] = index_quotes
            market_snapshot["date"] = ""
        except Exception:
            pass

        # 3.1 计算大盘技术面信号（MACD / 九转 / 斐波那契），供 market_summary 使用
        try:
            from qing_investment.kline_cache import (
                compute_fibonacci_time_report,
                compute_td_report,
                get_index_macd_snapshot,
            )

            # secid -> kline_cache 代码格式
            _INDEX_KLINE_MAP = {
                "1.000001": "sh000001",   # 上证指数
                "0.399001": "sz399001",   # 深证成指
                "0.399006": "sz399006",   # 创业板指
                "1.000688": "sh000688",   # 科创50
                "1.000985": "sh000985",   # 全A指数
            }

            tech_signals: dict[str, dict] = {}
            for secid, kline_code in _INDEX_KLINE_MAP.items():
                tech_signals[kline_code] = {
                    "macd": get_index_macd_snapshot(kline_code),
                    "td_daily": compute_td_report(kline_code, "daily"),
                    "td_60min": compute_td_report(kline_code, "60min"),
                    "fibonacci": compute_fibonacci_time_report(kline_code),
                }
            market_snapshot["tech_signals"] = tech_signals
            market_snapshot["macd_multi_tf_report"] = _format_macd_multi_tf_report(tech_signals)
            market_snapshot["td_sequential_report"] = _format_td_report(tech_signals)
            market_snapshot["fibonacci_time_report"] = _format_fibonacci_report(tech_signals)
        except Exception as e:
            logger.warning("大盘技术面信号计算失败: %s", e)

    # 4. 获取板块数据（如果是板块相关查询）
    if is_sector_query or is_market_query:
        try:
            from qing_investment.agent.tools.sector_data import get_sector_strength_snapshot
            sector_data = get_sector_strength_snapshot(top_n=15)
            external_sector_boards = {
                "available": True,
                **sector_data,
            }
        except Exception:
            external_sector_boards = {"available": False, "error": "板块数据获取失败"}
    
    # 5. 获取个股数据（如果提取到股票代码，或明确是股票分析类查询）
    stock_klines: list[dict] = []
    stock_intraday: list[dict] = []
    if fetched_stock_code or is_stock_query:
        try:
            from qing_investment.agent.tools.stock_data import fetch_single_stock, fetch_stock_kline, fetch_stock_intraday
            code_to_fetch = fetched_stock_code
            if not code_to_fetch:
                # 从 Neo4j 按名称模糊匹配股票代码（若 Neo4j 检索段失败时的再尝试）
                try:
                    from qing_investment.agent.tools.neo4j_client import Neo4jClient
                    n4j = Neo4jClient()
                    name_matches = n4j.get_stock_by_name(req.message)
                    n4j.close()
                    if name_matches:
                        code_to_fetch = name_matches[0]["code"]
                except Exception:
                    pass
            if code_to_fetch:
                # 获取实时行情
                stock_quote = fetch_single_stock(code_to_fetch)
                if stock_quote:
                    market_snapshot["quotes"].append(stock_quote)
                # 获取历史K线（90日）
                stock_klines = fetch_stock_kline(code_to_fetch, days=90)
                # 获取当日分时
                stock_intraday = fetch_stock_intraday(code_to_fetch)
        except Exception:
            pass

    # ── 过滤知识库内容 ──
    # 保留所有 wiki（包括市场分析、投资方法论、每日复盘等）
    all_wiki = [
        s for s in wiki_snippets
        if isinstance(s.get("source", ""), str)
        and s["source"].startswith(("knowledge/wiki/", "framework/"))
    ]
    
    # 保留所有 claims（不过滤，让 LLM 自己判断相关性）
    all_claims = claims

    # ── 读取持仓数据（如果匹配到个股） ──
    position_data: dict | None = None
    if fetched_stock_code:
        try:
            import yaml
            positions_path = "/home/ubuntu/learning-investment-strategies/config/stock_monitor/positions.yaml"
            with open(positions_path, "r", encoding="utf-8") as f:
                positions_data = yaml.safe_load(f)
            
            for account in positions_data.get("accounts", []):
                for pos in account.get("positions", []):
                    code = pos.get("code", "")
                    if isinstance(code, str):
                        code = code.replace(".SZ", "").replace(".SH", "").replace(".sz", "").replace(".sh", "")
                    if code == fetched_stock_code and pos.get("shares", 0) > 0:
                        position_data = {
                            "account": account.get("name", ""),
                            "name": pos.get("name", ""),
                            "code": code,
                            "shares": pos.get("shares", 0),
                            "cost": pos.get("cost", 0),
                            "risk_line": pos.get("risk_line", ""),
                            "risk_zone": pos.get("risk_zone", ""),
                            "reduce_zone": pos.get("reduce_zone", ""),
                            "notes": pos.get("notes", ""),
                        }
                        break
                if position_data:
                    break
        except Exception:
            pass

    # ── 构建 prompt ──
    context_parts = []

    # 实时数据部分
    from qing_investment.agent.tools.sector_data import (
        boards_have_market_data,
        quotes_have_market_data,
    )

    valid_quotes = [
        quote
        for quote in market_snapshot.get("quotes") or []
        if quotes_have_market_data([quote])
    ]
    quotes_usable = bool(valid_quotes)
    boards_usable = (
        external_sector_boards.get("available") is True
        and boards_have_market_data(external_sector_boards)
    )
    has_realtime_data = bool(
        quotes_usable or boards_usable or external_market.get("available")
    )
    if has_realtime_data:
        context_parts.append("【实时行情数据】（✅ 主要分析依据）")
        if quotes_usable:
            context_parts.append("- 个股/指数行情:")
            for q in valid_quotes:
                name = q.get("name", "")
                code = q.get("code", "")
                price = q.get("price", "")
                open_p = q.get("open", "")
                high = q.get("high", "")
                low = q.get("low", "")
                pct = q.get("pct_change", "")
                context_parts.append(f"  {name}({code}): 开{open_p} 收{price} 高{high} 低{low} 涨跌{pct}%")
        
        # 【新增】添加历史K线数据
        if stock_klines:
            from qing_investment.agent.tools.stock_data import format_kline_for_prompt
            context_parts.append("\n- 个股历史K线（近90日）:")
            context_parts.append(format_kline_for_prompt(stock_klines))
        
        # 【新增】添加当日分时数据
        if stock_intraday:
            from qing_investment.agent.tools.stock_data import format_intraday_for_prompt
            # 找到昨收价
            prev_close = None
            for q in valid_quotes:
                if not q.get("is_index"):
                    prev_close = q.get("prev_close")
                    break
            context_parts.append("\n- 个股当日分时:")
            context_parts.append(format_intraday_for_prompt(stock_intraday, prev_close))
        
        if boards_usable:
            context_parts.append("\n- 板块数据:")
            concept_leaders = external_sector_boards.get("concept", {}).get("leaders", [])
            for item in concept_leaders[:5]:
                context_parts.append(f"  {item['name']}: {item['pct_change']}%")

        if external_market.get("available"):
            context_parts.append("\n- 外围市场数据:")
            gm = external_market.get("global_macro") or {}
            if gm:
                us_idx = gm.get("美股三指数", {})
                for idx in ["^IXIC", "^DJI", "^GSPC"]:
                    if idx in us_idx:
                        d = us_idx[idx]
                        context_parts.append(f"  美股{d.get('name', idx)}: {d.get('pct_change', 'N/A')}%")
            ov = external_market.get("overnight_us") or {}
            if ov:
                themes = ov.get("themes", [])
                for t in themes[:3]:
                    context_parts.append(f"  映射股主题: {t.get('name', '')} ({t.get('pct_change', 'N/A')}%)")
            pmb = external_market.get("pre_market_brief") or {}
            if pmb:
                ca = pmb.get("core_assumption", "")
                if ca:
                    context_parts.append(f"  核心假设: {ca}")
    else:
        context_parts.append("【实时行情数据】（❌ 无法获取）")

    if all_wiki:
        context_parts.append("\n【博主知识库】（Wiki专题分析、投资方法论、市场复盘等）")
        for s in all_wiki[:8]:  # 限制数量避免prompt过长
            src_raw = s["source"]
            if not isinstance(src_raw, str):
                src_raw = str(src_raw)
            src = src_raw.replace("knowledge/wiki/", "[Wiki] ").replace("framework/", "[框架] ")
            text_raw = s.get("text", "")
            if not isinstance(text_raw, str):
                text_raw = str(text_raw)
            context_parts.append(f"- {src}: {text_raw[:300]}")

    if all_claims:
        # 应用时效分级
        fresh_claims = apply_claim_freshness(all_claims)

        # 分离方法论类和观点类
        method_claims = [
            c for c in fresh_claims
            if c.get('claim_type') in ('methodology', 'operation')
        ]
        view_claims = [
            c for c in fresh_claims
            if c.get('claim_type') not in ('methodology', 'operation')
        ]

        # 方法论只指导分析步骤，不提供当前市场结论。
        qing_methods = [c for c in method_claims if _claim_school(c) == "qing"]
        other_methods = [c for c in method_claims if _claim_school(c) != "qing"]
        if qing_methods:
            context_parts.append("\n【Qing历史方法论/操作框架】（仅作方法论指导，必须与实时数据配合）")
            for c in qing_methods[:5]:
                context_parts.append(_format_claim_line(c))
        if other_methods:
            context_parts.append("\n【其他学派历史方法论/操作框架】（仅作方法论指导，逐条标注学派）")
            for c in other_methods[:5]:
                context_parts.append(_format_claim_line(c))

        # 青枫浦上Q停止新增实时输入；所有观点统一按带日期的历史证据呈现。
        if fetched_stock_code:
            view_claims = [c for c in view_claims if c.get("intensity") != "low"]

        qing_views = [c for c in view_claims if _claim_school(c) == "qing"]
        other_views = [c for c in view_claims if _claim_school(c) != "qing"]
        if qing_views:
            context_parts.append("\n【Qing历史观点】（带日期的历史证据，不是当前信号；实时数据与证据等级优先）")
            for c in qing_views[:12]:
                context_parts.append(_format_claim_line(c))
        if other_views:
            context_parts.append("\n【其他学派历史观点】（带日期并逐条标注学派，不是当前信号）")
            for c in other_views[:12]:
                context_parts.append(_format_claim_line(c))

    # 注入持仓数据
    if position_data:
        context_parts.append("\n【用户持仓数据】")
        context_parts.append(f"- 标的: {position_data['name']}({position_data['code']})")
        context_parts.append(f"- 持仓: {position_data['shares']}股")
        context_parts.append(f"- 成本: {position_data['cost']}元")
        if position_data.get('risk_zone') or position_data.get('risk_line'):
            context_parts.append(f"- 风控线: {position_data.get('risk_zone') or position_data.get('risk_line')}")
        if position_data.get('reduce_zone'):
            context_parts.append(f"- 减仓区: {position_data['reduce_zone']}")
        if position_data.get('notes'):
            context_parts.append(f"- 备注: {position_data['notes']}")

    if memories:
        context_parts.append("\n【用户历史记忆】")
        for m in memories:
            content = m.get("content", "") if isinstance(m, dict) else str(m)
            context_parts.append(f"- {content}")

    dual_school_contract = ""
    has_gator = any(_claim_school(c) == "gator" for c in all_claims)
    if has_gator or any(term in query_lower for term in ("两派", "双学派", "鳄鱼", "gator")):
        from qing_investment.agent.graph.nodes import _load_prompt

        dual_school_contract = _load_prompt("dual_school_output")

    prompt_lines = [
        "你是青枫浦上Q的助手，风格犀利但不劝赌，不用机构研报腔。",
        "",
        "【分析框架——必须严格按此顺序执行】",
        "",
        "第一步：判断市场周期和情绪阶段",
        "- 只根据大盘指数（上证/深证/创业板/科创50）的实时涨跌、量能和情绪数据判断",
        "- 【Qing历史观点】中的 market-cycle 内容只能作为带日期的历史案例，不得采纳为当前周期结论",
        "- 实时数据不足时明确标记数据不足，不能用历史观点补齐当前判断",
        "",
        "第二步：判断所属板块是否是当前主线",
        "- 此步只能基于实时板块数据（板块涨跌幅、资金流向）",
        "- 板块轮动快，以当日数据为准，历史方向判断不得参与当前优先级排序",
        "- 判断板块是主线/支线/边缘/退潮方向，并给出实时证据",
        "",
        "第三步：判断个股地位",
        "- 当前地位优先根据实时板块内排名、相对强弱、市值和换手率判断",
        "- Qing历史claim中的龙头/中军/核心等标签仅作带日期的历史参考，不是当前权威定位",
        "- 没有实时排名时必须明确降级为未知，不得由历史标签直接决定当前地位",
        "",
        "第四步：检索历史提及与方法论（如有）",
        "- 查看【Qing历史观点】时必须同时展示日期，并明确其不是当前信号",
        "- 引用纪律：实时数据与证据等级先于历史claim，格式为（实时数据）→（历史参考）→（独立结论）",
        "- 如果存在【Qing历史方法论/操作框架】，只引用其分析步骤和操作纪律，不继承其中的市场结论",
        "",
        "第五步：结合技术位置和资金面判断风险收益",
        "- 看90日K线：趋势、支撑、压力、量能变化",
        "- 看当日分时：开盘/盘中/尾盘结构，资金流向",
        "- 看实时行情：价格、涨跌幅、换手率（如有）",
        "- 判断当前位置的风险收益比；历史观点不能替代数据分析",
        "",
        "第六步：输出证伪条件和跟踪字段",
        "- 如果看多，什么信号出现会证伪这个判断？",
        "- 如果看空，什么信号出现会证伪这个判断？",
        "- 下一交易日需要跟踪的关键指标",
        "",
        "【持仓关联分析（如适用）】",
        "- 如果用户提到持仓，必须结合成本、仓位、风控线给出建议",
        "- 区分：浮盈/浮亏、仓位轻重、是否符合原计划",
        "- 所有操作建议必须附带条件（'若X则Y'），禁止无条件买卖指令",
        "",
        "【核心原则】",
        "1. 【实时数据与证据等级优先】——当前判断必须基于实时、可核验数据，获取不到时明确降级",
        "2. 【Qing观点均为历史证据】——不因freshness、intensity或claim日期较近而视为当前信号",
        "3. 【方法论与观点分离】——方法论可指导分析，历史周期、方向和个股定位不得直接成为当前结论",
        "4. 【其他学派独立】——不得删除或改写gator等其他UP的独立输入，也不得归到qing名下",
        "5. 禁止引用claim ID支持当前观点",
        "6. 如果【实时行情数据】为空，请明确说明无法形成当前判断，不要编造",
        "7. 如果知识库中没有相关信息，请明确说明，不要编造\n"
        "8. 【输出格式】回复开头必须标注：'[Qing-Agent 分析]'，然后空一行再写正文\n"
        "9. 分析必须按上述六步框架执行，不能跳过步骤\n"
        "10. intensity只描述历史材料的分析深度，不代表UP当前推荐强度\n",
        "",
        dual_school_contract,
        *context_parts,
        f"\n用户：{req.message}\n",
        "请按上述六步框架直接回复：",
    ]
    prompt = "\n".join(prompt_lines)

    try:
        llm = get_llm_client()
        reply = llm.invoke(prompt).content or ""
    except Exception as e:
        reply = f"[服务暂时不可用] {e}"

    return ChatResponse(
        reply=reply,
        memories_used=memories if memories else [],
    )
@app.post("/memory/add")
async def add_memory(session_id: str, content: str, memory_type: str = "fact"):
    """Add a memory entry. Falls back to local JSON if mem0 server unavailable."""
    mem0 = Mem0ClientWrapper()
    result = mem0.add(
        content=content,
        user_id=session_id,
        metadata={"memory_type": memory_type},
    )
    return {"status": "ok", "result": result}
