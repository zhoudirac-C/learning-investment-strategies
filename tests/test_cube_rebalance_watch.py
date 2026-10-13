"""cube_rebalance_watch diff 清仓行显示股票名（2026-10-13 用户要求）。

根因：state 快照只存 symbol→weight，清仓标的已不在新持仓里拿不到名称。
修复：state 增加 names 映射，diff_holdings 清仓行从 old_names 取名。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "xueqiu_expert"))

from cube_rebalance_watch import diff_holdings  # noqa: E402


class TestClearedShowsName:
    def test_cleared_shows_name_from_old_names(self):
        old = {"SH600636": 10.0, "SZ000001": 5.0}
        new = {"SH600636": 10.0}
        names = {"SH600636": "风华高科"}          # 新持仓只有保留股的名
        old_names = {"SH600636": "风华高科", "SZ000001": "平安银行"}
        lines = diff_holdings(old, new, names, old_names=old_names)
        cleared = [l for l in lines if "清仓" in l]
        assert len(cleared) == 1
        assert "平安银行" in cleared[0] and "SZ000001" in cleared[0]

    def test_cleared_falls_back_to_symbol(self):
        """旧 state 无 names（升级前基线）→ 退回只显示代码，不报错。"""
        old = {"SZ000001": 5.0}
        new = {}
        lines = diff_holdings(old, new, {}, old_names=None)
        assert "清仓 SZ000001" in lines[0]

    def test_default_param_backward_compat(self):
        """不传 old_names（旧调用方式）不炸。"""
        lines = diff_holdings({"SZ000001": 5.0}, {}, {})
        assert any("清仓" in l for l in lines)
