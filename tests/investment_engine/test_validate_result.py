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

    def test_first_violations_recorded_on_retry(self):
        """重试时记录首版违规清单（A/B 归因用）；未重试则无该字段。"""
        client = _mock_client([BAD_JSON, GOOD_JSON])
        _, _, validation = run_with_validation(
            MESSAGES, None, client=client, tag="t")
        assert any("规则15" in x for x in validation["first_violations"])

        client = _mock_client([GOOD_JSON])
        _, _, validation = run_with_validation(
            MESSAGES, None, client=client, tag="t")
        assert "first_violations" not in validation

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


class TestIndexLevelSanity:
    """规则26：指数点位须落在 pack 当日收盘价合理区间内。

    背景：2026-08-21 复盘盲判 invalidation 出现「跌破前低4588.7」——
    上证当日实际 3905 点附近，4588 为幻觉数字。机械校验：输出中出现的
    「上证指数/大盘」语境的千位级点位，若偏离 pack 任一主要指数当日
    收盘价 ±10% 以上且无法对齐任何指数近期价位，判为违规。
    """

    PACK = {"index": {
        "IDX000001": [{"d": "2026-08-21", "c": 3905.2}],
        "IDX399006": [{"d": "2026-08-21", "c": 3495.6}],
    }}

    def test_hallucinated_level_flagged(self):
        r = _result(invalidation=["上证指数跌破前低4588.7且放量，则震荡判断失效"])
        v = validate_result(r, pack=self.PACK)
        assert any("规则26" in x for x in v), v

    def test_realistic_level_pass(self):
        # 3850 距上证 3905 约 -1.4%，在容差内
        r = _result(invalidation=["上证指数跌破3850平台支撑则判断失效"])
        assert not any("规则26" in x for x in validate_result(r, pack=self.PACK))

    def test_level_near_other_index_pass(self):
        # 创业板指 3495 附近的点位也应合法（多指数对齐）
        r = _result(watch_next=["创业板指能否守住3480不破位"])
        assert not any("规则26" in x for x in validate_result(r, pack=self.PACK))

    def test_no_index_data_no_check(self):
        r = _result(invalidation=["上证指数跌破4588.7则失效"])
        assert not any("规则26" in x for x in validate_result(r, pack={}))


class TestDirectionClusterLimit:
    """规则27（v11）：方向同簇限选——directions 不得同簇多选。

    提案：framework/proposals/2026-08-24-pattern-direction-cluster-limit.md
    回归样本：2026-08-12（pcb/光通信/存储同选 C1，簇内回调 3 样本 2 miss）、
    2026-08-14（5G概念/存储芯片同选 C1，全 miss）。
    """

    def test_same_cluster_pool_ids_flagged(self):
        # 08-12 真实违规样本：pcb_ai_chain + optical_communication + memory_nor 同属 C1
        r = _result(directions=[
            {"direction_id": "pcb_ai_chain", "reason": "", "stocks": []},
            {"direction_id": "optical_communication", "reason": "", "stocks": []},
            {"direction_id": "memory_nor", "reason": "", "stocks": []},
        ])
        v = validate_result(r, pack={})
        assert any("规则27" in x and "C1" in x for x in v), v

    def test_same_cluster_freetext_flagged(self):
        # 08-14 真实违规样本：自由文本「5G概念」「存储芯片」按语义归簇 C1
        r = _result(directions=[
            {"direction_id": "5G概念", "reason": "", "stocks": []},
            {"direction_id": "存储芯片", "reason": "", "stocks": []},
        ])
        v = validate_result(r, pack={})
        assert any("规则27" in x for x in v), v

    def test_cross_cluster_pass(self):
        r = _result(directions=[
            {"direction_id": "pcb_ai_chain", "reason": "", "stocks": []},
            {"direction_id": "green_power_ai_electric", "reason": "", "stocks": []},
        ])
        assert not any("规则27" in x for x in validate_result(r, pack={}))

    def test_single_direction_pass(self):
        # 合规出口：其它簇无合格候选时只输出 1 条
        r = _result(directions=[
            {"direction_id": "pcb_ai_chain", "reason": "同簇限选，无其它簇合格候选",
             "stocks": []},
        ])
        assert validate_result(r, pack={}) == []

    def test_unclassifiable_direction_skipped(self):
        # 无法归簇的自由文本不参与校验（宁漏不误拦）
        r = _result(directions=[
            {"direction_id": "某全新题材", "reason": "", "stocks": []},
            {"direction_id": "另一个新题材", "reason": "", "stocks": []},
        ])
        assert not any("规则27" in x for x in validate_result(r, pack={}))

    def test_alias_priority_longer_keyword_first(self):
        # 「铜箔」须归 C1 而非被 C3 的「铜」截胡
        r = _result(directions=[
            {"direction_id": "铜箔概念", "reason": "", "stocks": []},
            {"direction_id": "煤炭", "reason": "", "stocks": []},
        ])
        assert not any("规则27" in x for x in validate_result(r, pack={}))
        r2 = _result(directions=[
            {"direction_id": "铜箔概念", "reason": "", "stocks": []},
            {"direction_id": "pcb_ai_chain", "reason": "", "stocks": []},
        ])
        assert any("规则27" in x for x in validate_result(r2, pack={}))


