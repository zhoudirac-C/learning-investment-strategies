# 方案C（独立Agent版）：不依赖 Kimi Code CLI 的实现方案

> 如果你不想把 Agent 集成在 Kimi Code CLI 里，而是想要一个**能独立运行、直接对话**的 UP 数字分身，架构可以大幅简化。
>
> 核心变化：**去掉 FastAPI + HTTP API 层**，直接在本地起一个带 UI 的 Python 应用，用户打开浏览器或终端就能对话。

---

## 1. 架构对比

### 原方案（Kimi Code CLI 集成版）

```
用户 → Kimi Code CLI → HTTP API → qing-agent(FastAPI) → 存储层
```

**问题**：
- 每次分析都要经过 Kimi Code CLI 的上下文窗口，多一层转发
- 需要维护 FastAPI 服务进程
- 终端输出受限于 Kimi 的格式

### 独立 Agent 版（推荐）

```
用户 → Chainlit Web UI / CLI
         ↓
    qing-agent (纯 LangGraph，无 FastAPI)
         ↓
    ┌────┴────┬──────────┬──────────┐
    ▼         ▼          ▼          ▼
 Neo4j    Qdrant      Mem0      Kimi API
(图谱)    (向量检索)  (记忆)     (LLM推理)
    ↑
    └────── 本地 stock_monitor 数据 ──────┘
```

**优势**：
- 直接对话，无中间层，延迟更低
- 自动保存对话历史，跨会话记忆由 Mem0 管理
- 可以上传文件（UP 的截图、PDF 研报）让 Agent 分析
- 界面可展示 Agent 思考过程（先查了什么、再推理了什么）

---

## 2. 三种独立交互方式对比

| 方式 | 启动命令 | 适用场景 | 开发量 | 体验 |
|------|---------|---------|--------|------|
| **A. CLI 终端** | `python -m qing_agent` | 极简个人使用，习惯命令行 | 30分钟 | ⭐⭐ |
| **B. Chainlit Web** | `chainlit run app.py` | **推荐**。浏览器聊天，自动会话管理 | 1小时 | ⭐⭐⭐⭐ |
| **C. Open WebUI** | `docker run open-webui` | 功能最全，支持多模型、插件、RAG | 2小时 | ⭐⭐⭐⭐⭐ |

**推荐 B（Chainlit）**：
- 纯 Python，无需前端开发
- 几行代码就能接入 LangGraph
- 自动处理会话状态、文件上传、流式输出
- 支持自定义界面（显示 claimed 引用、数据源、思考步骤）

---

## 3. 方案 B：Chainlit + LangGraph（详细实现）

### 3.1 项目结构

```
src/qing_investment/agent/
├── core/                          # 原方案中的 graph + tools
│   ├── __init__.py
│   ├── graph.py                   # LangGraph StateGraph 定义
│   ├── nodes.py                   # 各Agent节点
│   ├── state.py                   # 共享状态
│   └── tools/
│       ├── neo4j_client.py
│       ├── qdrant_client.py
│       ├── mem0_client.py
│       ├── kimi_client.py
│       └── stock_data.py          # 复用现有监控数据
├── ui/
│   ├── __init__.py
│   ├── chainlit_app.py            # Chainlit 主入口
│   └── elements.py                # 自定义界面组件（引用卡片、证据表）
├── cli/
│   └── main.py                    # 可选：CLI版本入口
└── config.py                      # 环境变量配置
```

### 3.2 依赖（pyproject.toml）

```toml
[project.optional-dependencies]
agent = [
  "langgraph>=0.2.0",
  "langchain>=0.3.0",
  "langchain-openai>=0.2.0",
  "neo4j>=5.24.0",
  "qdrant-client>=1.12.0",
  "mem0ai>=0.1.0",
  "sentence-transformers>=3.0",
  "chainlit>=1.2.0",           # Web UI 框架
  "pydantic-settings>=2.0",
]
```

安装：
```bash
uv pip install -e ".[agent]"
```

### 3.3 Chainlit 主应用（`ui/chainlit_app.py`）

