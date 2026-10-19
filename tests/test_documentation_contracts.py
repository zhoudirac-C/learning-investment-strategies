from pathlib import Path

import pytest


def test_design_spec_is_chinese_and_uses_plantuml():
    spec = Path("docs/superpowers/specs/2026-05-16-continuous-investment-learning-system-design.md")
    if not spec.exists():
        pytest.skip("Design spec not present in this checkout")
    text = spec.read_text(encoding="utf-8")
    assert "持续学习型投资方法论系统技术方案" in text
    assert "```plantuml" in text
    assert "@startuml" in text
    assert "@enduml" in text
    assert "```mermaid" not in text


def test_no_placeholder_markers_in_docs():
    """设计文档不得残留未完成的占位符。

    2026-10-20 修正：原实现把所有 "待定" 一律判为占位符，误伤正常中文
    （如"待定提案"= pending 提案，是正式术语）。改为匹配**独立占位符形态**：
    行首/列表项/标题中的裸占位词、TODO/TBD 标记、尖括号占位。
    """
    import re

    patterns = {
        "裸占位词": re.compile(r"^[\s>\-*#|]*(" + "待" + "定|T" + "BD|TO" + "DO" + r")[\s。，,;；]*$"),
        "TODO标记": re.compile(r"\bTO" + "DO\b", re.IGNORECASE),
        "尖括号占位": re.compile(r"(place" + r"holder|\{\{[^}]{0,40}\}\}|<[A-Z_]{3,}>|待补[充填])"),
    }
    for path in sorted(Path("docs/superpowers/specs").rglob("*.md")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for label, pat in patterns.items():
                assert not pat.search(line), f"{path}:{lineno} contains {label}: {line.strip()[:60]}"


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
