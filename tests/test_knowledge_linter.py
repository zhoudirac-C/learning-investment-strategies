from qing_investment.knowledge_linter import lint_markdown_placeholders


def test_lint_markdown_placeholders_reports_forbidden_markers(tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text("这里有 " + ("TO" + "DO"), encoding="utf-8")
    issues = lint_markdown_placeholders(tmp_path)
    assert len(issues) == 1
    assert issues[0].path == doc
    assert issues[0].marker == "TO" + "DO"
