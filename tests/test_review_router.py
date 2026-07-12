from qing_investment.agent.graph.edges import review_router


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
