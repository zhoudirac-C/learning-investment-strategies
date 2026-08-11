"""影子预测硬事实校验测试。"""
import json
import tempfile
from pathlib import Path

from investment_engine.shadow.factcheck import check_prediction


def _lp_dir() -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "20260630.json").write_text(json.dumps({
        "date": "2026-06-30",
        "zt_items": [{"code": "603758", "name": "秦安股份", "lbc": 3},
                     {"code": "002826", "name": "首板股", "lbc": 1}],
        "zb_items": [],
    }, ensure_ascii=False), encoding="utf-8")
    return root


class TestCheckPrediction:
    def setup_method(self):
        self.lp = _lp_dir()

    def test_fake_limit_up_caught(self):
        # 风华高科不在当日涨停池（2026-08-11 真实幻觉案例）
        result = {"directions": [{"reason": "风华高科涨停且封板资金大"}]}
        errors = check_prediction(result, "2026-06-30",
                                  extra_names=["风华高科"], lp_root=self.lp)
        assert len(errors) == 1 and "风华高科" in errors[0]

    def test_correct_lianban_passes(self):
        result = {"directions": [{"reason": "秦安股份3连板，梯队完整"}]}
        assert check_prediction(result, "2026-06-30", lp_root=self.lp) == []

    def test_wrong_lianban_caught(self):
        result = {"stage_reason": "秦安股份2连板"}
        errors = check_prediction(result, "2026-06-30", lp_root=self.lp)
        assert len(errors) == 1 and "实际为 3 连板" in errors[0]

    def test_first_board_claim_passes(self):
        result = {"stage_reason": "首板股涨停，低位新题材"}
        assert check_prediction(result, "2026-06-30", lp_root=self.lp) == []

    def test_negation_skipped(self):
        result = {"stage_reason": "风华高科未涨停，仅涨5%"}
        assert check_prediction(result, "2026-06-30",
                                extra_names=["风华高科"], lp_root=self.lp) == []

    def test_no_pool_data_skips(self):
        result = {"stage_reason": "任何股涨停"}
        assert check_prediction(result, "2026-01-01", lp_root=self.lp) == []
