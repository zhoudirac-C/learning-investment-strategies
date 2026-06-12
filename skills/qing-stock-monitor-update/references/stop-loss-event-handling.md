# 止损/清仓事件处理流程

当用户报告某持仓触发止损条件单时，按以下流程更新全部 config。

## 触发信号

- 用户说「X触发止损条件单，已经清仓了」
- 用户说「X跌破了止损线」
- 用户说「X清仓了」
- positions.yaml 对应标的的 `stop_loss` 被行情跌破

## 第一步：确认止损执行数据

拉取当日 K 线确认止损触发的价格区间：

```python
import akshare as ak
df = ak.stock_zh_a_hist(symbol='000636', period='daily', start_date='YYYYMMDD', end_date='YYYYMMDD', adjust='qfq')
# 关注 open, low, high, close — 看最低价是否触发了止损
```

数据来源：akshare `stock_zh_a_hist`，腾讯 API 实时行情。

## 第二步：更新文件清单

### 1. positions.yaml（私有，.gitignore，不提交）

- **从 `positions` 移除**该标的整段（含 code/name/shares/cost/entered_at/direction/stop_loss/note）
- **添加到 `closed_positions`**，格式：
  ```yaml
  - code: 000636.SZ
    name: 风华高科
    shares: 0
    cost: 64.067
    closed_note: '6/12 触发60.9止损清仓，执行价约60.68-60.9，持有1天，亏损约3.3元/股(-5.1%)。MLCC方向未共振，止损纪律执行。'
  ```
- **更新 `cash_note`**：修改总仓位比例说明
- **更新 `strategy_summary`**：移除已清仓标的，更新核心观点
- **更新 `risk_reminder`**：移除该标的的止损线
- **更新 `today_key_signals`**：如有持仓状态描述，同步更新
- **更新 `portfolio_stats`**：`total_positions` 减1，`total_exposure_pct` 减去对应仓位
- **更新 `direction_concentration`**：移除该标的对应方向

### 2. watchlist.yaml（跟踪提交）

- **lifecycle**：`holding` → `stopped_out`
- **新增字段**：
  ```yaml
  lifecycle:
    stage: stopped_out
    entered_stage: '2026-06-11'
    stopped_out_at: '2026-06-12'
    stopped_note: 触发60.9止损清仓，亏损约330元(-5.1%)
  ```
- **priority**：从 P1/P2 降级到 **P3-观察**
- **entry_zone**：清除价格区间和 hard_stop，标记「已止损清仓」
  ```yaml
  entry_zone:
    description: 【已止损清仓】6/12触发60.9止损出局。保留观察，若板块放量走强+新高+全A中阳线可重新评估。
    current_ref: 2026-06-12 收盘=60.92(-5.26%) 止损执行
    method: 已止损，等待重新评估信号
    confirm_signal: 板块放量走强+全A放量中阳线+重新站稳MA5
    hard_stop: null
    position_ratio: 0（已清仓）
  ```
- **watch_reason**：追加止损执刑记录，说明是否保留作为板块锚点
- **core_operation**（该文件顶部）：更新总仓位表述，移除已清仓标的

### 3. strategy_pack.yaml（跟踪提交）

查找并更新所有引用该标的的文字：

| 区域 | 示例原文 | 改后 |
|------|---------|------|
| `market_framework.core_question` | 当前持有雅克科技+**风华高科** | 当前仅持有雅克科技 |
| `invalidation_conditions` | 雅克跌破123.2 / **风华跌破60.9** | 仅保留雅克止损 |
| `intraday_schedule` 09:15-09:30 | 观察持仓标的（雅克/**风华**）竞价 | 仅雅克 |
| `intraday_schedule` 09:30-10:00 | MLCC板块联动验证**风华方向** | MLCC板块联动方向变化（已清仓，观察替代标的如三环/洁美） |
| 方向/情景内提及 | 情景B标的列表含该标的 | 仅当该标的是情景锚点时保留，改持仓类引用为方向类 |

### 4. Cron prompt 文件（如存在独立的 prompt 文件）

- 检查 `prompts/system/cron_*.txt` 或 cron job 定义中的 `prompt` 字段
- Agent cron prompt 是创建时的快照，必须手动更新
- 用 `cronjob(action='list')` 查看所有 cron job 的 prompt 是否有旧持仓引用

**本系统的特殊情况**：cron prompt 已内嵌在 cron job 定义中（通过 `cronjob update` 同步），因此修改 `watchlist.yaml` 和 `strategy_pack.yaml` 后，Agent 在运行时会读取最新配置——无需额外更新 cron prompt 文件。

## 第三步：Git 提交

只提交跟踪的文件（watchlist.yaml, strategy_pack.yaml 等）：

```bash
git add config/stock_monitor/strategy_pack.yaml config/stock_monitor/watchlist.yaml
git commit -m "更新：X触发止损清仓

- watchlist.yaml: lifecycle→stopped_out, P1→P3保留观察锚点
- strategy_pack.yaml: 移除全部持仓引用，更新板块观察方式
- positions.yaml: (本地.gitignore) 移出持仓→转入已清仓

X 当日开盘价→最低价→收盘价，触发止损条件单
执行价约X，亏损约X%
原因：板块未共振/大盘破位/个股反转，止损纪律执行完毕

当前仅持Y，总仓位X%"
```

## 关键纪律

1. **positions.yaml 不提交** — 它在 `.gitignore` 中。用普通 `git add` 提交（不要 `-f`）
2. **保留板块锚点** — 即使清仓，如果该标的是板块核心情绪锚（如风华高科是 MLCC 方向代表），保留在 watchlist 中作为方向观察，但 lifecycle 标记为 `stopped_out`
3. **全链路检查** — 改完 watchlist 后必须检查 strategy_pack 中所有引用，不遗漏 intraday_schedule 内的观察点
4. **确认总仓位** — 仓位百分比从 `portfolio_stats.total_exposure_pct` 减去对应比例，更新所有出现总仓位的文本位置
5. **不删旧数据** — 清仓不删除 watchlist 中的标的，仅降级生命周期，保留历史关系
