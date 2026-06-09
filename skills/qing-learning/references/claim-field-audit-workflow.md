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
| timeframe | `timeframe` (正确) | `time_frame` (下划线，2026-06-09 已统一修复为 `timeframe`) |

> **2026-06-09 已修复**：4 个文件 `time_frame` → `timeframe`，22 个文件非标值（中文/英语）→ schema 枚举。全部 103 个文件已验证通过 `yaml.safe_load()`。详见下方「timeframe 规范化映射」章节。

### 2. 字段名不一致

- `text` vs `statement` — 迁移脚本兼容两者，但 YAML 应统一
- `timeframe` 的 `time_frame` 变体 — 2026-06-09 已全量修复，不再兼容
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

### PyYAML 字段重排序陷阱（2026-06-09）

> ⚠️ **不要用 `yaml.dump()` 写回批量修改的 claim 文件**

`yaml.dump()` 会按 PyYAML 的内部顺序重新排列所有字段（如 `claim_type` 可能在文件首行、`statement` 可能被挪到末尾），导致：
- git diff 噪音巨大（4800+ 行变更中只有几十行是实际语义修改）
- review 几乎不可行
- 历史 blame 信息被破坏

**正确做法**：使用 `patch` 工具或基于原始字符串（`Path(path).read_text()`）做锁定替换，而非 YAML 序列化-反序列化往返。

```python
# ❌ 错误：yaml.dump 重排字段
import yaml
data = yaml.safe_load(open(f))
for claim in data['claims']:
    claim['timeframe'] = 'short-term'
yaml.dump(data, open(f, 'w'))  # 字段全乱！

# ✅ 正确：基于原始字符串的锁定替换
from pathlib import Path
text = Path(f).read_text()
text = text.replace('timeframe: 短期（1-2周）', 'timeframe: short-term')
text = text.replace('time_frame:', 'timeframe:')
Path(f).write_text(text)

# ✅ 验证 YAML 有效
yaml.safe_load(Path(f).read_text())
```

如果已经误用了 `yaml.dump()` 导致大范围重排：`git checkout -- <file>` 恢复，改用字符串替换重做。

### timeframe 规范化映射表（参考）

2026-06-09 全量审计发现 26 个文件的 `timeframe` 不符合 schema 枚举（`intraday`/`short-term`/`trend`/`industry`/`permanent`）。规范映射规则：

| 原值 | 映射到 | 说明 |
|------|--------|------|
| `短期` / `短期（N-M天/周/日）` | `short-term` | 日/周级别交易 |
| `当日` / `次日（5月19日）` | `intraday` | 当日/次日操作 |
| `中期` / `中期（N-M周/月/年）` / `中期（2026H2）` | `trend` | 周/月级别趋势 |
| `medium-term` / `durable` | `trend` | 英语非标统一处理 |
| `长期` / `long-term` | `industry` | 行业/产业级长期判断 |
| `持续有效` | `permanent` | 方法论级别 |
| `immediate` | `intraday` | 立即/当日 |
| `2026-06-04`（日期误填） | `short-term` | 参考同文件 `scope` 字段 |

## Neo4j 关系验证

```cypher
// 孤立 Claim（无任何关系）
MATCH (c:Claim) WHERE NOT (c)-[]-() RETURN count(c);

// 缺 EXTRACTED_FROM 的 Claim
MATCH (c:Claim) WHERE NOT (c)-[:EXTRACTED_FROM]-() RETURN count(c);

// 缺 CITED_IN 的 Claim
MATCH (c:Claim) WHERE NOT (c)-[:CITED_IN]-() RETURN count(c);
```
