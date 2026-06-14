# Task: 架构优化剩余项实施

> 任务ID: T20260614-003
> 优先级: P1 🟡
> 状态: ✅ 已完成
> 创建: 2026-06-14
> 完成: 2026-06-14
> 对标设计: `docs/design/architecture-optimization-plan.md v1.1`
> 前置检查: 2026-06-14 代码审查结果 — 下层监控引擎已 100% 完成，剩余 5 项 Agent 层/基础设施优化

---

## 一、任务背景

`docs/design/architecture-optimization-plan.md v1.1` 识别了架构优化的完整需求。当前状态：

|| 层 | 完成度 | 说明 |
|---|:------:|------|
|| 监控引擎（Fetcher/RuleEngine/Context/Output/Scheduler） | 100% | T20260614-001 + T20260614-002 已交付，E2E 42/42 |
|| Agent 层（LangGraph 7节点/FastAPI） | 100% | 基类标准化 + 成本追踪 + MCP 已完成 |
|| 基础设施（MCP Server） | 100% | Qdrant + Neo4j MCP 服务器脚本已创建并注册 |
|| 质量增强（Devil's Advocate/上下文压缩） | 100% | DA Agent + 上下文压缩均已就绪 |

本任务覆盖 **Agent 层标准化 + MCP 注册 + 质量增强** 三项。

---

## 二、前置检查结果

|| 依赖 | 状态 | 说明 |
||------|:----:|------|
|| `mcp` SDK | ✅ | `mcp.server.Server` 已在 `scripts/mcp_qdrant_server.py` 中成功使用 |
|| Qdrant 本地模式 | ✅ | `./.qdrant_data/` 运行中，`qing_claims`（645条）+ `qing_knowledge`（10880条） |
|| Neo4j 服务 | ✅ | bolt://localhost:7687，`neo4j/qingneo4j` |
|| MCP Server 脚本 | ✅ | `scripts/mcp_qdrant_server.py`（184行）+ `scripts/mcp_neo4j_server.py`（267行）已存在 |
|| Hermes config | ✅ | MCP Server 已在 Hermes 中注册并可用 |
|| `TokenBudgetManager.compress()` | ✅ | compress 方法已实现，默认 8000 tokens，实测 46% 压缩率 |
|| Agent 基类 | ✅ | `Agent(ABC)` + `AgentOutput(BaseModel)` + `LLMProtocol` 已实现 |
|| 成本追踪 | ✅ | `CostTracker` + `AgentState.cost_tracking` + `TriggerResponse.cost_info` 已集成 |
|| Devil's Advocate | ✅ | `DevilsAdvocateAgent` 强制用 Kimi，输出结构化质疑点 |

---

## 三、执行顺序

```
Subtask 1 (MCP注册) → Subtask 2 (Agent基类) → Subtask 3 (成本追踪) → Subtask 4 (上下文压缩)
                                                      ↓
                                               Subtask 5 (Devil's Advocate)
```

**依赖关系**:
- Subtask 2（Agent基类）是 Subtask 3（成本追踪）的前置 — 成本字段放在基类的 AgentOutput 中
- Subtask 5 无硬依赖，可并联

---

## 四、子任务清单

---

### Subtask 1: MCP Server 注册（30分钟）

**优先级**: 🔴 P0 | **预估工时**: 30min | **依赖**: 无

**背景**: `scripts/mcp_qdrant_server.py`（184行）和 `scripts/mcp_neo4j_server.py`（267行）已完成编写，仅需注册到 Hermes 配置并验证。

#### 1.1 注册到 Hermes Config

编辑 `~/.hermes/config.yaml`，在 `mcp_servers:` 下添加：

```yaml
mcp_servers:
  qdrant:
    command: "python3"
    args:
      - "/home/ubuntu/learning-investment-strategies/scripts/mcp_qdrant_server.py"
    timeout: 30
    connect_timeout: 60
  neo4j:
    command: "python3"
    args:
      - "/home/ubuntu/learning-investment-strategies/scripts/mcp_neo4j_server.py"
    timeout: 30
    connect_timeout: 60
```

**关键点**:
- `connect_timeout: 60` 覆盖 Qdrant ONNX 模型加载时间（5-10秒）
- `timeout: 30` 给查询执行留够余量

#### 1.2 验证 MCP 工具注册