def _bars(closes):
    """收盘价序列 → pack index 块 compact bars（收盘价口径，同 _compact_bars）。"""
    return [{"d": f"2026-08-{i + 1:02d}", "c": c} for i, c in enumerate(closes)]


class TestPriceStructureVeto:
    """规则28（v12）：价格结构前置否决——双核心指数破位且收跌日禁止「缩量企稳」。

    合并裁决：framework/proposals/2026-08-30-pattern-price-structure-veto-merged.md
    （merged_from: 2026-08-24 / 2026-08-25 两份 pattern-patch）。
    回归样本：08-24-pre / 08-25 两单真实判错（调整日判震荡/缩量企稳）；
    假阳防护样本：08-20/08-21 磨底期（双破位但收涨，判震荡/缩量企稳是对的）。
    """

    # 上证指数/创业板指双破位（收盘 < MA5 且 < 近10根收盘低点）且当日收跌
    PACK_BROKEN_DOWN = {
        "index": {
            "IDX000001": _bars([4000, 3980, 3960, 3940, 3920, 3910,
                                3905, 3900, 3895, 3890, 3885, 3882]),
            "IDX399006": _bars([3600, 3580, 3560, 3540, 3520, 3510,
                                3500, 3490, 3480, 3470, 3460, 3432]),
        },
    }

    def test_broken_down_day_steady_nature_flagged(self):
        # 08-24-pre / 08-25 真实判错形态：双破位收跌日判「缩量企稳」
        r = _result(market_stage="震荡", nature="缩量企稳",
                    stage_reason="上涨家数修复，缩量企稳")
        v = validate_result(r, pack=self.PACK_BROKEN_DOWN)
        assert any("规则28" in x for x in v), v

    def test_broken_down_day_other_nature_passes(self):
        # 机械层只拦「缩量企稳」；其他 nature 的 stage 判断由 prompt 条文引导
        r = _result(market_stage="调整", nature="内生瓦解",
                    stage_reason="双指数破位下行")
        assert not any("规则28" in x for x in validate_result(r, pack=self.PACK_BROKEN_DOWN))

    def test_broken_but_up_day_passes(self):
        # 08-20/08-21 磨底期假阳防护：双破位但创业板指当日收涨，企稳判断允许
        pack = {"index": {
            "IDX000001": _bars([4000, 3980, 3960, 3940, 3920, 3910,
                                3905, 3900, 3895, 3890, 3885, 3895]),
            "IDX399006": _bars([3600, 3580, 3560, 3540, 3520, 3510,
                                3500, 3490, 3480, 3470, 3432, 3460]),
        }}
        r = _result(market_stage="震荡", nature="缩量企稳")
        assert not any("规则28" in x for x in validate_result(r, pack=pack))

    def test_single_index_broken_passes(self):
        # 08-26/08-28 形态：上证健康、仅创业板破位收跌——机械层不拦（宁漏不误拦）
        pack = {"index": {
            "IDX000001": _bars([3800, 3820, 3840, 3860, 3880, 3890,
                                3895, 3900, 3905, 3908, 3910, 3913]),
            "IDX399006": _bars([3600, 3580, 3560, 3540, 3520, 3510,
                                3500, 3490, 3480, 3470, 3460, 3432]),
        }}
        r = _result(market_stage="震荡", nature="缩量企稳")
        assert not any("规则28" in x for x in validate_result(r, pack=pack))

    def test_no_index_block_skipped(self):
        r = _result(nature="缩量企稳")
        assert validate_result(r, pack={}) == []

    def test_insufficient_bars_skipped(self):
        pack = {"index": {"IDX000001": _bars([100, 99, 98, 97, 96]),
                          "IDX399006": _bars([100, 99, 98, 97, 96])}}
        r = _result(nature="缩量企稳")
        assert not any("规则28" in x for x in validate_result(r, pack=pack))


