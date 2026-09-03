"""测试套件级安全网：隔离 daily_state 持久化路径。

背景（2026-08-31 事故）：全图测试（test_qing_agent_monitor_workflow.py）
未隔离 daily_state 持久化，FakeLLM 的 canned 输出写入生产文件
config/stock_monitor/daily_state.json，污染当日收盘复盘。

load_daily_state / save_daily_state / archive_daily_state 在调用时读取模块级
DEFAULT_STATE_PATH，因此这里重定向该变量即可对所有调用方生效——包括
worktree 场景（repo_root() 在 worktree 中会解析回主仓库，只有显式
重定向才能保证测试不写主仓库的真实文件）。

回归守护：tests/test_daily_state_isolation.py
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_daily_state_path(tmp_path, monkeypatch):
    """把 daily_state 默认路径重定向到每个测试独立的临时目录。"""
    from qing_investment.agent.tools import daily_state as ds

    monkeypatch.setattr(ds, "DEFAULT_STATE_PATH", tmp_path / "daily_state.json")
