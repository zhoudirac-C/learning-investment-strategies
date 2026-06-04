---
name: qing-agent-cli
description: 使用 Qing-Agent (青枫浦上Q风格) 分析股票、市场、持仓问题。通过 LangGraph 调用知识库+LLM，输出 UP 风格分析。
trigger: 用户询问个股分析、大盘走势、板块判断、持仓复盘，或任何包含股票代码/名称的问句
---

# Qing-Agent CLI Skill

通过 REST API（首选）或 `delegate_task`（备选）将股票相关问题路由到 Qing-Agent，输出青枫浦上Q风格的分析。

## 前提条件：配置 API Key

Qing-Agent 需要 `.env` 文件配置 LLM API Key 才能调用 LLM。在项目根目录创建：

```bash
cat > /home/ubuntu/learning-investment-strategies/.env << 'EOF'
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-你的key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
EOF
```

**注意**：Hermes 安全框架会屏蔽环境变量中的 API key（显示为 `***`），无法从 `auth.json` 或 `/proc/*/environ` 提取。必须先由用户提供完整 key 后写入 `.env`。

### .env 文件保护

`.env` 文件包含 API key 敏感信息，**不要提交到 git**。检查 `.gitignore` 中是否已包含 `.env`：

```bash
grep "^\.env$" .gitignore  # 应返回 `.env`
```

### 重启服务

配置 `.env` 后需重启 Qing-Agent 服务：

```bash
# 停止旧服务（找到 PID 后 kill）
pgrep -f "uvicorn.*qing_investment"
kill <PID>

# 启动新服务
cd ~/learning-investment-strategies
.venv/bin/python -m uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000 &
```

## 两种调用模式

### 模式 A：REST API 直接调用（首选，响应更快）

当用户问股票问题时，直接 `terminal()` 调 Qing-Agent 的 `/chat` 端点：

```python
from hermes_tools import terminal

# 确保服务在线
health = terminal("curl -s http://127.0.0.1:8000/health")
# 应返回 {"status":"ok","version":"0.1.0"}

# 个股/市场分析
result = terminal("""curl -s -X POST http://127.0.0.1:8000/chat \\
  -H "Content-Type: application/json" \\
  -d '{"message": "分析一下安泰科技，现在能买吗？", "session_id": "user-001"}'""")
```

**优点**：直接返回 UP 风格结果，不需要 `delegate_task` 开销，响应更快（10-30s）。

### 模式 B：delegate_task → CLI（备选，兼容旧版）

当 REST API 不可用时（服务未启动、端口不通、返回 503），通过 `delegate_task` 调用 CLI 版本：

```python
delegate_task(
    goal=f"Run Qing-Agent analysis via CLI...",
    toolsets=["terminal"],
    workdir="/home/ubuntu/learning-investment-strategies",
)
```

详见下方【执行流程】和【delegate_task 调用必须指定 workdir】。

### 模式 C：Hermes 自身能力（最终降级）

当 Qing-Agent 服务完全不可用时，使用 Hermes 自身能力 + 本地知识库文件直接分析：

1. 读取本地 claims（`knowledge/claims/`）
2. 读取 wiki（`knowledge/wiki/`）
3. 按 `qing-stock-analysis` 框架执行分析
4. 输出时不模拟 UP 口吻，说明"未走 Qing-Agent 链路"

## 触发条件（任何模式都适用）

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

### 前置检查：服务是否在线

```python
from hermes_tools import terminal
health = terminal("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health")
if health == "200":
    # 模式 A：直接调 REST API
    mode = "rest"
else:
    # 模式 B 或 C：尝试 CLI 或降级
    mode = "cli_or_fallback"
```

### 模式 A 执行流程（REST API）

1. 构造查询消息（从用户问题提取核心内容 + 必要上下文）
2. 调 `/chat` 端点：`curl -s -X POST http://127.0.0.1:8000/chat -d '{"message": "..."}'`
3. 解析返回的 `reply` 字段
4. 直接呈现给用户，不额外包装

### 模式 B 执行流程（CLI - 旧版）

1. 提取查询
2. 通过 delegate_task 调用 CLI
3. 返回结果

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
- `references/rest-api-usage.md` — REST API 端点说明、调用示例、错误码、降级路径

## 注意事项

1. **耗时**：完整 Graph 通常需要 15-60 秒（涉及 LLM 多次调用 + 知识库检索）
2. **知识库依赖**：需要 Neo4j（claims）+ Qdrant（wiki）正常运行
3. **LLM 依赖**：需要 LLM_PROVIDER 和对应 API key 配置
4. **网络依赖**：外部行情源需要网络可达（东方财富/新浪）
5. **行情数据**：若无实时行情注入，外部板块数据可能不可用 → 分析会中止返回"数据不可用"
6. **非交易时段**：分析功能仍然可用（仅板块数据可能受限）

## 常见陷阱

### REST API vs CLI 的选择

| 条件 | 推荐模式 |
|------|---------|
| `localhost:8000/health` 返回 200 | **模式 A（REST）** — 直接 `curl /chat` |
| 服务离线但 `.venv` 可用 | **模式 B（CLI）** — `delegate_task` + `scripts/cli_qing_agent.py` |
| 两者都不可用 | **模式 C（Hermes 自身）** — 读本地 claims/wiki 直接分析，说明"未走 Qing-Agent 链路" |

### Hermes 安全存储无法提取 API Key

Hermes 通过安全框架管理 API keys，`auth.json` 和 `/proc/*/environ` 中的 key 均被屏蔽为 `***` 或 `sk-xxx...xxx`。无法通过任何终端命令或 Python 脚本提取。必须直接请用户提供完整 key。

### 服务启动后需验证

```bash
# 验证服务正常
curl -s http://127.0.0.1:8000/health
# → {"status":"ok","version":"0.1.0"}

# 若返回空或 Connection refused → 服务未启动或启动中
```

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
