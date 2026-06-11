# Cron Prompt 数据流 4 层架构模式

> 场景：向 Hermes stock monitor 添加新功能或数据字段时，确保数据从底层计算到达 LLM prompt
> 案例：Phase 1-5 of 个股深度分析（昨日摘要→竞价快照→持仓成本→板块梯队→Prompt重写）

---

## 架构总览

```
Layer 1: _agent_context_data()       — 计算衍生字段
Layer 2: format_agent_analysis_context() — 格式化到 text context
Layer 3: format_agent_json_context()   — 格式化到 JSON context
Layer 4: cron_*.txt 文件              — 告诉 LLM 如何使用这些字段
```

**关键洞察**：Layer 1-3 注入数据，Layer 4 让数据产生价值。只有 Layer 4 改好了，前面的数据层才不会白做。

---

## 每层的职责

### Layer 1: `_agent_context_data()`

计算字段并注入 `enriched_positions` 或返回 dict 顶层。

**示例**：Phase 6.2 — position_type 计算

```python
# 在 sector_tier 注入之后、龙虎榜之前添加
_ys_for_ptype = _load_yesterday_summary(config_dir=config.config_dir)
yesterday_positions = (_ys_for_ptype or {}).get("positions", {})
for pos in enriched_positions:
    code = _pure_stock_code(str(pos.get("code", "")))
    yp = yesterday_positions.get(code, {})
    is_limit_up = yp.get("is_limit_up", False) or pos.get("pct_change", 0) >= 9.0
    unrealized = pos.get("unrealized_pct", 0) or 0
    board_quality = yp.get("board_quality", "")
    amplitude = yp.get("amplitude", 0) or 0

    if is_limit_up and (board_quality == "weak" or amplitude > 6.0):
        pos["position_type"] = "weak_board"
    elif is_limit_up:
        pos["position_type"] = "limit_up"
    elif unrealized < -5:
        pos["position_type"] = "floating_loss"
    else:
        pos["position_type"] = "trend"
```

**常见陷阱**：
- 用到 `_load_yesterday_summary()` 等外部数据的，必须在循环前显式 load，不要等 return dict 最后才调用
- 函数中间需要的数据就地在需要处 load，不依赖 return dict 的惰性求值

### Layer 2: `format_agent_analysis_context()`

将 Layer 1 返回的 dict 中的字段转为可读文本。

输出示例：
```
=== 持仓成本 ===
- 002409: [weak_board] 成本23.5 浮盈12% 保护线24.68 T2/板块7.9%
```

**原则**：
- 文本输出应自包含（LLM 不需要再跳转到 JSON 中查找）
- 使用符号标记（如 `[weak_board]`）让 LLM 一目了然
- 若数据不存在（如竞价快照只在 09:20-09:30），该段直接跳过不输出

### Layer 3: `format_agent_json_context()`

将 Layer 1 的数据序列化为 JSON（供 Qing-Agent HTTP API 消费）。通常只是 `json.dumps(data)` 加上 quote 截断。只要 Layer 1 的 return dict 包含了新字段，JSON context 自动继承。

### Layer 4: cron\_\*.txt 文件

9 个文件对应 9 个时间节点。每个文件告诉 LLM：
- 当前节点的时间特征
- 需要回答哪些问题
- **哪些上下文中的字段应该被使用**
- 输出格式（JSON schema）
- 强制输出 `daily_state` 代码块

**Phase 5 的关键改进**：让 prompt 显式引用上下文中的数据字段。

**示例**：14:52 尾盘 prompt 引用 position_type
```
烂板票特殊处理：若某持仓是 weak_board 类型，需回顾龙虎榜席位...
```

---

## 添加新功能的完整流程

### 步骤 1: Layer 1 — 在 `_agent_context_data()` 中计算

```python
new_field_data = _compute_new_field(config, ...)
for pos in enriched_positions:
    code = ...
    if code in new_field_data:
        pos["new_field"] = new_field_data[code]
```

**验证**：import 不报错

### 步骤 2: Layer 2 — 在文本上下文中展示

```python
if data.get("new_field_parent"):
    lines.extend(["", "=== 新字段标题 ==="])
    lines.append(f"- 字段值: {data['new_field_parent']}")
```

**验证**：python 字符串检查关键词

### 步骤 3: Layer 4 — 更新相关 prompt

在 prompt 中增加引用：
```
【新增】现在的上下文中有「xxx」字段，结合它做以下判断：
- 如果 xxx，则 YYY
- 如果 yyy，则 ZZZ
```

**验证**：prompt 文件加载检查（语法正确 + daily_state 输出块完整）

---

## Phase 5 的 Prompt 字段引用矩阵

