# 方案C：投研级多Agent数字分身系统（Hermes云端子Agent集成版）

> 目标：基于现有 `learning-investment-strategies` 项目，构建一个云端运行的多Agent投研系统，作为 Hermes 的**子 Agent**，使股票分析具备UP人格化表达、跨周期关联、观点演化和事实核查能力。
>
> 核心变化：Hermes 负责调度/监控/微信推送，qing-agent 负责深度分析。Hermes 不再直接调用大模型 API，而是通过 HTTP 把结构化上下文发给 qing-agent，由后者调用配置好的 LLM 返回带引用、证据表和观点演化时间线的分析结果。

---

## 1. 架构总览

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              用户（微信端）                                │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          Hermes 主服务（云端）                             │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  Cron 调度器                                                        │  │
│  │  ├─ 每10分钟 → qing_stock_monitor.py → 规则监控 → 微信告警          │  │
│  │  └─ 固定时间 → qing_stock_monitor_agent.py → 构建结构化上下文        │  │
│  │                                              ↓                     │  │
│  │                                      HTTP POST /analyze/trigger    │  │
│  │                                              ↓                     │  │
│  │                                    ┌─────────────────────┐         │  │
│  │                                    │   qing-agent 子 Agent │         │  │
│  │                                    │  （同机 localhost:8000）│        │  │
│  │                                    └─────────────────────┘         │  │
│  │                                              ↓                     │  │
│  │                                    返回结构化分析结果               │  │
│  │                                              ↓                     │  │
│  │                                    微信推送（ richer 格式）          │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
                                   │
                                   │ 内部 HTTP（localhost:8000）
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                        qing-agent 深度分析引擎                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐               │
│  │  Orchestrator│  │   Knowledge  │  │    Market        │               │
│  │   (LangGraph)│  │   Retriever  │  │   Analyst        │               │
│  └──────┬───────┘  │(Neo4j+Qdrant)│  └────────┬─────────┘               │
│         │          └──────┬───────┘           │                         │
│         │                 │                   │                         │
│         ▼                 ▼                   ▼                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐               │
│  │    Stock     │  │    Style     │  │    Reviewer      │               │
│  │   Analyst    │  │   Writer     │  │   (事实核查)      │               │
│  └──────────────┘  └──────────────┘  └──────────────────┘               │
│                                                                          │
│  存储层：Neo4j + Qdrant + PostgreSQL + Mem0                             │
│  LLM：多厂商可配置（OpenAI / Kimi / DeepSeek / 通义 / 智谱 / SiliconFlow 等）│
└──────────────────────────────────────────────────────────────────────────┘
```

**角色分工：**

| 角色 | 职责 | 技术载体 |
|------|------|----------|
| **Hermes 主服务** | cron调度、规则监控、构建上下文、微信推送 | 现有 cron + shell 脚本 |
| **qing-agent 子Agent** | 深度分析（图谱检索、观点演化、UP风格、事实核查） | FastAPI + LangGraph |
| **存储层** | 知识图谱、向量检索、长期记忆 | Neo4j + Qdrant + PostgreSQL + Mem0 |

---

## 2. qing-agent 核心实现（重点）

### 2.1 项目结构

在现有项目内新增 `src/qing_investment/agent/` 目录：

```
src/qing_investment/agent/
├── __init__.py
├── main.py                  # FastAPI入口
├── config.py                # 环境变量配置（Pydantic Settings）
├── graph/
│   ├── __init__.py
│   ├── state.py             # LangGraph共享状态定义
│   ├── builder.py           # StateGraph构建器
│   ├── nodes.py             # 各Agent节点实现
│   └── edges.py             # 条件路由边
├── tools/
│   ├── __init__.py
│   ├── neo4j_client.py      # 知识图谱查询（Cypher）
│   ├── qdrant_client.py     # 向量语义检索
│   ├── mem0_client.py       # 长期记忆读写
│   ├── llm_client.py        # 通用LLM客户端（多厂商兼容，OpenAI API格式）
│   ├── stock_data.py        # 复用现有stock_monitor数据读取
│   └── style_injector.py    # UP人格注入工具
├── prompts/
│   ├── __init__.py
│   ├── system/              # System Prompt模板
│   │   ├── orchestrator.txt
│   │   ├── market_analyst.txt
│   │   ├── stock_analyst.txt
│   │   ├── style_writer.txt
│   │   └── reviewer.txt
│   └── few_shot/            # Few-shot示例库
│       ├── early_market.md
│       ├── intraday_alert.md
│       ├── sector_rotation.md
│       └── stock_specific.md
└── models/
    ├── __init__.py
    └── schemas.py           # Pydantic模型（Request/Response）
```

### 2.2 依赖（pyproject.toml）

```toml
[project.optional-dependencies]
agent = [
  "langgraph>=0.2.0",
  "langchain>=0.3.0",
  "langchain-openai>=0.2.0",    # 兼容各厂商OpenAI API格式
  "fastapi>=0.115.0",
  "uvicorn>=0.32.0",
  "neo4j>=5.24.0",
  "qdrant-client>=1.12.0",
  "mem0ai>=0.1.0",
  "sentence-transformers>=3.0",  # 本地Embedding模型
  "pydantic-settings>=2.0",
]
```

安装：
```bash
uv pip install -e ".[agent]"
```

### 2.2.1 通用LLM配置（config.py）

qing-agent 支持多厂商大模型，通过 `LLM_PROVIDER` 环境变量切换，**无需修改代码**。

```python
# src/qing_investment/agent/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # === LLM 通用配置 ===
    llm_provider: str = "kimi"      # 可选: openai, azure, kimi, deepseek, zhipu, qwen, baichuan, siliconflow, groq, together
    llm_model: str | None = None    # 覆盖默认模型（可选）
    llm_base_url: str | None = None # 覆盖默认base_url（可选，仅azure等需要）
    
    # 各厂商API Key（按需填写，不用的可留空）
    openai_api_key: str | None = None
    azure_openai_api_key: str | None = None
    kimi_api_key: str | None = None
    deepseek_api_key: str | None = None
    zhipu_api_key: str | None = None
    qwen_api_key: str | None = None
    baichuan_api_key: str | None = None
    siliconflow_api_key: str | None = None
    groq_api_key: str | None = None
    together_api_key: str | None = None
    
    # === 存储层配置 ===
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str
    
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    
    mem0_api_key: str | None = None
    mem0_base_url: str = "http://localhost:8001"
    
    # === 项目路径 ===
    repo_path: str = "/opt/qing-agent"
    
    class Config:
        env_file = ".env"

