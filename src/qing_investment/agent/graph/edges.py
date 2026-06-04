from __future__ import annotations

from .state import AgentState


def review_router(state: AgentState) -> str:
    if state.get("review_passed", False):
        return "pass"
    retry_count = state.get("_retry_count", 0)
    if retry_count >= 3:
        return "pass"
    return "fail"
