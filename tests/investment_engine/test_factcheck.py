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


class TestUnknownNameClaims:
    """反向提取：输出中「X涨停」的 X 不在涨停池也应报错（2026-08-21 江海股份案例）。

    旧逻辑只遍历已知名单（涨停池∪pack stocks），江海股份两者皆不在 → 漏检。
    """

    def _pool(self, tmp_path):
        p = tmp_path / "20260821.json"
        p.write_text(json.dumps(
            {"zt_items": [{"name": "星网锐捷", "lbc": 1}]}), encoding="utf-8")
        return tmp_path

    def test_unknown_stock_limit_up_claim_flagged(self, tmp_path):
        r = {"directions": [{"direction_id": "元器件",
                             "reason": "江海股份涨停、华正新材大涨", "stocks": []}]}
        errors = check_prediction(r, "2026-08-21", lp_root=self._pool(tmp_path))
        assert any("江海股份" in e for e in errors), errors

    def test_context_words_not_flagged(self, tmp_path):
        # 非股票语境词 + 涨停 不应误报
        r = {"stage_reason": "情绪修复涨停家数回升，竞价封板减少，批量涨停未现"}
        assert check_prediction(r, "2026-08-21", lp_root=self._pool(tmp_path)) == []

    def test_known_pool_name_still_validated(self, tmp_path):
        r = {"stage_reason": "星网锐捷2连板"}
        errors = check_prediction(r, "2026-08-21", lp_root=self._pool(tmp_path))
        assert any("星网锐捷" in e and "1 连板" in e for e in errors), errors

    def test_negation_still_skipped(self, tmp_path):
        r = {"stage_reason": "江海股份未涨停，仅涨7%"}
        assert check_prediction(r, "2026-08-21", lp_root=self._pool(tmp_path)) == []


class TestQuestionPhraseRegression:
    """疑问语段误报回归（2026-W36 周）：watch_next「国芳集团…是否继续封板」
    被反向提取出「是否继续」当股票名报「涨停池无 是否继续」。

    提案：framework/proposals/2026-09-05-pattern-patch-blind-up-comparison-w36.md
    工程问题 2。
    """

    def _pool(self, tmp_path):
        p = tmp_path / "20260904.json"
        p.write_text(json.dumps(
            {"zt_items": [{"name": "国芳集团", "lbc": 5}]}), encoding="utf-8")
        return tmp_path

    def test_shifou_jixu_not_flagged(self, tmp_path):
        r = {"watch_next": ["国芳集团（5板）是否继续封板：封板则高位抱团仍有参照，断板则退潮"]}
        assert check_prediction(r, "2026-09-04", lp_root=self._pool(tmp_path)) == []

    def test_nengfou_jixu_not_flagged(self, tmp_path):
        r = {"watch_next": ["国芳集团能否继续封板是今日情绪锚"]}
        assert check_prediction(r, "2026-09-04", lp_root=self._pool(tmp_path)) == []

    def test_real_stock_claim_still_caught(self, tmp_path):
        # 拦截能力不退化：真实幻觉个股声明仍须捕获
        r = {"watch_next": ["江海股份涨停带动板块"]}
        errors = check_prediction(r, "2026-09-04", lp_root=self._pool(tmp_path))
        assert any("江海股份" in e for e in errors), errors
