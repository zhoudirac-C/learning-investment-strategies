from pathlib import Path

import yaml


def load_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, frontmatter, _ = text.split("---", 2)
    return yaml.safe_load(frontmatter)


def test_qing_learning_skill_metadata():
    meta = load_frontmatter(Path("skills/qing-learning/SKILL.md"))
    assert meta["name"] == "qing-learning"
    assert "Use when" in meta["description"]
    assert "ingest" in meta["description"] or "学习" in meta["description"]


def test_all_skill_docs_are_chinese_after_frontmatter():
    for path in Path("skills").glob("*/SKILL.md"):
        text = path.read_text(encoding="utf-8")
        body = text.split("---", 2)[-1]
        assert "##" in body
        assert any(ch in body for ch in "学习方法论个股分析")


def test_qing_stock_analysis_skill_metadata():
    meta = load_frontmatter(Path("skills/qing-stock-analysis/SKILL.md"))
    assert meta["name"] == "qing-stock-analysis"
    assert "Use when" in meta["description"]
    assert "stock" in meta["description"] or "个股" in meta["description"]


def test_qing_stock_analysis_references_include_f10_and_glm():
    f10 = Path("skills/qing-stock-analysis/references/f10-financial-analysis.md").read_text(encoding="utf-8")
    glm = Path("skills/qing-stock-analysis/references/glmv-stock-analyst-workflow.md").read_text(encoding="utf-8")
    assert "PE / PB / PEG / PS" in f10
    assert "glmv-stock-analyst" in glm


def test_qing_methodology_review_skill_metadata():
    meta = load_frontmatter(Path("skills/qing-methodology-review/SKILL.md"))
    assert meta["name"] == "qing-methodology-review"
    assert "Use when" in meta["description"]
    assert "methodology" in meta["description"] or "方法论" in meta["description"]
