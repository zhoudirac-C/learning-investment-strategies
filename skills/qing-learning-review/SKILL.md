---
name: qing-learning-review
description: |
  方法论复盘 — 检查 claims 一致性、识别观点漂移、标记矛盾/过期。
  触发词：qing review、方法论复盘、review claims、检查一致性
---

# qing-learning-review

## 范围确定

- 默认：最近 7 天（含今天）
- 用户可指定：日期范围、特定主题、特定 claim ID

## 9 步复盘流程

### Step 1: 读取 Claims

```bash
grep "source_date:" knowledge/claims/claim-*.yaml | sort
```

提取：date, topic, text, claim_type, confidence, status, supersedes, contradicts

### Step 2: 统计分析

- 每日 claim 数量、主题分布（Top 20）
- claim_type 分布、confidence 分布、status 分布
- 有 supersedes/contradicts 的 claims

### Step 3: 主题漂移

| 变化类型 | 含义 |
|----------|------|
| no-change | 观点一致，重复确认 |
| clarification | 细化、补充条件 |
| extension | 扩展到新场景 |
| correction | 修正旧判断 |
| contradiction | 明确矛盾，需标记 |
| expiration | 观点过期 |

### Step 4: 矛盾分类

按 `framework/contradiction-policy.md`：

| 类型 | 处理 |
|------|------|
| timeframe-shift | 无需标记 |
| cycle-shift | 标记，更新 status |
| logic-broken | 标记 contradicts |
| risk-repriced | 标记 |
| true-conflict | 高亮提醒用户 |

### Step 5: Durable Rule 筛选

进 framework 条件（满足其一）：
1. 有具体数字/条件/阈值
2. 同一方法论出现 2 次以上
3. 能解释旧冲突
4. 改变操作纪律

### Step 6: 一致性检查

新 claims 与前期框架的冲突检查。

### Step 7: 生成报告

输出格式见 `references/review-report-template.md`，保存到 `reports/methodology-review-YYYYMMDD.md`

### Step 8: 提交

```bash
git add reports/methodology-review-YYYYMMDD.md
```

### Step 9: 汇报

核心结论（3-5条）+ 结构化数据 + 建议后续动作

## 关键坑

- 轨道B（technical-knowledge）不参与 drift 分析
- timeframe-shift 和 cycle-shift 是正常变化，不是错误
- durable rule 门槛要高，不要将单日观点推入 framework
