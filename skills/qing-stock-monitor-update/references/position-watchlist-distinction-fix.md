# 持仓/观察池区分修复记录

> 2026-06-10 修复。防止 AI 将 watchlist 标的误认为持仓。

---

## 问题现象

用户实际空仓（`positions.yaml`: `positions: []`），但 cron 报告输出：
> 景旺电子(CCL) +4.18%  
> 鼎龙股份(材料) +2.03%

仿佛这些标的是持仓。AI 将 `watchlist.yaml` 中的观察标的当作了持仓分析。

---

## 根因分析

1. **`format_analysis_context()` 格式模糊**：
   ```
   持仓：          ← 无空仓标注，AI 可能忽略空列表
   
   观察池：        ← 与持仓平级，无明确区分说明
   - 标的A...
   - 标的B...
   ```

2. **cron prompt 无区分说明**：9个 prompt 文件均未说明"持仓池"和"观察池"的区别

3. **AI 上下文理解偏差**：当持仓为空时，AI 可能将观察池的标的"填充"到持仓分析中

---

## 修复方案

### 修复 A：`stock_monitor.py` context 格式强化

**`format_analysis_context()` 变更：**

```python
lines = [
    "...",
    "=== 持仓池（positions.yaml）===",
    f"状态：{'【空仓】当前无持仓' if not positions else f'共 {len(positions)} 只持仓'}",
    "",
    "重要区分：",
    "- 持仓池 = 你当前实际持有的股票（来自 positions.yaml）",
    "- 观察池 = 你关注但尚未买入的股票（来自 watchlist.yaml）",
    "- 严禁将观察池标的当作持仓分析！",
    "",
    "持仓明细：",
]
if not positions:
    lines.append("  （无持仓）")
# ... 列出现有持仓

lines.extend(["", "=== 观察池（watchlist.yaml）===", "这些标的尚未买入，仅作观察："])
# ... 列出观察标的
```

**`format_live_analysis_context()` 变更：**

在输出模板指令前增加持仓状态提醒：
```python
positions = position_rows(config)
position_status = "空仓" if not positions else f"持仓{len(positions)}只"

lines.extend([
    "...",
    "【重要】当前持仓状态：" + position_status,
    "【重要】观察池标的 ≠ 持仓，严禁混淆！",
    "...",
])
```

### 修复 B：9个 cron prompt 增加区分说明

每个 prompt 文件开头插入：
```
【持仓池 vs 观察池 区分说明】
- 持仓池 = positions.yaml 中列出的股票，是你当前实际持有的仓位
- 观察池 = watchlist.yaml 中列出的股票，是你关注但尚未买入的标的
- 【严禁】将观察池标的当作持仓分析或给出持仓操作建议！
- 当前持仓状态已在上下文顶部标明，分析前务必确认
```

涉及文件：
- `cron_opening.txt`
- `cron_open_confirm.txt`
- `cron_morning_confirm.txt`
- `cron_opportunity_scan.txt`
- `cron_noon_review.txt`
- `cron_afternoon_risk.txt`
- `cron_midday.txt`
- `cron_tail_condition.txt`
- `cron_closing.txt`

---

## 验证方法

```bash
cd ~/learning-investment-strategies
python3 -c "
import sys; sys.path.insert(0, 'src')
from qing_investment.stock_monitor import format_analysis_context, load_monitor_config
from datetime import datetime
from zoneinfo import ZoneInfo

config = load_monitor_config()
ctx = format_analysis_context(config, datetime.now(ZoneInfo('Asia/Shanghai')))

# 检查关键标记
assert '【空仓】当前无持仓' in ctx, '空仓标注缺失'
assert '严禁将观察池标的当作持仓分析' in ctx, '区分说明缺失'
assert '持仓池（positions.yaml）' in ctx, '持仓池标题缺失'
assert '观察池（watchlist.yaml）' in ctx, '观察池标题缺失'
assert '（无持仓）' in ctx, '无持仓提示缺失'

print('✓ 持仓/观察池区分验证通过')
"
```

---

## 预防复发

1. **新增 watchlist 标的时**：确认是否需要同步到 positions（只有实际买入才进 positions）
2. **修改 prompt 时**：检查是否涉及"持仓"相关描述，确保区分说明完整
3. **空仓状态下**：AI 输出若提及具体股票操作，优先怀疑是观察池标的被误认为持仓

---

## 相关文件

- `src/qing_investment/stock_monitor.py` — `format_analysis_context()`, `format_live_analysis_context()`
- `src/qing_investment/agent/prompts/system/cron_*.txt` — 9个 cron prompt
- `config/stock_monitor/positions.yaml` — 持仓配置（当前空仓）
- `config/stock_monitor/watchlist.yaml` — 观察池配置
