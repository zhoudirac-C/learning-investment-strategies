"""Task 2: 用例 YAML 加载/校验测试。

schema：case_id/bars/expect 必需，claim_refs 必需且每个 id 必须真实存在于
knowledge/claims/*.yaml（全局约束：每条用例必须挂 claim id）；
expect 子键仅允许 fx/bi/seg/zs/bsp，均可选。
"""

import textwrap

import pytest

from chan_engine.spec import case_io
from chan_engine.spec.case_io import Case, CaseValidationError, load_case, load_claim_ids
from chan_engine.spec.model import Bar

# 真实存在于 knowledge/claims/claim-20070905-001.yaml 的 id
REAL_CLAIM_ID = "claim-20070905-001-b"

MINIMAL_CASE = textwrap.dedent(
    f"""\
    case_id: BI-TEST-001
    claim_refs:
      - {REAL_CLAIM_ID}
    bars:
      - [10, 11, 9, 10.5]
      - [10.5, 12, 10, 11.5]
      - [11.5, 12, 8, 9]
    expect:
      bi:
        - {{start_idx: 0, end_idx: 2, dir: down}}
    """
)


@pytest.fixture()
def case_file(tmp_path):
    p = tmp_path / "case.yaml"
    p.write_text(MINIMAL_CASE, encoding="utf-8")
    return p


def write_case(tmp_path, body: str):
    p = tmp_path / "bad_case.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


class TestLoadCase:
    def test_load_minimal_case(self, case_file):
        case = load_case(case_file)
        assert isinstance(case, Case)
        assert case.case_id == "BI-TEST-001"
        assert case.claim_refs == [REAL_CLAIM_ID]
        assert len(case.bars) == 3
        assert all(isinstance(b, Bar) for b in case.bars)
        # bars 数组转 Bar：ohlc 保留，ts 递增补齐，vol 补常量
        assert case.bars[0].o == 10 and case.bars[0].h == 11
        assert case.bars[0].l == 9 and case.bars[0].c == 10.5
        assert [b.ts for b in case.bars] == [0, 1, 2]
        assert len({b.vol for b in case.bars}) == 1
        # expect 原样保留（归一到模型是 diff 的职责）
        assert case.expect["bi"] == [{"start_idx": 0, "end_idx": 2, "dir": "down"}]

    def test_expect_subkeys_all_optional(self, tmp_path):
        p = write_case(
            tmp_path,
            f"""\
            case_id: X-001
            claim_refs: [{REAL_CLAIM_ID}]
            bars: [[10, 11, 9, 10.5]]
            expect: {{}}
            """,
        )
        assert load_case(p).expect == {}

    @pytest.mark.parametrize("missing", ["case_id", "bars", "expect", "claim_refs"])
    def test_missing_required_field_raises(self, tmp_path, missing):
        fields = {
            "case_id": "case_id: X-001",
            "claim_refs": f"claim_refs: [{REAL_CLAIM_ID}]",
            "bars": "bars: [[10, 11, 9, 10.5]]",
            "expect": "expect: {}",
        }
        del fields[missing]
        p = write_case(tmp_path, "\n".join(fields.values()) + "\n")
        with pytest.raises(CaseValidationError, match=missing):
            load_case(p)

    def test_empty_bars_raises(self, tmp_path):
        p = write_case(
            tmp_path,
            f"""\
            case_id: X-001
            claim_refs: [{REAL_CLAIM_ID}]
            bars: []
            expect: {{}}
            """,
        )
        with pytest.raises(CaseValidationError, match="bars"):
            load_case(p)

    def test_unknown_expect_subkey_raises(self, tmp_path):
        p = write_case(
            tmp_path,
            f"""\
            case_id: X-001
            claim_refs: [{REAL_CLAIM_ID}]
            bars: [[10, 11, 9, 10.5]]
            expect:
              macd: []
            """,
        )
        with pytest.raises(CaseValidationError, match="macd"):
            load_case(p)

    def test_not_a_mapping_raises(self, tmp_path):
        p = write_case(tmp_path, "- just\n- a\n- list\n")
        with pytest.raises(CaseValidationError):
            load_case(p)


class TestClaimRefsValidation:
    def test_real_claim_id_passes(self, case_file):
        # 不抛异常即通过（真实 id 来自 knowledge/claims/）
        load_case(case_file)

    def test_unknown_claim_id_raises(self, tmp_path):
        p = write_case(
            tmp_path,
            """\
            case_id: X-001
            claim_refs: [claim-99999999-999-z]
            bars: [[10, 11, 9, 10.5]]
            expect: {}
            """,
        )
        with pytest.raises(CaseValidationError, match="claim-99999999-999-z"):
            load_case(p)

    def test_empty_claim_refs_raises(self, tmp_path):
        p = write_case(
            tmp_path,
            """\
            case_id: X-001
            claim_refs: []
            bars: [[10, 11, 9, 10.5]]
            expect: {}
            """,
        )
        with pytest.raises(CaseValidationError, match="claim_refs"):
            load_case(p)


class TestLoadClaimIds:
    def test_real_id_in_set(self):
        ids = load_claim_ids()
        assert REAL_CLAIM_ID in ids
        assert len(ids) > 300  # 缠论 claims 约 337 条

    def test_result_cached(self):
        case_io.clear_claim_id_cache()
        first = load_claim_ids()
        second = load_claim_ids()
        assert first is second  # 模块级缓存：同一对象，不重复扫描
