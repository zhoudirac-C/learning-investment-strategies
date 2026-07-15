"""
Qing-Agent 端到端工作流测试：模拟交易日看盘定时任务

1. 构造 mock 持仓池 / 观察池 / 策略配置
2. 用 QING_AGENT_MOCK_QUOTES=1 获取 mock 大盘/指数/板块行情
3. run_tick(agent_json_context=True) 生成 agent 上下文 JSON
4. 用该 JSON 构建 AgentState
5. mock _safe_llm_invoke，调用完整 LangGraph
6. 断言生成 final_output

整个流程不访问真实网络和真实 LLM。
"""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from qing_investment.monitor.scheduler import run_tick


CN_TZ = ZoneInfo("Asia/Shanghai")


def make_mock_monitor_config():
    """完全在内存中构造 MonitorConfig 替代品，不读写 YAML 文件。"""
    positions = {
        "accounts": [
            {
                "name": "主账户",
                "positions": [
                    {
                        "code": "000021.SZ",
                        "name": "深科技",
                        "shares": 1000,
                        "cost": 36.2,
                        "role": "core_holding",
                        "reduce_zone": "36.9-37.5",
                        "risk_line": 35.9,
                    }
                ],
            }
        ]
    }
    watchlist = {
        "themes": [
            {
                "id": "domestic_compute",
                "name": "国产算力",
                "stocks": [
                    {
                        "code": "000021.SZ",
                        "name": "深科技",
                        "watch_reason": "测试观察",
                    }
                ],
            }
        ]
    }
    strategy_pack = {
        "market_framework": {
            "current_stage": "磨底期观察",
            "index_rules": [
                {
                    "index": "上证指数",
                    "trigger_condition": "intraday_below",
                    "threshold": 3400.0,
                    "action": "指数跌破观察",
                    "severity": "observe",
                }
            ],
        },
        "agent_analysis_schedule": [{"hour": 10, "minute": 30, "id": "morning_brief"}],
        "notification_policy": {"message_fields": ["time", "action", "stock", "price"]},
    }
    return SimpleNamespace(
        config_dir=None,
        positions_path=None,
        positions=positions,
        watchlist=watchlist,
        strategy_pack=strategy_pack,
        direction_pool={"directions": []},
        stock_pool={"stocks": []},
        entry_points=[],
        market_framework=strategy_pack["market_framework"],
        sector_groups=[],
    )


def _build_agent_state(agent_json: dict, query: str) -> dict:
    """仿照 cli_qing_agent.py 的 _default_state，用 run_tick 输出构建 AgentState。"""
    # 将 positions 从 {"accounts": [{"positions": [...]}]} 展开为 flat list
    positions: list[dict] = []
    for account in agent_json.get("positions", {}).get("accounts", []) or []:
        positions.extend(account.get("positions", []) or [])
    # watchlist 同理，提取 themes list
    watchlist_themes = agent_json.get("watchlist", {}).get("themes", []) or []

    state = {
        "query": query,
        "session_id": "test-monitor-workflow",
        "trigger": agent_json.get("trigger"),
        "alerts": agent_json.get("alerts", []),
        "positions": positions,
        "watchlist": watchlist_themes,
        "market_snapshot": agent_json.get("quote_snapshot", {}),
        "sector_strengths": [],
        "external_sector_boards": {},
        "sector_context": [],
        "claims": [],
        "wiki_snippets": [],
        "knowledge_graph": {},
        "memories": [],
        "few_shot_examples": [],
        "market_context": {},
        "stock_analysis": {},
        "draft_analysis": "",
        "styled_output": "",
        "review_notes": [],
        "final_output": "",
        "claims_cited": [],
        "data_sources": [],
        "confidence": "medium",
        "review_passed": False,
        "reasoning_steps": [],
        "parsed_intent": {
            "stock_code": None,
            "analysis_type": "market",
            "urgency": "scheduled",
            "focus": query,
        },
    }
    # 如果 agent_json 里带 market_framework，也可以补充进 state
    return state


class _FakeLangChainResponse:
    def __init__(self, content: str):
        self.content = content