settings = Settings()
```

**`.env` 配置示例（切换不同厂商只需改2行）：**

```bash
# 示例1：使用 Kimi
LLM_PROVIDER=kimi
KIMI_API_KEY=sk-xxx

# 示例2：使用 DeepSeek
# LLM_PROVIDER=deepseek
# DEEPSEEK_API_KEY=sk-xxx

# 示例3：使用 OpenAI
# LLM_PROVIDER=openai
# OPENAI_API_KEY=sk-xxx
# LLM_MODEL=gpt-4o

# 示例4：使用 SiliconFlow（模型聚合平台，一个Key调多个模型）
# LLM_PROVIDER=siliconflow
# SILICONFLOW_API_KEY=sk-xxx
# LLM_MODEL=deepseek-ai/DeepSeek-R1

# 存储层
NEO4J_PASSWORD=your-neo4j-password
POSTGRES_PASSWORD=your-postgres-password
```

**支持的厂商列表（预置在 `llm_client.py` 中）：**

| Provider | Base URL | 默认模型 | 说明 |
|----------|----------|---------|------|
| `openai` | https://api.openai.com/v1 | gpt-4o | 国际通用 |
| `azure` | 需自定义 | gpt-4o | 企业级，需配 `llm_base_url` |
| `kimi` | https://api.moonshot.cn/v1 | moonshot-v1-128k | 长上下文强项 |
| `deepseek` | https://api.deepseek.com/v1 | deepseek-chat | 推理价格低 |
| `zhipu` | https://open.bigmodel.cn/api/paas/v4 | glm-4 | 中文理解好 |
| `qwen` | https://dashscope.aliyuncs.com/compatible-mode/v1 | qwen-max | 阿里通义 |
| `baichuan` | https://api.baichuan-ai.com/v1 | Baichuan4 | 百川智能 |
| `siliconflow` | https://api.siliconflow.cn/v1 | deepseek-ai/DeepSeek-V3 | 国内模型聚合平台 |
| `groq` | https://api.groq.com/openai/v1 | llama-3.3-70b-versatile | 海外高速推理 |
| `together` | https://api.together.xyz/v1 | meta-llama/Llama-3.3-70B | 海外开源模型 |

### 2.3 LangGraph 状态机设计

#### 状态定义（`graph/state.py`）

```python
from typing import TypedDict, Annotated, Sequence
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    # 输入层
    query: str                          # 用户原始问题/触发描述
    session_id: str                     # 会话ID（用于Mem0记忆）
    trigger: dict | None                # Hermes传入的触发信息
    alerts: list[dict]                  # 规则信号列表
    market_snapshot: dict               # 行情快照
    positions: list[dict]               # 当前持仓
    watchlist: list[dict]               # 观察池关键标的

    # 检索层
    claims: list[dict]                  # 检索到的相关claims
    wiki_snippets: list[dict]           # 语义检索到的wiki片段
    knowledge_graph: dict               # Neo4j查询结果（实体关系路径）
    memories: list[dict]                # Mem0检索到的用户偏好和UP历史立场
    few_shot_examples: list[str]        # 动态检索的Few-shot示例

    # 分析层
    market_context: dict                # 市场分析结果（周期/主线/板块）
    stock_analysis: dict                # 个股分析结果（地位/技术/基本面）
    draft_analysis: str                 # 综合分析草稿

    # 生成层
    styled_output: str                  # UP风格化后的最终文本
    review_notes: list[str]             # Reviewer的修改意见

    # 输出层
    final_output: str                   # 最终输出（Hermes直接转发微信）
    claims_cited: list[str]             # 引用的claim IDs
    data_sources: list[str]             # 数据来源列表
    confidence: str                     # high / medium / low
    review_passed: bool                 # 事实核查是否通过
    reasoning_steps: list[str]          # 思考步骤（调试用）
```

#### 图结构（`graph/builder.py`）

```python
from langgraph.graph import StateGraph, END
from .state import AgentState
from . import nodes, edges

def build_graph() -> StateGraph:
    builder = StateGraph(AgentState)

    # 注册节点
    builder.add_node("parse_query", nodes.parse_query)
    builder.add_node("retrieve_knowledge", nodes.retrieve_knowledge)
    builder.add_node("market_analyst", nodes.market_analyst)
    builder.add_node("stock_analyst", nodes.stock_analyst)
    builder.add_node("synthesize", nodes.synthesize)
    builder.add_node("style_writer", nodes.style_writer)
    builder.add_node("reviewer", nodes.reviewer)

    # 边：线性 + 并行 + 条件
    builder.set_entry_point("parse_query")
    builder.add_edge("parse_query", "retrieve_knowledge")

    # retrieve_knowledge 之后并行执行 market_analyst 和 stock_analyst
    builder.add_edge("retrieve_knowledge", "market_analyst")
    builder.add_edge("retrieve_knowledge", "stock_analyst")

    # 两者都完成后进入 synthesize
    builder.add_edge("market_analyst", "synthesize")
    builder.add_edge("stock_analyst", "synthesize")

    # synthesize → style_writer → reviewer
    builder.add_edge("synthesize", "style_writer")
    builder.add_edge("style_writer", "reviewer")

    # reviewer 条件边：通过则结束，不通过则回 style_writer
    builder.add_conditional_edges(
        "reviewer",
        edges.review_router,
        {
            "pass": END,
            "fail": "style_writer",
        },
    )

    return builder.compile()
