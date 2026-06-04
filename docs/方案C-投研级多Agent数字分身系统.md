# 方案C技术方案：投研级多Agent数字分身系统

> 目标：基于现有 `learning-investment-strategies` 项目，构建一个本地运行的多Agent投研系统，使Kimi Code CLI在分析个股/板块时，能够像UP一样思考、表达，并具备跨周期关联、观点演化、事实核查和个性化记忆能力。
>
> 约束：使用已有Kimi API Key；不引入视频转录；充分利用现有claims/wiki/raw/framework资产；本地部署存储层；qing-agent作为服务与Kimi Code CLI交互。

---

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                    Kimi Code CLI (用户入口)                   │
│              通过 HTTP API 调用本地 qing-agent               │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              qing-agent (FastAPI + LangGraph)               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Orchestrator│  │   Knowledge  │  │    Market        │  │
│  │   (路由/状态) │  │   Retriever  │  │   Analyst      │  │
│  └──────┬───────┘  │(Neo4j+Qdrant)│  └────────┬─────────┘  │
│         │          └──────┬───────┘           │            │
│         │                 │                   │            │
│         ▼                 ▼                   ▼            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │    Stock     │  │    Style     │  │    Reviewer      │  │
│  │   Analyst    │  │   Writer     │  │   (事实核查)      │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
│                                                             │
│  外部依赖：Kimi API (LLM+Embedding) | 现有stock_monitor数据  │
└───────────────────────────┬─────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────────┐
│   Neo4j      │   │   Qdrant     │   │  Mem0 Server     │
│  (知识图谱)   │   │  (向量检索)   │   │ (PostgreSQL后端)  │
│  7474/7687   │   │   6333       │   │   8000           │
└──────────────┘   └──────────────┘   └──────────────────┘
```

**核心设计决策：**
- **不用微软官方GraphRAG完整套件**：对于3.3M文本+81个claims的数据量，官方GraphRAG索引成本高、调参复杂。改为**自建轻量图谱流水线**：用LLM抽取实体关系→存入Neo4j→Cypher查询+向量混合检索，效果相当且更可控。
- **qing-agent不Docker化**：作为项目内Python服务用`uv run`启动，便于直接读写项目文件（positions.yaml、watchlist.yaml等）。只有状态存储层用Docker。
- **Embedding走本地**：24GB RAM足够跑BGE-large-zh等开源Embedding模型，节省API成本且降低延迟。LLM推理走Kimi API。

---

## 2. 基础设施部署（Docker Compose）

### 2.1 创建 `docker-compose.infra.yml`

在项目根目录创建，包含：
- **Neo4j** (`neo4j:5.19-community`)：图谱存储，暴露Bolt(7687)和HTTP(7474)
- **Qdrant** (`qdrant/qdrant:v1.9`)：向量库，暴露HTTP(6333)和gRPC(6334)
- **PostgreSQL** (`postgres:16`)：Mem0的后端存储，暴露5432
- **Mem0 Server** (`mem0ai/mem0:latest`)：自托管记忆API，暴露8000，依赖PostgreSQL+Qdrant

**用户需要执行的命令：**
```bash
# 1. 创建数据卷目录
mkdir -p infra/data/neo4j infra/data/qdrant infra/data/postgres

# 2. 启动基础设施
docker compose -f docker-compose.infra.yml up -d

# 3. 验证
open http://localhost:7474  # Neo4j Browser
open http://localhost:6333/dashboard  # Qdrant UI
```

### 2.2 初始配置

- Neo4j：设置初始密码，创建约束和索引（`scripts/init_neo4j.cypher`）
- Qdrant：创建collection（`qing_knowledge`），配置向量维度（1024 for BGE-large-zh）
- PostgreSQL：Mem0自动建表

---

## 3. qing-agent 服务开发

### 3.1 项目结构

在现有项目内新增 `src/qing_investment/agent/` 目录：

```
src/qing_investment/agent/
├── __init__.py
├── main.py              # FastAPI入口，uvicorn启动
├── config.py            # 环境变量/API Key配置
├── graph/
│   ├── __init__.py
│   ├── state.py         # LangGraph共享状态定义
│   ├── nodes.py         # 各Agent节点实现
│   └── edges.py         # 路由逻辑
├── tools/
│   ├── __init__.py
│   ├── neo4j_client.py      # 知识图谱查询
│   ├── qdrant_client.py     # 语义检索
│   ├── mem0_client.py       # 记忆读写
│   ├── kimi_client.py       # LLM/Embedding封装
│   ├── stock_monitor.py     # 复用现有监控数据
│   └── style_injector.py    # UP人格注入
├── pipelines/
│   ├── __init__.py
│   ├── entity_extraction.py # 从raw/claims抽取图谱
│   └── embedding_index.py   # 文档向量化入库
└── prompts/
    ├── __init__.py
    ├── orchestrator.txt
    ├── market_analyst.txt
    ├── stock_analyst.txt
    ├── style_writer.txt
    └── reviewer.txt
