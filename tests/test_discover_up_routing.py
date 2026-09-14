"""多 up 体系：discover 关系分流测试（2026-09-14）。

验证 judge_relation 按 up_id 分流：
  - 同 up  → supersedes / supplements / contradicts / none
  - 跨 up  → agrees / disagrees / supplements / none（禁止 supersedes/contradicts）
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from qing_investment.agent.tools.discover_claim_relations import (
    CROSS_UP_RELATIONS,
    SAME_UP_RELATIONS,
    is_same_up,
    judge_relation,
)


class FakeLLM:
    """返回预设 relation 的假 LLM，记录收到的 prompt。"""

    def __init__(self, relation: str, reason: str = "test"):
        self.relation = relation
        self.reason = reason
        self.last_prompt = ""

    def invoke(self, prompt):
        self.last_prompt = prompt

        class R:
            content = json.dumps({"relation": self.relation, "reason": self.reason})

        return R()


def _claim(cid, up_id, subject="半导体", statement="看多半导体"):
    return {
        "id": cid,
        "up_id": up_id,
        "up_name": f"up-{up_id}",
        "subject": subject,
        "statement": statement,
        "interpretation": "测试",
        "source_date": "2026-09-14",
        "claim_type": "sector-theme",
    }


# ── is_same_up ──────────────────────────────────────

def test_is_same_up_true_for_identical():
    assert is_same_up(_claim("a", "1420210197"), _claim("b", "1420210197")) is True


def test_is_same_up_false_for_different():
    assert is_same_up(_claim("a", "1420210197"), _claim("b", "9999999")) is False


def test_is_same_up_unknown_treated_as_same():
    """两边都缺 up_id → 保守视为同 up，避免误判为跨 up 分歧。"""
    a = _claim("a", None)
    b = _claim("b", None)
    a.pop("up_id")
    b.pop("up_id")
    assert is_same_up(a, b) is True


def test_is_same_up_missing_vs_present_is_different():
    a = _claim("a", None)
    a.pop("up_id")
    b = _claim("b", "1420210197")
    assert is_same_up(a, b) is False


def test_is_same_up_chanlun_virtual():
    assert is_same_up(_claim("a", "chanlun-original"), _claim("b", "chanlun-original")) is True


# ── 同 up 分支 ──────────────────────────────────────

def test_same_up_allows_supersedes():
    llm = FakeLLM("supersedes")
    r = judge_relation(_claim("a", "1420210197"), _claim("b", "1420210197"), llm)
    assert r["relation"] == "supersedes"
    assert r["same_up"] is True


def test_same_up_allows_contradicts():
    llm = FakeLLM("contradicts")
    r = judge_relation(_claim("a", "1420210197"), _claim("b", "1420210197"), llm)
    assert r["relation"] == "contradicts"
    assert r["same_up"] is True


def test_same_up_prompt_does_not_mention_cross_up():
    llm = FakeLLM("none")
    judge_relation(_claim("a", "1420210197"), _claim("b", "1420210197"), llm)
    assert "不同博主" not in llm.last_prompt
    assert "supersedes" in llm.last_prompt


# ── 跨 up 分支 ──────────────────────────────────────

def test_cross_up_allows_disagrees():
    llm = FakeLLM("disagrees")
    r = judge_relation(_claim("a", "1420210197"), _claim("b", "9999999"), llm)
    assert r["relation"] == "disagrees"
    assert r["same_up"] is False


def test_cross_up_allows_agrees():
    llm = FakeLLM("agrees")
    r = judge_relation(_claim("a", "1420210197"), _claim("b", "9999999"), llm)
    assert r["relation"] == "agrees"
    assert r["same_up"] is False


def test_cross_up_prompt_mentions_different_bloggers():
    llm = FakeLLM("none")
    judge_relation(_claim("a", "1420210197"), _claim("b", "9999999"), llm)
    assert "不同博主" in llm.last_prompt
    assert "disagrees" in llm.last_prompt


def test_cross_up_rejects_supersedes_downgraded_to_none():
    """跨 up 若 LLM 违规输出 supersedes → 降级为 none 并标注。"""
    llm = FakeLLM("supersedes", "违规输出")
    r = judge_relation(_claim("a", "1420210197"), _claim("b", "9999999"), llm)
    assert r["relation"] == "none"
    assert "越界" in r["reason"]


def test_cross_up_rejects_contradicts_downgraded_to_none():
    llm = FakeLLM("contradicts", "违规输出")
    r = judge_relation(_claim("a", "1420210197"), _claim("b", "9999999"), llm)
    assert r["relation"] == "none"
    assert "越界" in r["reason"]


def test_cross_up_allows_supplements():
    llm = FakeLLM("supplements")
    r = judge_relation(_claim("a", "1420210197"), _claim("b", "9999999"), llm)
    assert r["relation"] == "supplements"


# ── 关系集合定义 ────────────────────────────────────

def test_relation_sets_disjoint_on_authorship():
    """supersedes/contradicts 只能在同 up 集合里，agrees/disagrees 只能在跨 up 集合里。"""
    assert "supersedes" in SAME_UP_RELATIONS
    assert "contradicts" in SAME_UP_RELATIONS
    assert "supersedes" not in CROSS_UP_RELATIONS
    assert "contradicts" not in CROSS_UP_RELATIONS
    assert "agrees" in CROSS_UP_RELATIONS
    assert "disagrees" in CROSS_UP_RELATIONS
    assert "agrees" not in SAME_UP_RELATIONS
    assert "disagrees" not in SAME_UP_RELATIONS
    # supplements/none 两边都允许
    assert "supplements" in SAME_UP_RELATIONS and "supplements" in CROSS_UP_RELATIONS
    assert "none" in SAME_UP_RELATIONS and "none" in CROSS_UP_RELATIONS
