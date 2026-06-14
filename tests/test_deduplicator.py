"""Tests for BilibiliClaimsDeduplicator.

覆盖场景:
- 全新 claims → 全部通过
- 重复 claims → 跳过
- 部分重复 → 部分通过
- 缓存持久化
- 缓存大小限制（50条）
"""

import json
import tempfile
from pathlib import Path

import pytest

from qing_investment.monitor.deduplicator import (
    BilibiliClaimsDeduplicator,
    DiffResult,
    deduplicate_bilibili_claims,
)


@pytest.fixture
def temp_cache():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


class TestBilibiliClaimsDeduplicator:

    def test_all_new_claims(self, temp_cache):
        claims = [
            {"claim_type": "market-cycle", "statement": "大盘处于磨底期"},
            {"claim_type": "sector-theme", "statement": "AI算力板块加速"},
        ]
        dedup = BilibiliClaimsDeduplicator(cache_dir=temp_cache)
        result = dedup.diff(claims)

        assert result.has_new is True
        assert len(result.new_claims) == 2
        assert len(result.skipped_claims) == 0

    def test_duplicate_claims_skipped(self, temp_cache):
        claims = [
            {"claim_type": "market-cycle", "statement": "大盘处于磨底期"},
        ]
        dedup = BilibiliClaimsDeduplicator(cache_dir=temp_cache)

        # 第一次
        result1 = dedup.diff(claims)
        assert result1.has_new is True
        assert len(result1.new_claims) == 1

        # 第二次（重复）
        result2 = dedup.diff(claims)
        assert result2.has_new is False
        assert len(result2.new_claims) == 0
        assert len(result2.skipped_claims) == 1

    def test_partial_duplicate(self, temp_cache):
        claims1 = [
            {"claim_type": "market-cycle", "statement": "大盘处于磨底期"},
        ]
        claims2 = [
            {"claim_type": "market-cycle", "statement": "大盘处于磨底期"},  # 重复
            {"claim_type": "sector-theme", "statement": "AI算力板块加速"},  # 新
        ]
        dedup = BilibiliClaimsDeduplicator(cache_dir=temp_cache)

        dedup.diff(claims1)
        result = dedup.diff(claims2)

        assert result.has_new is True
        assert len(result.new_claims) == 1
        assert result.new_claims[0]["claim_type"] == "sector-theme"
        assert len(result.skipped_claims) == 1

    def test_cache_persistence(self, temp_cache):
        claims = [
            {"claim_type": "market-cycle", "statement": "大盘处于磨底期"},
        ]
        # 第一次实例化
        dedup1 = BilibiliClaimsDeduplicator(cache_dir=temp_cache)
        dedup1.diff(claims)

        # 第二次实例化（从文件加载缓存）
        dedup2 = BilibiliClaimsDeduplicator(cache_dir=temp_cache)
        result = dedup2.diff(claims)

        assert result.has_new is False
        assert len(result.skipped_claims) == 1

    def test_cache_size_limit(self, temp_cache):
        dedup = BilibiliClaimsDeduplicator(cache_dir=temp_cache)
        dedup.MEMORY_CACHE_SIZE = 3  # 调小便于测试

        claims = [
            {"claim_type": "market-cycle", "statement": f"第{i}条"}
            for i in range(5)
        ]
        dedup.diff(claims)

        # 缓存应只保留最近 3 条
        assert len(dedup._memory_cache) == 3

        # 第 0 条应该被挤出缓存，再次传入视为新
        result = dedup.diff([claims[0]])
        assert result.has_new is True

    def test_fingerprint_normalization(self, temp_cache):
        """相同内容不同格式应被视为重复."""
        claims = [
            {"claim_type": "market-cycle", "statement": "大盘处于磨底期"},
            {"claim_type": "market-cycle", "statement": "大盘，处于磨底期！"},  # 标点不同
        ]
        dedup = BilibiliClaimsDeduplicator(cache_dir=temp_cache)
        result = dedup.diff(claims)

        assert result.has_new is True
        assert len(result.new_claims) == 1
        assert len(result.skipped_claims) == 1

    def test_diff_log_format(self, temp_cache):
        claims = [
            {"claim_type": "market-cycle", "statement": "大盘处于磨底期"},
        ]
        dedup = BilibiliClaimsDeduplicator(cache_dir=temp_cache)
        result = dedup.diff(claims)

        assert "B站 Claims Diff 结果" in result.diff_log
        assert "输入: 1 条" in result.diff_log
        assert "新:   1 条" in result.diff_log

    def test_convenience_function(self, temp_cache):
        claims = [
            {"claim_type": "market-cycle", "statement": "大盘处于磨底期"},
        ]
        result = deduplicate_bilibili_claims(claims, cache_dir=temp_cache)
        assert isinstance(result, DiffResult)
        assert result.has_new is True
