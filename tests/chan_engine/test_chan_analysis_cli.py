"""M7-5：chan_analysis.py 薄壳 CLI 兼容测试（mock 数据层，不触网）。

口径：设计 §8.1（CLI 兼容契约）+ §8.4（直接替换，无 legacy）。
boll7 依赖 _parse_cli 三元组返回与 fetch_sina/fetch_tencent_daily 原签名——
这两个契约必须保持。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[2]
          / "skills/finance/chanlun-course/scripts/chan_analysis.py")
FIXTURE = Path(__file__).parent / "fixtures" / "mt512400_20260828.json"


@pytest.fixture(scope="module")
def ca():
    """以模块方式加载 CLI 脚本（不触发 __main__）。"""
    spec = importlib.util.spec_from_file_location("chan_analysis", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestParseCli:
    """_parse_cli 契约：(codes, scale, fresh) 三元组——boll7 原样解包。"""

    def test_default_day(self, ca):
        codes, scale, fresh = ca._parse_cli(["sh512400"])
        assert codes == ["sh512400"] and scale == "day" and fresh is False

    def test_named_flags(self, ca):
        assert ca._parse_cli(["--60m", "sh512400"])[1] == 60
        assert ca._parse_cli(["--30m", "sh512400"])[1] == 30
        assert ca._parse_cli(["--day", "sh512400"])[1] == "day"

    def test_scale_and_fresh(self, ca):
        codes, scale, fresh = ca._parse_cli(["--scale", "15", "--fresh", "sh512400"])
        assert scale == 15 and fresh is True and codes == ["sh512400"]

    def test_multi_codes(self, ca):
        codes, _, _ = ca._parse_cli(["sh512400", "sh000688"])
        assert codes == ["sh512400", "sh000688"]


class TestMainPipeline:
    """薄壳主流程：mock chan_engine.data 的 fetch（用 golden fixture 数据），
    断言输出文件结构与报告字段。"""

    @pytest.fixture()
    def fake_data(self, ca, monkeypatch, tmp_path):
        data = json.loads(FIXTURE.read_text())

        def fake_fetch_daily(code, start=None, end=None):
            # fetch_daily 归一输出键为 date（load_daily 行是 trade_date，需还原）
            rows = []
            for r in data["daily"]:
                r2 = dict(r)
                r2["date"] = r2.pop("trade_date")
                rows.append(r2)
            return rows, "akshare"

        def fake_fetch_minute(code, tf, datalen=260):
            rows = data["m60"] if tf == 60 else data["m30"]
            return [dict(r) for r in rows], "sina"

        monkeypatch.setattr(ca, "fetch_daily", fake_fetch_daily)
        monkeypatch.setattr(ca, "fetch_minute", fake_fetch_minute)
        monkeypatch.setattr(ca, "DEFAULT_DB", tmp_path / "chan_bars.db")
        out = tmp_path / "chan_results.json"
        monkeypatch.setattr(ca, "OUT_JSON", out)
        return out

    def test_run_and_output_contract(self, ca, fake_data, capsys):
        rc = ca.main(["sh512400"])
        assert rc == 0
        results = json.loads(fake_data.read_text())
        assert isinstance(results, list) and len(results) == 1  # list 形态保持
        r = results[0]
        assert r["label"] == "sh512400"
        # skill 输出惯例七项 + 级别标注
        assert r["position_nature"]["label"] == "观察"
        assert r["position_nature"]["basis"] == "日线"
        levels = {d["level"] for d in r["defense_lines"]}
        assert "60m" in levels
        assert any(e["level"] == "60m" and e["type"] == "三买"
                   for e in r["entry_points"])
        assert r["backchi"]["60m"]["backchi_type"] == "consolidation_div"
        assert r["asof"]["daily"] == "2026-08-28"
        # 控制台摘要含关键行
        out_text = capsys.readouterr().out
        assert "防守线" in out_text and "仓位性质" in out_text

    def test_scale_60_only_sub60(self, ca, fake_data):
        rc = ca.main(["--60m", "sh512400"])
        assert rc == 0
        r = json.loads(fake_data.read_text())[0]
        assert "30m" not in r["asof"]
        assert all(e["level"] == "60m" for e in r["entry_points"])

    def test_scale_unsupported_rejected(self, ca, fake_data, capsys):
        """--scale 15 超出 30/60（30m 已是最细）→ 明确报错，非静默。"""
        rc = ca.main(["--scale", "15", "sh512400"])
        assert rc == 1
        assert "15" in capsys.readouterr().out

    def test_day_only_no_sub(self, ca, fake_data):
        rc = ca.main(["--day", "sh512400"])
        assert rc == 0
        r = json.loads(fake_data.read_text())[0]
        assert "60m" not in r["asof"] and "30m" not in r["asof"]

    def test_decomp_mode(self, ca, fake_data, capsys):
        rc = ca.main(["--decomp", "--60m", "sh512400"])
        assert rc == 0
        out_text = capsys.readouterr().out
        assert "同级别分解" in out_text and "中枢" in out_text

    def test_fetch_failure_marks_fail(self, ca, monkeypatch, tmp_path, capsys):
        """双源皆挂 → [FAIL] 行，exit 1，不编造（数据诚实纪律）。"""
        from chan_engine.data.fetch import DataFetchError

        def boom(*a, **k):
            raise DataFetchError("all sources failed")

        monkeypatch.setattr(ca, "fetch_daily", boom)
        monkeypatch.setattr(ca, "fetch_minute", boom)
        monkeypatch.setattr(ca, "DEFAULT_DB", tmp_path / "empty.db")
        monkeypatch.setattr(ca, "OUT_JSON", tmp_path / "out.json")
        rc = ca.main(["sh512400"])
        assert rc == 1
        assert "[FAIL]" in capsys.readouterr().out
