# MCP 接入 Qdrant + Neo4j 实施计划

> 目标：将 Qdrant 语义搜索和 Neo4j 图查询注册为 Hermes MCP 工具，对话 Agent 自动发现并调用。
> 创建：2026-06-09

---

## 前置检查结果

| 依赖 | 状态 |
|------|:---:|
| mcp SDK (1.26.0) | ✅ |
| qdrant-client (1.18.0) | ✅ |
| neo4j (6.2.0) | ✅ |
| onnxruntime (1.25.1) | ✅ |
| ONNX 模型 (bge-small-zh-v1.5) | ✅ |
| transformers | ❌ 缺失 |
| Neo4j 服务 (v2026.05.0) | ✅ 运行中 |
| Qdrant 本地模式 (`.qdrant_data/`) | ✅ |
| `~/.hermes/config.yaml` mcp_servers | ❌ 尚无 |

---

## 任务分解

### 任务 1：安装缺失依赖

```bash
pip install transformers
```

预估：1 分钟。仅需 tokenizer，不加载完整模型。

---

### 任务 2：编写 Qdrant MCP Server

**文件**：`scripts/mcp_qdrant_server.py`

**架构**：Python stdio MCP server，使用项目已有的 `OnnxEmbeddingModel` 做 query embedding，查 Qdrant 本地模式。

**暴露工具**：

| 工具名 | 参数 | 功能 |
|--------|------|------|
| `search_claims` | query, limit=5 | 语义搜索 claims，返回 id/topic/statement/confidence/timeframe |
| `search_knowledge` | query, limit=5 | 语义搜索 wiki/docs，返回路径+内容片段 |

**关键约束**：
- 只读，不暴露 write/delete/upsert
- embedding 模型只加载一次（server 启动时初始化，常驻内存）
- 返回结果精简（json），不给 Agent 灌太多 token

**预估代码量**：~120 行

**Qdrant 连接信息**：
- 本地模式路径：`/home/ubuntu/learning-investment-strategies/.qdrant_data`
- Collection：`qing_claims`（645条）、`qing_knowledge`（10880条）
- 维度：512，距离：Cosine

---

### 任务 3：编写 Neo4j MCP Server

**文件**：`scripts/mcp_neo4j_server.py`

**架构**：Python stdio MCP server，使用 `neo4j` driver 直连 Bolt。

**暴露工具**：

| 工具名 | 参数 | 功能 |
|--------|------|------|
| `get_claim_relations` | claim_id | 查一个 claim 的 supersedes/contradicts/supplements 关系 |
| `search_claims_graph` | keyword, limit=10 | 按关键词搜 claim 的 statement/topic，返回匹配结果 |
| `get_recent_claims` | days=7, claim_type | 按时间和类型过滤 claims |

**关键约束**：
- 只读 Cypher（MATCH + RETURN），不执行 CREATE/MERGE/DELETE
- 返回结果格式化（不暴露原始 Neo4j 内部 ID）
- 连接复用（server 级别单 driver 实例）

**预估代码量**：~100 行

**Neo4j 连接信息**：
- URI：bolt://localhost:7687
- 用户/密码：从环境变量读取或硬编码 `neo4j/qingneo4j`

---

### 任务 4：注册到 Hermes Config

在 `~/.hermes/config.yaml` 添加：

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

**预估**：10 行 YAML

---

### 任务 5：验证

```bash
# 重启 Hermes 后，对话中测试：
# "用 qdrant 搜一下'涨价逻辑分类'相关的 claim"
# "用 neo4j 查 claim-20260609-005-c 和其他 claim 的关系"
```

验证点：
1. Hermes 启动日志出现 `mcp_qdrant_search_claims` 等工具注册信息
2. 对话中 Agent 自然能调用这些工具
3. 返回结果格式正确、延迟可接受（<2s）

---

## 工作量估算

| 任务 | 预估时间 |
|------|---------|
| 1. 安装 transformers | 2 分钟 |
| 2. 写 Qdrant MCP server | 20 分钟 |
| 3. 写 Neo4j MCP server | 15 分钟 |
| 4. 注册 config | 2 分钟 |
| 5. 验证调试 | 10 分钟 |
| **合计** | **~50 分钟** |

---

## 风险和注意事项

1. **ONNX 模型加载时间**：Qdrant server 启动时需加载 BGE-small-zh-v1.5 ONNX 模型（~100MB），首次启动 5-10 秒。`connect_timeout: 60` 足够覆盖。

2. **内存占用**：Qdrant server 加载 ONNX 模型常驻约 300-500MB。两个 server 合计 ~600MB，当前机器内存可承受。

3. **Qdrant 并发锁**：本地模式不支持并发访问。如果 Qing-Agent 同时在跑索引任务，MCP 查询可能冲突。短期可接受（很少并发），长期可加文件锁。

4. **Neo4j 密码硬编码**：暂时写死在脚本里（仅本地），后续可改为环境变量 `NEO4J_PASSWORD`。
