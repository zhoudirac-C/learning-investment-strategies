# daily_state 链路断裂根因分析

> 日期：2026-06-10
> 场景：用户询问"代码和定时任务是否写入了 daily_state.json，是否保证观点上下文"
> 结论：**链路断裂，daily_state.json 从未被创建**

---

## 现象

```bash
ls -la ~/learning-investment-strategies/config/stock_monitor/daily_state.json
# ❌ 不存在
```

`sync_daily_state.py` 已存在（250 行）且已注册为 cron job（`0a62d01fbd45`，每 5 分钟），但 `daily_state.json` 从未生成。

---

## 根因链（四层断裂）

### 第一层：Qing-Agent 服务未启动

```bash
ss -tlnp | grep 8000
# Port 8000 not listening
```

Qing-Agent 进程不存在，8000 端口无监听。

### 第二层：cron 走 fallback 路径

`hermes_stock_monitor_agent.py` → `call_qing_agent()` → 连接被拒绝 → 走 fallback → 打印 `stock_monitor.py` 的文本上下文。

Cron 输出文件里**没有** `[Qing-Agent ✓]` 标记，全部是 fallback 文本。

### 第三层：fallback 文本不含 daily_state 代码块

Hermes cron 的 prompt 字段直接让 LLM 生成微信提醒，prompt 里没有 `daily_state` 输出要求。

LLM 输出示例（09:32 cron）：
```
【盘面】上证低开...
【持仓池】...
【观察池】...
【关键信号】...
```

**没有 ```daily_state 代码块。**

### 第四层：sync_daily_state.py 扫描不到代码块

```bash
python3 scripts/sync_daily_state.py --dry-run
# 输出："未找到 daily_state 代码块"（9 个 job 全部）
```

---

## 即使 Qing-Agent 启动后，仍有第二层断裂

假设 Qing-Agent 启动并正常响应：

```
market_analyst 节点
  → LLM 输出 JSON + ```daily_state 代码块
  → 但 market_analyst 节点只解析 JSON 部分作为 market_context
  → ```daily_state 代码块被丢弃

synthesize 节点
  → 从 market_context 拼草稿
  → 没有 daily_state 字段

style_writer 节点
  → 重写为 UP 风格文本
  → final_output 不含代码块

reviewer 节点
  → 返回 final_output
  → hermes_stock_monitor_agent.py 打印 final_output
  → 仍然没有 ```daily_state
```

**Qing-Agent 内部没有任何节点调用 `save_daily_state()`。**

---

## 修复方案（二选一）

### 方案 A：Qing-Agent 内部闭环（推荐）

修改 `src/qing_investment/agent/graph/nodes.py`：

1. 在 `market_analyst` 节点，LLM 返回后，用正则提取 ```daily_state 代码块
2. 调用 `daily_state.save_daily_state()` 直接写入
3. 或在 `synthesize`/`style_writer` 之后、`reviewer` 之前加 `persist_daily_state` 节点

优点：一次调用完成，不依赖 cron 输出格式。  
缺点：需要改 graph 结构。

### 方案 B：Hermes 层闭环

1. 在 9 个看盘 cron 的 prompt 字段末尾加入 ```daily_state 输出要求
2. 修改 `hermes_stock_monitor_agent.py` 的 fallback 路径，也提取并保存 daily_state
3. 确保 `sync_daily_state.py` 能解析到

优点：不动 Qing-Agent graph。  
缺点：依赖 LLM 遵守 prompt，且需要改 9 个 cron prompt。

---

## 验证清单（修复后）

```bash
# 1. Qing-Agent 服务启动
curl -s --max-time 30 -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"测试","session_id":"test","analysis_type":"market"}' \
  | grep -c "daily_state"
# 期望：>=1（final_output 包含 daily_state）

# 2. daily_state.json 生成
ls -la ~/learning-investment-strategies/config/stock_monitor/daily_state.json
# 期望：文件存在

# 3. sync_daily_state.py 能解析
python3 scripts/sync_daily_state.py --dry-run
# 期望："已合并 daily_state" 而非 "未找到"

# 4. 跨节点连续性
# 09:26 cron 输出中的 core_assumption 能在 09:45 cron 的 daily_state 加载中看到
cat config/stock_monitor/daily_state.json | jq '.intraday_narrative | length'
# 期望：>0（有 narrative 记录）
```

---

## 相关文件

| 文件 | 作用 |
|------|------|
| `scripts/sync_daily_state.py` | 扫描器（已存在，已注册 cron） |
| `src/qing_investment/agent/tools/daily_state.py` | load/save/archive 工具函数 |
| `src/qing_investment/agent/prompts/system/market_analyst.txt` | 含 daily_state 输出要求（第 162-177 行） |
| `src/qing_investment/agent/graph/nodes.py` | **缺 daily_state 提取/保存逻辑** |
| `src/qing_investment/agent/graph/state.py` | AgentState 定义 |
| `src/qing_investment/stock_monitor.py` | 注入 daily_state 到 prompt |