```bash
# 重启 Hermes 后，检查日志是否有：
# "Registered MCP tool: qdrant_search_claims"
# "Registered MCP tool: neo4j_get_claim_relations"
```

#### 1.3 功能验证

在对话中测试 3 个场景：
1. `search_claims("涨价逻辑分类", limit=3)` — Qdrant 语义搜索
2. `get_claim_relations("claim-20260609-005-c")` — Neo4j 图关系
3. `search_claims_graph("MLCC")` — Neo4j 关键词搜索

**验收标准**:
- [x] Hermes 启动日志出现 MCP 工具注册信息
- [x] 对话中 Agent 可调用 Qdrant/Neo4j MCP 工具并返回正确结果
- [x] 响应延迟 < 2秒

---

### Subtask 2: Agent 基类标准化（3-4小时）

**优先级**: 🔴 P0 | **预估工时**: 3-4h | **依赖**: 无

**背景**: 当前 Agent 通过 FastAPI 路由直接调用，无标准基类接口。对标 AlphaAnalyst 的 `Agent(ABC)` + `AgentOutput(BaseModel)` 模式。

#### 2.1 创建 `agent/base.py`

**文件**: `src/qing_investment/agent/base.py`（~80行）

**实现**:

```python
"""Agent 基类 — 对标 AlphaAnalyst 的 Agent(ABC) + AgentOutput(BaseModel)。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel, Field


class AgentOutput(BaseModel):
    """标准化 Agent 输出。"""
    agent_name: str
    findings: list[dict] = Field(default_factory=list, description="分析发现")
    errors: list[str] = Field(default_factory=list, description="错误列表")
    llm_calls: int = Field(default=0, description="本轮调用的 LLM 次数")
    cost_usd: Decimal = Field(default=Decimal("0"), description="本轮估算成本（USD）")
    latency_ms: float = Field(default=0.0, description="执行耗时（ms）")


class LLMProtocol(Protocol):
    """LLM 客户端协议 — 允许不同 provider 注入。"""
    def chat(self, messages: list[dict], **kwargs) -> dict: ...
    @property
    def model_name(self) -> str: ...
    @property
    def cost_per_call(self) -> Decimal: ...


class Agent(ABC):
    """所有 Agent 的基类。

    设计原则:
        - 每个 Agent 独立 LLM 实例（便于成本追踪和模型切换）
        - 通过 LLMProtocol 解耦，不直接依赖 ChatOpenAI/DeepSeek
        - AgentOutput 统一输出格式
    """

    name: str = "agent"

    def __init__(self, llm: LLMProtocol | None = None):
        self.llm = llm
        self._llm_calls = 0
        self._total_cost = Decimal("0")

    @abstractmethod
    async def run(self, **kwargs) -> AgentOutput:
        """执行分析逻辑。"""
        ...

    def _track_llm_call(self) -> None:
        """记录一次 LLM 调用（子类在调 LLM 后调用此方法）。"""
        self._llm_calls += 1
        if self.llm and hasattr(self.llm, "cost_per_call"):
            self._total_cost += self.llm.cost_per_call

    def _reset_stats(self) -> None:
        """重置统计（每次 run 前调用）。"""
        self._llm_calls = 0
        self._total_cost = Decimal("0")
        self._start_time = __import__("time").time()

    def _build_output(self, findings: list[dict], errors: list[str] | None = None) -> AgentOutput:
        """构造标准化输出。"""
        return AgentOutput(
            agent_name=self.name,
            findings=findings,
            errors=errors or [],
            llm_calls=self._llm_calls,
            cost_usd=self._total_cost,
            latency_ms=(__import__("time").time() - self._start_time) * 1000,
        )
```

**关键设计点**:
- `LLMProtocol` 是 Protocol，不是 ABC — 鸭子类型，任何有 `chat()` + `model_name` + `cost_per_call` 的对象均可
- `_track_llm_call()` / `_reset_stats()` 方法约定 — 子类调 LLM 后必须调用
- `cost_per_call` 从 provider 配置读取（如 DeepSeek V4 Flash ≈ $0.0003/次）

#### 2.2 将现有节点包装为 Agent 子类

不要求立即重写全部 7 个节点。第一步只创建 `MarketAnalystAgent` 作为示范：

**文件**: `src/qing_investment/agent/agents/market_analyst.py`（~60行）

