"""extract_reasoning_patterns 前置过滤的 frontmatter 剥离测试。"""

from scripts.extract_reasoning_patterns import strip_source_headers


def test_strip_bilibili_frontmatter_and_attribution():
    content = (
        "---\n"
        'source: "bilibili_dynamic"\n'
        'up_name: "青枫浦上Q"\n'
        "---\n"
        "\n"
        "> 来源：B站动态 [青枫浦上Q](https://space.bilibili.com/1420210197)\n"
        "> 发布时间：2026年08月19日 22:43\n"
        "\n"
        "## 原文\n"
        "\n"
        "今天这根大阴线，要从板块逻辑判断。\n"
    )
    stripped = strip_source_headers(content)
    assert stripped.startswith("## 原文")
    assert "板块逻辑" in stripped[:100]
    assert "bilibili_dynamic" not in stripped


def test_strip_leaves_plain_content_untouched():
    content = "复盘：今天板块轮动逻辑清晰。"
    assert strip_source_headers(content) == content


def test_strip_incomplete_frontmatter_untouched():
    content = "---\n没有闭合的frontmatter\n主线判断"
    # 没有闭合 ---，原样返回（保守不截断）
    assert "主线判断" in strip_source_headers(content)