class TestDualTrackCrossCheck:
    """规则5b（v13）：双轨互证——收盘与当日盘前预判不一致时必须写明推翻理由。

    来源：2026-08-30 周归因（08-24/08-25 两单错判均为一轨对一轨错，
    收盘轨无推翻说明义务）。
    """

    PM_PRE = {"premarket_today": {"date": "2026-08-25", "market_stage": "调整",
                                  "nature": "外力扰动", "stage_reason": "……"}}

    def test_divergence_without_override_reason_flagged(self):
        # 08-25 真实错判形态：盘前判调整、收盘改判震荡且未提盘前
        r = _result(market_stage="震荡", stage_reason="宽度修复，缩量企稳")
        v = validate_result(r, pack=self.PM_PRE)
        assert any("规则5b" in x for x in v), v

    def test_divergence_with_override_reason_passes(self):
        r = _result(market_stage="震荡",
                    stage_reason="盘前预判调整，但今日涨停65家宽度修复证伪盘前预判")
        assert not any("规则5b" in x for x in validate_result(r, pack=self.PM_PRE))

    def test_consistent_with_premarket_skipped(self):
        r = _result(market_stage="调整", stage_reason="指数破位下行")
        assert not any("规则5b" in x for x in validate_result(r, pack=self.PM_PRE))

    def test_no_premarket_block_skipped(self):
        r = _result(market_stage="震荡", stage_reason="量能温和")
        assert not any("规则5b" in x for x in validate_result(r, pack={}))



class TestRule26StockCodeRegression:
    """规则26 误报回归（2026-W36 周每日触发）：6 位股票代码被 \\d{4,5} 正则
    截取前 5 位误判为幻觉指数点位——国芳集团601086→60108、龙版传媒605577→60557、
    中际旭创300308→30030。与规则22（watch_next 必含个股级节点）直接冲突。

    提案：framework/proposals/2026-09-05-pattern-patch-blind-up-comparison-w36.md
    工程问题 1。
    """

    PACK = {"index": {
        "IDX000001": [{"d": "2026-09-04", "c": 3930.1}],
        "IDX399006": [{"d": "2026-09-04", "c": 3286.6}],
    }}

    def test_six_digit_stock_code_not_flagged(self):
        # 2026-09-04 真实误报：「60108」来自国芳集团（601086）
        r = _result(watch_next=[
            "国芳集团（601086，5板）今日能否晋级6板：封板则高位抱团仍有参照，断板则情绪退潮确认"])
        assert not any("规则26" in x for x in validate_result(r, pack=self.PACK))

    def test_six_digit_code_3xxxxx_not_flagged(self):
        # 2026-08-31 真实误报：「30030」来自中际旭创（300308）
        r = _result(watch_next=["中际旭创（300308）若补跌则外部冲击升级"])
        assert not any("规则26" in x for x in validate_result(r, pack=self.PACK))

    def test_hallucinated_level_still_flagged(self):
        # 原有拦截能力不退化：幻觉点位仍须捕获
        r = _result(invalidation=["上证指数跌破前低4588.7且放量，则震荡判断失效"])
        assert any("规则26" in x for x in validate_result(r, pack=self.PACK))

    def test_year_string_not_flagged(self):
        # 日期年份（2026）不应被当作指数点位
        r = _result(watch_next=["2026-09-05 观察创业板指能否收复3286"])
        assert not any("规则26" in x for x in validate_result(r, pack=self.PACK))


class TestRule31ExternalNatureEvidence:
    """规则31（v14，提案 2026-09-05 模式二）：nature=「外力扰动」但盘面无恐慌特征
    （跌停 ≤5 家）时，stage_reason 必须附盘面三证据鉴别（消息冲击/跌停家数/连板梯队），
    禁止把内生性回调记到隔夜外盘账上（2026-09-01/09-02 连续两单归因错误）。
    """

    CALM_PACK = {"emotion": {"daban": {"跌停": 0, "上涨家数": 3300}}}

    def test_external_nature_without_evidence_flagged(self):
        # 09-01 真实错法：引外盘下跌但无跌停/梯队盘面鉴别
        r = _result(nature="外力扰动",
                    stage_reason="隔夜费半-2.92%、美债10Y+8.6bp压制风险偏好，科技承压")
        v = validate_result(r, pack=self.CALM_PACK)
        assert any("规则31" in x for x in v), v

    def test_external_nature_with_evidence_pass(self):
        r = _result(nature="外力扰动",
                    stage_reason="外盘冲击成立（费半-2.92%）；盘面鉴别：跌停0家、"
                                 "连板梯队完整、无新消息冲击，仍判外力扰动因映射板块直接受压")
        assert not any("规则31" in x for x in validate_result(r, pack=self.CALM_PACK))

    def test_extreme_day_not_in_scope(self):
        # 跌停 ≥80 的情绪极端日由规则18 管辖，规则31 不叠加
        pack = {"emotion": {"daban": {"跌停": 118, "上涨家数": 449}}}
        r = _result(nature="外力扰动", stage_reason="强势股补跌、多杀多出现，流动性未见底")
        assert not any("规则31" in x for x in validate_result(r, pack=pack))

    def test_internal_nature_not_checked(self):
        r = _result(nature="内生瓦解", stage_reason="高位抱团断板，情绪内部瓦解")
        assert not any("规则31" in x for x in validate_result(r, pack=self.CALM_PACK))

    def test_no_emotion_data_skips(self):
        r = _result(nature="外力扰动", stage_reason="外盘大跌压制")
        assert not any("规则31" in x for x in validate_result(r, pack={}))
