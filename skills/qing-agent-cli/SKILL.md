---
name: qing-agent-cli
description: 使用 Qing-Agent (青枫浦上Q风格) 分析股票、市场、持仓问题。通过 LangGraph 调用知识库+LLM，输出 UP 风格分析。
trigger: 用户询问个股分析、大盘走势、板块判断、持仓复盘，或任何包含股票代码/名称的问句
---

# Qing-Agent CLI Skill

通过 `delegate_task` 将股票相关问题路由到 Qing-Agent CLI，输出青枫浦上Q风格的分析。

## 触发条件

以下场景应触发此 skill：

1. **个股分析**：用户问"分析一下xx"、"xx怎么样了"、"xx能买吗"等
2. **大盘/市场**：用户问"今天大盘怎么看"、"市场怎么走"等
3. **板块判断**：用户问"光互连板块怎么看"、"算力还能追吗"等
4. **持仓复盘**：用户问"持仓需要调整吗"、"安泰科技怎么办"等
5. **任何包含股票代码或UP逻辑关键词的问题**

### 何时不使用

- 用户问的是纯技术问题（Python、部署、配置等）→ 使用通用能力
- 用户问的是具体数据查询（"查一下xx的PE"）→ 使用 qing-stock-analysis skill

## 执行流程

### Step 1: 提取查询

从用户的问题中提取核心查询内容：

```python
query = "分析一下安泰科技，现在能买吗？"
```

如果有明确的股票代码，一并提取：
```python
stock_code = "000969"
```

### Step 2: 通过 delegate_task 调用 CLI

```python
delegate_task(
    goal=f"""Run Qing-Agent analysis via CLI.

Execute: .venv/bin/python scripts/cli_qing_agent.py --query "{query}" {stock_code_arg} --verbose

The project root is /home/ubuntu/learning-investment-strategies.
Set PYTHONPATH=src and workdir to the project root.
""",
    context=f"""Project root: /home/ubuntu/learning-investment-strategies
Query: {query}
Interpret this as: the user wants a Qing-Agent analysis.
The CLI command is: .venv/bin/python scripts/cli_qing_agent.py --query "{query}" {stock_code_arg} --verbose
Working directory: /home/ubuntu/learning-investment-strategies
Environment: LLM_PROVIDER=deepseek, NEO4J and QDRANT are running locally.
""",
    toolsets=["terminal"],
)
```

### Step 3: 返回结果

将 sub-agent 返回的 stdout 直接呈现给用户。

## 示例

### 个股分析

**用户输入**：分析一下中国长城

**调用**：
```bash
.venv/bin/python scripts/cli_qing_agent.py --query "分析一下中国长城" --stock-code 000066 --verbose
```

**返回**：UP 风格的分析文本，包含盘面、周期定位、主线判断、个股地位、多空证据、触发/失效条件等。

### 市场分析

**用户输入**：今天大盘怎么看

**调用**：
```bash
.venv/bin/python scripts/cli_qing_agent.py --query "今天大盘怎么看" --verbose
```

**返回**：UP 风格的市场复盘。

## 参考文件

- `references/neo4j-query-pitfalls.md` — Neo4j 查询常见问题（缺失属性、ORDER BY 别名、coalesce 用法）

## 注意事项

1. **耗时**：完整 Graph 通常需要 15-60 秒（涉及 LLM 多次调用 + 知识库检索）
2. **知识库依赖**：需要 Neo4j（claims）+ Qdrant（wiki）正常运行
3. **LLM 依赖**：需要 LLM_PROVIDER 和对应 API key 配置
4. **网络依赖**：外部行情源需要网络可达（东方财富/新浪）
5. **行情数据**：若无实时行情注入，外部板块数据可能不可用 → 分析会中止返回"数据不可用"
6. **非交易时段**：分析功能仍然可用（仅板块数据可能受限）

## 常见陷阱

### delegate_task 调用必须指定 workdir

```python
delegate_task(
    goal="...",
    context="...",
    toolsets=["terminal"],
    workdir="/home/ubuntu/learning-investment-strategies",
)
```

缺失 `workdir` 时，子 agent 的终端默认在 `~/.hermes/hermes-agent/`，找不到 `.venv` 和 `scripts/`。必须传 project root。

### PYTHONPATH 必须设置

CLI 需要 `PYTHONPATH=src` 才能 import `qing_investment.agent.graph.builder`。两种方式：
1. 调用时显式设置：`PYTHONPATH=src .venv/bin/python scripts/cli_qing_agent.py --query "..."`  
2. 在 `delegate_task context` 中注明需要设置

### Neo4j property does not exist 警告

当 Neo4j 查询访问不存在的属性时，输出 `warn: property key does not exist` 但不阻断。修复方法见 `references/neo4j-query-pitfalls.md`。

### Graph invoke 超时

完整图（parse → retrieve → market + stock → synthesize → style → review）含 4-5 次 LLM 调用，默认 `--timeout=120`。若 LLM API 响应慢可调高。

### 输出为空

可能原因：
- LLM API key 未配置或已过期 → 检查 `LLM_PROVIDER` 和对应 key
- 外部板块数据不可用 → `market_analyst` 返回"数据不可用"
- 查询不含可解析的股票代码 → `parsed_intent.analysis_type` 为 `stock` 但 `stock_code` 为 None → `stock_analyst` 跳过

检查方法：加 `--verbose` 查看 reasoning_steps 和 confidence。
