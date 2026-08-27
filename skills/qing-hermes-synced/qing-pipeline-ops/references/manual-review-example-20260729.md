# 手动方法论复盘执行示例 — 2026-07-29

> 对应 qing-learning-review skill 的 9 步流程
> 窗口：2026-07-20 至 2026-07-29（10 天，186 条 claims）

## 实际执行序列

### Step 1: 获取 claims（Neo4j MCP + Python 并行）

```
1. mcp__neo4j__get_recent_claims(days=10) → 返回结构化 JSON
2. Python 脚本读取 knowledge/claims/claim-2026072*.yaml → 提取 subject/type/date
3. 两者交汇得到完整列表：186 条 claims，按日期降序排列
```

### Step 2: 统计分析

用 Python 脚本生成分布表：

```python
import os, yaml, collections

path = 'knowledge/claims'
files = [f for f in os.listdir(path) if f.startswith('claim-2026072')]

by_type = collections.Counter()
by_date = collections.Counter()
by_conf = collections.Counter()

for f in files:
    with open(os.path.join(path, f)) as fh:
        data = yaml.safe_load(fh)
    claims = data.get('claims', []) if isinstance(data, dict) else data
    for c in (claims if isinstance(claims, list) else [claims]):
        by_type[c.get('claim_type','?')] += 1
        by_date[c.get('source_date','?')] += 1
        by_conf[c.get('confidence','?')] += 1

# 输出分布表
for date, count in sorted(by_date.items()):
    print(f"{date}: {count} claims")
```

### Step 3: 主题漂移分析

按三大核心 claim_type 逐日追踪：

| 类型 | 判断标准 | 窗口内条数 |
|------|---------|:---------:|
| market-cycle | 大盘定调、量能判断、结构分析 | ~30 |
| sector-theme | 板块方向、题材轮动 | ~40 |
| operation | 操作纪律、情景框架 | ~20 |

**发现**：双情景框架（情形A/B）在 5 天中重复出现（7/20, 7/21, 7/24, 7/28, 7/29），
判定为 UP 核心决策工具 → 建议写入 framework。

### Step 4: 矛盾分类

3 处疑似矛盾经分析后均为正常演变：
- 消费走强定性：7/28 → 7/29 为深化（supplements），非矛盾
- 反弹带队方向：始终认为科技带队（一致）
- 量能判断：上午→下午为信息增量（timeframe-shift）
- 结果：0 处 true-conflict

### Step 5: Durable Rule 筛选

对每条 claim_type=methodology 的 claim 执行 6 条件筛选：
- 符合条件 1（明确规则）：2 条（情绪数据校验标准、四项纪律）
- 符合条件 2（多次重复 ≥2）：4 条（双情景框架、右侧确认、量能质量、看跌停龙止跌）
- 符合条件 3-6：2 条（避险三件套、AI 证伪条件）
- 总计：8 条候选

### Step 6-9: 报告生成

- 写入 `reports/methodology-review-20260729.md`
- git add + commit
- 向用户汇报 5 条核心结论 + 结构化数据
- 用户请求写 framework → 在 review 下游执行

## 关键经验

1. **Neo4j MCP 比 grep 高效得多**：`get_recent_claims(days=10)` 直接返回结构化 JSON
2. **Python 脚本比多次终端调用快**：一次 execute_code 完成统计+格式化
3. **框架写入在 review 下游**：review 是只读，write 是用户决策后的独立操作
4. **185+ 条 claims 不需要逐条阅读**：按类型聚合 → 找漂移 → 找矛盾 → 找规则，效率足够