```

### 2.4 各Agent节点详解

#### Node 1: parse_query（意图解析）

```python
def parse_query(state: AgentState) -> AgentState:
    """解析用户/Hermes输入，提取股票代码、分析类型、时间紧迫度"""
    query = state["query"]

    # 用LLM做意图识别和实体抽取
    llm = get_llm_client()
    prompt = f"""
    从以下输入中提取信息，返回JSON：
    - stock_code: 股票代码（如有）
    - analysis_type: stock(个股) / market(市场) / portfolio(持仓复盘)
    - urgency: scheduled(定时) / event(事件触发)
    - focus: 用户关注的具体问题

    输入：{query}
    """
    response = llm.invoke(prompt)
    parsed = json.loads(response.content)

    return {
        **state,
        "parsed_intent": parsed,
        "reasoning_steps": [f"意图解析: {parsed['analysis_type']}, 标的: {parsed.get('stock_code', 'N/A')}"],
    }
```

#### Node 2: retrieve_knowledge（知识检索）

**核心逻辑**：并行查询三个数据源，合并去重。

```python
import asyncio

async def retrieve_knowledge(state: AgentState) -> AgentState:
    query = state["query"]
    stock_code = state.get("parsed_intent", {}).get("stock_code")
    session_id = state["session_id"]

    # 并行检索
    results = await asyncio.gather(
        # 1. Neo4j：实体关系图谱
        neo4j_search(query, stock_code),
        # 2. Qdrant：语义相似文档
        qdrant_search(query, top_k=5),
        # 3. Mem0：用户记忆 + UP立场
        mem0_search(session_id, query),
        # 4. Few-shot示例库
        few_shot_retrieve(query),
    )

    neo4j_result, qdrant_result, mem0_result, few_shot = results

    return {
        **state,
        "claims": neo4j_result.get("claims", []),
        "knowledge_graph": neo4j_result.get("graph", {}),
        "wiki_snippets": qdrant_result,
        "memories": mem0_result,
        "few_shot_examples": few_shot,
        "reasoning_steps": state.get("reasoning_steps", []) + [
            f"检索到 {len(neo4j_result.get('claims', []))} 条claims",
            f"检索到 {len(qdrant_result)} 个wiki片段",
            f"检索到 {len(mem0_result)} 条记忆",
        ],
    }
```

**Neo4j 查询示例**：
```python
async def neo4j_search(query: str, stock_code: str | None) -> dict:
    driver = get_neo4j_driver()

    # 查询1：直接匹配股票/板块的claims
    cypher_claims = """
    MATCH (c:Claim)-[:ABOUT]->(s:Stock {code: $stock_code})
    WHERE c.status IN ['active', 'superseded']
    RETURN c.id, c.statement, c.confidence, c.source_date, c.status
    ORDER BY c.source_date DESC
    LIMIT 10
    """

    # 查询2：观点演化链（supersedes/contradicts）
    cypher_evolution = """
    MATCH (c:Claim {id: $claim_id})
    OPTIONAL MATCH (c)-[:SUPERSEDES]->(old:Claim)
    OPTIONAL MATCH (c)-[:CONTRADICTS]->(opp:Claim)
    RETURN c, old, opp
    """

    # 查询3：关联wiki文档
    cypher_wiki = """
    MATCH (c:Claim)-[:CITED_IN]->(w:WikiPage)
    WHERE c.id IN $claim_ids
    RETURN w.title, w.path, collect(DISTINCT c.id) as claims
    """

    with driver.session() as session:
        claims = session.run(cypher_claims, stock_code=stock_code).data()
        # ... 其他查询

    return {"claims": claims, "graph": {...}}
```

**Qdrant 查询示例**：
```python
async def qdrant_search(query: str, top_k: int = 5) -> list[dict]:
    client = get_qdrant_client()

    # 用本地Embedding模型生成查询向量
    embedding = get_embedding_model().encode(query)

    results = client.search(
        collection_name="qing_knowledge",
        query_vector=embedding.tolist(),
        limit=top_k,
        with_payload=True,
    )

    return [
        {
            "text": r.payload["chunk_text"],
            "source": r.payload["source"],
            "date": r.payload["date"],
            "score": r.score,
        }
        for r in results
    ]
```

**Mem0 查询示例**：
```python
async def mem0_search(session_id: str, query: str) -> list[dict]:
    mclient = get_mem0_client()

    # 检索用户偏好 + UP近期立场
    memories = mclient.search(
        query=query,
        user_id=session_id,
        filters={"type": ["user_preference", "agent_preference", "fact"]},
    )

    return memories
```

#### Node 3: market_analyst（市场分析师）

```python
def market_analyst(state: AgentState) -> AgentState:
    """
    判断：周期定位 → 主线识别 → 板块强弱
    输出 market_context 字典
    """
    llm = get_llm_client()

    prompt = load_prompt("market_analyst.txt")
    # prompt 内容见下方 2.5 Prompt 体系

    # 注入检索到的知识
    context = build_market_context(
        claims=state["claims"],
        wiki_snippets=state["wiki_snippets"],
        market_snapshot=state["market_snapshot"],
        memories=state["memories"],
    )

    response = llm.invoke(prompt.format(context=context))
    result = json.loads(response.content)

    return {
        **state,
        "market_context": result,
        "reasoning_steps": state.get("reasoning_steps", []) + [
            f"市场周期: {result['market_phase']}",
            f"当前主线: {', '.join(result['main_themes'])}",
        ],
    }
