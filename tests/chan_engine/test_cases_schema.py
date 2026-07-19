"""Task 7 Step 8 + Task 8：全部用例（synthetic 26 条 + 金标）的 schema + claim_refs 校验。

扫描 ``src/chan_engine/spec/cases/*.yaml`` 与 ``src/chan_engine/spec/golden/*.yaml``，
逐条过 ``case_io.load_case``（验收清单：26+3 条用例全部过 schema 与 claim_refs
校验）。golden 与 cases 同 schema，仅多一个可选 ``source_ref`` 字段（课号+原文
段落），case_io 不限制额外顶层字段，无需特殊处理。
只验格式（schema / claim_refs 存在性 / 命名约定），不验实现对错——
实现（chan.py / czsc）与 expect 的对表由 harness 的 diff 引擎负责（Task 6/9）。
目录扫描在模块级完成，用例族由多个批次并行写入，本测试对目录内全部文件生效。
"""

from pathlib import Path

import pytest

from chan_engine.spec.case_io import load_case

# tests/chan_engine/test_cases_schema.py -> 仓根 src/chan_engine/spec/{cases,golden}/
_SPEC_DIR = Path(__file__).resolve().parents[2] / "src" / "chan_engine" / "spec"
CASES_DIR = _SPEC_DIR / "cases"
GOLDEN_DIR = _SPEC_DIR / "golden"

CASE_FILES = sorted(CASES_DIR.glob("*.yaml"))
CASE_IDS = [p.stem for p in CASE_FILES]
GOLDEN_FILES = sorted(GOLDEN_DIR.glob("*.yaml"))
GOLDEN_IDS = [p.stem for p in GOLDEN_FILES]
ALL_FILES = CASE_FILES + GOLDEN_FILES
ALL_IDS = CASE_IDS + GOLDEN_IDS


def test_cases_dir_not_empty():
    assert CASES_DIR.is_dir(), f"用例目录不存在: {CASES_DIR}"
    assert CASE_FILES, f"用例目录为空: {CASES_DIR}"


def test_golden_dir_not_empty():
    assert GOLDEN_DIR.is_dir(), f"金标目录不存在: {GOLDEN_DIR}"
    assert GOLDEN_FILES, f"金标目录为空: {GOLDEN_DIR}"


@pytest.mark.parametrize("case_path", ALL_FILES, ids=ALL_IDS)
def test_case_schema_and_claim_refs(case_path):
    """load_case 内含完整校验：必需字段、bars 合法性、expect 子键白名单、
    claim_refs 每个 id 必须存在于 knowledge/claims/*.yaml。不抛异常即通过。"""
    case = load_case(case_path)
    assert case.case_id
    assert case.bars
    assert isinstance(case.expect, dict)
    assert case.claim_refs


@pytest.mark.parametrize("case_path", ALL_FILES, ids=ALL_IDS)
def test_case_id_matches_filename(case_path):
    """命名约定（实施计划 Task 7）：文件名为 case_id 的小写，如 include-001.yaml。"""
    case = load_case(case_path)
    assert case_path.stem == case.case_id.lower()


@pytest.mark.parametrize("case_path", GOLDEN_FILES, ids=GOLDEN_IDS)
def test_golden_has_source_ref(case_path):
    """金标约定（实施计划 Task 8 Step 3）：比 cases 多一个 ``source_ref`` 字段
    （课号+原文段落），非空字符串。"""
    import yaml

    raw = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    ref = raw.get("source_ref")
    assert isinstance(ref, str) and ref.strip(), f"{case_path.name} 缺 source_ref"


def test_case_ids_unique():
    ids = [load_case(p).case_id for p in ALL_FILES]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"case_id 重复: {dupes}"