```

### 3.2 技术栈与依赖

在 `pyproject.toml` 中新增依赖组：
```toml
[project.optional-dependencies]
agent = [
  "langgraph>=0.2.0",
  "langchain>=0.3.0",
  "langchain-openai>=0.2.0",  # 兼容Kimi API (OpenAI-compatible)
  "fastapi>=0.115.0",
  "uvicorn>=0.32.0",
  "neo4j>=5.24.0",
  "qdrant-client>=1.12.0",
  "mem0ai>=0.1.0",           # Mem0 Python SDK
  "sentence-transformers>=3.0", # 本地Embedding (BGE)
  "pydantic-settings>=2.0",
]
```

安装命令：
```bash
uv pip install -e ".[agent]"
```

### 3.3 LangGraph 多Agent工作流

定义 `StateGraph`，状态对象包含：
- `query`: 用户原始问题
- `stock_code`: 解析出的股票代码
- `market_context`: 大盘/板块数据
- `claims`: 检索到的相关claims列表
- `wiki_snippets`: 语义检索到的wiki片段
- `knowledge_graph`: Neo4j查询结果（实体关系路径）
- `memories`: Mem0检索到的用户偏好和UP历史立场
- `draft_analysis`: 分析草稿
- `styled_output`: 风格化后的最终输出
- `review_notes`: Reviewer的修改意见
- `final_output`: 最终输出

**节点流程：**
```
parse_query → retrieve_knowledge → [并行] → market_analyst / stock_analyst
                                           ↓
                                     synthesize_analysis
                                           ↓
                                     style_writer (注入UP人格)
                                           ↓
                                     reviewer (事实核查)
                                           ↓
                                     [条件边] → 通过 → final_output
                                                → 不通过 → style_writer (循环)
```

**关键节点说明：**
- `retrieve_knowledge`：并行查询Neo4j（实体关系）+ Qdrant（语义相似）+ Mem0（用户记忆），合并去重。
- `market_analyst`：先判断周期→主线→板块，输出市场语境。
- `stock_analyst`：在market_analyst基础上，分析个股地位、技术位、F10，输出多空证据表。
- `style_writer`：加载`framework/persona/`下的UP人格定义 + 从Mem0检索的最近风格反馈 + 2-3个相似场景的few-shot示例，重写为UP口吻。
- `reviewer`：检查①是否有无条件买卖指令 ②claim引用是否准确 ③与UP历史立场是否矛盾 ④数据时间戳是否标注。发现问题则打回修改。

### 3.4 FastAPI 接口

暴露以下端点：
- `POST /analyze/stock`：个股分析，返回完整报告
- `POST /analyze/market`：市场/板块分析
- `POST /analyze/portfolio`：持仓复盘（读取positions.yaml）
- `POST /memory/add`：向Mem0写入用户反馈或UP新观点
- `GET /health`：健康检查

---

## 4. 数据迁移（一次性 + 增量）

### 4.1 Claims → Neo4j

编写迁移脚本 `scripts/migrate_claims_to_neo4j.py`：

对于每个 `knowledge/claims/*.yaml`：
1. 创建 `Claim` 节点（属性：id, statement, confidence, status, source_date等）
2. 提取 `subject` 中的股票代码/板块名，创建 `Stock`/`Sector` 实体节点
3. 创建关系：`(Claim)-[:ABOUT]->(Stock)` 或 `(Claim)-[:ABOUT]->(Sector)`
4. 创建 `supersedes`/`contradicts` 关系：`(ClaimA)-[:SUPERSEDES]->(ClaimB)`
5. 从 `links.wiki_pages` 创建 `(Claim)-[:CITED_IN]->(Wiki)` 关系

### 4.2 Raw/Wiki → Qdrant

编写脚本 `scripts/index_documents_to_qdrant.py`：

1. 读取 `sources/raw/财经/*.md` 和 `knowledge/wiki/**/*.md`
2. 按段落/主题切分chunk（保留source_path和日期元数据）
3. 用本地BGE模型生成embedding
4. 写入Qdrant `qing_knowledge` collection，payload包含：source, date, type, chunk_text

### 4.3 Framework → Mem0

初始化Mem0记忆：
1. UP人格定义（`framework/persona/`）→ 作为 `agent_preference` 类型记忆
2. 用户持仓习惯（从 `config/personal-context.yaml` 或现有positions推断）→ 作为 `user_preference`
3. UP近期核心立场（最近7天active claims）→ 作为 `fact` 类型记忆

### 4.4 运行迁移

```bash
uv run python scripts/migrate_claims_to_neo4j.py
uv run python scripts/index_documents_to_qdrant.py
uv run python scripts/init_mem0_memories.py
```

---

## 5. Kimi Code CLI 集成

### 5.1 方案：HTTP API 调用（推荐）

修改 `AGENTS.md` 或新增 `skills/qing-stock-analysis/SKILL.md` 的执行流程：

当用户请求个股分析时，Kimi Code CLI 执行：
```bash
curl -X POST http://localhost:8000/analyze/stock \
  -H "Content-Type: application/json" \
  -d '{
    "query": "分析一下天孚通信",
    "stock_code": "300394",
    "session_id": "user-001",
    "include_portfolio": true
  }'