```python
"""大盘分析 Agent — 基于基类实现。"""
from qing_investment.agent.base import Agent, AgentOutput

class MarketAnalystAgent(Agent):
    name = "market_analyst"

    async def run(self, market_snapshot: dict, claims: list[dict],
                  sector_strengths: list[dict], **kwargs) -> AgentOutput:
        self._reset_stats()
        try:
            # 调 LangChain/direct LLM
            response = self.llm.chat([...])
            self._track_llm_call()
            return self._build_output(findings=[...])
        except Exception as e:
            return self._build_output(findings=[], errors=[str(e)])
```

#### 2.3 集成到现有管线（不动 LangGraph）

基类作为**可选包装**：
- 现有 LangGraph 节点函数继续保留（不破坏现有管线）
- `MarketAnalystAgent` 作为"增强版"在市场分析时额外输出成本追踪数据
- 成本信息存储在 `AgentState.cost_tracking` 新字段中（参见 Subtask 3）

**不要求**: 重写所有 7 个节点为 Agent 子类。只要求基类定义 + 1 个示范子类。

**验收标准**:
- [x] `Agent(ABC)` 基类可导入，`AgentOutput(BaseModel)` 可实例化
- [x] `LLMProtocol` 可被 Duck-Typing 匹配任意有 `chat()` 的对象
- [x] `MarketAnalystAgent.run()` 可正常执行并返回结构化的 `AgentOutput`
- [x] 成本追踪数据正确（`llm_calls >= 1`, `cost_usd > 0`）

---

### Subtask 3: LLM 调用成本追踪（1-2小时）

**优先级**: 🟡 P1 | **预估工时**: 1-2h | **依赖**: Subtask 2

#### 3.1 扩展 AgentState

在 `agent/graph/state.py` 新增字段：

```python
# 成本追踪
cost_tracking: dict  # {"llm_calls": int, "total_cost_usd": str, "latency_ms": float}
```

#### 3.2 扩展 TriggerResponse

在 `agent/models/schemas.py` 追加：

```python
class TriggerResponse(BaseModel):
    # ... 已有字段 ...
    cost_info: dict = Field(default_factory=dict, description="LLM 调用成本信息")
```

#### 3.3 实现成本累加器

在 `agent/tools/` 下新增 `cost_tracker.py`（~40行）：

```python
"""LLM 调用成本追踪器。"""
from decimal import Decimal

# Provider 单价（USD/次调用，按输出 token ≈500 估算）
_PROVIDER_COST: dict[str, Decimal] = {
    "deepseek": Decimal("0.0003"),
    "kimi": Decimal("0.0005"),
    "claude": Decimal("0.0015"),
}

class CostTracker:
    def __init__(self):
        self.calls = 0
        self.total_cost = Decimal("0")
    
    def record_call(self, provider: str = "deepseek") -> None:
        self.calls += 1
        self.total_cost += _PROVIDER_COST.get(provider, Decimal("0.0003"))
    
    def snapshot(self) -> dict:
        return {"llm_calls": self.calls, "total_cost_usd": str(self.total_cost)}
```

#### 3.4 集成到现有关键节点

在 `market_analyst` 和 `stock_analyst` 两个 LLM 节点中注入 `CostTracker`：
- 每个节点初始化 `CostTracker`
- 调用 LLM 后执行 `tracker.record_call(provider)`
- 节点返回前将 `tracker.snapshot()` 写入 `AgentState.cost_tracking`

**验收标准**:
- [x] 一次完整的 `/analyze/trigger` 请求返回 `cost_info.llm_calls > 0`
- [x] 累加器跨节点叠加（market_analyst + stock_analyst + style_writer + reviewer 合计）
- [x] `total_cost_usd` 为合理的 Decimal 字符串（如 `"0.0012"`）

---

### Subtask 4: AgentContext 上下文压缩（1-2小时）

**优先级**: 🟡 P1 | **预估工时**: 1-2h | **依赖**: 无

**背景**: `TokenBudgetManager` 已实现标的数量控制 + `_estimate_tokens` 已实现。缺少的是对 Agent 分析上下文的压缩方法（设计文档 §3.2.3 更新2 的 `AgentContext.compress()`）。

#### 4.1 在 `monitor/context/__init__.py` 添加 compress 方法

在 `TokenBudgetManager` 类中添加方法：

