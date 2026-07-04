from pathlib import Path

import yaml


def load_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, frontmatter, _ = text.split("---", 2)
    return yaml.safe_load(frontmatter)


import pytest


def _has_chinese(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def test_qing_learning_skill_metadata():
    meta = load_frontmatter(Path("skills/qing-learning/SKILL.md"))
    assert meta["name"] == "qing-learning"
    assert _has_chinese(meta["description"])
    assert "学习" in meta["description"] or "投资" in meta["description"]


def test_all_skill_docs_are_chinese_after_frontmatter():
    # Only project-specific qing-* skills are required to be in Chinese;
    # bundled superpowers skills may be English.
    skill_docs = list(Path("skills").glob("qing-*/SKILL.md"))
    assert skill_docs, "no qing skill docs found"
    for path in skill_docs:
        text = path.read_text(encoding="utf-8")
        body = text.split("---", 2)[-1]
        assert "##" in body
        assert _has_chinese(body), f"{path} body has no Chinese characters"


@pytest.mark.skipif(
    not Path("skills/qing-stock-analysis/SKILL.md").exists(),
    reason="qing-stock-analysis skill not present in this checkout",
)
def test_qing_stock_analysis_skill_metadata():
    meta = load_frontmatter(Path("skills/qing-stock-analysis/SKILL.md"))
    assert meta["name"] == "qing-stock-analysis"
    assert _has_chinese(meta["description"])
    assert "stock" in meta["description"] or "个股" in meta["description"]


@pytest.mark.skipif(
    not Path("skills/qing-stock-analysis/references/f10-financial-analysis.md").exists(),
    reason="qing-stock-analysis references not present in this checkout",
)
def test_qing_stock_analysis_references_include_f10_and_glm():
    f10 = Path("skills/qing-stock-analysis/references/f10-financial-analysis.md").read_text(encoding="utf-8")
    glm = Path("skills/qing-stock-analysis/references/glmv-stock-analyst-workflow.md").read_text(encoding="utf-8")
    assert "PE / PB / PEG / PS" in f10
    assert "glmv-stock-analyst" in glm


@pytest.mark.skipif(
    not Path("skills/qing-methodology-review/SKILL.md").exists(),
    reason="qing-methodology-review skill not present in this checkout",
)
def test_qing_methodology_review_skill_metadata():
    meta = load_frontmatter(Path("skills/qing-methodology-review/SKILL.md"))
    assert meta["name"] == "qing-methodology-review"
    assert _has_chinese(meta["description"])
    assert "methodology" in meta["description"] or "方法论" in meta["description"]