```

qing-agent 返回JSON：
```json
{
  "final_output": "【盘面】...",
  "claims_cited": ["claim-20260603-001", "claim-20260528-003"],
  "data_sources": [...],
  "confidence": "high",
  "review_passed": true
}
```

Kimi Code CLI 将 `final_output` 直接展示给用户。

### 5.2 备选：MCP (Model Context Protocol)

如果后续Kimi Code CLI支持MCP，可将qing-agent封装为MCP Server，暴露`analyze_stock`、`search_knowledge`、`update_memory`等tools，实现更原生的工具调用。

### 5.3 与现有skill的衔接

qing-agent内部会调用现有 `src/qing_investment/stock_monitor.py` 的函数来获取实时行情和持仓数据，不需要重写数据层。现有 `skills/qing-stock-analysis/SKILL.md` 的分析框架（周期→主线→个股→F10）作为 `stock_analyst` 节点的system prompt固化在 `prompts/stock_analyst.txt` 中。

---

## 6. 增量更新机制

系统需要持续学习UP的新内容，保持知识新鲜度。

### 6.1 定时增量索引

新增脚本 `scripts/delta_index.py`，由cron或手动触发：
1. 读取 `sources/processed-log.md`，找出新增raw文档
2. 对新文档执行：抽取实体→写入Neo4j；生成embedding→写入Qdrant；抽取核心观点→写入Mem0
3. 对已更新的claims，同步更新Neo4j中的节点和关系

### 6.2 Mem0记忆衰减

Mem0自动处理记忆的时效性：
- 短期观点（intraday/short-term）自动标记过期
- 用户偏好（user_preference）长期保留
- 当UP观点改变时，Mem0的冲突解决机制会自动更新旧记忆

---

## 7. 部署步骤总览

用户需要按顺序执行以下步骤：

### Phase 1: 基础设施（约30分钟）
1. 确认Docker运行正常
2. 创建 `docker-compose.infra.yml`
3. 执行 `docker compose up -d`
4. 验证各服务端口可访问

### Phase 2: 依赖安装（约15分钟）
1. 修改 `pyproject.toml`，添加 `[agent]` 依赖组
2. 执行 `uv pip install -e ".[agent]"`
3. 配置 `.env` 文件（Kimi API Key、Neo4j密码、PostgreSQL密码）

### Phase 3: 代码开发（约4-6小时，可分多次）
1. 实现 `src/qing_investment/agent/` 核心模块
2. 实现Neo4j/Qdrant/Mem0客户端
3. 实现LangGraph工作流
4. 实现FastAPI服务

### Phase 4: 数据迁移（约20分钟）
1. 运行 `migrate_claims_to_neo4j.py`
2. 运行 `index_documents_to_qdrant.py`
3. 运行 `init_mem0_memories.py`

### Phase 5: 集成测试（约30分钟）
1. 启动 `qing-agent`：`uv run python -m qing_investment.agent.main`
2. 用curl测试 `/analyze/stock`
3. 对比qing-agent输出与现有skill输出，校准prompt
4. 修改 `AGENTS.md`，将分析请求路由到qing-agent

---

## 8. 运维与监控

### 8.1 日常操作

```bash
# 查看基础设施状态
docker compose -f docker-compose.infra.yml ps

