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


class TestThreeSignalCheck:
    """规则18（v9）：情绪极端日判「调整/内生瓦解」必须先过三信号见底清单。

    提案：framework/proposals/2026-08-21-pattern-patch-blind-up-comparison.md
    回归样本：2026-08-20 早盘盲判真实 miss——跌停 118/上涨 449 极端日直接判
    「调整/内生瓦解」（真值=震荡），未做强势股补跌/多杀多/流动性见底检验。
    """

    EXTREME = {"emotion": {"daban": {"跌停": 118, "上涨家数": 449}}}

    def test_extreme_day_adjust_without_checklist_flagged(self):
        # 8-20-pre 真实 miss 形态：极端日只引内部情绪指标判内生瓦解
        r = _result(market_stage="调整", nature="内生瓦解",
                    stage_reason="上涨家数仅449家、跌停118家，涨停36家萎缩，"
                                 "连板高度降至3板，晋级率11.48%，属内生瓦解")
        v = validate_result(r, pack=self.EXTREME)
        assert any("规则18" in x for x in v), v

    def test_extreme_day_nature_collapse_also_flagged(self):
        r = _result(market_stage="震荡", nature="内生瓦解",
                    stage_reason="情绪退潮，梯队瓦解")
        v = validate_result(r, pack=self.EXTREME)
        assert any("规则18" in x for x in v), v

    def test_checklist_cited_passes(self):
        r = _result(market_stage="调整", nature="内生瓦解",
                    stage_reason="强势股补跌与多杀多已现，但放量下跌说明流动性未见底，"
                                 "按内生瓦解处理")
        assert not any("规则18" in x for x in validate_result(r, pack=self.EXTREME))

    def test_named_checklist_passes(self):
        r = _result(market_stage="调整",
                    stage_reason="按三信号见底清单逐条检验后判定仍在出清中")
        assert not any("规则18" in x for x in validate_result(r, pack=self.EXTREME))

    def test_extreme_day_neutral_verdict_skipped(self):
        r = _result(market_stage="震荡", nature="缩量企稳")
        assert validate_result(r, pack=self.EXTREME) == []

    def test_non_extreme_day_skipped(self):
        pack = {"emotion": {"daban": {"跌停": 10, "上涨家数": 3000}}}
        r = _result(market_stage="调整", stage_reason="指数破位下行")
        assert validate_result(r, pack=pack) == []

    def test_no_emotion_block_skipped(self):
        r = _result(market_stage="调整", stage_reason="缩量下行")
        assert validate_result(r, pack={}) == []


class TestCurrentStepAnchor:
    """规则15 v9 扩展：当前台阶锚定——守住/跌破当日（或前日）成交额量级合法。

    回归样本：2026-08-20 复盘盲判 watch_next「回升至24000亿以上」——量能下台阶
    阶段把确认线挂在上一台阶（当日 20793.6 亿），属自拍阈值；UP 式表述
    「守住 2 万亿台阶」合法。
    """

    PACK = {"emotion": {"daban": {"两市成交额_亿": 20793.6,
                                  "昨日两市成交额_亿": 25110.0}}}

    def test_hold_current_step_passes(self):
        r = _result(watch_next=["两市成交额(亿)能否守住20000亿关口"])
        assert validate_result(r, pack=self.PACK) == []

    def test_shrink_to_current_step_passes(self):
        # 8-20 复盘真实合规表述：萎缩至当前台阶下方（20000 ≈ 当日 20793.6）
        r = _result(scenarios=[{"name": "情形B",
                                "condition": "下一交易日成交额(亿)继续萎缩至20000以下，或涨停家数回落至50家以下",
                                "conclusion": "反弹乏力", "key": "情绪能否持续"}])
        assert validate_result(r, pack=self.PACK) == []

    def test_rebound_to_upper_step_still_flagged(self):
        # 8-20 复盘真实输出（无「亿」后缀逃逸形态）：回升至上台阶且无守住/跌破语境
        r = _result(
            scenarios=[{"name": "情形A",
                        "condition": "下一交易日两市成交额(亿)回升至24000以上，且涨停家数维持70家以上",
                        "conclusion": "情绪修复确认", "key": "量能是否配合"}],
            watch_next=["两市成交额(亿)能否回升至24000以上"])
        v = validate_result(r, pack=self.PACK)
        assert sum("规则15" in x and "24000" in x for x in v) == 2, v

    def test_break_far_below_step_flagged(self):
        r = _result(invalidation=["若成交额(亿)跌破17000亿则判断失效"])
        v = validate_result(r, pack=self.PACK)
        assert any("规则15" in x for x in v), v

    def test_anchor_without_pack_amounts_falls_back(self):
        r = _result(watch_next=["两市成交额(亿)能否守住20000亿关口"])
        v = validate_result(r, pack={})
        assert any("规则15" in x for x in v), v