class _FakeLangChainLLM:
    """基于 prompt 关键词返回不同 canned 响应，驱动 graph 走到 END。"""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def invoke(self, prompt: str, config=None):
        response = self._response_for(prompt)
        self.calls.append((prompt[:60], response[:60]))
        return _FakeLangChainResponse(response)

    def _response_for(self, prompt: str) -> str:
        # parse_query：唯一出现该前缀的是意图解析
        if "从以下输入中提取信息" in prompt:
            return json.dumps(
                {
                    "stock_code": None,
                    "analysis_type": "market",
                    "urgency": "scheduled",
                    "focus": "今天大盘怎么看",
                }
            )

        # market_summary：模板固定前缀
        if "【分析时必须获取的实时数据】" in prompt:
            return json.dumps(
                {
                    "market_phase": "磨底期",
                    "market_summary": "mock 市场处于磨底期，指数缩量震荡",
                    "phase_reasoning": "mock reasoning",
                    "main_themes": ["国产算力"],
                    "sector_map": {"国产算力": [{"name": "深科技", "status": "主升", "key_stocks": ["深科技"], "logic": "mock"}]},
                    "sector_strength": {"国产算力": "强"},
                    "themes_in_focus": ["国产算力"],
                    "index_discipline": {"support": "3350", "resistance": "3400", "action_below": "观望", "action_above": "试探", "middle_zone": "震荡"},
                    "volume_note": "缩量",
                    "emotion_signals": {},
                    "risk_notes": ["mock risk"],
                    "citations": [],
                }
            )

        # stock_scanner：模板固定前缀
        if "【任务】" in prompt and "opportunity_scan" in prompt:
            return json.dumps(
                {
                    "opportunity_scan": [
                        {
                            "code": "000021",
                            "name": "深科技",
                            "reason": "板块强势",
                            "confidence": "medium",
                        }
                    ],
                    "position_plans": [
                        {
                            "code": "000021.SZ",
                            "action": "减仓观察",
                            "reason": "触及减仓区",
                            "trigger": "冲高减仓区",
                            "invalidation": "跌破风险线",
                        }
                    ],
                }
            )

        # style_writer：模板固定前缀，返回长度>100避免 reviewer / citation_validator 强制打回
        if "你是青枫浦上Q的语言风格模拟器" in prompt:
            return (
                "## 早盘观察\n\n"
                "mock 早盘观察：大盘磨底，深科技触发减仓观察，科技主线需确认承接。\n\n"
                "上证指数当前跌破3400点，全A指数缩量震荡，情绪指标偏冷。"
                "持仓方面，深科技进入预设减仓区36.9-37.5，建议控制仓位，等待板块共振。"
                "进攻方向关注国产算力链扩散，防御方向保持现金流。"
            )

        # reviewer：模板固定前缀
        if "你是事实核查员" in prompt:
            return json.dumps({"passed": True, "issues": [], "verified_claims": []})

        # fallback：给一个非空字符串，避免节点因空内容走失败分支
        return "mock fallback response"


def test_monitor_run_tick_produces_agent_json(monkeypatch, tmp_path):
    """run_tick 在 mock 行情 + mock 持仓池/观察池下，能生成 agent JSON 上下文。"""
    monkeypatch.setenv("QING_AGENT_MOCK_QUOTES", "1")
    monkeypatch.setenv("QING_AGENT_IGNORE_TRADING_TIME", "1")

    config = make_mock_monitor_config()

    agent_json_text = run_tick(
        config,
        datetime(2026, 5, 22, 10, 30, tzinfo=CN_TZ),
        emit_status=False,
        ignore_trading_time=False,
        agent_json_context=True,
        state_path=tmp_path / "state.json",
    )

    assert agent_json_text
    agent_json = json.loads(agent_json_text)
    assert agent_json["trigger"]["id"] in ("morning_brief", "rule_alert")
    assert agent_json["positions"]["accounts"][0]["positions"][0]["code"] == "000021.SZ"
    assert "上证指数" in {q.get("label") or q.get("name") for q in agent_json["quote_snapshot"]["quotes"]}


def test_qing_agent_full_workflow_from_monitor_context(monkeypatch, tmp_path):
    """模拟完整交易日看盘定时任务：monitor -> agent context -> qing agent graph invoke。"""
    monkeypatch.setenv("QING_AGENT_MOCK_QUOTES", "1")
    monkeypatch.setenv("QING_AGENT_IGNORE_TRADING_TIME", "1")
    # 确保不会意外走本地 CLI/ACP（它们会 spawn 子进程）
    monkeypatch.setenv("KIMI_CODE_ACP_FIRST", "0")
    monkeypatch.setenv("KIMI_CODE_CLI_FIRST", "0")

    # 1) mock 持仓池 / 观察池 / 策略配置，生成 agent JSON
    config = make_mock_monitor_config()
    agent_json_text = run_tick(
        config,
        datetime(2026, 5, 22, 10, 30, tzinfo=CN_TZ),
        emit_status=False,
        ignore_trading_time=False,
        agent_json_context=True,
        state_path=tmp_path / "state.json",
    )
    assert agent_json_text
    agent_json = json.loads(agent_json_text)

    # 2) 用 agent_json 构建 AgentState
    query = agent_json["trigger"]["title"] + "：" + agent_json["trigger"]["reason"]
    state = _build_agent_state(agent_json, query)

    # 3) mock 检索（不访问 Qdrant/Neo4j）
    async def fake_retrieve_knowledge(state_in: dict) -> dict:
        return {
            "claims": [],
            "wiki_snippets": [],
            "knowledge_graph": {},
            "memories": [],
            "few_shot_examples": [],
        }

    monkeypatch.setattr(
        "qing_investment.agent.graph.nodes.retrieve_knowledge", fake_retrieve_knowledge
    )
    # build_graph 从 builder 模块导入 retrieve_knowledge，因此也要 patch builder 模块的引用
    import qing_investment.agent.graph.builder as builder_module

    monkeypatch.setattr(builder_module, "retrieve_knowledge", fake_retrieve_knowledge)

    # 4) mock LLM：让 get_llm_client 无论 provider 都返回 FakeLLM
    fake_llm = _FakeLangChainLLM()
    monkeypatch.setattr(
        "qing_investment.agent.tools.llm_client.get_llm_client",
        lambda provider=None: fake_llm,
    )
    # nodes.py 在 import 时绑定了 get_llm_client，_safe_llm_invoke 用的是该引用
    import qing_investment.agent.graph.nodes as nodes_module

    monkeypatch.setattr(nodes_module, "get_llm_client", lambda provider=None: fake_llm)

    # devils_advocate 直接实例化 DevilsAdvocateAgent，需要单独 mock
    import qing_investment.agent.agents.devils_advocate as da_module

    class _FakeDevilsAdvocateResult:
        findings = [{"target": "mock", "point": "mock finding"}]
        errors = []
        cost_usd = 0.0

    class _FakeDevilsAdvocateAgent:
        def __init__(self, llm=None):
            pass

        async def run(self, **kwargs):
            return _FakeDevilsAdvocateResult()

    monkeypatch.setattr(da_module, "DevilsAdvocateAgent", _FakeDevilsAdvocateAgent)

    # 5) build + invoke graph（必须在 patch retrieve_knowledge 之后再 import build_graph，
    #    否则 graph 会持有原函数的引用）
    import asyncio

    from qing_investment.agent.graph.builder import build_graph

    graph = build_graph()
    result = asyncio.run(graph.ainvoke(state))

    # 5) 验证流程走完并产生输出
    assert result["final_output"]
    assert "mock 早盘观察" in result["final_output"]
    assert result.get("review_passed") is True

    # 验证多个节点确实调用了 LLM
    assert len(fake_llm.calls) >= 5


