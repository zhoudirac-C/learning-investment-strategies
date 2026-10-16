#!/usr/bin/env python3
"""gator 公众号抓取钩子（并入 B站任务）的时间门控与幂等测试。

背景：2026-10-16 用户拍板把原独立 23:00「公众号抓取」cron 并入「B站多UP动态监控」
任务（每 5 分钟跑一次）。钩子必须满足：
  1. 只在 18:00 窗口内触发（默认 [18:00, 18:30)），窗口外一律不跑
  2. 同一自然日只触发一次（幂等），且**先写标记再调用**（失败不重试）
  3. `--check-only` / `--uid` / `--backfill` 等只读模式不触发
  4. 抓取子进程 stdout 透传到本进程 stdout（供 no_agent watchdog 投递）

运行：.venv/bin/python -m pytest tests/test_bilibili_notify_gator_hook.py -q
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "bilibili_notify.py"


def _load_module():
    """独立加载 bilibili_notify 模块（不通过包导入，脚本无 __init__）。"""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("bilibili_notify_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bilibili_notify_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mod(tmp_path, monkeypatch):
    m = _load_module()
    # 隔离：标记文件写到 tmp，抓取入口用假对象，subprocess.run 打桩
    m._GATOR_DAILY_MARKER = tmp_path / "gator_fetch_last_run.txt"

    class _FakeEntry:
        def exists(self) -> bool:
            return True

        def __str__(self) -> str:
            return "/fake/qing_fetch_wechat_mp.py"

    m._GATOR_FETCH_ENTRY = _FakeEntry()
    m._gator_calls = []

    class _Result:
        returncode = 0
        stdout = "NEW_ARTICLE: /x/y.md"
        stderr = ""

    def _fake_run(cmd, **kwargs):
        m._gator_calls.append(cmd)
        return _Result()

    import subprocess as _sp

    monkeypatch.setattr(_sp, "run", _fake_run)
    return m


def _at(h: int, mi: int) -> datetime:
    return datetime(2026, 10, 16, h, mi, 0)


def test_outside_window_does_not_run(mod):
    assert mod.maybe_run_gator_fetch(_at(17, 55)) is False
    assert mod.maybe_run_gator_fetch(_at(18, 30)) is False
    assert mod.maybe_run_gator_fetch(_at(12, 0)) is False
    assert mod._gator_calls == []


def test_inside_window_runs_once(mod):
    assert mod.maybe_run_gator_fetch(_at(18, 0)) is True
    assert len(mod._gator_calls) == 1


def test_idempotent_same_day(mod):
    assert mod.maybe_run_gator_fetch(_at(18, 0)) is True
    # 同一天窗口内的后续 tick 不再触发
    assert mod.maybe_run_gator_fetch(_at(18, 5)) is False
    assert mod.maybe_run_gator_fetch(_at(18, 25)) is False
    assert len(mod._gator_calls) == 1


def test_marker_written_before_call(mod, monkeypatch):
    """先写标记再调用：即使子进程抛异常，同日第二次也不会重跑。"""
    import subprocess as _sp

    def _boom(cmd, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(_sp, "run", _boom)
    assert mod.maybe_run_gator_fetch(_at(18, 1)) is True  # 已尝试
    assert mod._GATOR_DAILY_MARKER.read_text().strip() == "2026-10-16"
    # 换回正常 run，同日仍不触发
    monkeypatch.undo()
    assert mod.maybe_run_gator_fetch(_at(18, 10)) is False


def test_next_day_runs_again(mod):
    assert mod.maybe_run_gator_fetch(_at(18, 0)) is True
    nxt = datetime(2026, 10, 17, 18, 0)
    assert mod.maybe_run_gator_fetch(nxt) is True
    assert len(mod._gator_calls) == 2
    assert mod._GATOR_DAILY_MARKER.read_text().strip() == "2026-10-17"


def test_gate_window_env_override(mod, monkeypatch):
    monkeypatch.setenv("GATOR_FETCH_AT", "09:15")
    assert mod._gator_gate_window() == (9, 15)
    assert mod.maybe_run_gator_fetch(_at(9, 20)) is True
    assert len(mod._gator_calls) == 1


def test_bad_env_falls_back_to_default(mod, monkeypatch):
    monkeypatch.setenv("GATOR_FETCH_AT", "garbage")
    assert mod._gator_gate_window() == (18, 0)


def test_stdout_is_forwarded(mod, capsys):
    mod.maybe_run_gator_fetch(_at(18, 0))
    out = capsys.readouterr().out
    assert "NEW_ARTICLE: /x/y.md" in out


def test_missing_entry_skips(mod):
    class _Missing:
        def exists(self) -> bool:
            return False

        def __str__(self) -> str:
            return "/nope/missing.py"

    mod._GATOR_FETCH_ENTRY = _Missing()
    assert mod.maybe_run_gator_fetch(_at(18, 0)) is False
    assert mod._gator_calls == []
