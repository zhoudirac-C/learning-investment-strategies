# Claim Relations Discovery — 脚本与工作流

## 脚本

`src/qing_investment/agent/tools/discover_claim_relations.py` — 通过 ONNX embedding + LLM 自动发现 claim 间关系。（2026-06-08 已从 `scripts/` 迁移至 agent tools，与 neo4j_client / llm_client 同目录）

### 模式

| 参数 | 作用 |
|------|------|
| `--file PATH` | 处理单个 claim YAML 文件 |
| `--claim-id ID` | 处理单个 claim |
| `--all-missing` | 处理所有尚无 `supersedes`/`contradicts` 的 claims |
| `--dry-run` | 判断但不写入 YAML |
| `--limit N` | 限制处理数量（测试用） |

**⚠️ 没有 `--all` 模式**。常见错误：假设存在 `--all` 参数。正确用法是 `--all-missing`。

### 续跑机制

`--all-missing` 天然支持中断续跑：只处理尚无关系的 claims，已处理的自动跳过。

## 进度汇报 Wrapper

文件：`scripts/run_discover_with_progress.sh`

### 功能
- 每 10 分钟自动输出进度到日志文件（`logs/discover_relations_<timestamp>.log`）
- 同步写入 `.progress` 文件（仅保留最新进度行）
- 脚本退出时自动记录 exit code 和中断原因（SIGTERM/SIGKILL/OOM/正常完成）
- 支持 `tee` 双写（终端 + 日志）

### 使用方式

```bash
# 直接运行
bash scripts/run_discover_with_progress.sh

# Hermes 后台模式（推荐 — 完成后自动通知）
terminal(background=True, notify_on_complete=True)
  bash scripts/run_discover_with_progress.sh
```

### 中断原因映射

| Exit code | 含义 |
|-----------|------|
| 0 | 正常完成 |
| 130 | SIGINT (Ctrl+C 或进程被中断) |
| 137 | SIGKILL (OOM Killer 或强制杀掉) |
| 143 | SIGTERM (正常终止信号) |
| 其他 | 未知错误 |

### 查看进度

```bash
# 最新进度行
grep -E '^\[[0-9]+/[0-9]+\]' logs/discover_relations_*.log | tail -1

# 进度汇报历史
cat logs/discover_relations_*.progress
```

## YAML 缩进 Corruption（已修复，2026-06-08 补充）

### 根因 1：硬编码 4 空格前缀

`write_results_to_yaml()` 曾硬编码 4 空格前缀：
```python
new_lines.append(f"    supersedes: {json.dumps(results['supersedes'])}")
```

但 claim 文件中的字段缩进是 2 空格（`  supersedes:`），导致 YAML 解析失败。

### 错误症状

- `mapping values are not allowed here`（行级字段缩进错误）
- `expected <block end>, but found '<block mapping start>'`（跨 claim 边界缩进错误）

### 修复 1

改为保留原始行缩进：
```python
indent = line[:len(line) - len(line.lstrip())]
new_lines.append(f"{indent}supersedes: {json.dumps(results['supersedes'])}")
```

### 根因 2：`last_discovered` 插入位置不当（2026-06-08 发现）

旧版代码在 claim 块**末尾**追加 `last_discovered` 行（while 循环结束后 append）。在 list-格式 YAML（`- id:` 开头）中，如 claim 块末尾有 `tags:` 序列：

```yaml
- id: claim-xxx
  tags:
  - AI
  - 芯片
  last_discovered: 2026-06-08    ← 插入此处 → YAML 解析器处于序列上下文！
- id: claim-yyy
```

YAML 解析器遇到 `tags:` 后进入序列上下文，此时插入映射键 `last_discovered:` 导致 `mapping values are not allowed here`。80+ 文件因此损坏，discover 返回 0 关系。

