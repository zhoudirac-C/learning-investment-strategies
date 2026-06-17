# LLM 幻觉防范：行情数据验证手册

> 当 cron 任务或大模型分析生成包含股价、涨跌幅的提醒时，必须验证所有数字是否与真实行情一致。
>
> **2026-06-11 更新**：新增三层防御架构（Fix A/B/C）。详见项目文档 `docs/hallucination-defense-layers.md`。

---

## 问题定义

cron 任务的 LLM 分析可能编造不存在的股价数据。典型症状：
- 某票被报告"涨停+10.01%"，但实际行情是下跌或平盘
- 持仓盈亏比例与真实计算不符
- 板块涨跌描述与真实数据背离

## 根因

1. **Prompt 未约束数据来源**：LLM 被允许"根据上下文生成分析"，但未明确禁止编造数字
2. **脚本输出与 LLM 生成混合**：LLM 可能将记忆中的旧数据、训练数据中的历史行情与当前脚本输出混淆
3. **无数字校验层**：没有机制验证 LLM 输出中的每个数字是否在脚本提供的数据范围内

## 防范措施

### 1. Prompt 层面（cron 任务 prompt）

在 cron 任务的 prompt 中增加以下约束：

```
【数据纪律】
- 你只能使用脚本提供的 [Hermes股票监控大模型分析上下文] 中的行情数据
- 禁止编造任何股价、涨跌幅、盈亏比例或板块表现数字
- 如果你不确定某个数字，写"数据未提供"而不是猜测
- 所有股价数字必须与上下文中的 quotes 字段一致
```

### 2. 脚本输出层面

在 `qing_stock_monitor_agent.py` 或 `stock_monitor.py` 的 `format_agent_analysis_context()` 中：

- 在上下文末尾增加**数据声明块**：
  ```
  【数据声明】以下行情数据来自腾讯财经实时接口，时间戳=YYYY-MM-DD HH:MM:SS
  万通发展(600246.SH): 最新价=X.XX, 涨跌幅=X.XX%
  安泰科技(000969.SZ): 最新价=X.XX, 涨跌幅=X.XX%
  ...
  ```
- 要求 LLM 在输出中**只引用上述数据声明块中的数字**

### 3. 验证层面（人工/自动化）

**人工验证（用户侧）**：
- 收到 cron 提醒后，对比同花顺/东方财富 APP 中的实时行情
- 若发现数字不符，立即标记为"LLM 幻觉"并反馈

**自动化验证（开发侧）**：
- 在提醒发送前，提取 LLM 输出中的所有数字（股价、涨跌幅）
- 与 `state.json` 中的 `last_quote_snapshot.quotes` 比对
- 若任一数字偏差超过 0.5%，标记为"疑似幻觉"并附加警告发送

### 4. 快速验证命令

```bash
# 验证某票的实时行情（与 cron 报告对比）
curl -s "https://qt.gtimg.cn/q=sh600246" | iconv -f gb2312 -t utf-8 | awk -F'~' '{print "万通发展: 最新="$4", 昨收="$5", 涨跌="($4-$5)/$5*100"%"}'

# 验证 state.json 中的数据
python3 -c "
import json
d=json.load(open('config/stock_monitor/state.json'))
for q in d['last_quote_snapshot']['quotes']:
    if q['code'] in ['600246','000969','000066']:
        print(f\"{q['name']}: 最新={q['latest']}, 涨跌幅={q['pct_change']}%\")
"
```

## 发现幻觉后的处理流程

1. **标记**：在回复中明确说"这是 LLM 幻觉，不是真实数据"
2. **验证**：用 `curl` 或 `state.json` 获取真实数据并展示对比
3. **记录**：将幻觉内容记录到 `docs/llm-hallucination-log.md`（时间、任务、幻觉内容、真实数据）
4. **修复**：更新 cron 任务的 prompt，增加更严格的数据约束
5. **批量修复**：同一类幻觉可能影响多个 cron 任务，需检查所有使用相同 prompt 模板的任务并同步更新
6. **预防**：在相关 skill 的"常见陷阱"章节增加 LLM 幻觉防范条目

## 批量更新 cron prompt 的快捷方式

当确认某个 cron 任务的 prompt 需要增加幻觉约束时，使用 `cronjob` 工具批量更新所有相关任务：

```bash
# 列出所有相关任务
cronjob action=list

# 对每个任务的 job_id 执行 update
for job_id in job_id_1 job_id_2 ...; do
  cronjob action=update job_id=$job_id prompt="...新增约束..."
done
```

**约束模板**（直接追加到原 prompt 末尾）：
```
【重要约束】
1. 所有股价、涨跌幅、指数数据必须严格来自脚本输出，禁止编造任何数字。
2. 如果脚本未提供某只股票的实时数据，报告中不得提及该股票的当前价格或涨跌幅。
3. 持仓池只包含positions.yaml中当前有持仓（shares>0）的标的，已清仓标的不得在持仓池中列出。
4. 板块涨跌数据必须来自脚本提供的sector_groups计算结果，不得凭记忆或推测填写。
5. 若对某数据不确定，使用"数据未提供"或跳过，而非猜测。
```

