# Discover Pipeline "0 relations" 诊断工作流

> 当 `discover_claim_relations.py --all-missing` 返回 `Found 0 supersedes/contradicts relations` 时的系统排查步骤。

## 症状

```
[578/578] claim-xxx: ...
✅ Done. Found 0 supersedes/contradicts relations.
```

578 条 claim 全部处理但 0 条关系。Neo4j 中已有 154+143 条边，LLM 不可能全部判为 none。

## 排查步骤（从源头到消费端逐层验证）

### Step 1: 验证 Qdrant 搜索是否返回结果

```python
from qing_investment.agent.tools.qdrant_client import QdrantClientWrapper
from qing_investment.agent.tools.llm_client import get_embedding_model

qdrant = QdrantClientWrapper(local_mode=True)
emb = get_embedding_model()
text = "测试claim的 subject | statement"
vec = emb.encode(text).tolist()
results = qdrant.search(vec, collection="qing_claims", limit=4)
print(f"Results: {len(results)}")  # 应有 4 条（含 SELF）
```

若返回 0 → Qdrant collection 为空或向量维度不匹配（用 `--force-recreate` 重建）。

### Step 2: 验证 Neo4j 查询返回正确格式

```python
from qing_investment.agent.tools.neo4j_client import Neo4jClient

nc = Neo4jClient()
result = nc.get_claim_evolution('claim-xxx')
# 关键：检查返回格式是扁平 dict {id, statement, subject...} 还是嵌套 {"c": {...}}
print(type(result[0]))  # 应为 dict
print(list(result[0].keys()))  # 应有 ['id', 'statement', 'subject', ...]
```

**⚠️ 最常见根因**：`get_claim_evolution` 格式变更后 `fetch_full_claim` 未同步更新。
- 旧格式：`[{"c": {"id": ..., "statement": ...}}]` → `first.get("c", {})`
- 新格式：`[{"id": ..., "statement": ...}]` → `first.get("statement")` 直接取
- 若格式不匹配，`fetch_full_claim` 返回 None → 所有相似 claim 被静默跳过

### Step 3: 验证 LLM 判断是否正常

直接用 `judge_relation` prompt 测试一对已知关系的 claim：

```python
from qing_investment.agent.tools.llm_client import get_llm_client

llm = get_llm_client()
prompt = RELATION_PROMPT.format(subject_a=..., statement_a=..., ...)
resp = llm.invoke(prompt).content
print(resp)  # 应为 JSON: {"relation": "supersedes|...", "reason": "..."}
```

若 LLM 返回 "none" 但人工判断应为 supersedes/contradicts → LLM 配置或模型问题。

### Step 4: 验证单条完整流程

```bash
PYTHONPATH=src .venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py \
  --claim-id "claim-xxx" --dry-run
```

若单条 dry-run 正常输出关系但 `--all-missing` 返回 0 → YAML 写入损坏。

### Step 5: 验证 YAML 未被写入损坏

```bash
cd ~/learning-investment-strategies
python -c "
import yaml; from pathlib import Path
bad = [f.name for f in Path('knowledge/claims').glob('*.yaml') 
       if not _try_parse(f)]
print(f'Bad: {len(bad)}')
"
```

**YAML 损坏常见模式**：
- `mapping values are not allowed here` at `last_discovered` 行 → `last_discovered` 插在 tags 序列上下文中
- `expected <block end>, but found '<block sequence start>'` → 游离的 `- claim-xxx` 列表项
- `'list' object has no attribute 'get'` → list 格式 YAML 顶层结构

## 强制重跑（清除状态后全量重新发现）

当 YAML 损坏已修复但 `last_discovered` 标记导致 `--all-missing` 跳过时：

```bash
# 1. 恢复到干净 YAML（丢弃损坏版本）
cd ~/learning-investment-strategies
git checkout HEAD -- knowledge/claims/

# 2. 清除 last_discovered（否则 --all-missing 全部跳过）
python -c "
import re; from pathlib import Path
for f in Path('knowledge/claims').glob('*.yaml'):
    t = f.read_text()
    if 'last_discovered:' in t:
        f.write_text(re.sub(r'(?m)^\s*last_discovered:.*\n?', '', t))
"

# 3. 验证 YAML 全部可解析
python -c "import yaml; [yaml.safe_load(open(str(f))) for f in __import__('pathlib').Path('knowledge/claims').glob('*.yaml')]"

# 4. 重跑
PYTHONPATH=src .venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py --all-missing
```

## 修复脚本

- `scripts/fix_corrupted_yaml.py` — 移除游离 claim ID 行 + 从 Neo4j 回填关系
- `scripts/fix_20260524_fields.py` — 修复 20260524 系列 tab/空格缩进问题

## 历史案例

| 日期 | 症状 | 根因 |
|------|------|------|
| 2026-06-08 (第1轮) | 578条→0关系 | YAML 80 文件损坏（批量字段回填游离列表项） |
| 2026-06-08 (第2轮) | 578条→0关系 | `fetch_full_claim` 未适配扁平 Neo4j 格式 |
| 2026-06-08 (第3轮) | 578条→0关系 | `write_results_to_yaml` 在 tags 序列后插 `last_discovered` |
| 2026-06-08 (第4轮) | ✅ 250条关系 | 三个 bug 全部修复 |
| 2026-06-08 (第5轮) | ⚠️ 250条但56文件损坏 | HEAD 旧格式 `supersedes:\n    - claim-xxx` 被重写为 `supersedes: []` 后孤儿 `- claim-xxx` 行残留 |

## `write_results_to_yaml` 孤儿列表项修复（2026-06-08 第5轮追加）

**问题**：HEAD commit (6facc98) 中部分文件使用旧 YAML 格式：
```yaml
  supersedes:
    - claim-20260406-001
```
而非 JSON 数组格式 `supersedes: ["claim-xxx"]`。discover 的写入函数替换 `supersedes:` 行为 `supersedes: []`（内联 JSON），但未消费后续的缩进列表项，导致孤儿 `    - claim-xxx` 行成为非法 YAML。

**修复**：在 `write_results_to_yaml()` 中，替换 `supersedes:` 或 `contradicts:` 后，立即跳过后续的孤儿列表项：

```python
# After writing supersedes: [...] or contradicts: [...]
new_lines.append(f"{indent}supersedes: {json.dumps(results['supersedes'])}")
i += 1
# Skip orphan list items from old YAML format
while i < len(lines) and lines[i].strip().startswith("- claim-"):
    i += 1
```

此逻辑对 `supersedes:` 和 `contradicts:` 都适用。已集成到 `src/qing_investment/agent/tools/discover_claim_relations.py`。