def test_qing_agent_internal_sharding(monkeypatch, tmp_path):
    """验证 watchlist 超过 shard_size 时，graph 内部走分片并行扫描。"""
    monkeypatch.setenv("QING_AGENT_MOCK_QUOTES", "1")
    monkeypatch.setenv("QING_AGENT_IGNORE_TRADING_TIME", "1")
    monkeypatch.setenv("KIMI_CODE_ACP_FIRST", "0")
    monkeypatch.setenv("KIMI_CODE_CLI_FIRST", "0")

    config = make_mock_monitor_config()
    # 扩展观察池到 3 只，shard_size=1 强制分片
    config.watchlist["themes"].append({
        "id": "other",
        "name": "其他",
        "stocks": [
            {"code": "000002.SZ", "name": "万科A", "watch_reason": "测试"},
            {"code": "000063.SZ", "name": "中兴通讯", "watch_reason": "测试"},
        ],
    })

    agent_json_text = run_tick(
        config,
        datetime(2026, 5, 22, 10, 30, tzinfo=CN_TZ),
        emit_status=False,
        ignore_trading_time=False,
        agent_json_context=True,
        state_path=tmp_path / "state.json",
    )
    assert agent_json_text
    agent_json = json.loads(agent_json_text)

    query = agent_json["trigger"]["title"] + "：" + agent_json["trigger"]["reason"]
    state = _build_agent_state(agent_json, query)
    state["shard_size"] = 1
    state["core_only"] = False

    async def fake_retrieve_knowledge(state_in: dict) -> dict:
        return {
            "claims": [],
            "wiki_snippets": [],
            "knowledge_graph": {},
            "memories": [],
            "few_shot_examples": [],
        }

    monkeypatch.setattr(
        "qing_investment.agent.graph.nodes.retrieve_knowledge", fake_retrieve_knowledge
    )
    import qing_investment.agent.graph.builder as builder_module
    monkeypatch.setattr(builder_module, "retrieve_knowledge", fake_retrieve_knowledge)

    fake_llm = _FakeLangChainLLM()
    monkeypatch.setattr(
        "qing_investment.agent.tools.llm_client.get_llm_client",
        lambda provider=None: fake_llm,
    )
    import qing_investment.agent.graph.nodes as nodes_module
    monkeypatch.setattr(nodes_module, "get_llm_client", lambda provider=None: fake_llm)

    import qing_investment.agent.agents.devils_advocate as da_module

    class _FakeDevilsAdvocateResult:
        findings = [{"target": "mock", "point": "mock finding"}]
        errors = []
        cost_usd = 0.0

    class _FakeDevilsAdvocateAgent:
        def __init__(self, llm=None):
            pass

        async def run(self, **kwargs):
            return _FakeDevilsAdvocateResult()

    monkeypatch.setattr(da_module, "DevilsAdvocateAgent", _FakeDevilsAdvocateAgent)

    import asyncio
    from qing_investment.agent.graph.builder import build_graph

    graph = build_graph()
    result = asyncio.run(graph.ainvoke(state))

    assert result["final_output"]
    assert result.get("review_passed") is True
    # 至少调用了 market_summary + 多个 stock_scanner_shard + style + reviewer
    assert len(fake_llm.calls) >= 5
