# Stock Monitor 修复记录 — 2025-06-10

> 基于 cron job 报告问题（job_id: 41c8e6da0e65）的修复

---

## 问题清单

| # | 问题 | 严重度 | 根因 |
|---|------|--------|------|
| 1 | 数据源限流：东财 API 对服务器 IP 严格限流，导致行情获取失败 | 🔴 高 | 单数据源，无降级 |
| 2 | 持仓幻觉：AI 将观察池标的当作持仓分析 | 🟡 中 | prompt 未明确区分 positions vs watchlist |
| 3 | daily_state.json 不存在 | 🟡 中 | 有代码未集成，非本次修复范围 |

---

## 修复 1：数据源降级（已完成 ✅）

### 修改文件
- `src/qing_investment/stock_monitor.py`

### 变更内容

#### 1.1 新增 `fetch_sina_quotes()` 函数
- 新浪财经备用接口：`https://hq.sinajs.cn/list=sh600519,sz000001`
- 支持批量查询（chunk_size=80）
- 解析格式：`var hq_str_sh600519="贵州茅台,1740.00,...";`

#### 1.2 重写 `fetch_quotes_with_fallback()` 降级逻辑

**旧逻辑（问题）：**
```
东财优先 → 腾讯回退
- 东财 0 quotes + errors 时，不会触发降级
- 腾讯即使能返回数据也被跳过
```

**新逻辑（修复）：**
```
腾讯优先 → 新浪备用 → 东财兜底 → 合并兜底
1. 腾讯(gtimg): 最稳定，对服务器IP友好
   - 成功条件：返回 ≥80% 标的 且 无错误
2. 新浪(hq.sinajs.cn): 备用
   - 成功条件：返回数据且 无错误
   - 若腾讯已返回部分数据，合并补充
3. 东财(push2.eastmoney.com): 数据最全但限流严格
   - 最后尝试
4. 兜底：合并所有可用数据源的数据 + 汇总错误信息
5. 完全失败：返回 all_failed + 详细错误
```

#### 1.3 新增 `_merge_quotes()` 辅助函数
- 合并两个 quote 列表，以 base 为主，extra 补充缺失的 secid

### 测试验证

```bash
# 测试1: 正常场景（腾讯优先）
184 个标的 → 数据源: tencent_gtimg, 返回: 184/184, 耗时: 156ms ✅

# 测试2: 新浪接口
3 个标的 → 数据源: sina_hq, 返回: 3/3 ✅

# 测试3: 东财失败场景（模拟）
184 个标的 + 东财限流 → 腾讯返回 162/184 ✅
```

---

## 修复 2：持仓/观察池区分（已完成 ✅）

### 修改文件
1. `src/qing_investment/stock_monitor.py`
2. `src/qing_investment/agent/prompts/system/cron_*.txt` (9个文件)

### 变更内容

#### 2.1 `format_analysis_context()` — 明确标注持仓状态

**旧格式：**
```
持仓：
- ...（可能为空，但无明确标注）

观察池：
- ...
```

**新格式：**
```
=== 持仓池（positions.yaml）===
状态：【空仓】当前无持仓

重要区分：
- 持仓池 = 你当前实际持有的股票（来自 positions.yaml）
- 观察池 = 你关注但尚未买入的股票（来自 watchlist.yaml）
- 严禁将观察池标的当作持仓分析！

持仓明细：
  （无持仓）

=== 观察池（watchlist.yaml）===
这些标的尚未买入，仅作观察：
- ...
```

#### 2.2 `format_live_analysis_context()` — 注入持仓状态提醒

在输出模板前增加：
```
【重要】当前持仓状态：空仓
【重要】观察池标的 ≠ 持仓，严禁混淆！
```

#### 2.3 所有 cron prompt 增加区分说明

在每个 prompt 文件开头插入：
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

### 测试验证

```bash
# 验证 context 输出
>>> format_analysis_context(config, now)
=== 持仓池（positions.yaml）===
状态：【空仓】当前无持仓
...
=== 观察池（watchlist.yaml）===
这些标的尚未买入，仅作观察：
```

---

## 问题 3：daily_state.json（未修复 ⚠️）

### 现状
- 代码已写：`src/qing_investment/agent/tools/daily_state.py`
- 设计路径：`config/stock_monitor/daily_state.json`
- **但**：`stock_monitor.py` 未调用 daily_state 模块
- **且**：cron prompt 虽有 daily_state 输出格式说明，但无解析保存逻辑

### 影响
- 各 cron 节点间无观点连续性
- 无法追踪全天观点演进

### 建议修复（需单独 PR）
1. `stock_monitor.py` 集成 `daily_state.load/save`
2. 添加 `sync_daily_state.py` 解析 AI 输出的 ```daily_state 代码块
3. 在 `format_agent_analysis_context()` 中注入 `get_state_summary()`

---

## 提交记录

```bash
git add src/qing_investment/stock_monitor.py
git add src/qing_investment/agent/prompts/system/cron_*.txt
git add docs/fix-stock-monitor-20250610.md
git commit -m "fix(stock-monitor): 多数据源降级 + 持仓观察池区分

- 数据源: 腾讯优先→新浪备用→东财兜底，解决东财IP限流
- 新增 fetch_sina_quotes() 和 _merge_quotes()
- 重写 fetch_quotes_with_fallback() 降级逻辑
- 持仓/观察池: context 明确标注 + 9个cron prompt增加区分说明
- 防止AI将watchlist标的误认为持仓

Fixes: cron job 数据源失败 + 持仓幻觉问题"
```

---

## 验证清单

- [x] 修复1：腾讯接口返回 184/184 标的
- [x] 修复1：新浪接口返回 3/3 标的
- [x] 修复1：东财限流时降级到腾讯
- [x] 修复2：context 显示 "【空仓】当前无持仓"
- [x] 修复2：9个 cron prompt 包含区分说明
- [x] 修复2：live context 包含 "观察池标的 ≠ 持仓" 提醒
- [ ] 修复3：daily_state.json 集成（待后续）
