from pathlib import Path


def test_design_spec_is_chinese_and_uses_plantuml():
    spec = Path("docs/superpowers/specs/2026-05-16-continuous-investment-learning-system-design.md")
    text = spec.read_text(encoding="utf-8")
    assert "持续学习型投资方法论系统技术方案" in text
    assert "```plantuml" in text
    assert "@startuml" in text
    assert "@enduml" in text
    assert "```mermaid" not in text


def test_no_placeholder_markers_in_docs():
    forbidden = ["T" + "BD", "TO" + "DO", "待" + "定", "以后" + "再", "place" + "holder"]
    for path in Path("docs/superpowers/specs").rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text, f"{path} contains {marker}"


def test_core_methodology_and_framework_files_exist():
    required = [
        "methodology/index.md",
        "methodology/market-cycle.md",
        "methodology/sector-rotation.md",
        "methodology/stock-selection.md",
        "methodology/f10-fundamental-analysis.md",
        "methodology/technical-analysis.md",
        "methodology/position-risk.md",
        "methodology/decision-flow.md",
        "framework/README.md",
        "framework/learning-update-protocol.md",
        "framework/stock-analysis-playbook.md",
        "framework/methodology-review-protocol.md",
        "framework/contradiction-policy.md",
        "framework/output-contracts.md",
    ]
    for file_name in required:
        assert Path(file_name).exists(), file_name


def test_f10_methodology_contains_required_sequence():
    text = Path("methodology/f10-fundamental-analysis.md").read_text(encoding="utf-8")
    required_phrases = [
        "先识别公司类型",
        "三大报表质量检查",
        "ROE",
        "杜邦",
        "PE / PB / PEG / PS",
        "字段缺失",
    ]
    for phrase in required_phrases:
        assert phrase in text


def test_eval_fixtures_exist():
    required = [
        "evals/README.md",
        "evals/learning/raw/2026-05-16-早盘-样例.md",
        "evals/learning/expected-claims.md",
        "evals/methodology-review/review-window.md",
        "evals/stock-analysis/sample-stock-context.md",
    ]
    for file_name in required:
        assert Path(file_name).exists(), file_name
