# Neo4j Claim 关系更新流水线

> 全流程操作手册：从关系发现到索引重建、Agent 重启。
> 最后更新：2026-06-08（discover 脚本迁移至 src/qing_investment/agent/tools/）

## 流水线总览

```
discover_claim_relations.py    migrate_claims_to_neo4j.py    index_claims_to_qdrant.py    重启 Agent
   (关系发现)          →         (Neo4j 同步)         →      (Qdrant 重建)         →    (uvicorn)
```

**每一步的输出是下一步的输入，不可跳过。**
**⚠️ 必须先跑 discover，再跑 migrate！** 否则 YAML 中的空 `supersedes: []` / `contradicts: []` 会覆盖 Neo4j 中已有关系边。

---

## 第一步：关系发现

### 脚本

`src/qing_investment/agent/tools/discover_claim_relations.py`

> 已从 `scripts/` 迁移至 agent tools 目录，与 neo4j_client / llm_client 同目录。

### 原理

1. 读取所有 claim YAML，找出尚无 `supersedes` / `contradicts` 的 claims
2. 对每个 claim，用 ONNX embedding 在 Qdrant 中搜索 top-3 最相似 claims
3. 从 Neo4j 获取完整 claim 内容
4. 调用 LLM 判断关系类型：supersedes / supplements / contradicts / none
5. supersedes 和 contradicts 写回 YAML 文件

### 命令

```bash
cd /home/ubuntu/learning-investment-strategies
PYTHONPATH=src .venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py --all-missing
```

### 续跑机制

`--all-missing` 天然支持中断续跑——只处理尚无关系的 claims，已处理的自动跳过。无需手动指定断点。

### 进度汇报

使用 wrapper 脚本获得 10 分钟进度 + 中断原因：

```bash
bash scripts/run_discover_with_progress.sh
```

输出文件：
- `logs/discover_relations_<timestamp>.log` — 完整输出
- `logs/discover_relations_<timestamp>.progress` — 仅进度行（每 10 分钟一条）

### ⚠️ 关键坑

1. **Venv 路径**：必须用 `.venv`（含 langchain_openai），不能用 `venv`
2. **YAML 缩进 bug 已修复**：`write_results_to_yaml()` 曾硬编码 4 空格导致 42 个文件损坏。修复方案：改为保留原始行缩进。如再次遇到缩进错误，最快恢复方式：`git checkout -- knowledge/claims/`
3. **耗时**：547 条 claims × ~10 秒/条 ≈ 90 分钟

---

## 第二步：Neo4j 迁移

### 脚本

`scripts/migrate_claims_to_neo4j.py`

### 原理

将 YAML 中的 claims（含 `supersedes`/`contradicts` 字段）同步到 Neo4j：

1. **节点迁移**：每个 claim → `(:Claim)` 节点，属性含 `intensity`、`claim_type`、`supersedes`、`contradicts` 等
2. **关系迁移**：`supersedes` 列表 → `[:SUPERSEDES]` 边，`contradicts` 列表 → `[:CONTRADICTS]` 边

### 命令

```bash
cd /home/ubuntu/learning-investment-strategies
PYTHONPATH=src .venv/bin/python scripts/migrate_claims_to_neo4j.py
```

### ⚠️ 关键坑

- 仅迁移有变化的文件（按 mtime 判断）
- 关系边使用 `MERGE` 避免重复创建

---

## 第三步：Qdrant 索引重建

### 脚本

`scripts/index_claims_to_qdrant.py`

### 原理

从 Neo4j 读取所有 claims，用 ONNX embedding 生成向量，写入 Qdrant。payload 包含 `intensity` 字段用于检索时过滤。

### 命令

```bash
cd /home/ubuntu/learning-investment-strategies
PYTHONPATH=src .venv/bin/python scripts/index_claims_to_qdrant.py --force-recreate
```

### ⚠️ 关键坑

1. **必须先停 Agent**：脚本会自动检测并 kill Agent 进程（释放 Qdrant lock）
2. **Qdrant lock 问题**：脚本有 30 秒等待 + 强制删除机制
3. **完整性自检**：完成后自动抽检 10 条向量，确认维度 (512) 和内容非空

---

## 第四步：重启 Agent

### 命令

```bash
cd /home/ubuntu/learning-investment-strategies
PYTHONPATH=src .venv/bin/python -m uvicorn qing_investment.agent.main:app \
  --host 0.0.0.0 --port 8000 --log-level info &
```

### 验证

```bash
curl -s http://localhost:8000/health
# {"status":"ok","version":"0.1.0"}
```

### ⚠️ 模块路径

正确路径是 `qing_investment.agent.main:app`，**不是** `src.qing_investment.api.main:app`。

---

## 一次性全流程（推荐）

```bash
cd /home/ubuntu/learning-investment-strategies

# 1. 关系发现（带进度）
bash scripts/run_discover_with_progress.sh

# 2. Neo4j 同步
PYTHONPATH=src .venv/bin/python scripts/migrate_claims_to_neo4j.py

# 3. Qdrant 重建
PYTHONPATH=src .venv/bin/python scripts/index_claims_to_qdrant.py --force-recreate

# 4. 重启
PYTHONPATH=src .venv/bin/python -m uvicorn qing_investment.agent.main:app \
  --host 0.0.0.0 --port 8000 --log-level info &
```

---

## 检索管线中的关系使用

关系发现写入的是**持久存储**，检索时通过两个途径使用：

| 途径 | 代码位置 | 触发时机 |
|------|---------|---------|
| 方案1: 图遍历 | `nodes.py` / `main.py` | 每次检索时，从 top-3 claims 的实体出发遍历 Neo4j 同实体 claims |
| 方案3: 关系边 | `neo4j_client.py` | `get_claims_with_evolution()` 查询 SUPERSEDES/CONTRADICTS 边 |

**注意**：方案1 是检索时实时计算，方案3 是写入时预计算。两者互补，不冲突。

---

## 定时维护建议

建议在以下事件后运行全流程：

1. **新增 raw 文档并提取 claims 后**（新 claims 需要建立关系）
2. **UP 发布重大观点更新后**（旧 claims 可能被 supersede）
3. **每月一次全量校验**（确保 Neo4j / Qdrant / YAML 三方一致）
