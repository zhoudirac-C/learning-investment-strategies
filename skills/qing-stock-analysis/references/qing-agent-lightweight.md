# Qing-Agent 零基础设施运行模式

> 日期: 2026-06-04 | 来源: 代码审阅 + 架构分析

## 概述

Qing-Agent（`src/qing_investment/agent/`）是基于 LangGraph 的多智能体分析系统，设计目标是让 AI 用 UP 的框架和口吻分析市场。它可以在**零 Docker 容器**的情况下运行。

## 架构

```
parse_query → retrieve_knowledge → market_analyst → stock_analyst
                                                    ↓
                                              synthesize
                                                    ↓
                                              style_writer
                                                    ↓
                                               reviewer → END
```

共 7 个节点，其中 4 个调用 LLM（market_analyst, stock_analyst, style_writer, reviewer），3 个为纯规则处理。

## 基础设施依赖分析

| 组件 | 硬依赖 | 不可用时的行为 |
|------|--------|---------------|
| **LLM** (DeepSeek/Kimi) | ✅ 必须 | 整个 pipeline 的核心 |
| **Neo4j** (claims 图数据库) | ❌ 可选 | `claims = []`，静默降级 |
| **Qdrant** (向量检索) | ❌ 可选 | `wiki_snippets = []`，静默降级 |
| **PostgreSQL** (mem0) | ❌ 可选 | mem0 有本地 JSON fallback |
| **Docker** | ❌ 不需要 | 所有降级路径已实现 |

### 降级代码证据

`graph/nodes.py` 中 `retrieve_knowledge()` 节点:

```python
try:
    claims = neo4j.get_claims_about_stock(stock_code, limit=10)
except Exception as e:
    claims = []  # 静默降级，不阻断流程

try:
    wiki_snippets = [...]
except Exception as e:
    wiki_snippets = []  # 同样静默降级
```

`tools/mem0_client.py`:
```python
def search(self, query, user_id):
    try:
        # 尝试远程 mem0 API
        ...
    except Exception:
        return self._local_search(query)  # 本地 JSON 关键词匹配 fallback
```

## 资源需求（零容器模式）

| 资源 | 需求 | 说明 |
|------|------|------|
| CPU | 1+ 核 | 只运行 Python，无 Java/数据库进程 |
| 内存 | ~500 MB | Python + LangGraph 图状态 |
| 存储 | 0 额外 | 不需要 Docker 镜像或数据库文件 |
| API | DeepSeek/Kimi key | 唯一的硬依赖 |

对比完整模式需要 3 个 Docker 容器（Neo4j ~1-2GB + Qdrant ~500MB + PostgreSQL ~300MB），总计需要 2.5GB+ 内存。

## 功能影响

| 功能 | 完整模式 | 零容器模式 |
|------|---------|-----------|
| LLM 市场分析 | ✅ | ✅ |
| LLM 个股分析 | ✅ | ✅ |
| UP 风格文风注入 | ✅ | ✅ |
| 事实核查/禁用词检测 | ✅ | ✅ |
| 博主历史 claims 检索 | ✅ Neo4j | ❌ |
| 文档向量语义搜索 | ✅ Qdrant | ❌ |
| 长期记忆上下文 | ✅ mem0 API | ⚠️ 本地 JSON fallback |
| 动态板块提取 | ✅ | ✅（不依赖容器） |
| 外部板块数据 | ✅ 东财/新浪 | ✅（不依赖容器） |

## CLI 入口设计（规划中）

```bash
# 直接调用 LangGraph（不需要 FastAPI/uvicorn）
python scripts/cli_qing_agent.py "分析一下安泰科技"
python scripts/cli_qing_agent.py "今天大盘怎么看" --type market
```

可作为 Hermes `delegate_task` 的目标脚本，实现「用户问股票→自动委托给 Qing-Agent 子进程→返回 UP 风格分析」。

## 启动检查清单

1. ✅ 确认 LLM API key 可用：`echo $DEEPSEEK_API_KEY`
2. ✅ 确认 Python 环境：`.venv/bin/python -c "import qing_investment.agent"`
3. ⬜ （可选）启动 Docker：`docker-compose -f docker-compose.infra.yml up -d`
4. ⬜ （可选）同步知识库：`.venv/bin/python scripts/index_documents_to_qdrant.py`
