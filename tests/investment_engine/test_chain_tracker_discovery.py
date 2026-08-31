"""发现引擎纯逻辑测试（T17 触发过滤 / T18 prompt+解析 / T19 提议去重）。"""
import json

import pytest

from investment_engine.chain_tracker.discovery import (
    TRIGGER_KEYWORDS, build_discovery_messages, filter_duplicate_proposals,
    is_discovery_candidate, parse_discovery,
)


def _item(title: str, *, source: str = "report", info_id: str = "X1") -> dict:
    return {"info_id": info_id, "source": source, "title": title,
            "published_at": "2026-08-31", "stock_code": None, "stock_name": None,
            "industry_name": "电子", "org": "测试证券", "url": None,
            "chain_ids": []}


def _proposal(**over) -> dict:
    base = {
        "chain_id": "solid-state-battery",
        "name": "固态电池产业链",
        "driver": "硫化物电解质量产 + 车企装车验证",
        "thesis": "电解质技术突破 → 中试线投产 → 车企定点 → 材料体系重构",
        "chain": {
            "upstream": {"materials": ["硫化锂", "锗"], "key_nodes": [], "stocks": []},
            "midstream": {"materials": ["电解质膜"], "key_nodes": [], "stocks": []},
            "downstream": {"materials": ["整车"], "key_nodes": [], "stocks": []},
        },
        "current_stage": "阶段1-启动期",
        "timing": "上游材料（弹性最大）",
        "confidence": "中",
        "source": "测试证券研报",
    }
    base.update(over)
    return base


class TestTrigger:
    @pytest.mark.parametrize("kw", TRIGGER_KEYWORDS)
    def test_each_keyword_triggers(self, kw):
        assert is_discovery_candidate(_item(f"某某行业{kw}观察"))

    def test_plain_title_not_candidate(self):
        assert not is_discovery_candidate(_item("某公司半年报点评"))

    def test_notice_with_keyword_is_candidate(self):
        assert is_discovery_candidate(
            _item("关于投建扩产项目的公告", source="notice", info_id="AN1"))

    def test_empty_title_not_candidate(self):
        assert not is_discovery_candidate(_item(""))


class TestBuildMessages:
    def test_prompt_contains_existing_chains_pending_and_items(self):
        chains = [{"chain_id": "ai-pcb-ccl", "name": "AI PCB/CCL 产业链",
                   "driver": "Rubin代际升级"}]
        pending = [_proposal()]
        items = [_item("钠离子电池深度：层状氧化物突围", info_id="AP1")]
        msgs = build_discovery_messages(chains, pending, items)
        assert msgs[0]["role"] == "system"
        user = msgs[1]["content"]
        assert "ai-pcb-ccl" in user and "AI PCB/CCL 产业链" in user  # 已有链清单
        assert "solid-state-battery" in user  # pending 清单（避免重复提议）
        assert "钠离子电池深度" in user  # 新信息
        assert "proposals" in user
        # 2026-08-31 回放校准：单家公司与置信度硬约束必须在 prompt 里
        assert "产业链级证据" in user
        assert "独立来源" in user

    def test_prompt_truncates_long_batch(self):
        items = [_item(f"涨价专题{i}", info_id=f"AP{i}") for i in range(100)]
        msgs = build_discovery_messages([], [], items, max_items=40)
        assert msgs[1]["content"].count("info_id=") <= 40


class TestParseDiscovery:
    def test_parse_proposals_list(self):
        raw = json.dumps({"proposals": [_proposal()]}, ensure_ascii=False)
        out = parse_discovery(raw)
        assert len(out) == 1
        assert out[0]["chain_id"] == "solid-state-battery"

    def test_empty_proposals(self):
        assert parse_discovery('{"proposals": []}') == []

    def test_tolerates_markdown_fence(self):
        raw = "```json\n" + json.dumps({"proposals": [_proposal()]},
                                       ensure_ascii=False) + "\n```"
        assert len(parse_discovery(raw)) == 1

    def test_accepts_bare_list_and_single_object(self):
        assert len(parse_discovery(json.dumps([_proposal()],
                                              ensure_ascii=False))) == 1
        assert len(parse_discovery(json.dumps(_proposal(),
                                              ensure_ascii=False))) == 1

    def test_invalid_chain_id_dropped(self):
        raw = json.dumps({"proposals": [_proposal(chain_id="固态电池!")]},
                         ensure_ascii=False)
        assert parse_discovery(raw) == []

    def test_missing_required_field_dropped(self):
        p = _proposal()
        del p["driver"]
        assert parse_discovery(json.dumps({"proposals": [p]},
                                          ensure_ascii=False)) == []

    def test_invalid_stage_and_confidence_normalized(self):
        raw = json.dumps({"proposals": [_proposal(current_stage="阶段9-飞天",
                                                  confidence="爆表")]},
                         ensure_ascii=False)
        out = parse_discovery(raw)
        assert out[0]["current_stage"] == "阶段0-观察"
        assert out[0]["confidence"] == "中"

    def test_non_dict_chain_normalized_to_empty(self):
        raw = json.dumps({"proposals": [_proposal(chain="上游下游")]},
                         ensure_ascii=False)
        assert parse_discovery(raw)[0]["chain"] == {}

    def test_non_json_raises(self):
        with pytest.raises(ValueError):
            parse_discovery("这不是JSON")


class TestFilterDuplicates:
    def test_skip_existing_chain_id_and_name(self):
        chains = [_proposal(chain_id="solid-state-battery")]
        kept, skipped = filter_duplicate_proposals([_proposal()], chains, [])
        assert kept == [] and len(skipped) == 1
        # 名称撞已有链也跳过
        kept, skipped = filter_duplicate_proposals(
            [_proposal(chain_id="new-id")], chains, [])
        assert kept == [] and len(skipped) == 1

    def test_skip_pending(self):
        kept, skipped = filter_duplicate_proposals(
            [_proposal()], [], [_proposal()])
        assert kept == [] and len(skipped) == 1

    def test_skip_in_batch_duplicates(self):
        kept, skipped = filter_duplicate_proposals(
            [_proposal(), _proposal()], [], [])
        assert len(kept) == 1 and len(skipped) == 1

    def test_keep_genuinely_new(self):
        kept, skipped = filter_duplicate_proposals(
            [_proposal()], [{"chain_id": "ai-pcb-ccl", "name": "AI PCB/CCL 产业链"}],
            [])
        assert len(kept) == 1 and skipped == []
