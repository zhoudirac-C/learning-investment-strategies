# 幻觉防御层架构文档

> 版本: 2026-06-11
> 对应 Commit: `8006274` (Fix A/B/C 同步提交)
> 触发: 尾盘条件单输出 2025 年旧数据，识破 LLM 价格幻觉

---

## 1. 概述

Qing-Agent 使用 LLM 生成投资分析和操作建议。LLM 固有的幻觉倾向可能导致：

| 幻觉类型 | 示例 | 根因 |
|---------|------|------|
| **时间幻觉** | 引用 2025 年季报/目标价，当前已 2026 年 | LLM 训练数据截止日期 |
| **价格幻觉** | 从记忆中调取旧价格，不是实时行情 | LLM 记忆 vs 实时数据冲突 |
| **事实幻觉** | 编造行业排名、龙头地位 | LLM 生成事实而非检索事实 |
| **推理幻觉** | 基于错误前提推导出看似合理的结论 | 逻辑链断裂 |

**防御原则**：不在 LLM 层堵死所有幻觉（不可能），而在 Hermes 集成层和输入层建立多层拦截，让幻觉即使产生也无法到达用户。

---

## 2. 三层防御架构

```
LLM (Qing-Agent) 输出
        │
        ▼
┌─────────────────────────────────────┐
│  Fix A: 输出侧拦截                   │
│  hermes_stock_monitor_agent.py      │
│  年份 regex → HALLUCINATION → fallback │
└─────────────────────────────────────┘
        │ 通过
        ▼
┌─────────────────────────────────────┐
│  Fix B: 输入侧注入                   │
│  stock_monitor.py _agent_context_data│
│  watchlist/positions 带实时 latest/  │
│  pct_change（从 API 读，不写 YAML）  │
└─────────────────────────────────────┘
        │ 通过
        ▼
┌─────────────────────────────────────┐
│  Fix C: Prompt 约束                  │
│  format_agent_analysis_context()    │
│  + format_live_analysis_context()   │
│  "实时行情快照优先于config参考价"     │
└─────────────────────────────────────┘
        │
        ▼
   微信推送
```

---

## 3. 每层详解

### 3.1 Fix A: 输出侧拦截（Hermes Wrapper）

**代码位置**：`scripts/hermes_stock_monitor_agent.py`

**原理**：Hermes cron 入口 `hermes_stock_monitor_agent.py` 读取 Qing-Agent 的 `final_output`，在推送到微信前做一次正则检测：

```python
# 简化的检测逻辑
HALLUCINATION_PATTERNS = [
    r"2025",       # 当前 2026 年 → 任何 2025 年引用都是幻觉
]

if re.search(r"2025", final_output):
    logger.warning("[HALLUCINATION] Qing-Agent output contains 2025 year reference")
    # 不走 Qing-Agent 输出 → 走 fallback
    fallback_to_raw_llm(agent_context_json)
```

**Fallback 路径**：不走 Qing-Agent，直接调用本地 LLM（同个模型的 prompt-only 版本），注入：

- 实时行情快照（最新报价）
- 数据优先级提示（Fix C）
- 带 `latest/pct_change` 的位置和观察池（Fix B）

**效果**：拦截了 2025 年季报、2025 年目标价、2025 年历史价格等时间幻觉。首次触发在 2026-06-10 尾盘条件单。

**局限性**：
- 只检测年份幻觉（`2025`），不检测其他类型
- 是黑名单策略（已知 pattern），不是白名单验证（验证每个数据点）
- Fallback 路径的 LLM 输出质量可能低于 Qing-Agent 的完整 LangGraph 分析

### 3.2 Fix B: 输入侧注入（Real-Time Quote Injection）

**代码位置**：`src/qing_investment/stock_monitor.py` → `_agent_context_data()`

**改动**：在构造 JSON 上下文时，watchlist 的每一行新增 `latest` 和 `pct_change` 字段：

```python
# line 1437-1440
"latest": _to_float((_quote_for_stock(quotes_by_code, row.get("code", "")) or {}).get("latest")),
"pct_change": _to_float((_quote_for_stock(quotes_by_code, row.get("code", "")) or {}).get("pct_change")),
```

**数据流**：

```
API 实时行情 (quotes_by_code)
    │
    ├── positions → 已有 latest/pct_change（更早实现）
    └── watchlist → 新增 latest/pct_change（Fix B）
```

**关键设计**：
- 不写入 `watchlist.yaml`（YAML 保持纯 config 存根）
- 只在内存中拼接 JSON 返回
- 数据来源：同 positions 使用的 `_quote_for_stock()`，从东财 API 实时获取

**效果**：LLM 不再需要从记忆中回忆价格。优先级关系：`latest: 139.xx`（API 实时）> `current_ref: 127.22`（config 旧价）。

### 3.3 Fix C: Prompt 约束（Data Priority）

**代码位置**：`src/qing_investment/stock_monitor.py`
- `format_agent_analysis_context()` — Hermes agent 调用路径
- `format_live_analysis_context()` — Qing-Agent 不可达时的文本 fallback 路径

