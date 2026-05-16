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
