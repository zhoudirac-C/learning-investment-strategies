"""M7-1 分钟数据层真实拉取验收（live：触网，常规套件不跑）。

固化「抓取 → 落库 → 复读一致」链路（评审 Minor：验收证据须可重放）。
运行：.venv/bin/python -m pytest -m live tests/chan_engine/test_data_minute_live.py
"""
from __future__ import annotations

import pytest

from chan_engine.data import fetch_minute, load_bars, load_minute, save_minute

pytestmark = pytest.mark.live


@pytest.mark.parametrize("tf", [60, 30])
def test_fetch_save_reload_roundtrip(tf, tmp_path):
    db = tmp_path / "chan_bars.db"
    rows, source = fetch_minute("sh512400", tf)
    assert source in ("sina", "tdx")
    assert len(rows) > 200  # datalen=260 窗口（停牌裁剪除外）

    n = save_minute("sh512400", tf, rows, source=source, db_path=db)
    assert n == len(rows)
    # 幂等：重存行数不变
    assert save_minute("sh512400", tf, rows, source=source, db_path=db) == len(rows)

    back = load_minute("sh512400", tf, db_path=db)
    expected_dts = [r["dt"] for r in rows if r["complete"] == 1]
    assert [r["dt"] for r in back] == expected_dts  # 默认剔除未完成 bar

    bars = load_bars("sh512400", tf=tf, db_path=db)
    assert len(bars) == len(expected_dts)
    assert [b.ts for b in bars] == list(range(len(bars)))
    complete_rows = [r for r in rows if r["complete"] == 1]
    assert bars[-1].c == complete_rows[-1]["close"]
