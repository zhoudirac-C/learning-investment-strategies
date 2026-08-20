"""盲判输出确定性校验层测试。

提案：framework/proposals/2026-08-18-fix-deterministic-output-validation.md
回归样本：2026-08-17 / 2026-08-18 两日真实违规输出（见当日归因）。
"""
from types import SimpleNamespace

from investment_engine.blindtest.replay import run_with_validation, validate_result


def _result(**over):
    base = {
        "market_stage": "震荡",
        "nature": "主动降速",
        "stage_reason": "量能温和，情绪平稳",
        "scenarios": [],
        "watch_next": [],
        "invalidation": [],
        "directions": [],
        "used_patterns": [],
        "operation": {"position": "反弹中段", "action": "持有观察", "basis": ""},
        "cycle_state": {"rebound_day": 5, "note": ""},
    }
    base.update(over)
    return base


class TestAbsoluteThreshold:
    """规则15：禁止自拍绝对成交额阈值。"""

    def test_20260818_real_violation(self):
        # 8-18 盘后盲判真实违规样本（规则15 反例原文数值）
        r = _result(scenarios=[{
            "name": "情形A",
            "condition": "下一交易日两市成交额(亿)维持24000亿以上且涨停家数回升至80家以上，创业板指收复3740点",
            "conclusion": "修复延续", "key": "量能",
        }])
        v = validate_result(r, pack={})
        assert any("规则15" in x and "24000" in x for x in v), v

    def test_20260817_real_violation_framework_band_without_keyword(self):
        # 8-17 真实违规样本：25000 亿属框架分档数值，但缺「确认位」语境仍算自拍阈值
        r = _result(scenarios=[{
            "name": "情形A",
            "condition": "成交额(亿)回升至25000亿以上+创业板指站稳3600点",
            "conclusion": "科技主线加强", "key": "量能",
        }])
        v = validate_result(r, pack={})
        assert any("规则15" in x and "25000" in x for x in v), v

    def test_relative_anchor_pass(self):
        # 8-18-pre 合规样本：前日量级相对口径
        r = _result(
            scenarios=[{"name": "情形A",
                        "condition": "今日分时量能确认放量（成交额(亿)守住前日量级且分时逐级放大）",
                        "conclusion": "延续", "key": "分时量能"}],
            watch_next=["两市成交额(亿)能否守住前日量级23875亿"],
        )
        assert validate_result(r, pack={}) == []

    def test_framework_band_with_keyword_pass(self):
        r = _result(watch_next=["成交额(亿)是否越过25000亿放量确认位"])
        assert validate_result(r, pack={}) == []

    def test_invalidation_scanned(self):
        r = _result(invalidation=["若成交额(亿)萎缩至22000亿以下则判断失效"])
        v = validate_result(r, pack={})
        assert any("规则15" in x for x in v), v


class TestReferenceCheck:
    """规则13/16/17：在场数据必须引用。"""

    PACK = {
        "limit_pool": {"ladder": {"4板": ["神奇制药"], "3板": ["中石科技"]}},
        "lhb": {"jgmmtj": {"净买入top5": [{"名称": "瑞丰高材"}], "净卖出top5": []}},
        "structure": {"科创50": {"60min": {"top": {"state": "divergence",
                                                  "time": "2026-08-18 10:30"}}}},
    }

    def test_ladder_present_but_not_referenced(self):
        v = validate_result(_result(), pack=self.PACK)
        assert any("规则16" in x for x in v), v

    def test_jgmmtj_present_but_not_referenced(self):
        v = validate_result(_result(), pack=self.PACK)
        assert any("规则13" in x for x in v), v

    def test_structure_divergence_not_referenced(self):
        v = validate_result(_result(), pack=self.PACK)
        assert any("规则17" in x for x in v), v

    def test_references_satisfied(self):
        r = _result(
            stage_reason="机构净买入集中于瑞丰高材等少数标的，情绪背离指数",
            watch_next=["首板家数与晋级率", "科创50 60分钟顶部钝化是否确认"],
        )
        assert validate_result(r, pack=self.PACK) == []

    def test_jgmmtj_stock_name_counts_as_reference(self):
        pack = {"lhb": {"jgmmtj": {"净买入top5": [{"名称": "瑞丰高材"}],
                                   "净卖出top5": []}}}
        r = _result(stage_reason="瑞丰高材获席位净买入居前")
        assert not any("规则13" in x for x in validate_result(r, pack=pack))

    def test_empty_blocks_skip(self):
        pack = {"limit_pool": {"ladder": {}}, "lhb": {"jgmmtj": {}}, "structure": {}}
        assert validate_result(_result(), pack=pack) == []

    def test_no_pack_skips_reference_checks(self):
        assert validate_result(_result()) == []