```python
import chainlit as cl
from qing_investment.agent.core.graph import build_graph
from qing_investment.agent.core.state import AgentState

graph = build_graph()

@cl.on_chat_start
async def on_chat_start():
    """初始化会话，加载用户记忆"""
    session_id = cl.user_session.get("id")
    # 从 Mem0 加载用户历史偏好
    memories = await load_user_memories(session_id)
    cl.user_session.set("memories", memories)
    await cl.Message(
        content="青枫浦上Q 数字分身已就绪。直接输入股票代码或问题即可。"
    ).send()

@cl.on_message
async def on_message(message: cl.Message):
    """处理用户消息"""
    session_id = cl.user_session.get("id")
    memories = cl.user_session.get("memories", [])

    # 构建输入状态
    state = AgentState(
        query=message.content,
        session_id=session_id,
        memories=memories,
    )

    # 运行 LangGraph（流式输出中间步骤）
    msg = cl.Message(content="")
    await msg.send()

    async for event in graph.astream(state):
        if "market_analyst" in event:
            # 显示思考步骤：市场分析完成
            await msg.stream_token(f"\n🧠 市场周期定位: {event['market_analyst']['market_phase']}\n")
        elif "stock_analyst" in event:
            await msg.stream_token(f"📊 个股分析完成，正在风格化...\n")
        elif "style_writer" in event:
            # 流式输出最终 UP 风格文本
            await msg.stream_token(event["style_writer"]["styled_output"])
        elif "reviewer" in event:
            if not event["reviewer"]["passed"]:
                await msg.stream_token(f"\n⚠️ 事实核查未通过，正在修正...\n")

    await msg.update()

    # 保存本轮对话到 Mem0
    await save_to_mem0(session_id, message.content, msg.content)
```

### 3.4 启动方式

```bash
# 1. 先启动基础设施（Neo4j + Qdrant + PostgreSQL + Mem0）
docker compose -f docker-compose.infra.yml up -d

# 2. 启动 Chainlit Web UI
uv run chainlit run src/qing_investment/agent/ui/chainlit_app.py --port 8000

# 3. 浏览器打开 http://localhost:8000
```

---

## 4. 界面效果预览

Chainlit 可以渲染自定义元素，让对话更有信息密度：

### 4.1 用户输入
```
你: 分析一下天孚通信
```

### 4.2 Agent 输出（带自定义元素）

```
🤖 青枫浦上Q:
【盘面】今日CPO板块大幅高开，天孚通信+9.63%，隔夜Marvell业绩超预期催化。
但注意，这个位置不是买点，是持筹者的盛宴。

<ClaimCard>
  📌 引用观点: claim-20260603-001
  📅 来源: 2026-06-03 早盘
  📝 原文: "CPO核心标的早盘大幅高开，隔夜Marvell大涨催化..."
</ClaimCard>

<EvidenceTable>
  利多                    | 利空
  ────────────────────────┼────────────────────────
  Marvell业绩超预期      | 短期涨幅过大，偏离均线
  光互连需求持续         | 大盘调整周期未完
</EvidenceTable>

💡 UP 历史观点演化:
  → 05-28: 光模块主升初期，可积极参与 (claim-20260528-003)
  → 06-01: 注意分化，只留核心 (claim-20260601-002)
  → 06-03: 持筹观望，新开仓等回踩 (claim-20260603-001)

⚡ 触发条件: 回踩5日线且缩量至今日1/2
❌ 失效条件: 收盘跌破今日低点
📊 数据时间: 2026-06-03 10:41 CST
```

### 4.3 文件上传

用户可以直接上传 UP 的动态截图或研报 PDF：
```
你: [上传文件] 2026-06-03-早盘截图.png

🤖 青枫浦上Q:
已识别图片内容。UP 今日早盘观点：
- 周期定位: 调整第15天，上升途中调整临近尾声
- 纪律线: 收盘跌穿4033清仓，突破4130满仓
- 你的持仓中天孚通信今日+9.63%，处于加速段...
```

---