```

#### Node 4: stock_analyst（个股分析师）

```python
def stock_analyst(state: AgentState) -> AgentState:
    """
    判断：个股地位 → 技术位置 → F10基本面 → 多空证据表
    输出 stock_analysis 字典
    """
    llm = get_llm_client()
    prompt = load_prompt("stock_analyst.txt")

    context = build_stock_context(
        stock_code=state["parsed_intent"].get("stock_code"),
        positions=state["positions"],
        watchlist=state["watchlist"],
        claims=state["claims"],
        market_context=state["market_context"],
    )

    response = llm.invoke(prompt.format(context=context))
    result = json.loads(response.content)

    return {
        **state,
        "stock_analysis": result,
        "reasoning_steps": state.get("reasoning_steps", []) + [
            f"个股地位: {result['stock_role']}",
            f"技术位置: {result['technical_position']}",
        ],
    }
```

#### Node 5: synthesize（综合合成）

```python
def synthesize(state: AgentState) -> AgentState:
    """合并 market_analyst 和 stock_analyst 的结果，生成分析草稿"""
    market = state["market_context"]
    stock = state["stock_analysis"]

    draft = f"""
【盘面】{market['market_summary']}

【周期定位】{market['market_phase']}，{market['phase_reasoning']}

【主线判断】{', '.join(market['main_themes'])}

【个股地位】{stock['stock_name']}({stock['stock_code']}) 当前为 {stock['stock_role']}。
{stock['role_reasoning']}

【技术位置】{stock['technical_position']}

【多空证据】
利多：{'；'.join(stock['bullish_evidence'])}
利空：{'；'.join(stock['bearish_evidence'])}

【触发条件】{stock['trigger_conditions']}
【失效条件】{stock['invalidation_conditions']}

【风险提示】{stock['risk_notes']}
"""

    return {
        **state,
        "draft_analysis": draft,
        "reasoning_steps": state.get("reasoning_steps", []) + ["综合合成完成"],
    }
```

#### Node 6: style_writer（风格化生成）

```python
def style_writer(state: AgentState) -> AgentState:
    """
    注入UP人格、语气、修辞，把分析草稿改写成UP风格。
    如果 reviewer 打回，根据 review_notes 修正。
    """
    llm = get_llm_client()
    prompt = load_prompt("style_writer.txt")

    # 注入UP人格定义 + Few-shot示例 + 市场周期对应的语气强度
    persona = load_persona()
    examples = "\n\n".join(state["few_shot_examples"])
    tone = get_tone_by_market_phase(state["market_context"]["market_phase"])

    # 如果有 reviewer 的修改意见，一起注入
    review_notes = state.get("review_notes", [])
    revision_hint = ""
    if review_notes:
        revision_hint = f"【上一轮修改意见】{'；'.join(review_notes)}\n请按以上意见修正。"

    response = llm.invoke(prompt.format(
        draft=state["draft_analysis"],
        persona=persona,
        examples=examples,
        tone=tone,
        revision_hint=revision_hint,
    ))

    return {
        **state,
        "styled_output": response.content,
        "reasoning_steps": state.get("reasoning_steps", []) + ["风格化生成完成"],
    }
```

#### Node 7: reviewer（事实核查员）

```python
def reviewer(state: AgentState) -> AgentState:
    """
    检查：
    1. 是否有无条件买卖指令
    2. claim引用是否准确（与检索到的 claims 对比）
    3. 与UP历史立场是否矛盾（检查 contradicts 链）
    4. 数据时间戳是否标注
    5. 风格是否符合UP人设（攻击性词汇、过度乐观等）
    """
    llm = get_llm_client()
    prompt = load_prompt("reviewer.txt")

    response = llm.invoke(prompt.format(
        output=state["styled_output"],
        claims=json.dumps(state["claims"], ensure_ascii=False),
        cited_claims=json.dumps(state.get("claims_cited", []), ensure_ascii=False),
    ))

    result = json.loads(response.content)

    return {
        **state,
        "review_passed": result["passed"],
        "review_notes": result.get("issues", []),
        "claims_cited": result.get("verified_claims", []),
        "reasoning_steps": state.get("reasoning_steps", []) + [
            f"事实核查: {'通过' if result['passed'] else '未通过'}"
        ],
    }
```

#### 条件路由边（`graph/edges.py`）

```python
def review_router(state: AgentState) -> str:
    if state.get("review_passed", False):
        return "pass"
    # 最多重试3次，避免无限循环
    retry_count = state.get("_retry_count", 0)
    if retry_count >= 3:
        return "pass"  # 强制通过，但标记需要人工复核
    return "fail"
```

### 2.5 Prompt 体系

#### system/market_analyst.txt

```
你是青枫浦上Q（UP）的市场分析助手。你的任务是根据检索到的博主观点和实时行情，判断当前市场周期和主线方向。

分析框架（必须按此顺序）：
1. 周期定位：当前处于冰点/回暖/高潮/退潮的哪个阶段？依据是什么？
2. 主线识别：当前市场核心主线是什么？支线有哪些？
3. 板块强弱：进攻板块（科技/成长）和防御板块（红利/高股息）的相对强度如何？
4. 情绪指标：涨停家数、连板高度、炸板率等情绪信号

约束：
- 必须引用具体的 claim ID 作为依据
- 区分"博主观点"和"客观数据"
- 不要给出个股操作建议（这是 stock_analyst 的职责）

输出格式：JSON
{
  "market_phase": "回暖期",
  "phase_reasoning": "...",
  "main_themes": ["AI硬件", "半导体"],
  "sector_strength": {...},
  "emotion_signals": {...}
}
```

#### system/stock_analyst.txt

```
你是青枫浦上Q的个股分析助手。在 market_analyst 判断的市场语境下，分析具体个股。

