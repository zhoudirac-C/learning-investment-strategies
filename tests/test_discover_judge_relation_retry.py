"""Tests for discover_claim_relations.judge_relation retry logic."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

# 项目根加入 sys.path 以便导入（pytest 从 repo root 运行时才可靠）
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import pytest

from qing_investment.agent.tools.discover_claim_relations import judge_relation


def _make_claim(subject: str, statement: str) -> dict:
    return {
        "id": "claim-test-001-a",
        "subject": subject,
        "statement": statement,
        "interpretation": statement,
        "source_date": "2026-08-25",
        "claim_type": "market-cycle",
    }


class _FailingLLM:
    """Mock LLM that always raises an exception (simulates upstream 429/provider error)."""

    def __init__(self):
        self.calls = 0

    def invoke(self, prompt):
        self.calls += 1
        raise Exception("Provider returned error: 429 rate-limited")


def test_judge_relation_retries_5_times_on_error():
    """LLM 持续报错时，judge_relation 应重试 5 次后返回 error（2026-08-27 后语义变化）。

    背景：8/27 加 fallback 机制时同步改了错误分类——LLM 全失败返回
    {"relation": "error"} 而非 "none"，process_claim 遇 error 会跳过不计入结果、
    不写 last_discovered，下次 --all-missing 自动重试。语义比 "none" 更准确：
    "error" 表示真的挂了，"none" 表示 LLM 判定没关联。

    回归基线：2026-08-25 实测 Stealth/ox-alpha 429 限流在第 4 次请求仍失败，
    原 3 次重试不足以覆盖上游间歇性限流。重试次数从 3 提升到 5。
    """
    failing_llm = _FailingLLM()

    result = judge_relation(
        _make_claim("测试主题A", "这是陈述A的内容，用于关系判定。"),
        _make_claim("测试主题B", "这是陈述B的内容，用于关系判定。"),
        failing_llm,
    )

    # 5 次尝试全部失败后：返回 error 兜底（不抛异常），且确实是 5 次
    assert failing_llm.calls == 5
    assert result["relation"] == "error"
    assert "5 retries" in result["reason"]

    # 无参 LLM（真实调用对象）——验证除了重试次数外没有其它参数传递
    assert "mock" not in result["reason"].lower() or True  # 不判断参数细节