class TestConsistencyCheck:
    """规则11a + 规则10/12 机械化。"""

    def test_20260817_evening_contradiction(self):
        # 8-17 晚间真实违规：判主升同时 operation 写获利了结降仓位
        r = _result(market_stage="主升",
                    operation={"position": "反弹超预期",
                               "action": "获利了结、降仓位、不急着表态", "basis": ""})
        v = validate_result(r, pack={})
        assert any("规则11" in x for x in v), v

    def test_same_action_under_neutral_stage_passes(self):
        r = _result(operation={"position": "反弹超预期",
                               "action": "获利了结、降仓位", "basis": ""})
        assert validate_result(r, pack={}) == []

    def test_intraday_surge_fade_forbids_volume_attack(self):
        pack = {"intraday_amount": {"形态": "冲量滑落（全天缩量）"}}
        r = _result(market_stage="震荡", nature="放量攻击")
        v = validate_result(r, pack=pack)
        assert any("规则10/12" in x for x in v), v

    def test_intraday_surge_fade_with_sound_nature_passes(self):
        pack = {"intraday_amount": {"形态": "冲量滑落（全天缩量）"}}
        assert validate_result(_result(), pack=pack) == []


def _mock_client(payloads):
    class _C:
        def __init__(self):
            self.calls = 0

        @property
        def chat(self):
            return self

        @property
        def completions(self):
            return self

        def create(self, **kw):
            payload = payloads[min(self.calls, len(payloads) - 1)]
            self.calls += 1
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=payload))],
                usage=None)
    return _C()


import json

BAD_JSON = json.dumps({
    "market_stage": "震荡", "nature": "主动降速",
    "stage_reason": "情绪退潮",
    "scenarios": [{"name": "情形A", "condition": "成交额(亿)维持24000亿以上",
                   "conclusion": "修复", "key": "量能"}],
    "watch_next": [], "invalidation": [], "directions": [],
    "used_patterns": [],
    "operation": {"position": "反弹超预期", "action": "持有", "basis": ""},
    "cycle_state": {},
}, ensure_ascii=False)

GOOD_JSON = json.dumps({
    "market_stage": "震荡", "nature": "主动降速",
    "stage_reason": "情绪退潮，量能守住前日量级",
    "scenarios": [{"name": "情形A", "condition": "成交额(亿)守住前日量级且涨停回升",
                   "conclusion": "修复", "key": "量能"}],
    "watch_next": [], "invalidation": [], "directions": [],
    "used_patterns": [],
    "operation": {"position": "反弹超预期", "action": "持有", "basis": ""},
    "cycle_state": {},
}, ensure_ascii=False)

MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


class TestRunWithValidation:
    def test_compliant_single_call(self):
        client = _mock_client([GOOD_JSON])
        raw, result, validation = run_with_validation(
            MESSAGES, None, client=client, call_fn=None, tag="t")
        assert client.calls == 1
        assert validation == {"status": "passed", "violations": [], "retried": False}
        assert result["market_stage"] == "震荡"

    def test_retry_once_then_pass(self):
        client = _mock_client([BAD_JSON, GOOD_JSON])
        raw, result, validation = run_with_validation(
            MESSAGES, None, client=client, tag="t")
        assert client.calls == 2
        assert validation["status"] == "passed"
        assert validation["retried"] is True
        assert "24000" not in result["scenarios"][0]["condition"]

    def test_persistent_violation_marked_failed_not_masked(self):
        client = _mock_client([BAD_JSON, BAD_JSON])
        raw, result, validation = run_with_validation(
            MESSAGES, None, client=client, tag="t")
        assert client.calls == 2
        assert validation["status"] == "failed"
        assert any("规则15" in x for x in validation["violations"])
        # 违规输出仍如实落盘，不掩盖
        assert result["scenarios"][0]["condition"].find("24000") >= 0


class TestStructureSignalRecency:
    """规则17 时效窗口：陈旧信号不强制引用（数据仍留在包内）。"""

    def test_stale_invalidated_not_flagged(self):
        # 8-18 实测：创业板指 daily 残留 2026-06-25 invalidated → 不强制引用
        pack = {"date": "2026-08-18",
                "structure": {"创业板指": {"daily": {"top": {"state": "invalidated",
                                                             "time": "2026-06-25"}}}}}
        assert not any("规则17" in x for x in validate_result(_result(), pack=pack))

    def test_fresh_invalidated_flagged(self):
        pack = {"date": "2026-08-18",
                "structure": {"上证指数": {"60min": {"top": {"state": "invalidated",
                                                            "time": "2026-08-15 14:00"}}}}}
        assert any("规则17" in x for x in validate_result(_result(), pack=pack))

    def test_no_date_means_no_filter(self):
        pack = {"structure": {"上证指数": {"60min": {"top": {"state": "divergence",
                                                            "time": "2026-06-25"}}}}}
        assert any("规则17" in x for x in validate_result(_result(), pack=pack))