# 查看qing-agent日志
tail -f logs/qing-agent.log

# 增量更新知识库
uv run python scripts/delta_index.py

# 备份数据
docker exec neo4j neo4j-admin database dump neo4j
docker exec qdrant qdrant-snapshot  # 或复制卷
```

### 8.2 资源占用预估

在24GB RAM的Mac上：
- Neo4j：~1.5GB RAM
- Qdrant：~512MB RAM（3.3M文本的向量索引）
- PostgreSQL：~256MB RAM
- Mem0 Server：~512MB RAM
- qing-agent + 本地Embedding模型：~2-3GB RAM
- **总计：~5-6GB RAM**，余量充足

### 8.3 持久化

所有Docker数据通过bind mount映射到 `infra/data/`，定期备份此目录即可。

---

## 9. 成本估算

### 9.1 本地成本（一次性/持续）

- **硬件**：无额外成本，复用现有Mac
- **Docker镜像**：无成本
- **本地Embedding模型**：BGE-large-zh（免费开源，约1GB下载）

### 9.2 API成本（按月估算）

基于当前数据量和预期使用量：

| 项目 | 估算 | 说明 |
|------|------|------|
| 初始索引（LLM抽取实体+摘要） | ~¥30-50 | 一次性，3.3M文本约需20-30次API调用 |
| 初始Embedding（向量生成） | ¥0 | 本地BGE模型，不调用API |
| 日常查询（LLM推理） | ~¥50-100/月 | 假设每天10次分析，每次2-3轮Agent对话 |
| 增量索引 | ~¥10-20/月 | 每周新增5-10篇raw文档 |
| **总计** | **~¥60-120/月** | 随着数据量增长缓慢上升 |

### 9.3 对比方案

- 纯文件方案：API成本 ~¥20-40/月（无存储层，直接走Kimi长上下文）
- 方案C：API成本 ~¥60-120/月（多Agent多次调用+图谱查询的额外开销）

**结论：每月多付出约¥50-80，换取多Agent校验、知识图谱关联、长期记忆能力。**

---

## 10. 风险与回退策略

### 10.1 主要风险

1. **Neo4j图谱质量依赖LLM抽取准确性**：如果实体抽取错误，图谱关联会失真。
   - **缓解**：在迁移脚本中加入人工审核环节；对关键股票/板块手动校验实体关系。

2. **多Agent增加延迟**：一次分析可能需要5-10秒（串行节点+多次LLM调用）。
   - **缓解**：关键节点并行化（market_analyst和stock_analyst可并行）；Reviewer节点可配置为异步或跳过。

3. **Mem0自托管文档不够完善**：
   - **缓解**：保留纯PostgreSQL作为备用；如果Mem0遇到问题，可用简单的key-value表替代。

4. **本地Embedding模型性能**：BGE-large-zh在CPU上推理3.3M文本可能需要10-20分钟。
   - **缓解**：初始索引用脚本跑（非实时）；日常增量索引量小，实时性无要求。

### 10.2 回退策略

如果方案C运行不稳定，可以**无损回退到纯文件方案**：
- qing-agent的FastAPI服务停掉即可
- Neo4j/Qdrant/Mem0数据保留在 `infra/data/`，不影响现有项目文件
- 改回 `skills/qing-stock-analysis/SKILL.md` 的原有流程，Kimi Code CLI继续正常工作
- 已抽取的图谱数据可作为参考，手动维护到wiki中

---

## 11. 下一步行动

1. **用户确认本方案后**，我将创建 `docker-compose.infra.yml` 和基础设施初始化脚本
2. **然后开发** `src/qing_investment/agent/` 的核心骨架（FastAPI + LangGraph + 单Agent链路）
3. **接着实现** Neo4j/Qdrant客户端和 claims 迁移脚本
4. **最后实现** 多Agent完整工作流和Reviewer节点
5. **交付时提供** 部署文档和运维手册
