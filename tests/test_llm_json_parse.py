"""LLM JSON 输出解析测试 — k3 间歇性 ```json 围栏包裹导致 json_parse_error 的回归测试。

复现背景（2026-10-12）：model.default 切到 k3 (Kimi coding) 后，
market_summary / stock_scanner_shard 等节点间歇收到 ```json 围栏包裹的 JSON，
nodes.py 原解析只剥 ```daily_state 围栏 → json.loads 失败 → fallback 降级。
"""


class TestParseLlmJsonContent:
    """_parse_llm_json_content 的行为契约。"""

    def test_bare_json(self):
        from qing_investment.agent.graph.nodes import _parse_llm_json_content
        assert _parse_llm_json_content('{"market_phase": "反弹延续"}') == {"market_phase": "反弹延续"}

    def test_json_fence(self):
        """k3 的典型输出：```json 围栏包裹。"""
        from qing_investment.agent.graph.nodes import _parse_llm_json_content
        content = '```json\n{\n  "market_phase": "高位震荡整理期",\n  "market_summary": "上证指数收报3813.79点"\n}\n```'
        result = _parse_llm_json_content(content)
        assert result["market_phase"] == "高位震荡整理期"

    def test_plain_fence_without_lang(self):
        from qing_investment.agent.graph.nodes import _parse_llm_json_content
        content = '```\n{"a": 1}\n```'
        assert _parse_llm_json_content(content) == {"a": 1}

    def test_daily_state_block_stripped_and_json_fence_parsed(self):
        """原有 ```daily_state 剥离行为必须保留，且与 ```json 围栏共存。"""
        from qing_investment.agent.graph.nodes import _parse_llm_json_content
        content = (
            '```json\n{"market_phase": "震荡"}\n```\n\n'
            '```daily_state\n{"emotion": "冰点"}\n```'
        )
        result = _parse_llm_json_content(content)
        assert result == {"market_phase": "震荡"}

    def test_preamble_prose_before_fence(self):
        """模型在围栏前加了说明文字。"""
        from qing_investment.agent.graph.nodes import _parse_llm_json_content
        content = '好的，以下是分析结果：\n```json\n{"x": 2}\n```'
        assert _parse_llm_json_content(content) == {"x": 2}

    def test_trailing_text_after_json(self):
        from qing_investment.agent.graph.nodes import _parse_llm_json_content
        content = '{"x": 3}\n以上仅供参考。'
        assert _parse_llm_json_content(content) == {"x": 3}

    def test_garbage_returns_empty_dict(self):
        from qing_investment.agent.graph.nodes import _parse_llm_json_content
        assert _parse_llm_json_content("完全不是JSON的输出") == {}

    def test_empty_and_none(self):
        from qing_investment.agent.graph.nodes import _parse_llm_json_content
        assert _parse_llm_json_content("") == {}
        assert _parse_llm_json_content(None) == {}

    def test_non_dict_json_returns_empty_dict(self):
        """顶层是 list / 标量时不应冒充 dict 结果。"""
        from qing_investment.agent.graph.nodes import _parse_llm_json_content
        assert _parse_llm_json_content('[1, 2, 3]') == {}
        assert _parse_llm_json_content('```json\n[1, 2]\n```') == {}