## 5. 与 Kimi Code CLI 方案的关键差异

| 维度 | Kimi Code CLI 集成版 | 独立 Agent 版（Chainlit） |
|------|---------------------|-------------------------|
| **入口** | 在 VS Code/Terminal 里和 Kimi 对话 | 浏览器打开 localhost:8000 |
| **会话历史** | 依赖 Kimi 的会话，无法持久化 | Chainlit 自动保存，Mem0 跨会话记忆 |
| **文件上传** | 不方便（需要拖进 VS Code） | 直接拖拽上传截图/PDF |
| **思考过程展示** | 纯文本输出 | 可展示卡片、表格、时间线、引用 |
| **与现有项目集成** | 直接读写项目文件（positions.yaml 等） | 同样可以，只是通过 Python 直接读 |
| **部署复杂度** | FastAPI + HTTP 调用 | 更简单，纯 Python 应用 |
| **多用户支持** | 仅个人 | 可共享给其他设备访问（局域网） |

---

## 6. 推荐的执行顺序

如果你选择独立 Agent 版，建议按这个顺序：

### Phase 1: 起基础设施（30分钟）
与原方案相同：
```bash
docker compose -f docker-compose.infra.yml up -d
```

### Phase 2: 核心引擎（2-3小时）
1. 实现 `core/graph.py`（LangGraph 多 Agent 工作流）
2. 实现 `core/tools/`（Neo4j/Qdrant/Mem0/Kimi 客户端）
3. 实现 `core/nodes.py`（market_analyst, stock_analyst, style_writer, reviewer）

### Phase 3: UI 层（30分钟）
1. 实现 `ui/chainlit_app.py`
2. 实现 `ui/elements.py`（ClaimCard, EvidenceTable 等自定义组件）

### Phase 4: 数据迁移（20分钟）
与原方案相同：
```bash
uv run python scripts/migrate_claims_to_neo4j.py
uv run python scripts/index_documents_to_qdrant.py
uv run python scripts/init_mem0_memories.py
```

### Phase 5: 启动测试（10分钟）
```bash
uv run chainlit run src/qing_investment/agent/ui/chainlit_app.py
```

**总开发时间：约 3.5-4.5 小时**（比 Kimi Code CLI 集成版少 2 小时，因为省去了 FastAPI 封装和 AGENTS.md 路由改造）。

---

## 7. 另一种选择：Open WebUI（更重但更强）

如果你未来想支持：
- 多个 AI 角色（不只是 UP，还可以有基本面分析师、风控员）
- 多模型切换（Kimi / GPT-4o / Claude 对比分析）
- 知识库可视化（RAG 检索到的原文片段直接展示）

可以用 **Open WebUI** 作为前端：

```bash
docker run -d -p 3000:8080 \
  -v open-webui:/app/backend/data \
  --name open-webui \
  ghcr.io/open-webui/open-webui:main
```

然后：
1. 把 `qing-agent` 封装为一个 OpenAI-compatible API（直接用 FastAPI 包装 LangGraph）
2. 在 Open WebUI 中添加这个自定义模型
3. 在 Open WebUI 中配置 RAG（指向 Qdrant）和函数工具（调用 stock_monitor）

**优点**：功能极其丰富，社区活跃。  
**缺点**：需要维护另一个 Docker 服务，配置较复杂。

---

## 8. 总结建议

| 你的情况 | 推荐方案 |
|---------|---------|
| 想最快跑起来，自己用 | **Chainlit Web UI**（方案 B） |
| 习惯命令行，不想开浏览器 | **CLI 终端**（方案 A） |
| 以后想多人共用、多模型对比 | **Open WebUI**（方案 C） |
| 想保留 Kimi Code CLI 的编辑能力（改代码、改配置） | **原方案（Kimi 集成版）** |

**最推荐：Chainlit + LangGraph**。它在你现有方案C的存储层（Neo4j+Qdrant+Mem0）上，只需要加一个轻量 UI 层，开发量最小，体验最好。

---

下一步：你确认用哪种独立交互方式？确认后我可以直接开始写代码。
