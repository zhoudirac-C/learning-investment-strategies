# Claim 全量字段完整性审计工作流

> 创建：2026-06-08 | 触发：578 条 claim 字段完整性修复

## 何时运行

- 发现 Neo4j 中有孤立 Claim 节点（无 EXTRACTED_FROM/CITED_IN/ABOUT 关系）
- 怀疑 claim YAML 文件质量下降（新增格式 vs 旧格式混用）
- 季度数据质量审计
- 迁移脚本或 schema 变更后

## 审计命令

```bash
cd ~/learning-investment-strategies

# 全量字段缺失统计
python3 << 'PYEOF'
import yaml, glob
from collections import Counter

missing = Counter()
total = 0
for f in sorted(glob.glob('knowledge/claims/*.yaml')):
    data = yaml.safe_load(open(f))
    claims = data.get('claims', data) if isinstance(data, dict) else data
    claims = claims if isinstance(claims, list) else [claims]
    for c in claims:
        total += 1
        for field in ['id','statement','claim_type','subject','source_path','source_date',
                       'source_type','extracted_at','confidence','status','intensity',
                       'evidence_quote','interpretation','timeframe','supersedes',
                       'contradicts','links','topic','tags']:
            val = c.get(field)
            if val is None or val == '':  # Empty string = missing
                missing[field] += 1

print(f'Total: {total} claims')
for field, cnt in sorted(missing.items()):
    print(f'  {field:25s}: {cnt:4d} ({cnt/total*100:.1f}%)')
PYEOF
```

## 常见问题模式

### 1. 两代格式断层

| 特征 | 老格式 (83文件) | 新格式 (10文件) |
|------|----------------|----------------|
| 顶层结构 | `claims:` 包裹 或 裸列表 `- id:` | `claims:` 包裹 |
| 文本字段 | `statement` 或 `text` | `statement` |
| 缺的字段 | `topic`, `tags`, `related_stocks` | `source_path`, `source_date`, `subject` |
| timeframe | `timeframe` (蛇形) | `time_frame` (下划线) |

### 2. 字段名不一致

- `text` vs `statement` — 迁移脚本兼容两者，但 YAML 应统一
- `timeframe` vs `time_frame` — 迁移脚本兼容两者（`claim.get("time_frame","") or claim.get("timeframe","")`）
- `source` vs `source_path` — 迁移脚本只读 `source_path`
- `cited_in` vs `links.wiki_pages` — 迁移脚本读 `links.wiki_pages`
- `methodology_pages` in root vs `links.methodology_pages` — 迁移脚本读 `links.methodology_pages`

### 3. YAML 语法错误根因

最常见：**ASCII 双引号 `"` 出现在未用引号包裹的标量值中**

```yaml
# ❌ 解析失败
statement: 当前行情适合采用"买阴不买阳"策略

# ✅ 修复方式1：用单引号包裹
statement: '当前行情适合采用"买阴不买阳"策略'

# ✅ 修复方式2：用中文引号
statement: 当前行情适合采用「买阴不买阳」策略
```

**批量修复命令**：
```python
import re
text = open(f, encoding='utf-8').read()
text = re.sub(r'"([\u4e00-\u9fff][^"]{0,50}[\u4e00-\u9fff])"', r'「\1」', text)
```

## 修复优先级

| 级别 | 缺失字段 | 修复方法 |
|------|---------|---------|
| P0 | `source_path`/`source_date`/`source_type`/`extracted_at` | 扫描 `sources/raw/` 匹配源文档 |
| P0 | `subject` | 从 `statement` 提取主题或 `topic` |
| P1 | `statement`（仅有 `text`） | 复制 `text` → `statement` |
| P1 | `links` | 新建 `{wiki_pages:[], methodology_pages:[]}` |
| P2 | `topic`/`tags` | 运行 `scripts/add_topics_tags.py` 自动生成 |
| P2 | `supersedes`/`contradicts` | 补充 `[]`（无关系是合法的） |

## 修复后验证

```bash
# 全量验证
python3 << 'PYEOF'
import yaml, glob
R = ['id','statement','claim_type','subject','source_path','source_date',
     'source_type','extracted_at','confidence','status','intensity',
     'evidence_quote','interpretation','timeframe','supersedes',
     'contradicts','links','topic']
errors = 0
for f in sorted(glob.glob('knowledge/claims/*.yaml')):
    data = yaml.safe_load(open(f))
    claims = data.get('claims',data) if isinstance(data,dict) else data
    claims = claims if isinstance(claims,list) else [claims]
    for c in claims:
        m = [k for k in R if k not in c or c[k] in (None,'')]
        if m: print(f'{c.get("id")}: {m}'); errors += 1
if errors:
    print(f'\n❌ {errors} missing fields')
else:
    print(f'✅ All claims complete')
PYEOF
```

## Neo4j 关系验证

```cypher
// 孤立 Claim（无任何关系）
MATCH (c:Claim) WHERE NOT (c)-[]-() RETURN count(c);

// 缺 EXTRACTED_FROM 的 Claim
MATCH (c:Claim) WHERE NOT (c)-[:EXTRACTED_FROM]-() RETURN count(c);

// 缺 CITED_IN 的 Claim
MATCH (c:Claim) WHERE NOT (c)-[:CITED_IN]-() RETURN count(c);
```
