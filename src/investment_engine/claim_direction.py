"""claim 方向标注（M3 判向 v1，spec 2026-10-24-m3-outcome-writeback）。

LLM 批量给 claim 标注 direction（bullish/bearish/neutral + 定价基准），
写入 claim YAML 的 direction 块，供 claim_outcome 机械结算复用。
标注一次、长期复用；neutral（方法论/非方向观点）不参与命中率。
"""
from __future__ import annotations

import json
import re
from datetime import date

from investment_engine.claim_outcome import normalize_stock_code

ANNOTATOR = "m3-direction-v1"

DIRECTION_PROMPT = """你是投资研究助手。请判断下面这条投资观点的【方向】并给出可定价基准。

观点（{source_date}，类型 {claim_type}）:
  主题: {subject}
  表述: {statement}
  解释: {interpretation}
  相关标的: {related_stocks}

要求：
- value: bullish（看多/预期上涨/建议关注或买入）、bearish（看空/预期下跌/建议回避）、
  neutral（方法论/知识科普/非方向判断/无法定方向）
- basis_kind + basis_code: 用于验证该观点的市场基准——
  stock 用 6 位股票代码（如 600519）；index 用 sh000300（沪深300）/
  sh000001（上证）/sz399006（创业板指）等；neutral 时填观点最相关的标的即可
- market-cycle / market-regime 类观点默认 index=sh000300，除非表述明确指向其他指数
- 股票观点优先选 related_stocks 中代码最完整的一个
- rationale: ≤30 字

以 JSON 回复（只输出 JSON）：
{{"value": "bullish|bearish|neutral", "basis_kind": "stock|index", "basis_code": "...", "rationale": "..."}}"""


def _fmt_stocks(related_stocks) -> str:
    if not related_stocks:
        return "（无）"
    parts = []
    for s in related_stocks:
        if isinstance(s, dict):
            parts.append(f"{s.get('name', '')}({s.get('code', '')})")
        else:
            parts.append(str(s))
    return "、".join(parts)


def build_direction_prompt(claim: dict) -> str:
    return DIRECTION_PROMPT.format(
        source_date=claim.get("source_date", ""),
        claim_type=claim.get("claim_type", ""),
        subject=claim.get("subject", ""),
        statement=str(claim.get("statement", ""))[:500],
        interpretation=str(claim.get("interpretation", ""))[:300],
        related_stocks=_fmt_stocks(claim.get("related_stocks")),
    )


def parse_direction_response(resp: str) -> dict:
    """解析 LLM 判向 JSON；一切异常降级 neutral（不参与命中率，宁可漏不可错）。"""
    out = {"value": "neutral", "basis_kind": "stock", "basis_code": "",
           "rationale": ""}
    text = (resp or "").strip()
    try:
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("not a dict")
    except Exception:
        out["rationale"] = "LLM 响应解析失败，降级 neutral"
        out["basis_kind"] = "index"
        out["basis_code"] = "sh000300"
        return out

    value = str(parsed.get("value") or "").strip()
    out["value"] = value if value in ("bullish", "bearish", "neutral") else "neutral"
    kind = str(parsed.get("basis_kind") or "").strip()
    out["basis_kind"] = kind if kind in ("stock", "index") else "stock"
    code = str(parsed.get("basis_code") or "").strip()
    if out["basis_kind"] == "index" and not re.match(r"^(sh|sz)\d{6}$", code):
        code = "sh000300"  # 指数缺省沪深300
    out["basis_code"] = code
    out["rationale"] = str(parsed.get("rationale") or "")[:100]
    return out


def annotate_claim(claim: dict, llm) -> dict:
    """对单条 claim 判向 → direction dict（含 annotator/annotated_at）。"""
    prompt = build_direction_prompt(claim)
    try:
        resp = llm.invoke(prompt).content or ""
    except Exception as e:  # LLM 通道异常：降级 neutral，不阻断批处理
        parsed = {"value": "neutral", "basis_kind": "index",
                  "basis_code": "sh000300", "rationale": f"LLM 调用失败: {e}"[:100]}
    else:
        parsed = parse_direction_response(resp)
    if parsed["basis_kind"] == "stock" and parsed["basis_code"]:
        parsed["basis_code"] = normalize_stock_code(parsed["basis_code"])
    parsed["annotated_at"] = date.today().isoformat()
    parsed["annotator"] = ANNOTATOR
    return parsed
