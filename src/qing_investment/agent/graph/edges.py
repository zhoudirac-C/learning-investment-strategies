from __future__ import annotations

import logging

from .state import AgentState


import re

_CITATION_ONLY_PATTERN = re.compile(r"citation|来源|引用|reference|missing citation", re.IGNORECASE)
_CORE_METHOD_MISSING_PATTERN = re.compile(r"核心方法论无来源|核心方法论缺失|关键方法论", re.IGNORECASE)


def _is_citation_only_issue(notes: list[str]) -> bool:
    """判断 review_notes 是否仅为 citation/来源类问题，且不含核心方法论缺失。"""
    if not notes:
        return False
    for note in notes:
        note_str = note if isinstance(note, str) else str(note)
        # 只要包含非 citation 的硬性失败项，就不视为纯 citation 问题
        if _CORE_METHOD_MISSING_PATTERN.search(note_str):
            return False
        if not _CITATION_ONLY_PATTERN.search(note_str):
            return False
    return True


def review_router(state: AgentState) -> str:
    logger = logging.getLogger(__name__)
    passed = state.get("review_passed", False)
    if passed:
        logger.info("review_router: passed → end")
        return "pass"
    retry_count = state.get("_retry_count", 0)
    if retry_count >= 2:
        logger.info(f"review_router: retry={retry_count} max reached → force pass")
        return "pass"

    # Phase 8.2: citation 类问题不再触发重试，避免 token 浪费
    review_notes = state.get("review_notes", []) or []
    if _is_citation_only_issue(review_notes):
        logger.info("review_router: citation-only issues → pass (suggestion preserved in review_notes)")
        return "pass"

    logger.info(f"review_router: retry={retry_count} → back to style_writer")
    return "fail"