分析框架：
1. 个股地位：核心/跟风/补涨/后排？依据是什么？
2. 技术位置：支撑、压力、均线排列、量价关系
3. 基本面：F10关键指标（ROE、现金流、估值）
4. 多空证据表：列出至少2条利多和2条利空
5. 触发条件：什么情况下可以介入？
6. 失效条件：什么情况下逻辑证伪？

约束：
- 必须区分证据、解释、推断
- 必须给出触发条件和失效条件
- 禁止无条件买卖指令

输出格式：JSON
{
  "stock_code": "...",
  "stock_name": "...",
  "stock_role": "核心",
  "role_reasoning": "...",
  "technical_position": "...",
  "f10_summary": "...",
  "bullish_evidence": [...],
  "bearish_evidence": [...],
  "trigger_conditions": "...",
  "invalidation_conditions": "...",
  "risk_notes": "..."
}
```

#### system/style_writer.txt

```
你是青枫浦上Q的语言风格模拟器。你的任务是把专业的分析草稿，改写成UP的口吻和表达方式。

UP的人格特征：
- 身份：B站财经UP主，风格犀利但不劝赌
- 口头禅："不见长虹不回头"、"先把弹药留出来"、"等缩量等情绪回暖"
- 语气：根据市场周期变化
  - 冰点期：安抚、鼓励，"不要恐慌"
  - 回暖期：谨慎乐观，"可以试错但要控制仓位"
  - 高潮期：劝退、警示，"不要追高，韭菜行为"
  - 退潮期：收缩、防御，"收缩战线，保住利润"
- 禁忌：绝不给无条件的买卖指令、不说"一定涨/跌"、不用机构研报腔

参考示例（相似场景的历史表达）：
{examples}

当前市场语气强度：{tone}

{revision_hint}

请把以下草稿改写成UP风格：
{draft}
```

#### system/reviewer.txt

```
你是事实核查员。你的任务是检查AI生成的分析是否符合以下规则：

核查清单：
1. [ ] 是否包含无条件买卖指令？（如"买入"、"卖出"、"满仓"而没有条件限定）
2. [ ] 引用的 claim ID 是否真实存在？是否与检索到的 claims 一致？
3. [ ] 是否与UP的历史立场矛盾？（检查 contradicts 关系）
4. [ ] 是否标注了数据来源和时间戳？
5. [ ] 是否混淆了"博主观点"和"客观事实"？
6. [ ] 风格是否过度偏离UP人设？（如过于学术、过于情绪化）

如果发现问题，列出具体修改意见。如果没有问题，返回 passed=true。

输出格式：JSON
{
  "passed": true/false,
  "issues": ["问题1", "问题2"],
  "verified_claims": ["claim-id-1", "claim-id-2"]
}
```

### 2.6 FastAPI 接口定义（`main.py`）

```python
from fastapi import FastAPI
from pydantic import BaseModel, Field
from .graph.builder import build_graph
from .config import settings

app = FastAPI(title="Qing-Agent", version="0.1.0")
graph = build_graph()

# --- 请求/响应模型 ---

class TriggerRequest(BaseModel):
    trigger: dict = Field(description="Hermes传入的触发信息")
    alerts: list[dict] = Field(default=[], description="规则信号列表")
    market_snapshot: dict = Field(default={}, description="行情快照")
    positions: list[dict] = Field(default=[], description="当前持仓")
    watchlist: list[dict] = Field(default=[], description="观察池关键标的")
    session_id: str = Field(default="default", description="会话ID")
    query: str = Field(default="", description="用户原始问题")

class TriggerResponse(BaseModel):
    final_output: str = Field(description="UP风格化的最终分析文本")
    claims_cited: list[str] = Field(default=[], description="引用的claim IDs")
    data_sources: list[str] = Field(default=[], description="数据来源")
    confidence: str = Field(default="medium", description="置信度")
    review_passed: bool = Field(default=False, description="事实核查是否通过")
    reasoning_steps: list[str] = Field(default=[], description="思考步骤")

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"

class ChatResponse(BaseModel):
    reply: str
    memories_used: list[dict] = []

# --- 端点 ---

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}

@app.post("/analyze/trigger", response_model=TriggerResponse)
async def analyze_trigger(req: TriggerRequest):
    """
    Hermes 调用的主接口。
    接收结构化上下文，运行多Agent分析流水线，返回UP风格分析结果。
    """
    state = {
        "query": req.query or f"{req.trigger.get('title')}：{req.trigger.get('reason')}",
        "session_id": req.session_id,
        "trigger": req.trigger,
        "alerts": req.alerts,
        "market_snapshot": req.market_snapshot,
        "positions": req.positions,
        "watchlist": req.watchlist,
        # 初始化其他字段
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
    }

    result = await graph.ainvoke(state)

    return TriggerResponse(
        final_output=result["final_output"],
        claims_cited=result.get("claims_cited", []),
        data_sources=result.get("data_sources", []),
        confidence=result.get("confidence", "medium"),
        review_passed=result.get("review_passed", False),
        reasoning_steps=result.get("reasoning_steps", []),
    )

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """
    可选：直接对话接口。不走完整的 trigger 流程，而是轻量级问答。
    用于非交易时间的快速问答（如"UP 怎么看光模块"）。
    """
    # 简化版：直接检索知识库 + 生成回答
    # ...
    return ChatResponse(reply="...")

@app.post("/memory/add")
async def add_memory(session_id: str, content: str, memory_type: str = "fact"):
    """
    向 Mem0 写入记忆。可用于：
    - 用户反馈（"这次分析太乐观了"）
    - UP 新观点（手动录入）
    """
    # ...
    return {"status": "ok"}

# 启动命令（开发）
# uv run uvicorn qing_investment.agent.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2.7 工具层实现要点

#### llm_client.py（通用多厂商LLM客户端）