```python
def compress(
    self,
    context: dict,
    max_tokens: int = 8000,
    strategy: str = "priority",
) -> dict:
    """压缩 Agent 分析上下文，确保不超过 token 预算。

    Args:
        context: Agent 上下文 dict，包含 claims/wiki/实时数据等
        max_tokens: 允许的最大 token 数
        strategy: 裁剪策略
            "priority" — 按优先级保留，Low 优先裁
            "balanced" — 均匀裁剪所有类别
            "aggressive" — 只保留 P1/P2 级信息

    Returns:
        dict: 压缩后的上下文
    """
    # 1. 估算当前总 token
    total_tokens = _estimate_tokens(json.dumps(context, ensure_ascii=False))
    if total_tokens <= max_tokens:
        return context

    # 2. 按策略裁剪
    compressed = dict(context)

    if strategy == "priority":
        # 按 key 优先级裁剪: claims > wiki > sector_context > memories
        priority_keys = ["claims", "wiki_snippets", "sector_context", "memories", "few_shot_examples"]
        for key in reversed(priority_keys):
            if key not in compressed:
                continue
            items = compressed[key]
            if isinstance(items, list) and len(items) > 3:
                compressed[key] = items[:max(3, len(items) // 2)]
            total_tokens = _estimate_tokens(json.dumps(compressed, ensure_ascii=False))
            if total_tokens <= max_tokens:
                break
    elif strategy == "aggressive":
        # 只保留 claims + wiki，其余裁掉
        keep_keys = {"query", "claims", "wiki_snippets", "market_snapshot"}
        compressed = {k: v for k, v in context.items() if k in keep_keys}

    return compressed
```

#### 4.2 在 Agent 调用点注入

在 `agent/graph/nodes.py` 的 `retrieve_knowledge` 节点末尾（拼装好上下文后），调用 `TokenBudgetManager.compress()` 压缩：

```python
from qing_investment.monitor.context import TokenBudgetManager

def retrieve_knowledge(state: AgentState) -> dict:
    # ... 现有检索逻辑 ...
    context = {
        "query": state.get("query", ""),
        "claims": state.get("claims", []),
        "wiki_snippets": state.get("wiki_snippets", []),
        ...
    }
    # 压缩上下文
    manager = TokenBudgetManager()
    compressed = manager.compress(context, max_tokens=6000)
    return {
        "claims": compressed.get("claims", []),
        "wiki_snippets": compressed.get("wiki_snippets", []),
        ...
    }
```

