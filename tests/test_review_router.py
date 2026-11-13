from qing_investment.agent.graph.edges import review_router
from qing_investment.agent.graph.nodes import reviewer


def test_reviewer_llm_failure_never_passes_and_stops_at_retry_limit(monkeypatch):
    monkeypatch.setattr(
        "qing_investment.agent.graph.nodes._safe_llm_invoke",
        lambda *args, **kwargs: "not-json",
    )

    result = reviewer(
        {
            "styled_output": "正常条件化分析，触发与失效条件齐全。" * 8,
            "claims": [],
            "_retry_count": 1,
        }
    )

    assert result["review_passed"] is False
    assert "reviewer_llm_failed" in result["review_notes"]
    assert result["_reviewer_error"] is True
    assert result["_retry_count"] == 2
    assert review_router(result) == "pass"
    assert result["review_passed"] is False


def test_reviewer_rejects_non_boolean_and_malformed_fields(monkeypatch):
    payloads = (
        '{"passed":"false","issues":[],"verified_claims":[]}',
        '{"passed":true,"issues":"not-a-list","verified_claims":[]}',
        '{"passed":true,"issues":[],"verified_claims":"claim-1"}',
    )
    for payload in payloads:
        monkeypatch.setattr(
            "qing_investment.agent.graph.nodes._safe_llm_invoke",
            lambda *args, **kwargs: payload,
        )
        result = reviewer(
            {
                "styled_output": "正常条件化分析，触发与失效条件齐全。" * 8,
                "claims": [],
            }
        )
        assert result["review_passed"] is False
        assert result["_reviewer_error"] is True
        assert "reviewer_contract_error" in result["review_notes"]


def test_short_output_review_uses_effective_failure_status(monkeypatch):
    monkeypatch.setattr(
        "qing_investment.agent.graph.nodes._safe_llm_invoke",
        lambda *args, **kwargs: '{"passed":true,"issues":[],"verified_claims":[]}',
    )

    result = reviewer({"styled_output": "短输出", "claims": []})

    assert result["review_passed"] is False
    assert result["confidence"] == "low"
    assert result["reasoning_steps"] == ["事实核查: 未通过"]


def test_terminal_generation_failures_skip_style_retry():
    failures = (
        {"_validation_contract_errors": ["bad schema"]},
        {"_fallback_reason": "llm_empty"},
        {"_scan_failed": True},
    )
    for context_key in ("market_context", "market_summary_context"):
        for failure in failures:
            state = {
                "review_passed": False,
                "_retry_count": 0,
                "review_notes": ["包含无条件买入指令"],
                context_key: failure,
            }
            assert review_router(state) == "pass"
            assert state["review_passed"] is False

    stock_failure = {
        "review_passed": False,
        "_retry_count": 0,
        "review_notes": ["stock_analysis_failed"],
        "_stock_analysis_failed": True,
    }
    assert review_router(stock_failure) == "pass"


class TestReviewRouter:
    def test_passes_when_review_passed(self):
        assert review_router({"review_passed": True}) == "pass"

    def test_force_pass_after_max_retries(self):
        assert review_router({"review_passed": False, "_retry_count": 2}) == "pass"

    def test_citation_only_issue_passes(self):
        assert (
            review_router(
                {
                    "review_passed": False,
                    "_retry_count": 0,
                    "review_notes": ["部分数据缺少 citation 来源"],
                }
            )
            == "pass"
        )

    def test_core_method_missing_still_fails(self):
        assert (
            review_router(
                {
                    "review_passed": False,
                    "_retry_count": 0,
                    "review_notes": ["核心方法论无来源"],
                }
            )
            == "fail"
        )

    def test_non_citation_issue_fails(self):
        assert (
            review_router(
                {
                    "review_passed": False,
                    "_retry_count": 0,
                    "review_notes": ["包含无条件买入指令"],
                }
            )
            == "fail"
        )