```python
import os
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from sentence_transformers import SentenceTransformer

# 预置常见大模型厂商配置（写死，用户只需配置 provider + api_key）
LLM_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "api_key_env": "OPENAI_API_KEY",
    },
    "azure": {
        "base_url": None,  # 用户需自定义: https://{resource}.openai.azure.com/openai/deployments/{deployment}
        "default_model": "gpt-4o",
        "api_key_env": "AZURE_OPENAI_API_KEY",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-128k",
        "api_key_env": "KIMI_API_KEY",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4",
        "api_key_env": "ZHIPU_API_KEY",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-max",
        "api_key_env": "QWEN_API_KEY",
    },
    "baichuan": {
        "base_url": "https://api.baichuan-ai.com/v1",
        "default_model": "Baichuan4",
        "api_key_env": "BAICHUAN_API_KEY",
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "api_key_env": "SILICONFLOW_API_KEY",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "api_key_env": "GROQ_API_KEY",
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "api_key_env": "TOGETHER_API_KEY",
    },
}

def get_llm_client():
    """根据配置的 provider 返回对应的 LLM 客户端"""
    provider = settings.llm_provider.lower()
    if provider not in LLM_PROVIDERS:
        raise ValueError(
            f"Unknown LLM provider: {provider}. "
            f"Supported: {', '.join(LLM_PROVIDERS.keys())}"
        )
    
    config = LLM_PROVIDERS[provider]
    api_key = getattr(settings, config["api_key_env"].lower(), None) \
              or os.environ.get(config["api_key_env"])
    base_url = config["base_url"] or settings.llm_base_url
    model = settings.llm_model or config["default_model"]
    
    if not api_key:
        raise ValueError(
            f"Provider '{provider}' requires {config['api_key_env']}. "
            f"Set it in .env or environment variable."
        )
    if not base_url:
        raise ValueError(
            f"Provider '{provider}' requires llm_base_url to be set."
        )
    
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.3,
        max_tokens=4096,
    )

# Embedding 客户端（本地 BGE，与 LLM 厂商无关）
_embedding_model = None

def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer("BAAI/bge-large-zh-v1.5")
    return _embedding_model
```

#### neo4j_client.py

```python
from neo4j import GraphDatabase

class Neo4jClient:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    def get_claims_about_stock(self, stock_code: str, limit: int = 10):
        query = """
        MATCH (c:Claim)-[:ABOUT]->(s:Stock {code: $stock_code})
        WHERE c.status IN ['active', 'superseded']
        RETURN c.id as id, c.statement as statement,
               c.confidence as confidence, c.source_date as source_date,
               c.status as status
        ORDER BY c.source_date DESC
        LIMIT $limit
        """
        with self.driver.session() as session:
            return session.run(query, stock_code=stock_code, limit=limit).data()

    def get_claim_evolution(self, claim_id: str):
        """获取某条 claim 的演化链（被谁替代、与谁矛盾）"""
        query = """
        MATCH (c:Claim {id: $claim_id})
        OPTIONAL MATCH (c)-[:SUPERSEDES]->(old:Claim)
        OPTIONAL MATCH (c)-[:CONTRADICTS]->(opp:Claim)
        OPTIONAL MATCH (new:Claim)-[:SUPERSEDES]->(c)
        RETURN c, old, opp, new
        """
        with self.driver.session() as session:
            return session.run(query, claim_id=claim_id).data()

    def search_by_theme(self, theme: str, limit: int = 10):
        """按主题模糊搜索 claims"""
        query = """
        MATCH (c:Claim)
        WHERE c.subject CONTAINS $theme OR c.statement CONTAINS $theme
        RETURN c LIMIT $limit
        """
        with self.driver.session() as session:
            return session.run(query, theme=theme, limit=limit).data()
```

#### mem0_client.py

```python
from mem0 import MemoryClient

class Mem0Client:
    def __init__(self):
        self.client = MemoryClient(
            api_key=settings.mem0_api_key or "local",
            host=settings.mem0_base_url,
        )

    def search(self, query: str, user_id: str, filters: dict = None):
        return self.client.search(
            query=query,
            user_id=user_id,
            filters=filters,
        )

    def add(self, content: str, user_id: str, metadata: dict = None):
        return self.client.add(
            messages=content,
            user_id=user_id,
            metadata=metadata or {},
        )
```

---

## 3. 与 Hermes 的集成

### 3.1 数据流

```
Hermes Cron 触发
  → qing_stock_monitor_agent.py 运行
    → 调用 stock_monitor.py --agent-json-context（新增参数）
      → 输出结构化 JSON（而非纯文本）
    → 解析 JSON，构造 TriggerRequest
    → HTTP POST → qing-agent:8000/analyze/trigger
      → qing-agent 运行 LangGraph（5-10秒）
    → 接收 TriggerResponse
      → 提取 final_output
    → stdout 输出（Hermes 捕获并微信推送）
```

### 3.2 stock_monitor.py 改造：新增 `--agent-json-context`

在 `src/qing_investment/stock_monitor.py` 中新增：

```python
def format_agent_analysis_json(
    config: MonitorConfig,
    value: datetime,
    trigger: AgentAnalysisTrigger,
    alerts: list[RuleAlert],
    quote_snapshot: dict,
    state: dict,
) -> dict:
    """返回结构化字典，供 qing-agent 消费"""
    stage = config.strategy_pack.get("market_framework", {}).get("current_stage", "未配置")
    core_question = config.strategy_pack.get("market_framework", {}).get("core_question", "未配置")

    return {
        "timestamp": value.astimezone(CN_TZ).isoformat(),
        "trigger": {
            "kind": trigger.kind,
            "id": trigger.id,
            "title": trigger.title,
            "reason": trigger.reason,
        },
        "alerts": [
            {
                "action": a.action,
                "stock_code": a.stock_code,
                "stock_name": a.stock_name,
                "price": a.price,
                "trigger": a.trigger,
                "severity": a.severity,
                "summary": a.summary,
            }
            for a in alerts
        ],
        "market_snapshot": quote_snapshot,
        "market_framework": {
            "stage": stage,
            "core_question": core_question,
        },
        "positions": extract_positions_for_agent(config.positions),
        "watchlist_focus": extract_watchlist_for_agent(config.watchlist),
    }
```

