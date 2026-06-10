# Neo4j Claim 关系更新流水线

> 全流程操作手册：从关系发现到索引重建、Agent 重启。
> 最后更新：2026-06-08（discover 脚本迁移至 src/qing_investment/agent/tools/）

## 流水线总览

```
discover_claim_relations.py    migrate_claims_to_neo4j.py    index_claims_to_qdrant.py    重启 Agent
   (关系发现)          →         (Neo4j 同步)         →      (Qdrant 重建)         →    (uvicorn + MCP)
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

### 🐛 已修复的历史 bug（2026-06-08）

以下 bug 在 2026-06-08 的 discover 迁移+修复 session 中发现并修复，记录在此防止再次踩坑。

#### Bug 1: Python 脚本目录遮蔽 pip 包
**症状**：`ImportError: cannot import name 'QdrantClient' from 'qdrant_client'`
**根因**：Python 运行脚本时自动把脚本所在目录加到 `sys.path[0]`。discover 脚本在 `src/qing_investment/agent/tools/` 下，该目录的 `qdrant_client.py` 遮蔽了 pip 包 `qdrant_client`。
**修复**：在 discover 脚本中检测并移除 `sys.path[0]`（如果它是脚本目录）。
**代码**：`discover_claim_relations.py` 第 35-38 行

#### Bug 2: `get_claim_evolution` 返回格式变更导致 fetch_full_claim 永远返回 None
**症状**：discover 三轮跑完 578 条全部返回 0 关系，但 LLM 单独测试能正确判断
**根因**：之前 P1-1 修复将 `get_claim_evolution` 的返回格式从 `{"c": {...}}` 改为扁平 `{id, statement, ...}`。`fetch_full_claim` 仍用 `node = first.get("c", {})` 取值，永远得到空 dict → 返回 None → 所有相似 claim 被跳过。
**修复**：`fetch_full_claim` 直接读取扁平 dict，不再通过 `"c"` 键嵌套。
**教训**：改 Neo4j 查询返回格式时，**必须 grep 所有调用方**确认兼容。

#### Bug 3: `write_results_to_yaml` 写入后留下孤儿列表项
**症状**：YAML 出现 `supersedes: []` 后跟 `    - claim-xxx` 孤儿行，导致 parse error
**根因**：HEAD 版本 YAML 用 `supersedes:\n    - claim-xxx` 格式（非内联）。discover 将 `supersedes:` 替换为 `supersedes: []`（JSON 内联），但**没有删除后面缩进的列表项**。
**修复**：写入 `supersedes: []` / `contradicts: []` 后，循环跳过后续 `  - claim-` 开头的孤儿行。
**代码**：`write_results_to_yaml()` 第 240-245 行

#### Bug 4: `last_discovered` 在 tags 序列后插入导致 YAML 损坏
**症状**：list-格式 YAML 文件的 `tags:` 列表项后出现 `last_discovered:` 映射键，parser 从序列上下文切回映射时报错
**根因**：`write_results_to_yaml` 在 claim 块末尾追加 `last_discovered`，但 list-格式文件末尾可能是 `tags:\n  - xxx`，映射键插入序列上下文导致 parse error
**修复**：`last_discovered` 紧跟在 `contradicts:` 写入之后（在标签列表之前），不再在块末尾追加。
**代码**：`write_results_to_yaml()` 第 247-252 行

#### Bug 5: 迁移脚本路径后 PROJECT_ROOT 计算错误
**症状**：脚本从 `scripts/` 迁移到 `src/qing_investment/agent/tools/` 后，`PROJECT_ROOT = parent.parent` 指向错误目录
**修复**：`PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent`（5 级 `.parent` 回到仓库根目录）

### 🔧 调试工具

- `scripts/debug_discover.py` — 单条 claim 的 discover 管道追踪（Qdrant 搜索 → Neo4j 获取 → LLM 判断）
- `scripts/fix_corrupted_yaml.py` — 批量修复 YAML 孤儿行，从 Neo4j 回填 supersedes/contradicts

### 🩺 故障诊断速查

| 症状 | 可能原因 | 检查方法 |
|------|---------|---------|
| 0 关系 | Bug 2: fetch 返回 None | `debug_discover.py` 追踪 |
| 0 关系 | Bug 1: Qdrant 遮蔽 | 检查 import 报错 |
| YAML parse error | Bug 3: 孤儿列表项 | `grep -A1 'supersedes: \[]' *.yaml` |
| YAML parse error (list格式) | Bug 4: last_discovered 位置 | `grep -B2 'last_discovered' *.yaml` |

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

1. **必须先停 Agent + MCP server**：脚本会自动检测并 kill Agent 进程（释放 Qdrant lock），但 **不会杀 Hermes 的 MCP 子进程**。MCP server 持有 Qdrant 文件锁会导致索引失败。
   - 手动杀 MCP：`kill $(pgrep -f "mcp_qdrant_server") && kill $(pgrep -f "mcp_neo4j_server")`
   - 同步完成后：`hermes restart`（MCP server 自动重新接入）
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

# 0. 停 MCP server（如果有）
kill $(pgrep -f "mcp_qdrant_server") 2>/dev/null
kill $(pgrep -f "mcp_neo4j_server") 2>/dev/null

# 1. 关系发现（带进度）
bash scripts/run_discover_with_progress.sh

# 2. Neo4j 同步
PYTHONPATH=src .venv/bin/python scripts/migrate_claims_to_neo4j.py

# 3. Qdrant 重建
PYTHONPATH=src .venv/bin/python scripts/index_claims_to_qdrant.py --force-recreate

# 4. 重启 Agent
PYTHONPATH=src .venv/bin/python -m uvicorn qing_investment.agent.main:app \
  --host 0.0.0.0 --port 8000 --log-level info &

# 5. 重启 MCP server（Hermes 自动接回）
hermes restart
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