class TestExternalAttribution:
    """规则24（v9）：外力/内生归因前置——pack 含外盘数据时输出必须引用外部链条。

    提案：framework/proposals/2026-08-19-pattern-patch-note.md（主轨，open）+
    2026-08-21-pattern-patch-blind-up-comparison.md（试点落地）。
    回归样本：2026-08-20 复盘盲判 pack 已含 global_macro/overnight_us，
    输出对外盘零引用（"数据在场≠数据被用"）。
    """

    PACK_GM = {"global_macro": {"美股三指数": {"道指": {"pct": 0.22}},
                                "美债收益率": {"10Y": {"yield": 4.653}}}}
    PACK_OVN = {"overnight_us": {"themes": [{"name": "算力", "stocks": [
        {"symbol": "NVDA", "pct_change": -0.99}]}]}}

    def test_external_data_present_but_unreferenced(self):
        v = validate_result(_result(), pack=self.PACK_GM)
        assert any("规则24" in x for x in v), v

    def test_overnight_only_also_triggers(self):
        v = validate_result(_result(), pack=self.PACK_OVN)
        assert any("规则24" in x for x in v), v

    def test_external_check_conclusion_passes(self):
        # 判非外力扰动也须注明外部链条检验结论
        r = _result(stage_reason="隔夜美股翻红、10Y 收益率回落 5bp，外部链条平稳，"
                                 "今日缩量企稳属内部存量博弈")
        assert validate_result(r, pack=self.PACK_GM) == []

    def test_reference_in_scenarios_counts(self):
        r = _result(scenarios=[{"name": "情形A", "condition": "今夜美股费半止跌",
                                "conclusion": "修复延续", "key": "外盘"}])
        assert not any("规则24" in x for x in validate_result(r, pack=self.PACK_GM))

    def test_no_external_blocks_skipped(self):
        assert validate_result(_result(), pack={}) == []
        assert validate_result(_result(), pack={"global_macro": {}}) == []


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


class TestMacroThreeConditions:
    """规则25：宏观三条件校验——global_macro 含美债数据时必须做宏观压制检验。

    背景：2026-08-21 盲判 vs UP 早盘对比。UP 用「美联储不动/油价<80/10Y<4.70%
    三条前置条件全部失效」给下跌定性质（宏观而非 AI 证伪）；盲判只报外盘涨跌
    数字、无框架校验，美债 4.70%/布油 93 未进结论。
    """

    def test_us10y_in_pack_requires_macro_check(self):
        pack = {"global_macro": {"美债收益率": {"10Y": {"yield": 4.696, "chg_bp": 4.3}}}}
        r = _result(stage_reason="隔夜美股下跌，预判震荡")
        v = validate_result(r, pack=pack)
        assert any("规则25" in x for x in v), v

    def test_macro_check_pass(self):
        pack = {"global_macro": {"美债收益率": {"10Y": {"yield": 4.696, "chg_bp": 4.3}}}}
        r = _result(stage_reason="宏观三条件检验：十年期美债4.70%回升，油价93超80美元线，"
                                 "美联储不动——三条前置条件均不成立，压制定性为宏观扰动而非AI证伪")
        assert not any("规则25" in x for x in validate_result(r, pack=pack))

    def test_no_macro_data_no_check(self):
        # 无 global_macro 或无美债字段 → 不强制
        assert not any("规则25" in x
                       for x in validate_result(_result(), pack={"global_macro": {}}))
        assert not any("规则25" in x for x in validate_result(_result(), pack={}))

    def test_non_yield_macro_only_not_flagged(self):
        # global_macro 只有股指、无收益率字段 → 三条件校验无从谈起，不强制
        pack = {"global_macro": {"美股三指数": {"纳指": {"pct": -1.0}}}}
        assert not any("规则25" in x for x in validate_result(_result(), pack=pack))