CLI 参数新增：
```python
parser.add_argument(
    "--agent-json-context",
    action="store_true",
    help="输出结构化的JSON分析上下文（供qing-agent消费）",
)
```

### 3.3 hermes_stock_monitor_agent.py 改造

```python
#!/usr/bin/env python3
import os
import sys
import subprocess
import json
import urllib.request
from pathlib import Path

QING_AGENT_URL = os.environ.get("QING_AGENT_URL", "http://localhost:8000")

def repo_root() -> str:
    configured = os.environ.get("HERMES_REPO_ROOT")
    if configured:
        return configured
    cwd = Path.cwd()
    if (cwd / "scripts" / "stock_monitor.py").exists():
        return str(cwd)
    return str(Path(__file__).resolve().parents[1])

def main():
    # 1. 获取结构化JSON上下文
    command = [
        "uv", "run", "python", "scripts/stock_monitor.py",
        "--agent-json-context",
    ] + sys.argv[1:]

    result = subprocess.run(
        command, cwd=repo_root(), capture_output=True, text=True
    )

    try:
        context_json = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        # Fallback：输出原始文本
        print(result.stdout)
        return 0

    if not context_json:
        return 0

    # 2. 构造请求发给 qing-agent
    payload = {
        "trigger": context_json["trigger"],
        "alerts": context_json.get("alerts", []),
        "market_snapshot": context_json.get("market_snapshot", {}),
        "positions": context_json.get("positions", []),
        "watchlist": context_json.get("watchlist_focus", []),
        "session_id": "hermes-cloud-001",
        "query": f"{context_json['trigger']['title']}：{context_json['trigger']['reason']}",
    }

    req = urllib.request.Request(
        f"{QING_AGENT_URL}/analyze/trigger",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            # 输出最终文本给 Hermes
            print(result["final_output"])
    except Exception as e:
        # Fallback：输出简化版上下文，让 Hermes 原有 prompt 处理
        print(f"【{context_json['trigger']['title']}】{context_json['trigger']['reason']}")
        if context_json.get("alerts"):
            for alert in context_json["alerts"]:
                print(f"- {alert['summary']}")
        print(f"\n[qing-agent error: {e}]")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

### 3.4 Hermes Cron 配置

修改 `install-cloud-crons.sh`：

```bash
# 新增环境变量校验
: "${QING_AGENT_URL:?Set QING_AGENT_URL, e.g. http://localhost:8000}"

# Hermes 的 prompt 可以简化（因为风格化由 qing-agent 负责）
# 或者直接 --no-agent，让 Hermes 只做消息路由
AGENT_PROMPT="直接输出脚本返回的内容，不要修改格式。"

hermes cron create "26 9 * * 1-5" "$AGENT_PROMPT" \
  --name "A股大模型分析-集合竞价后" \
  --workdir "$HERMES_REPO_ROOT" \
  --script qing_stock_monitor_agent.py \
  --env QING_AGENT_URL="$QING_AGENT_URL" \
  --deliver "$HERMES_DELIVER_TARGET"

