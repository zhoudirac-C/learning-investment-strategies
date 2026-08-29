"""M7-5：chan_plot.py 移植冒烟测试（引擎输出口径，不触网）。

chan_plot 是 skill 绘图脚本（K线+笔+中枢+买卖点+MACD）；M7-5 将其数据源
从旧简化算法管线移植到 RecursionEngine 输出。smoke：合成 klines → PNG 落盘。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PLOT = (Path(__file__).resolve().parents[2]
        / "skills/finance/chanlun-structure-analysis/scripts/chan_plot.py")
FIXTURE = Path(__file__).parent / "fixtures" / "mt512400_20260828.json"

matplotlib = pytest.importorskip("matplotlib")


@pytest.fixture(scope="module")
def cp():
    spec = importlib.util.spec_from_file_location("chan_plot", PLOT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _klines_from_fixture():
    data = json.loads(FIXTURE.read_text())
    # 60m 行 → 旧 kline dict 形态（date/open/close/high/low/vol）
    return [{"date": r["dt"], "open": r["open"], "close": r["close"],
             "high": r["high"], "low": r["low"], "vol": r["volume"] or 0}
            for r in data["m60"]]


def test_plot_smoke_engine_pipeline(cp, tmp_path):
    """引擎口径绘图：PNG 生成且非空；结构计数来自 NormalizedChart。"""
    out = tmp_path / "plot.png"
    cp.plot(_klines_from_fixture(), "sh512400 60m", str(out))
    assert out.exists() and out.stat().st_size > 10_000


def test_plot_struct_counts(cp, capsys):
    """绘图摘要行报告结构计数（中枢/买点来自引擎）。"""
    out = Path("/tmp") / "chan_plot_smoke.png"
    cp.plot(_klines_from_fixture(), "sh512400 60m", str(out))
    text = capsys.readouterr().out
    assert "中枢=" in text and "买点=" in text
    out.unlink()