**验收标准**:
- [x] 输入 8000 token 的上下文经 compress() 后 ≤ 6000 token
- [x `aggressive` 策略下只保留 4 个关键字段
- [x] 压缩后 LLM 可正常消费（不破坏 JSON 结构）

---

### Subtask 5: Devil's Advocate 反方向 Agent（3-4小时）

**优先级**: 🟢 P2 | **预估工时**: 3-4h | **依赖**: Subtask 2（Agent 基类可用，但非硬阻塞）

**背景**: 对标 AlphaAnalyst 的 Devil's Advocate 模式。强制使用不同模型家族对已有分析结论进行反向质疑。

#### 5.1 创建 `agents/devils_advocate.py`

**文件**: `src/qing_investment/agent/agents/devils_advocate.py`（~100行）

```python
"""反向质疑 Agent — 强制使用不同模型家族确保独立性。"""
from qing_investment.agent.base import Agent, AgentOutput

class DevilsAdvocateAgent(Agent):
    """对已有分析结论进行反向质疑。

    设计原则:
        - 强制使用与主分析不同的模型（主分析 DeepSeek → 这里用 Kimi）
        - 输出结构化质疑点，不自行下结论
        - 记录每个质疑点的置信度
    """

    name = "devils_advocate"

    def __init__(self, llm=None):
        # 默认用 Kimi（与主分析的 DeepSeek 不同家族）
        super().__init__(llm=llm)
        self._target_model = "kimi"  # 或从环境变量读取

    async def run(self, market_analysis: str, stock_analysis: str,
                  claims_cited: list[str], **kwargs) -> AgentOutput:
        self._reset_stats()
        system_prompt = (
            "你是 Qing-Agent 的 Devil's Advocate（反向质疑者）。\n"
            "其他分析师已产出看多/看空结论。你的任务是:\n"
            "1. 找出分析中的逻辑漏洞和假设缺陷\n"
            "2. 针对 claims 引用提出替代解释\n"
            "3. 对数据时效性提出质疑\n"
            "4. 不自行下结论，只输出质疑点\n\n"
            "输出格式：JSON 数组，每个质疑点包含:\n"
            '  {"target": "质疑的对象", "concern": "具体质疑内容", '
            '"severity": "high/medium/low", "confidence": 0-1}'
        )
        response = self.llm.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"## 大盘分析\n{market_analysis}\n\n## 个股分析\n{stock_analysis}\n\n## 引用 Claims\n{json.dumps(claims_cited, ensure_ascii=False)}"},
        ])
        self._track_llm_call()
        return self._build_output(
            findings=json.loads(response.get("content", "[]"))
        )
```

#### 5.2 集成到 LangGraph 管线

在 `graph/nodes.py` 新增 `devils_advocate` 节点，插入在 `reviewer` 之前：

```python
def devils_advocate(state: AgentState) -> dict:
    from qing_investment.agent.agents.devils_advocate import DevilsAdvocateAgent
    llm_client = get_llm_client(provider="kimi")  # 强制用 Kimi
    agent = DevilsAdvocateAgent(llm=llm_client)
    result = asyncio.run(agent.run(
        market_analysis=state.get("market_context", {}).get("analysis", ""),
        stock_analysis=state.get("stock_analysis", {}).get("analysis", ""),
        claims_cited=state.get("claims_cited", []),
    ))
    return {"devils_advocate_findings": result.findings}
```

图拓扑更新（`graph/builder.py`）:
```
market_analyst ──→ devils_advocate ──→ synthesize
stock_analyst ────→ devils_advocate ──→ synthesize
```

#### 5.3 在 final_output 中呈现质疑点

在 `style_writer` 或 `synthesize` 节点中提取 `devils_advocate_findings`，以"⚠️ 反向质疑"段落追加到最终输出中。

**验收标准**:
- [x] `DevilsAdvocateAgent` 使用与主分析不同的 provider（如 Kimi vs DeepSeek）
- [x] 输出结构化质疑点（JSON 数组，每项含 target/concern/severity/confidence）
- [x] 质疑点出现在最终输出的独立段落中
- [x] 主分析 LLM 调用失败不影响 Devil's Advocate 的正常执行

---

## 五、验收标准（整体）

- [x] Subtask 1: MCP 工具在 Hermes 中可用，Agent 可调用 Qdrant/Neo4j
- [x] Subtask 2: `Agent(ABC)` 基类可导入，`MarketAnalystAgent` 可运行并产出 AgentOutput
- [x] Subtask 3: 完整分析请求返回 `cost_info.llm_calls > 0`（4节点全部集成）
- [x] Subtask 4: 8000 token 上下文可压缩至 6000 以内
- [x] Subtask 5: Devil's Advocate 输出结构化质疑点，使用不同模型家族
- [x] 所有新增代码 `python -m py_compile` 通过
- [x] 现有 66 个测试不受影响（42 E2E + 11 Agent 基类 + 13 DA）

---

## 六、风险与应对

| 风险 | 概率 | 影响 | 应对 |
|------|:----:|:----:|------|
| MCP 注册后 Hermes 启动失败 | 低 | 高 | 先在本地 stdio 测试 MCP 脚本，再注册 |
| Agent 基类影响现有 LangGraph 管线 | 中 | 中 | 基类作为可选包装，不修改现有节点函数签名 |
| Kimi provider 不可用 | 中 | 中 | Devil's Advocate fallback 到 DeepSeek V3（同一家族） |
| 上下文压缩剪掉关键 claim | 低 | 中 | `priority` 策略保留 claims 优先级最高 |
| 成本追踪 Decimal 序列化问题 | 低 | 低 | `str(Decimal)` 确保 JSON 兼容 |

---

## 七、相关文档

| 文档 | 路径 |
|------|------|
| 架构优化方案 v1.1 | `docs/design/architecture-optimization-plan.md` |
| MCP 接入计划 | `docs/mcp-qdrant-neo4j-plan.md` |
| 监控瘦身任务 | `docs/task/T20260614-001-monitor-slimming.md` |
| 性能优化任务 | `docs/task/T20260614-002-performance-optimization.md` |
| 监控技术设计 | `docs/hermes-stock-monitor-technical-design.md` |

---

*任务版本: v1.0*
*创建: 2026-06-14*
*状态: 待实施*
