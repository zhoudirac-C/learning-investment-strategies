# 自动化复盘脚本参考

> 2026-06-10 基于实际 review 会话提炼。用于周期性方法论复盘的自动化执行。

---

## 脚本定位

`scripts/methodology_review.py`（待实现）—— 读取 claims → 统计分析 → 主题漂移 → 矛盾识别 → Durable Rule 筛选 → 生成报告。

## 当前手工流程（可作为脚本实现参考）

### Step 1: 读取 Claims

```python
import yaml, glob
from collections import Counter, defaultdict

claim_files = glob.glob('knowledge/claims/claim-*.yaml')
all_claims = []
for f in sorted(claim_files):
    try:
        with open(f, 'r', encoding='utf-8') as fh:
            data = yaml.safe_load(fh)
        if data and 'claims' in data:
            for c in data['claims']:
                if isinstance(c, dict):
                    all_claims.append(c)
    except:
        pass
```

**坑点**：
- `source_date` 可能是 `datetime.date` 对象或字符串，需统一处理
- 部分 YAML 文件格式错误（特殊字符未转义），需 try/except 跳过

### Step 2: 统计分析

```python
# 按日期统计
date_counts = Counter()
for c in all_claims:
    sd = c.get('source_date', '')
    if hasattr(sd, 'strftime'):
        sd = sd.strftime('%Y-%m-%d')
    date_counts[str(sd)] += 1

# claim_type 分布
type_counts = Counter(c.get('claim_type', 'unknown') for c in all_claims)

# confidence/status 分布
conf_counts = Counter(str(c.get('confidence', 'unknown')) for c in all_claims)
status_counts = Counter(str(c.get('status', 'unknown')) for c in all_claims)
```

### Step 3: 主题漂移分析

按 `claim_type` 分组，按时间线排列，判断变化类型：

```python
claims_by_date = defaultdict(list)
for c in all_claims:
    sd = c.get('source_date', '')
    if hasattr(sd, 'strftime'):
        sd = sd.strftime('%Y-%m-%d')
    claims_by_date[str(sd)].append(c)

# 追踪 market-cycle 类型 claims 的时间线
for d in sorted(claims_by_date.keys()):
    mc = [c for c in claims_by_date[d] if c.get('claim_type') == 'market-cycle']
    for c in mc:
        print(f"{d}: {c.get('subject', '')}")
```

### Step 4: 矛盾识别

```python
# 显式标记的 contradicts
for c in all_claims:
    if c.get('contradicts'):
        print(f"{c.get('id')}: contradicts {c.get('contradicts')}")

# 隐式矛盾检测（同一主题在不同日期的方向变化）
# TODO: 需要主题聚类算法
```

### Step 5: Durable Rule 筛选

筛选 `claim_type == methodology` 的 claims，按进入条件打分：

| 条件 | 权重 |
|------|------|
| 有具体数字/阈值 | +3 |
| 多次重复（跨日期） | +2 |
| 改变操作纪律 | +3 |
| 首次即入例外（直接回答"现在怎么办"） | +3 |

### Step 6: 生成报告

报告模板见 `references/review-report-template.md`。

---

## 已知问题

1. **日期类型不一致**：Neo4j 返回 `neotime.Date`，YAML 解析返回 `datetime.date` 或 `str`。需统一用 `_to_date_str()` 处理。
2. **主题聚类缺失**：当前靠人工判断"同一主题"，脚本需要简单的关键词聚类或语义相似度。
3. **矛盾分类自动化困难**：timeframe-shift vs cycle-shift vs logic-broken 需要 LLM 判断，不能完全脚本化。

## 建议实现路径

1. **Phase 1**（已实现）：手工执行，用 Python 脚本辅助统计和格式化
2. **Phase 2**（待实现）：脚本自动生成统计+时间线，矛盾分类和 Durable Rule 筛选仍由 LLM 完成
3. **Phase 3**（远期）：全自动化，LLM 直接读取 claims 生成完整报告

## 参考

- 实际 review 会话：2026-06-10 review 青枫浦上过去14天观点
- 输出报告：`reports/methodology-review-20260610.md`
