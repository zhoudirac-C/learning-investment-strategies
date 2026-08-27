"""_direction_members 第三级回退测试：中文名方向 → 证监会行业 → stock_sector_mapping。

背景：盲判 LLM 偶尔输出中文名方向（银行/煤炭/医药/通信设备，2026-08-19/20 实测），
不在 TDX 概念板块和 direction_pool 内 → 成员空 → 方向评分 samples=0 静默失明。
修复：_direction_members 加第三级回退，读 config/stock_monitor/industry_alias.yaml
同义词映射 + stock_sector_mapping.json（每日 cron 刷新）反查行业成分股。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCORE_PATH = REPO_ROOT / "src" / "investment_engine" / "blindtest" / "score.py"


@pytest.fixture(scope="module")
def score_mod():
    spec = importlib.util.spec_from_file_location("score_under_test", SCORE_PATH)
    m = importlib.util.module_from_spec(spec)
    sys.modules["score_under_test"] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def fixture_env(tmp_path, monkeypatch):
    """合成 config_dir + industry_alias.yaml + stock_sector_mapping.json。"""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    (config_dir / "industry_alias.yaml").write_text(
        "银行: 货币金融服务\n"
        "煤炭: 煤炭开采和洗选业\n"
        "通信设备: 计算机、通信和其他电子设备制造业\n",
        encoding="utf-8",
    )
    mapping = {
        "600036": [{"board_type": "industry", "name": "货币金融服务"}],
        "601398": [{"board_type": "industry", "name": "货币金融服务"}],
        "601988": [{"board_type": "industry", "name": "货币金融服务"}],
        "601088": [{"board_type": "industry", "name": "煤炭开采和洗选业"}],
        "002491": [{"board_type": "industry", "name": "计算机、通信和其他电子设备制造业"}],
    }
    (config_dir / "stock_sector_mapping.json").write_text(
        json.dumps({"_built_at": 0, "mapping": mapping}, ensure_ascii=False),
        encoding="utf-8",
    )
    return config_dir


class TestIndustryAliasFallback:
    def test_alias_exact_lookup(self, score_mod, fixture_env):
        """中文名方向经 alias 精确匹配证监会行业名，反查出成分股。"""
        members = score_mod._direction_members(str(fixture_env), "银行")
        assert sorted(members) == ["600036", "601398", "601988"]

    def test_nonexistent_direction_returns_empty(self, score_mod, fixture_env):
        """映射表和概念板块都没有的方向仍返回空（宁缺勿滥，不编造成分）。"""
        members = score_mod._direction_members(str(fixture_env), "不存在的方向")
        assert members == []

    def test_fallback_only_after_concept_and_pool_miss(self, score_mod, fixture_env, monkeypatch):
        """前两级命中时不走第三级：sector_members 命中优先。"""
        # mock 第一级命中"芯片"
        monkeypatch.setattr(
            "investment_engine.blindtest.dataset._load_sector_members",
            lambda: {"芯片": ["000001"]},
        )
        members = score_mod._direction_members(str(fixture_env), "芯片")
        assert members == ["000001"]


class TestEndToEnd819:
    def test_bank_direction_now_scoreable(self, score_mod, fixture_env):
        """端到端回归：8-19 盲判输出的「煤炭」方向现在能解析出成分股。"""
        members = score_mod._direction_members(str(fixture_env), "煤炭")
        assert members == ["601088"]
