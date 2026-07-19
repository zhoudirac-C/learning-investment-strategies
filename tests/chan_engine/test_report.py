"""Task 6: 校准矩阵与报告生成测试（先红后绿）。

覆盖：run_case 的 PASS/FAIL/ERROR 三态（实现崩溃记 ERROR 且不中断整批）；
render_report 的矩阵/偏差明细/偏差条目模板渲染；CLI main 的玩具用例自测、
目录缺失、用例非法、适配器不可用（清晰错误而非栈 trace）。
"""

import textwrap

import pytest

from chan_engine.harness import report as report_mod
from chan_engine.harness.report import (
    CaseReport,
    CellResult,
    main,
    render_report,
    run_case,
)
from chan_engine.spec.case_io import Case
from chan_engine.spec.model import Bar, Bi, Direction, NormalizedChart

REAL_CLAIM_ID = "claim-20070905-001-b"


class FakeAdapter:
    """内存假适配器：返回预设 chart 或抛预设异常。"""

    def __init__(self, name, chart=None, error=None):
        self.name = name
        self.config_snapshot = {"fake": True}
        self._chart = chart if chart is not None else NormalizedChart()
        self._error = error

    def run(self, bars):
        if self._error is not None:
            raise self._error
        return self._chart


def make_case(case_id="TOY-001", expect=None):
    return Case(
        case_id=case_id,
        bars=[Bar(ts=i, o=10, h=11, l=9, c=10.5, vol=100) for i in range(5)],
        expect=expect if expect is not None else {},
        claim_refs=[REAL_CLAIM_ID],
    )


class TestRunCase:
    EXPECT_BI = {"bi": [{"start_idx": 0, "end_idx": 2, "dir": "down"}]}

    def test_pass_fail_error_cells(self):
        case = make_case(expect=self.EXPECT_BI)
        adapters = [
            FakeAdapter("ok-impl", NormalizedChart(bi=[Bi(0, 2, Direction.DOWN)])),
            FakeAdapter("off-impl", NormalizedChart(bi=[Bi(0, 3, Direction.DOWN)])),
            FakeAdapter("boom-impl", error=ValueError("爆炸")),
        ]
        rep = run_case(case, adapters)
        assert isinstance(rep, CaseReport)
        assert rep.case_id == "TOY-001"
        assert rep.claim_refs == [REAL_CLAIM_ID]
        assert [c.impl for c in rep.cells] == ["ok-impl", "off-impl", "boom-impl"]
        assert [c.status for c in rep.cells] == ["PASS", "FAIL", "ERROR"]

        fail_cell = rep.cells[1]
        assert fail_cell.diff is not None and fail_cell.diff.passed is False
        (bi,) = fail_cell.diff.problem_tables
        assert [(e.start_idx, e.end_idx) for e in bi.missing] == [(0, 2)]
        assert [(e.start_idx, e.end_idx) for e in bi.extra] == [(0, 3)]

        err_cell = rep.cells[2]
        assert err_cell.diff is None
        assert "爆炸" in err_cell.error  # 异常被捕获为 ERROR，不中断整批


@pytest.fixture()
def mixed_reports():
    case_ok = make_case("TOY-PASS-001")
    case_fail = make_case(
        "TOY-FAIL-001", expect={"bi": [{"start_idx": 0, "end_idx": 99, "dir": "up"}]}
    )
    adapters = [
        FakeAdapter("chanpy"),  # 空 chart：expect {} → PASS；有断言 → FAIL
        FakeAdapter("czsc", error=RuntimeError("rs_czsc 崩溃")),
    ]
    return [run_case(case_ok, adapters), run_case(case_fail, adapters)]


