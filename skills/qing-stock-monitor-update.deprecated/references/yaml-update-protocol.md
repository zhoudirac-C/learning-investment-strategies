# YAML 更新协议

> 规范更新 watchlist.yaml、strategy_pack.yaml、positions.yaml 的流程和纪律。

---

## 核心纪律

### 1. 观察池追加原则（用户硬性要求）

- **新 theme 追加到末尾**，不替换现有 themes。
- **旧 theme 保留**，除非用户明确说"删除/移除/替换 XXX"。
- 新 stock 在 theme 内追加，不删除同 theme 旧 stock。

### 2. 持仓更新原则

- `positions.yaml` 是隐私文件（gitignored），更新时只修改字段，不暴露敏感信息。
- `today_plan` 字段每次更新时重置，旧计划移入 `notes` 或历史记录。
  > ⚠️ 此为 Skill 层面的手动纪律规则，代码不会自动执行此重置。Agent 更新 positions.yaml 时必须手动清空旧 today_plan 并重写。

### 3. 字段兼容性

- 新增描述型字段不影响 stock_monitor.py 解析。
- 所有字段使用 snake_case。
- 价格区间统一格式：`"X.XX-X.XX"` 或 `"X.XX"`。

---

## 更新流程

```
Step 1: 拉取最新数据
  └─ 运行 fetch_stock_data.py 获取实时行情

Step 2: 检查 UP 最新观点
  └─ 读取最近 3 天的 claims/wiki/raw
  └─ 更新 up_mention_status 字段

Step 3: 更新 watchlist.yaml
  ├─ 新 theme → 追加到末尾
  ├─ 新 stock → 在对应 theme 内追加
  ├─ 更新 technical_narrative / sector_narrative
  └─ 更新 buy_setup / invalidation_setup（如有新观点）

Step 4: 更新 strategy_pack.yaml
  ├─ 更新 today_snapshot（市场环境）
  ├─ 更新 market_framework.current_stage（如周期变化）
  ├─ 更新 index_rules（如关键位变化）
  ├─ 更新 quant_entry_strategy（基于收盘数据）
  └─ 更新 sector_groups（如新增板块）

Step 5: 更新 positions.yaml
  ├─ 更新 latest_monitor_reference（最新行情）
  ├─ 更新 pnl（盈亏）
  ├─ 重置 today_plan（基于 UP 观点或技术推断）
  └─ 如 UP 明确操作，更新 strategy / reduce_zone / risk_line

Step 6: 验证
  └─ 运行 stock_monitor.py --status 确认无 YAML 解析错误
  └─ 运行 stock_monitor.py --analysis-context 确认输出正常

Step 7: Git 提交
  └─ git add config/stock_monitor/watchlist.yaml config/stock_monitor/strategy_pack.yaml
  └─ git commit -m "monitor: update watchlist/strategy for YYYY-MM-DD"
  └─ positions.yaml 不提交（已 gitignored）
```

---

## 无 UP 观点时的技术推断规则

### 观察池标的（无 UP 明确买点）

1. 读取 `technical_narrative` 和 `sector_narrative`
2. 结合 `framework/technical-analysis-framework.md` 中的规则
3. 推断合理买点，写入 `buy_setup`（追加，不覆盖原有）
4. 必须同时写入 `inference_note` 标注推断依据

### 持仓标的（无 UP 明确操作）

1. 检查 `latest_monitor_reference` 当前价格 vs `cost` / `risk_line` / `reduce_zone`
2. 结合技术形态判断：持有 / 做T / 减仓观察 / 风控观察
3. 更新 `today_plan`，必须包含：
   - 动作（持有/做T/减仓/清仓）
   - 触发条件
   - 证伪条件
   - 推断标注（如非 UP 原话）

---

## 常见错误

- ❌ 直接替换整个 themes 列表 → 丢失历史观察锚
- ❌ 删除旧 theme 的 stocks 只保留新的 → 违反 append-only
- ❌ 不标注推断来源 → 大模型可能误以为是 UP 原话
- ❌ 更新 positions.yaml 后忘记重置 today_plan → 旧计划误导
- ✅ 新 theme 追加，旧 theme 保留
- ✅ 推断必须写 inference_note
- ✅ 每次更新后验证 YAML 格式
