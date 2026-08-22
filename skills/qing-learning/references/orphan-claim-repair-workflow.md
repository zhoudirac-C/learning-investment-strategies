# 孤立 Claim 修复工作流

> 当 Neo4j 中发现有 Claim 节点但无任何关系（ABOUT/EXTRACTED_FROM/CITED_IN）时的系统化修复流程。
> 创建时间: 2026-06-08

## 症状

```cypher
MATCH (c:Claim) WHERE NOT (c)-[]-() RETURN count(c);
-- 应始终为 0。若 > 0，按以下流程修复。
```

## 根因分类

当 `MATCH (c:Claim) WHERE NOT (c)-[]-() RETURN count(c)` 返回 > 0 时，99% 的根因是 YAML 中缺失以下字段：

| 缺失字段 | 影响 | Neo4j 表现 |
|----------|------|-----------|
| `source_path` (或写为 `source`，但项目用 `source_path`) | EXTRACTED_FROM 关系无法创建 | 无 SourceDocument 关联 |
| `links.wiki_pages` | CITED_IN 关系无法创建 | 无 WikiPage 关联 |
| `links.methodology_pages` | 同上 | 同上 |
| `subject: ""` (空) | ABOUT 关系无法创建 | 无实体关联 |

## 修复流程

### Step 1: 扫描 raw 文档找 source_path

用 Python 扫描 `sources/raw/财经/` 与 `sources/original/bilibili/` 两个目录（UP raw 两个落点），按以下优先级匹配：

```python
import glob, yaml
from pathlib import Path

# 读取孤立 claim 的日期和 statement 关键词
orphan_dates = {'2026-06-07', '2026-06-04', '2026-06-05'}
orphan_keywords = ['长黑线', '上吊线', '流星线', '尾盘低吸', '人民币强势']

for fp in sorted(glob.glob('sources/raw/财经/*.md')) + sorted(glob.glob('sources/original/bilibili/*.md')):
    name = Path(fp).name
    # 按日期匹配
    date_in_name = any(d.replace('-', '') in name for d in orphan_dates)
    if not date_in_name:
        continue
    content = Path(fp).read_text()
    # 按关键词匹配
    if any(kw in content for kw in orphan_keywords):
        print(f'✅ {fp}')
```

### Step 2: 用 patch 工具精确写入

定位到具体 claim 所在 YAML 文件的行：

```bash
grep -n "id: claim-YYYYMMDD-XXX-[a-z]" knowledge/claims/claim-YYYYMMDD-XXX.yaml
```

然后用 `patch` 工具在 claim 的 `supersedes:` 或 `contradicts:` 后面插入：

```yaml
  source_path: <匹配到的 raw 文件路径>  # sources/raw/财经/ 或 sources/original/bilibili/
```

对 technical-knowledge 类 claim 同时加 wiki 关联：

```yaml
  links:
    wiki_pages:
    - 投资方法论/技术分析
```

### Step 3: 触发增量同步

```bash
# 关 Agent → 迁移（只处理 mtime 有变化的文件）→ Qdrant 重建 → 重启
kill $(pgrep -f "uvicorn qing_investment") 2>/dev/null
cd ~/learning-investment-strategies
PYTHONPATH=src .venv/bin/python scripts/migrate_claims_to_neo4j.py
PYTHONPATH=src .venv/bin/python scripts/index_claims_to_qdrant.py --force-recreate
.venv/bin/uvicorn qing_investment.agent.main:app --host 0.0.0.0 --port 8000 &
```

### Step 4: 验证

```cypher
MATCH (c:Claim) WHERE NOT (c)-[]-() RETURN count(c);
-- 应为 0
```

## 迁移脚本字段映射速查

以下是 YAML 字段 → Neo4j 创建的关系映射：

| YAML 字段 | 迁移代码读取 | Neo4j 关系 |
|-----------|-------------|-----------|
| `source_path` | `claim.get("source_path", "")` | `[:EXTRACTED_FROM]->SourceDocument` |
| `links.wiki_pages` | `links.get("wiki_pages", [])` | `[:CITED_IN]->WikiPage` |
| `links.methodology_pages` | `links.get("methodology_pages", [])` | `[:CITED_IN]->MethodologyPage` |
| `subject` + `statement` | `extract_stock_codes(subject + statement)` | `[:ABOUT]->Stock` |
| `supersedes` (string/list) | `claim.get("supersedes", [])` | `[:SUPERSEDES]->Claim` |
| `contradicts` (string/list) | `claim.get("contradicts", [])` | `[:CONTRADICTS]->Claim` |

⚠️ 注意 `links` 有两种格式：
- 新格式：`links: {wiki_pages: [...], methodology_pages: [...]}`（dict）
- 旧格式：`links: [claim-xxx, claim-yyy]`（related_claims 列表）

迁移脚本同时处理了这两种格式。

## 常见陷阱

1. **不要用 `--force-full` 修复孤立 Claim**：`--force-full` 已被移除（2026-06-08）。正确的做法是改 YAML → 增量迁移自动感知。
2. **不要删除孤立 Claim**：`DETACH DELETE` 会丢失知识。先尝试修复 YAML。
3. **不要只修 surface**：如果 YAML 的 `source_path` 始终为空，检查 claim 提取脚本的源头。
4. **`search_files` 不能可靠判定文件不存在**：对含中文路径的目录可能返回空结果。用 `ls` 或 `read_file` 做确定性检查。