class TestRenderReport:
    def test_matrix_details_and_deviation_template(self, mixed_reports):
        md = render_report(mixed_reports, command="python -m chan_engine.harness.report ...")
        # 校准矩阵：case_id × impl × 状态
        assert "## 校准矩阵" in md
        assert "| 用例 |" in md and "chanpy" in md and "czsc" in md
        assert "TOY-PASS-001" in md and "TOY-FAIL-001" in md
        assert "PASS" in md and "FAIL" in md and "ERROR" in md
        # 偏差明细：定位到表与缺/多元素
        assert "## 偏差明细" in md
        assert "bi 表" in md and "缺" in md and "end_idx=99" in md
        assert "rs_czsc 崩溃" in md
        # 偏差条目模板：规则源 claim / 两实现行为 / 三项人工占位
        assert "## 口径偏差清单" in md
        assert "规则源 claim" in md and REAL_CLAIM_ID in md
        assert "chan.py 行为" in md and "czsc 行为" in md
        assert "原文依据" in md and "仲裁结论" in md and "M2 改造点" in md
        assert "【待 Task 9 人工填写】" in md

    def test_all_pass_report_has_empty_deviation_list(self):
        rep = run_case(make_case(), [FakeAdapter("chanpy")])
        md = render_report([rep])
        assert "PASS" in md
        assert "### 偏差" not in md  # 无偏差条目


TOY_YAML = textwrap.dedent(
    f"""\
    case_id: {{case_id}}
    claim_refs: [{REAL_CLAIM_ID}]
    bars:
      - [10, 11, 9, 10.5]
      - [10.5, 12, 10, 11.5]
      - [11.5, 12, 8, 9]
    expect: {{expect}}
    """
)


class TestMainCLI:
    def test_toy_cases_end_to_end(self, tmp_path):
        cases = tmp_path / "cases"
        cases.mkdir()
        golden = tmp_path / "golden"
        golden.mkdir()
        (cases / "TOY-PASS-001.yaml").write_text(
            TOY_YAML.format(case_id="TOY-PASS-001", expect="{}"), encoding="utf-8"
        )
        (cases / "TOY-FAIL-001.yaml").write_text(
            TOY_YAML.format(
                case_id="TOY-FAIL-001",
                expect='{bi: [{start_idx: 0, end_idx: 99, dir: up}]}',
            ),
            encoding="utf-8",
        )
        (golden / "GOLD-001.yaml").write_text(
            TOY_YAML.format(case_id="GOLD-001", expect="{}"), encoding="utf-8"
        )
        out = tmp_path / "report.md"
        rc = main(
            ["--cases", str(cases), "--golden", str(golden), "--out", str(out)],
            adapters=[FakeAdapter("chanpy"), FakeAdapter("czsc")],
        )
        assert rc == 0
        md = out.read_text(encoding="utf-8")
        assert "TOY-PASS-001" in md and "TOY-FAIL-001" in md and "GOLD-001" in md
        assert "golden" in md  # 金标来源标注
        assert "FAIL" in md and "缺 1 条" in md

    def test_missing_cases_dir_returns_1(self, tmp_path, capsys):
        rc = main(
            ["--cases", str(tmp_path / "nope"), "--out", str(tmp_path / "r.md")],
            adapters=[FakeAdapter("chanpy")],
        )
        assert rc == 1
        assert "错误" in capsys.readouterr().err

    def test_invalid_case_returns_1(self, tmp_path, capsys):
        cases = tmp_path / "cases"
        cases.mkdir()
        (cases / "BAD-001.yaml").write_text(
            "case_id: BAD-001\nclaim_refs: [claim-99999999-999-z]\n"
            "bars: [[10, 11, 9, 10.5]]\nexpect: {}\n",
            encoding="utf-8",
        )
        rc = main(
            ["--cases", str(cases), "--out", str(tmp_path / "r.md")],
            adapters=[FakeAdapter("chanpy")],
        )
        assert rc == 1
        assert "claim-99999999-999-z" in capsys.readouterr().err

    def test_adapter_unavailable_returns_2(self, tmp_path, capsys, monkeypatch):
        def boom():
            raise report_mod._AdapterUnavailable("无法导入 Chan（测试注入）")

        monkeypatch.setattr(report_mod, "_default_adapters", boom)
        cases = tmp_path / "cases"
        cases.mkdir()
        rc = main(["--cases", str(cases), "--out", str(tmp_path / "r.md")])
        assert rc == 2
        err = capsys.readouterr().err
        assert "无法导入 Chan" in err and "Traceback" not in err

    def test_load_adapter_missing_module_has_clear_hint(self):
        with pytest.raises(report_mod._AdapterUnavailable, match="请这样运行"):
            report_mod._load_adapter(
                "definitely_not_a_module_xyz", "X", "请这样运行：PYTHONPATH=..."
            )