| 字段 | 来源 Layer 1 | 首次引入的 Prompt | Prompt 引用方式 |
|------|-------------|-------------------|----------------|
| `tomorrow_scenarios` | `_load_yesterday_summary()` | cron_opening.txt | 剧本验证：对比竞价 vs 明日剧本 |
| `position_type` | `_agent_context_data()` 循环内 | cron_open_confirm.txt | 持仓类型分支：连板/烂板/趋势/浮亏 |
| `avg_cost` + `unrealized_pct` | `_agent_context_data()` 循环内 | cron_open_confirm.txt | 同样-3%浮盈15%和浮亏8%操作不同 |
| `sector_tier` | `_build_sector_tiers()` | cron_open_confirm.txt | 对比同板块龙一/龙二 |
| `cost_protection_line` | `_agent_context_data()` 循环内 | cron_afternoon_risk.txt | 保护线触发检查 |
| `dragon_tiger_*` | `_fetch_dragon_tiger_data()` | cron_tail_condition.txt | 烂板票回顾龙虎榜席位 |
| `scenario_validation` | prompt 输出字段 | cron_opening.txt | 输出 JSON 中的验证结果 |

---

## 验证清单

- [ ] Layer 1 import 无报错
- [ ] Layer 2 文本输出包含新字段关键词
- [ ] Layer 4 所有相关 prompt 文件语法正确、含 daily_state 输出块
- [ ] `pytest tests/test_stock_monitor.py -x -q` 全部通过
- [ ] 无 `except Exception: pass` 吞异常

---

## 常见陷阱

### 陷阱 1: Layer 4 引用了 Layer 1 还没实现的数据

**反面案例（2026-06-11）**：Phase 5.2 prompt 要求 LLM 使用 `position_type` 做分支判断，但 `_agent_context_data()` 还没有计算这个字段。

**根因**：Phase 5 (prompt) 依赖 Phase 6.2 (position_type)，但任务清单照顺序做，没有提前完成跨阶段依赖。

**教训**：写 prompt 前先确认它引用的数据字段已经存在于 text context 中。有依赖就提前实现依赖（跨阶段也无妨）。

### 陷阱 2: 只在 return dict 中 load，不在循环前 load

**反面案例（2026-06-11）**：在 `_agent_context_data()` 的 return dict 中有 `_load_yesterday_summary(...)`，但 position_type 计算在 return dict 之前需要这个数据。

**正确做法**：任何函数中间需要的 `_load_*` 数据，在第一个需要的地方显式 load。

### 陷阱 3: 输出模板存在于两个地方（format_agent_analysis_context + format_daily_review_context）

**反面案例（2026-06-11 Phase 6.3）**：修改 `format_agent_analysis_context()` 底部的输出格式模板（合并【盘面】+【全A锚】，拆分【持仓池】→【重点分析】+【其他持仓】），但 `format_daily_review_context()` 中有一个独立的、用途不同的模板，结构类似但字段不同。第一次 patch 只改了一处，导致 daily review 输出格式不统一。

**根因**：
- `format_agent_analysis_context()` 的模板在 `stock_monitor.py` ~2904 行（供 9 个 cron 节点使用）
- `format_daily_review_context()` 的模板在 ~3870 行（供 17:00 收盘复盘使用）
- 两个模板都是 `lines.extend([...])` 中的固定字符串列表，没有共享代码

**正确做法**：
- 修改输出模板时，全局搜索 `format_daily_review_context` + 确认它的模板也同步修改
- 两个模板的 section 结构应当一致（【盘面】→【重点分析】→【其他持仓】→【观察池】→【脚注/参考来源】）
- daily review 可以在描述上更精简（没有分支指令），但 section 顺序不应有歧义

**修复方法（2026-06-11）**：
1. 先更新 `format_agent_analysis_context()` 模板（主要修改）
2. 然后搜索 `format_daily_review_context` 找到第二个模板
3. 按相同的 section 结构调整第二个模板（保留尾部差异如【脚注】）
4. 更新测试断言（见陷阱 4）
5. `pytest tests/test_stock_monitor.py -x -q` 全部通过

### 陷阱 4: 模板字符串更改后测试断言过时

**反面案例（2026-06-11 Phase 6.3）**：合并【盘面】+【全A锚】后，`test_agent_analysis_context_contains_trigger_alerts_and_quotes` 测试断言 `assert "每只触发/重点持仓必须单独一行" in message` 失败，因为该字符串已被移除。

**根因**：测试硬编码了旧模板中的特定字符串。模板更新后测试未同步更新。

**正确做法**：
- 修改 template 字符串时，在项目内搜索该字符串：`search_files(pattern="旧字符串", path="tests/")`
- 更新测试断言以匹配新模板内容
- 测试应该断言「新模板的特征性内容」而非「旧模板的残留」

**验证命令**：
```bash
# 修改模板前，记录有哪些测试可能受影响
grep -r "旧模板关键词" tests/

# 修改模板后，验证所有测试
pytest tests/test_stock_monitor.py -x -q
```

**教训**：不要断言模板中的「句式细节」（如"每只触发/重点持仓必须单独一行"），而要断言「section 存在性和期望的结构特征」（如"【重点分析】"和"【其他持仓】"同时出现）。结构断言对模板改动的容忍度更高。
