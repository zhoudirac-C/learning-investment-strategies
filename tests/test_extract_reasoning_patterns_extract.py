"""extract_reasoning_patterns 提取结果三分态（ok/skip/transient-fail）测试。"""

from scripts.extract_reasoning_patterns import extract_pattern_from_file


class _StubLLM:
    def __init__(self, content):
        self._content = content

    def invoke(self, prompt):
        from types import SimpleNamespace
        return SimpleNamespace(content=self._content)


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_llm_garbage_response_is_transient_fail(tmp_path):
    # 正文含分析关键词，能过前置过滤
    fp = _write(tmp_path, "2026-08-20-复盘-x.md", "因为量能判断主线板块逻辑策略。" * 50)
    result = extract_pattern_from_file(fp, _StubLLM("这不是JSON"), frameworks=[])
    assert result is False  # 瞬时失败：不应标记已处理


def test_llm_valid_json_returns_dict(tmp_path):
    fp = _write(tmp_path, "2026-08-20-复盘-x.md", "因为量能判断主线板块逻辑策略。" * 50)
    payload = ('{"has_pattern": true, "pattern_id": "t", "name": "n", "description": "d",'
               ' "trigger": [], "matched_framework": "others",'
               ' "reasoning_chain": [{"name": "s1", "action": "a"}, {"name": "s2", "action": "b"}],'
               ' "falsification": []}')
    result = extract_pattern_from_file(fp, _StubLLM(payload), frameworks=[])
    assert isinstance(result, dict)
    assert result["pattern_id"] == "t"


def test_prefilter_skip_returns_none(tmp_path):
    fp = _write(tmp_path, "2026-08-20-图片-x.md", "今天天气不错。" * 30)
    result = extract_pattern_from_file(fp, _StubLLM("{}"), frameworks=[])
    assert result is None  # 前置过滤跳过：可标记已处理（无需重试）