**症状识别**：
- discover 输出 `Found 0 supersedes/contradicts relations` 但 Neo4j 有大量现有关系
- `yaml.safe_load()` 报 `mapping values are not allowed here in "<string>", line N, column N: last_discovered: 2026-06-08`

### 修复 2

`last_discovered` 现在紧跟 `contradicts:` 行写入（在 while 循环内部，而非循环后）：

```python
elif line.strip().startswith("contradicts:"):
    indent = line[:len(line) - len(line.lstrip())]
    new_lines.append(f"{indent}contradicts: {json.dumps(results['contradicts'])}")
    # Write last_discovered right after contradicts (avoid tags sequence conflict)
    if results.get("supersedes") or results.get("contradicts") or force:
        new_lines.append(f"{indent}last_discovered: {today_str}")
        has_last_discovered = True
```

**2026-06-08 事件完整复盘**：三轮 discover 均返回 0 关系。第一轮→YAML 损坏（游离列表项）+ `_parse_claims` 静默返回空；第二轮→写入 bug 把 YAML 写坏；第三轮→先 revert 到 clean HEAD + 修复写入逻辑 = 预期正常。

### Python import shadowing（2026-06-08 新发现）

当 discover 脚本从 `src/qing_investment/agent/tools/` 运行时，Python 自动将脚本所在目录加到 `sys.path[0]`。该目录下的 `qdrant_client.py` 会遮蔽 pip 包 `qdrant_client`，导致：
```
ImportError: cannot import name 'QdrantClient' from 'qdrant_client'
```

**修复**：已在脚本中内置——导入前 pop 掉脚本目录：
```python
_script_dir = str(Path(__file__).resolve().parent)
if sys.path and sys.path[0] == _script_dir:
    sys.path.pop(0)
```

### 批量修复已损坏文件

最快方式：
```bash
git checkout -- knowledge/claims/
```

不要逐文件手工修 — 42 个文件、162 行缩进错误。

## Venv 路径

项目有两个 venv，只有 `.venv` 包含完整依赖：

```bash
# ✅ 正确
.venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py --all-missing

# ❌ 错误 — 缺少 langchain_openai
venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py --all-missing
```

## 预估耗时

~392 条 claims × ~8 秒/条 ≈ 50-90 分钟（ONNX embedding + LLM 判断）。当前知识库 578 claims，其中 392 条无关系需回填，186 条已有关系自动跳过。

### 实际运行统计（2026-06-07 全量回填）

| 关系类型 | LLM 判定次数 | Neo4j 边数 | 是否持久化 |
|----------|-------------|-----------|-----------|
| supplements | 753 (最多) | 0 | ❌ 不写入（设计决策：不改变 claim 有效性，Qdrant+entity 图遍历已覆盖关联） |
| none | 650 | 0 | ❌ 不写入（反模式：存储「无关系」边无业务价值） |
| contradicts | 123 | 143 | ✅ |
| supersedes | 117 | 154 | ✅ |

> **设计决策详情**：见 `skills/qing-stock-analysis/references/claim-relation-discovery.md` §设计决策。

## 完整流水线

关系发现是四步流水线的第一步。完成后的完整流程：

```
discover → Neo4j migrate → Qdrant rebuild → restart Agent
```

详见项目文档：[`docs/neo4j-relation-pipeline.md`](../../../docs/neo4j-relation-pipeline.md)

**每一步不可跳过**：关系写入 YAML 后，Neo4j 和 Qdrant 不会自动同步。必须手动运行迁移+重建，Agent 才能检索到新关系。

## `--all` 模式不存在的真实后果

2026-06-07 用户纠正：Agent 曾错误认为存在 `--all` 模式，将原本单一的 `--all-missing` 任务拆分为"已结束的 `--all`"和"当前运行的 `--all-missing`"两个任务，导致用户困惑。**实际只有 `--all-missing` 一个模式在运行**——脚本中断后重新运行 `--all-missing` 就是续跑，不需额外管理。
