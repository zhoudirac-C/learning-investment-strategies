# Prompt 输出模板格式重组模式

> 适用：修改 `format_agent_analysis_context()` 和 `format_daily_review_context()` 底部的 LLM 输出格式模板。
> 来源：2026-06-11 Phase 6.3 实施。

## 通用策略

输出模板重组的操作只有三类：**合并（merge）**、**拆分（split）**、**精简（prune）**。每次只做一类，验证后再做下一类。

## 三类操作

### 1. 合并（Merge）

将两个功能近似的段合并为一个，减少 LLM 输出冗余。

**案例**：合并【盘面】+【全A锚】为单一【盘面】

```python
# 旧
【盘面】一句话定性（必须含全A涨跌幅+强/弱修复判断+领涨方向）。
【全A锚】全A指数当前价/涨跌幅/量能/判断（强修复/弱修复/分歧/防御）。

# 新
【盘面】一句话定性（必须含全A涨跌幅+强/弱修复判断+领涨方向）。全A锚合并至此，不再另起一行。
```

**检查**：LLM 输出中不再出现独立【全A锚】行。

### 2. 拆分（Split）

将一个段按优先级分为两部分，精细控制 LLM 的注意分配。

**案例**：拆分【持仓池】→ 【重点分析】+【其他持仓】

```python
# 旧：所有持仓平铺，每只15-30字
【持仓池】
- 深科技(000021)：动作=持有；触发=...；证伪=...
- 通富微电(002156)：动作=...；触发=...；证伪=...

# 新：重点票详细分析，其余持仓精简
【重点分析】1-2只重点票，每只80-100字。按持仓类型（limit_up/weak_board/floating_loss/trend）套用对应分析框架，说明动作+触发+证伪。
【其他持仓】剩余持仓每只15字（动作+触发+证伪）。
```

**规则**：
- 重点票数：严格1-2只，不超过2只
- 字数差：重点票80-100字 vs 其他15字（5-7倍差距）
- 分类依据：`position_type` 字段（limit_up/weak_board/floating_loss/trend）

### 3. 精简（Prune）

减少选项数量，限制 LLM 输出范围。

**案例**：精简【观察池】

```python
# 旧
【观察池】
- 可买：最多3个满足/接近买入条件的标的和买点。
- 不买：最多3个不符合条件或风险较大的标的和原因。

# 新
【观察池】最多3只，每只15字。可买说明买点，不买说明原因。
```

## 执行步骤

### Step 1: 识别操作对象

读 `format_agent_analysis_context()` 底部的 `lines.extend([...])` 块：
- 【盘面】+【全A锚】并列 → 可合并
- 【持仓池】单一段 → 可拆分
- 【观察池】有子段 → 可精简

### Step 2: 改 prompt + 改断言

**修改两点**：
1. `format_agent_analysis_context()` 底部的输出模板
2. `format_daily_review_context()` 底部的输出模板（同步更新）

**同步更新测试断言**：
```python
# 旧断言
assert "每只触发/重点持仓必须单独一行" in message

# 新断言
assert "【重点分析】1-2只重点票，每只80-100字" in message
assert "【其他持仓】剩余持仓每只15字" in message
```

测试文件：`tests/test_stock_monitor.py`

### Step 3: 验证

```bash
.venv/bin/python -m pytest tests/test_stock_monitor.py -x -q
# 必须 49/49 passed
```

### Step 4: 手动检查（可选）

```bash
cd ~/learning-investment-strategies
PYTHONPATH=src .venv/bin/python -c "
from qing_investment.stock_monitor import format_agent_analysis_context
# mock 环境运行后 grep 关键段
import re
# 确认旧段不存在
assert '【全A锚】' not in text, '全A锚段未移除'
assert '【持仓池】' not in text, '持仓池段未拆分'
# 确认新段存在
assert '【重点分析】' in text, '重点分析段缺失'
assert '【其他持仓】' in text, '其他持仓段缺失'
"
```

## 陷阱

### 陷阱 1: 只改主模板不改 daily_review 模板

`format_agent_analysis_context()` 和 `format_daily_review_context()` 都有底部输出模板。改了一个不改另一个 → 17:00 收盘复盘输出格式不一致。

### 陷阱 2: 改模板不同步改测试断言

旧模板移除后，测试中的 `assert "旧文本"` 会失败。搜索 `tests/` 中所有引用旧模板文本的断言，一起更新。

### 陷阱 3: 字数限制不符合实际

重点分析80-100字 + 其他持仓15字：1-2只重点 + 3-4只其他 + 观察池 = 200-260字。如果总限450字，大盘定性预留50字 + 参考来源20字 = 剩余380字，足够。

但如果持仓>8只，其他持仓15字×6只=90字，加上重点2只×100字=200字，总持仓就290字 → 需要压缩其他持仓到10字或减少重点到1只。

## 检查清单

- [ ] 合并/拆分/精简三类操作，一次只做一类
- [ ] 主模板和 daily_review 模板同步更新
- [ ] 测试断言同步更新
- [ ] `49/49 pytest passed`
- [ ] LLM 输出格式符合新模板预期（非交易时间可跳过此步）
