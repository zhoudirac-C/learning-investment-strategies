from __future__ import annotations

import logging

from .state import AgentState


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
    logger.info(f"review_router: retry={retry_count} → back to style_writer")
    return "fail"
