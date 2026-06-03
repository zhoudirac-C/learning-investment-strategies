# Claims 一致性校验参考手册

> 当更新 strategy_pack.yaml 的 entry_points 或 position_rules 时，必须与 knowledge/claims/ 中的博主最新观点做一致性校验，防止策略与博主纪律直接矛盾。

---

## 问题场景

**典型错误**：
- 6月2日盘中动态明确说"MLCC已提前1-2周提示，现在追涨是韭菜行为"
- 但6月3日早盘 strategy_pack.yaml 却给风华高科/火炬电子配了介入区间（55-57、56-58）
- **结果**：策略直接 contradict 博主纪律，用户发现并纠正

**根因**：更新 strategy_pack 时只看了市场数据和技术面，未检查 claims 中博主对该方向的最新定性。

---

## 校验流程（必须执行）

在更新 `strategy_pack.yaml` 的 `entry_points` 或 `position_rules` 之前，必须执行以下检查：

### Step 1: 扫描相关 claims

```bash
cd ~/learning-investment-strategies
# 扫描最近 3 天的 claims，查找与目标标的相关的观点
grep -r "MLCC\|风华高科\|火炬电子\|三环集团" knowledge/claims/claim-202606*.yaml
```

### Step 2: 读取相关 claim 的 interpretation

重点读取 `interpretation` 字段，特别是：
- 博主是否明确说"不追高""只观察""韭菜行为"
- 博主是否给了具体的操作纪律（如"先知先觉，不追高"）
- 该方向是否已被博主"关闭"（即不再建议新买入）

### Step 3: 决策矩阵

| Claim 中的博主定性 | entry_points 应如何配置 |
|-------------------|------------------------|
| "现在追涨是韭菜行为" / "已提前提示，不追高" | **entry_zone: 只观察不介入**, position_ratio: 0, note 中引用 claim ID |
| "只观察不追高" / "等回调" | entry_zone: 只观察不介入 或 等回调区间（需明确回调幅度） |
| "核心方向，可介入" / "强者恒强" | 正常配置介入区间，但需满足联动条件 |
| 无明确观点 | 基于技术框架推断，但必须标注 `inference_note` |

### Step 4: 在 strategy_pack 中标注 claim 来源

对于因 claim 限制而不介入的标的，必须在 `note` 中明确引用：

```yaml
- code: sz000636
  name: 风华高科
  entry_zone: 只观察不介入
  position_ratio: '0'
  trigger: MLCC已提前1-2周提示，现在追涨是韭菜行为
  invalidation: 无
  note: '【纪律】6月2日盘中动态明确：MLCC已提前1-2周提示，现在追涨是韭菜行为。来源：claim-20260602-002.yaml'
```

---

## 常见矛盾类型

### 类型 1："已提前提示，现在追是韭菜"
- **claim**: "MLCC已提前1-2周提示，现在追涨是韭菜行为"
- **错误策略**: 给 MLCC 票配介入区间
- **正确策略**: entry_zone = "只观察不介入", position_ratio = 0

### 类型 2："规避方向"
- **claim**: "博主明确规避半导体"
- **错误策略**: 给半导体票配买入条件
- **正确策略**: 放入 `avoid_sector_discipline` forbidden 列表

### 类型 3："过渡性质，不持续"
- **claim**: "消费/白酒过渡性质确认，防御走强是分化而非切换"
- **错误策略**: 给消费票配重仓介入
- **正确策略**: 轻仓试探或只观察

### 类型 4："需等硬信号落地"
- **claim**: "SOFC和DSP国内多是预期博弈，需等硬信号落地"
- **错误策略**: 给 SOFC/DSP 票配明确介入区间
- **正确策略**: entry_zone = "等硬信号落地后观察", position_ratio = 0 或极低

---

## 校验清单

更新 strategy_pack.yaml 前必须确认：

- [ ] 最近 3 天的 claims 已扫描
- [ ] 所有 entry_points 中的标的已在 claims 中检查
- [ ] 若 claim 中博主明确说"不追高"/"韭菜行为"/"只观察"，对应标的 entry_zone 为"只观察不介入"
- [ ] 被 claim 限制的标的有明确的 claim 来源标注
- [ ] position_rules 中的 `forbidden` 列表与 claims 中的规避方向一致
- [ ] 无 claim 支持的买入建议已标注 `inference_note`

---

## 快速校验命令

```bash
# 扫描最近 claims 中的纪律性表述
grep -h "韭菜\|不追高\|只观察\|规避\|不介入" knowledge/claims/claim-*.yaml | head -20

# 检查 strategy_pack 中是否有与 claims 矛盾的买入建议
# （手动检查：对比 entry_points 中的票与 claims 中的规避列表）

# 验证特定标的的 claim 状态
grep -r "风华高科\|MLCC" knowledge/claims/claim-*.yaml
```