# ... 其他时间点同理
```

---

## 4. 数据同步（本地→云端）

### 4.1 同步策略

云端 qing-agent 需要以下数据：

| 数据 | 同步方式 | 频率 |
|------|---------|------|
| `knowledge/claims/*.yaml` | git pull | 每次更新后 |
| `sources/raw/财经/*.md` | git pull | 每次更新后 |
| `knowledge/wiki/**/*.md` | git pull | 每次更新后 |
| `framework/*.md` | git pull | 每次更新后 |
| `config/stock_monitor/strategy_pack.yaml` | git pull | 每次更新后 |
| `config/stock_monitor/watchlist.yaml` | git pull | 每次更新后 |
| `config/stock_monitor/positions.yaml` | **不上云**，HTTP实时传入 | 每次分析时 |

### 4.2 增量索引脚本

`scripts/delta_index.py`：

```python
#!/usr/bin/env python3
"""
增量索引脚本：检测新增/修改的 raw/claims，更新 Neo4j 和 Qdrant。
建议在 git pull 后运行。
"""
import json
from pathlib import Path
from qing_investment.paths import repo_root
from qing_investment.agent.tools.neo4j_client import Neo4jClient
from qing_investment.agent.tools.qdrant_client import QdrantClient

def main():
    # 1. 读取 processed-log，找出新增 raw 文档
    processed_log = repo_root() / "sources" / "processed-log.md"
    # ... 解析已处理列表

    # 2. 对新增文档：抽取实体 → Neo4j；生成 embedding → Qdrant
    neo4j = Neo4jClient()
    qdrant = QdrantClient()

    for new_raw in find_new_raw_files():
        # 抽取 claims 并写入 Neo4j
        claims = extract_claims_from_raw(new_raw)
        for claim in claims:
            neo4j.create_claim_node(claim)

        # 切分 chunk 并写入 Qdrant
        chunks = chunk_document(new_raw)
        for chunk in chunks:
            qdrant.upsert_chunk(chunk)

    # 3. 对已更新的 claims，同步更新 Neo4j 状态（active/superseded/contradicted）
    for updated_claim in find_updated_claims():
        neo4j.update_claim_status(updated_claim["id"], updated_claim["status"])

    print("Delta index complete.")

if __name__ == "__main__":
    main()
```

云端 cron：
```bash
# 每小时拉取最新代码并增量索引
0 * * * * cd /opt/qing-agent && git pull origin master && uv run python scripts/delta_index.py
```

---

## 5. 云端部署

### 5.1 服务器要求

- 1台云服务器（2C4G起步，4C8G更佳）
- Docker + Docker Compose
- 公网IP（或内网VPC，取决于Hermes部署位置）
- 开放端口：8000（qing-agent，建议仅内网访问）

### 5.2 Docker Compose（基础设施）

`docker-compose.infra.yml`：

```yaml
version: "3.8"

services:
  neo4j:
    image: neo4j:5.19-community
    container_name: qing-neo4j
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      - NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}
      - NEO4J_PLUGINS=["apoc"]
    volumes:
      - ./infra/data/neo4j:/data

  qdrant:
    image: qdrant/qdrant:v1.9
    container_name: qing-qdrant
    ports:
      - "6333:6333"
    volumes:
      - ./infra/data/qdrant:/qdrant/storage

  postgres:
    image: postgres:16
    container_name: qing-postgres
    environment:
      - POSTGRES_USER=mem0
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=mem0
    volumes:
      - ./infra/data/postgres:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  mem0:
    image: mem0ai/mem0:latest
    container_name: qing-mem0
    ports:
      - "8001:8000"
    environment:
      - MEM0_STORE_TYPE=postgres
      - MEM0_STORE_URI=postgresql://mem0:${POSTGRES_PASSWORD}@postgres:5432/mem0
      - MEM0_VECTOR_STORE_TYPE=qdrant
      - MEM0_VECTOR_STORE_URI=http://qdrant:6333
    depends_on:
      - postgres
      - qdrant
```

启动：
```bash
mkdir -p infra/data/{neo4j,qdrant,postgres}
docker compose -f docker-compose.infra.yml up -d
```

### 5.3 qing-agent 服务部署

qing-agent 不 Docker 化，作为 systemd 服务运行（便于热更新代码）：

```bash
# 1. 克隆项目
git clone git@github-personal:zhoudirac-C/learning-investment-strategies.git /opt/qing-agent
cd /opt/qing-agent

# 2. 安装依赖
uv pip install -e ".[agent]"

# 3. 首次数据迁移
uv run python scripts/migrate_claims_to_neo4j.py
uv run python scripts/index_documents_to_qdrant.py
uv run python scripts/init_mem0_memories.py

# 4. 配置 systemd
sudo tee /etc/systemd/system/qing-agent.service <<EOF
[Unit]
Description=Qing Agent Sub-Agent Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/qing-agent
Environment=LLM_PROVIDER=${LLM_PROVIDER}
Environment=${LLM_API_KEY_ENV}=${LLM_API_KEY}
Environment=NEO4J_PASSWORD=${NEO4J_PASSWORD}
Environment=POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
ExecStart=/opt/qing-agent/.venv/bin/uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable qing-agent
sudo systemctl start qing-agent
```

验证：
```bash
curl http://localhost:8000/health
```

---

## 6. 运维与监控

### 6.1 日常命令

```bash
# 查看服务状态
sudo systemctl status qing-agent
docker compose -f docker-compose.infra.yml ps

# 查看日志
sudo journalctl -u qing-agent -f

# 增量更新知识库
cd /opt/qing-agent && git pull && uv run python scripts/delta_index.py

# 重启服务
sudo systemctl restart qing-agent
```

### 6.2 资源占用

在 2C4G 云服务器上：
- Neo4j：~1.5GB RAM
- Qdrant：~512MB RAM
- PostgreSQL：~256MB RAM
- Mem0：~512MB RAM
- qing-agent：~1GB RAM
- **总计：~4GB RAM**，余量充足

### 6.3 备份

```bash
# Neo4j 备份
docker exec qing-neo4j neo4j-admin database dump neo4j --to=/backups/neo4j-$(date +%Y%m%d).dump

# Qdrant 快照
curl -X POST http://localhost:6333/snapshots

# 项目代码
cd /opt/qing-agent && git push backup master
```

---

## 7. 成本估算

| 项目 | 估算 | 说明 |
|------|------|------|
| 云服务器（2C4G） | ~¥50-100/月 | 轻量应用服务器 |
| LLM API（推理） | ~¥30-100/月 | 每天7次固定分析 + 触发分析，价格因厂商而异 |
| LLM API（索引） | ~¥20-50（一次性） | 初始实体抽取，价格因厂商而异 |
| **总计** | **~¥100-200/月** | 含服务器 + API |

---

## 8. 风险与回退

### 8.1 主要风险

1. **Neo4j 图谱质量依赖 LLM 抽取**：缓解措施是在迁移脚本中加入人工审核环节。
2. **qing-agent 延迟 5-10 秒**：Reviewer 节点可配置为异步或跳过。
3. **qing-agent 宕机**：Hermes 脚本有 Fallback，直接输出原始上下文，微信提醒不中断。

### 8.2 回退策略

如果 qing-agent 不稳定：
1. `sudo systemctl stop qing-agent`
2. Hermes 自动回退到原有模式（输出原始上下文，让 Hermes 原有 prompt 处理）
3. 已构建的 Neo4j/Qdrant 数据保留，可作为参考手动维护到 wiki

---

## 9. 下一步行动

确认后按以下顺序执行：

1. **基础设施**：创建 `docker-compose.infra.yml`，启动 Neo4j + Qdrant + PostgreSQL
2. **Agent骨架**：实现 `src/qing_investment/agent/` 核心模块（state、graph、nodes、tools）
3. **Prompt编写**：编写 market_analyst / stock_analyst / style_writer / reviewer 的 system prompt
4. **数据迁移**：运行 claims → Neo4j、raw/wiki → Qdrant 的迁移脚本
5. **Hermes改造**：新增 `stock_monitor.py --agent-json-context` 参数，改造 `hermes_stock_monitor_agent.py`
6. **集成测试**：启动 qing-agent，用 curl 测试 `/analyze/trigger`，对比输出质量
7. **部署上线**：配置 systemd，启动服务，观察盘中实际效果
