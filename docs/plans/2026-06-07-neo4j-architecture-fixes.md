# Neo4j 架构修复 Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 修复 Neo4j 读写路径中 8 个架构问题，确保 discover 不重复判断、检索链路一致、图关系被正确消费。

**Architecture:** 文件修改集中在 4 个文件：`scripts/discover_claim_relations.py`、`src/qing_investment/agent/tools/neo4j_client.py`、`src/qing_investment/agent/graph/nodes.py`、`src/qing_investment/agent/main.py`。

**Tech Stack:** Python, Neo4j (Py2neo driver), FastAPI, LangGraph

---

## 任务清单

### P0-1: discover 加 last_discovered 标记，解决重复判断

**Objective:** 让 `--all-missing` 跳过已做过 discovery 的 claim，不管结果有无 supersedes/contradicts。

**Files:**
- Modify: `scripts/discover_claim_relations.py:295-306` (跳过逻辑)
- Modify: `scripts/discover_claim_relations.py:320-333` (写入逻辑)

**改动：**
1. 跳过条件从 `if supersedes or contradicts` 改为 `if c.get("last_discovered")`
2. 写入时加一行 `last_discovered: 2026-06-07`，不管 results 有无 supersedes/contradicts
3. `write_results_to_yaml` 支持写入 `last_discovered` 字段

**验证：** 检查 YAML 中新增的 claim 是否有 `last_discovered` 字段

### P0-2: nodes.py 改用 get_claims_with_evolution

**Objective:** 让 LangGraph 的 `retrieve_knowledge` 也能获取 SUPERSEDES/CONTRADICTS 信息，与 `/chat` 保持一致。

**Files:**
- Modify: `src/qing_investment/agent/graph/nodes.py:637`
- Modify: `src/qing_investment/agent/tools/neo4j_client.py` (可选：确保返回值一致)

**改动：** `nodes.py:637` 行 `get_claims_about_stock` → `get_claims_with_evolution`

### P1-1: 修复 get_claim_evolution 返回值浪费

**Objective:** 将 `get_claim_evolution` 的笛卡尔积查询改为类似 `get_claims_with_evolution` 的结构化单行返回，或在调用方消费 old/opp/new。

**Files:**
- Modify: `src/qing_investment/agent/tools/neo4j_client.py:35-44` (查询改为 collect 模式)
- Modify: `src/qing_investment/agent/graph/nodes.py:653-667` (消费演化数据)
- Modify: `src/qing_investment/agent/main.py:216-230` (消费演化数据)

### P1-2: _detect_claim_conflicts 查 CONTRADICTS 边

**Objective:** 让冲突检测从关键词启发式升级为查询 Neo4j CONTRADICTS 边。

**Files:**
- Modify: `src/qing_investment/agent/graph/nodes.py:542-595`

### P2-1: main.py 合并两次 Neo4j 连接

**Objective:** 减少每个请求的 Neo4j 连接数。

**Files:**
- Modify: `src/qing_investment/agent/main.py:172-234`

### P2-2: Stock 节点补 name 属性

**Objective:** 支持个股名称直接搜索。

**Files:**
- Modify: `scripts/migrate_claims_to_neo4j.py:282-297` (Stock 节点加 name)
- Modify: `src/qing_investment/agent/tools/neo4j_client.py` (新增按名称查询)

### P3-1: keyword 检索加全文索引

**Objective:** 提升 keyword 搜索性能。

**Files:**
- Create: `scripts/create_neo4j_fulltext_index.py`
- No code changes needed

### P3-2: intensity 过滤策略统一

**Objective:** 确保 `/chat` 和 `retrieve_knowledge` 对 low intensity claims 的处理一致。

**Files:**
- Modify: `src/qing_investment/agent/graph/nodes.py:724`