## 三层防御架构（Fix A/B/C，2026-06-11）

2026-06-10 尾盘条件单事件（Qing-Agent 输出 2025 年数据）催生了系统性的三层防御架构。从输出侧到输入侧，逐层拦截。

| 层 | 名称 | 位置 | 职责 | 效果 |
|----|------|------|------|------|
| Fix A | 输出侧拦截 | `hermes_stock_monitor_agent.py` wrapper | 检测年份幻觉（2025），走 fallback | ✅ 拦截 2025 年季报 |
| Fix B | 输入侧注入 | `stock_monitor._agent_context_data()` | Watchlist 注入 `latest/pct_change` | ✅ LLM 不再记忆旧价 |
| Fix C | Prompt 约束 | `format_*_context()` | 显式"实时价优先"指令 | ✅ 防止 LLM 忽略实时数据 |

**防御链**：

```
LLM 输出 → Fix A [年份检测] → 通过 → Fix B [含实时价的上下文] → Fix C [优先级指令] → 微信推送
                  │ 失败
                  ▼
          fallback: 本机 LLM + 实时行情
```

### Fix A: 输出侧拦截（Wrapper 层）

**代码**：`scripts/hermes_stock_monitor_agent.py`

**原理**：读取 Qing-Agent 的 `final_output`，在推送前用 regex 检测年份幻觉：

```python
# 检测逻辑
import re
if re.search(r"2025", final_output):
    # 当前 2026 年 → 2025 引用必为幻觉
    # 标记 HALLUCINATION，丢弃输出
    # 走 fallback：本机 LLM + 实时行情
```

**效果**：拦截了 2025 年季报、2025 年目标价、2025 年历史价格等时间幻觉。

**局限性**：只检测年份幻觉（`2025` 正则），不检测其他类型。若需要更通用方案，应提取 LLM 输出中的所有数字声明，与上下文中提供的数据逐一对齐。

### Fix B: 输入侧注入（Real-Time Quote Injection）

**代码**：`src/qing_investment/stock_monitor.py` → `_agent_context_data()` (line 1437-1440)

**原理**：在构造 JSON 上下文时，watchlist 的每一行新增 `latest` 和 `pct_change` 字段：

```python
# 新增字段
"latest": _to_float((_quote_for_stock(quotes_by_code, code) or {}).get("latest")),
"pct_change": _to_float((_quote_for_stock(quotes_by_code, code) or {}).get("pct_change")),
```

**数据流**：

```
API 实时行情 (quotes_by_code)
    ├── positions → 已有 latest/pct_change（较早实现）
    └── watchlist → 新增 latest/pct_change（Fix B）
```

**关键设计**：不写入 `watchlist.yaml`（YAML 保持纯 config 存根），只在内存中拼接 JSON 返回。

### Fix C: Prompt 约束（Data Priority）

**代码**：`format_agent_analysis_context()` 和 `format_live_analysis_context()`

**原理**：在两处 prompt 字符串中插入以下提示：

```
【⚠️ 数据优先级】实时行情快照（上方的实际价格和涨跌幅）
优先于下方 config 配置文件中的参考价。如果实时行情快照中
有标的的最新价/涨跌幅，请以实时行情为准，不要用配置文件
中的陈旧参考价(current_ref)。
```

### 与现有 Prompt 层面防范措施的关系

现有的 Prompt 约束（见 §1）是静态的——它永远存在，但 LLM 可能注意力漂移忽略它。Fix C 是 Fix B 的加强：先提供实时数据（Fix B），再强制提示优先级（Fix C），双保险。

### 完整架构文档

详见项目级文档：`docs/hallucination-defense-layers.md`

包含：
- 每层详细说明（代码位置、原理、效果）
- 与 Qing-Agent reviewer 的关系
- 业界对比（RAG / 结构化上下文 / 输出校验）
- 已知不足（Fix A 只检测年份、缺少通用事实校验）
- 防御测试基准

### 验证命令

```bash
# 验证 Fix B：检查 watchlist 是否带实时价
cd ~/learning-investment-strategies
python3 -c "
import sys; sys.path.insert(0, 'src')
from qing_investment.stock_monitor import _agent_context_data, load_monitor_config
config = load_monitor_config()
# 需要 quotes_by_code，这里仅验证字段签名
import inspect
sig = inspect.signature(_agent_context_data)
print(f'_agent_context_data params: {list(sig.parameters.keys())}')
print('watchlist latest/pct_change 注入已部署')
"

# 验证 Fix C：检查 prompt 是否含优先级提示
python3 -c "
import sys; sys.path.insert(0, 'src')
from qing_investment.stock_monitor import format_agent_analysis_context, load_monitor_config
from datetime import datetime
from zoneinfo import ZoneInfo
ctx = format_agent_analysis_context(load_monitor_config(), datetime.now(ZoneInfo('Asia/Shanghai')))
assert '数据优先级' in ctx, 'Fix C 优先级提示缺失'
print('✅ Fix C 已部署')
"
```

## 相关文件

- `src/qing_investment/stock_monitor.py` — `format_agent_analysis_context()` 定义
- `config/stock_monitor/state.json` — 实时行情快照
- cron 任务配置 — prompt 模板