**改动**：两处均插入：

```
【⚠️ 数据优先级】实时行情快照（上方的实际价格和涨跌幅）
优先于下方 config 配置文件中的参考价。如果实时行情快照中
有标的的最新价/涨跌幅，请以实时行情为准，不要用配置文件
中的陈旧参考价(current_ref)。
```

**原理**：LLM 的注意力机制对 prompt 开头和结尾的内容最为敏感。将该提示放在关键数据段前后，强制 LLM 在面对价格冲突时选择 API 实时数据而非训练数据记忆或 config 旧值。

**效果**：即使 Fix B 提供了实时价，LLM 仍可能忽略它（注意力漂移）。Fix C 通过显式指令确保优先级语义被 LLM 遵循。

---

## 4. 与 Qing-Agent 架构中 Reviewer 的关系

Qing-Agent 的 `reviewer` 节点（§3.7）负责：

- 禁用词检测（"无条件买入"、"一定涨"）
- Claims 引用验证（claim ID 是否在检索列表中）
- Citation 完整性检查（是否包含【参考来源】段落）

**reviewer 不做的事**：
- ❌ 不检查价格准确性
- ❌ 不检查数据时效性
- ❌ 不检查推理逻辑一致性
- ❌ 不交叉验证输出中的事实声明

**因此三者互补**：

| 层 | 位置 | 检查范围 | 发现异常时 |
|----|------|---------|-----------|
| Fix A | Hermes wrapper | 年份幻觉（2025） | 丢弃输出，走 fallback |
| Fix B+C | Hermes 上下文构造 | 价格准确性 | 提供实时数据+提示（无法强制执行） |
| Reviewer | Qing-Agent | 风格/引用合规 | 回 style_writer 重写（最多3次） |

**当前缺口**：缺少一个在 fix A 之后、推送之前的事实校验层——验证 LLM 输出的每个数据点是否在已提供的数据中有依据。

---

## 5. 业界对比

| 防御方法 | 业界玩家 | 我们的实现 | 差距 |
|---------|---------|-----------|------|
| **RAG（检索增强）** | 所有主流 | ✅ Neo4j + Qdrant + mem0 | — |
| **结构化上下文** | 通用做法 | ✅ Fix B（latest/pct_change 直接填 JSON） | — |
| **Prompt 显式约束** | OpenAI system prompt | ✅ Fix C（数据优先级指令） | — |
| **输出侧虚假数据检测** | Nvidia NeMo Guardrails、Google SynthID | ⚠️ Fix A（只检测年份） | 应扩展为通用事实校验 |
| **独立验证 LLM** | Anthropic Constitution AI、Self-Check | ❌ 未实现 | 需要第二个 LLM 交叉验证 |
| **数值范围校验** | 自定义规则 | ❌ 未实现 | 如检查涨停/跌停限制 |
| **代码执行验证** | OpenAI Code Interpreter | ❌ 未实现 | 复杂计算应写 Python 跑 |

---

## 6. 已知不足

1. **Fix A 只检测年份幻觉**（硬编码 `2025` 正则）。更通用的方案：提取 LLM 输出中的所有数字声明，与上下文中的已提供数据逐一对比。

2. **Fix B+C 依赖 LLM 遵守指令**。如果 LLM 忽略或注意力分散，仍可能输出错误价格。目前无强制机制。

3. **缺乏正向事实校验**。当前体系是反向防御（拦截已知错误模式），而非正向验证（输出的每项事实都找到依据）。

4. **Fix A fallback 路径未优化**。fallback 的 LLM 调用使用通用 prompt，没有 Qing-Agent 的差异化 cron prompt 和 reasoning pattern 注入。

---

## 7. 文件清单

| 文件 | 职责 |
|------|------|
| `scripts/hermes_stock_monitor_agent.py` | Fix A — 包装器检测年份幻觉，走 fallback |
| `src/qing_investment/stock_monitor.py` | Fix B — `_agent_context_data()` 注入实时价 |
| `src/qing_investment/stock_monitor.py` | Fix C — `format_agent_analysis_context()` 和 `format_live_analysis_context()` 添加优先级提示 |
| `docs/hallucination-defense-layers.md` | 本文档 |
| `docs/fix-stock-monitor-20250610.md` | 修复记录（trap 32） |

---

## 8. 附录：防御测试基准

| 测试场景 | 修复前 | 修复后 | 防御层 |
|---------|--------|--------|--------|
| LLM 输出 2025 年季报数据 | 直接推送错误数据 | 拦截 + fallback | Fix A |
| LLM 使用记忆中旧价格 (127.22) | 输出旧价 | 优先使用 latest: 139.xx | Fix B+C |
| LLM 编造涨幅 (0.5% 实际 7.5%) | 输出错误涨幅 | 使用 API pct_change | Fix B+C |
| LLM 编造行业事实 | 直接推送 | 无防御（已知缺口） | 所有层 |
| LLM 搞混标的代码 | 直接推送 | 无防御（已知缺口） | 所有层 |
