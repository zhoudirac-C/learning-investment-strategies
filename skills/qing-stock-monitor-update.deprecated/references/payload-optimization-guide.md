# Payload 优化指南 — qing-stock-monitor-update

> 当 Qing-Agent 调用 timeout 或 payload 过大时，参考本指南诊断和优化 `_agent_context_data()` 的 JSON 输出。

---

## 问题诊断

Qing-Agent timeout 可能有三个原因：

| 原因 | 排查方法 | 解决 |
|------|---------|------|
| **Payload 过大** | `len(json.dumps(data)) > 100KB` | 精简 watchlist / 截断文本 |
| **Qdrant 并发锁** | 日志出现 `Storage folder .qdrant_data is already accessed` | 重启 Qing-Agent 或改用 Qdrant server 模式 |
| **LLM 管线慢** | `/health` 通过但 `/analyze/trigger` 超时 | 增加 timeout（120→180s） |

**重要**：先检查日志确认根因，不要假设是 payload 问题。2026-06-10 的实际案例显示 timeout 根因是 Qdrant 锁冲突，而非 payload 大小。

---

## Payload 构成分析（2026-06-10 实测）

| 部分 | 大小 | 占比 | 说明 |
|------|------|------|------|
| **watchlist** | 58.7 KB | 73% | 180 条观察标的，每条 484 字节 |
| quote_snapshot | 10.2 KB | 13% | 40 条行情 |
| external_sector_boards | 6.0 KB | 8% | 东方财富板块数据 |
| 其他 | 4.7 KB | 6% | trigger、positions 等 |
| **总计** | **78.6 KB** | 100% | |

**结论**：watchlist 是 payload 优化的最大收益点。

---

## 优化策略

### 1. 精简 watchlist（最大收益）

**优化前**：180 条 × 484 字节 = 58.7 KB
**优化后（实验）**：30 条 × 307 字节 = 9.2 KB

实现思路：`_build_compact_watchlist()` 函数

```python
def _build_compact_watchlist(
    watch_stocks, positions, alerts,
    max_items=30,           # 从 180 减到 30
    max_watch_reason_len=80, # 从 300+ 截断到 80
    max_setup_items=2,       # 从 5 条减到 2 条
    max_setup_item_len=40,   # 每条 40 字
):
    # 优先级：持仓 > alert 触发 > 其他（每主题最多3只）
    # 文本截断：超长自动加 "..."
```

**预期效果**：watchlist 大小 -84%，总 payload -46%

### 2. 截断长文本字段

| 字段 | 优化前 | 优化后 |
|------|--------|--------|
| watch_reason | 完整文本（300+字） | 80 字 + "..." |
| buy_setup | 5 条完整描述 | 2 条，每条 40 字 |
| invalidation_setup | 5 条完整描述 | 2 条，每条 40 字 |
| sell_setup | 空数组保留 | 空数组保留 |

### 3. 减少 quote_snapshot 条目

当前 40 条，可考虑减少到 20 条（持仓 + 观察池前 20）

---

## 实施状态

**2026-06-10**：
- 已分析 payload 构成并验证优化效果
- 代码改动被用户要求回滚（用户希望先思考再决定）
- 当前代码中 **未实现** `_build_compact_watchlist()`
- 当前采用 **timeout 180s + 停止 MCP Qdrant server** 解决 timeout

**未来如需实施 payload 优化**，参考上述 `_build_compact_watchlist()` 思路修改 `src/qing_investment/stock_monitor.py` 的 `_agent_context_data()`。

---

## 验证方法

```python
# 测试 payload 大小
import json
data = _agent_context_data(...)
payload = json.dumps(data, ensure_ascii=False)
print(f"Payload: {len(payload):,} bytes ({len(payload)/1024:.1f} KB)")

# 分析各部分占比
for key in data:
    size = len(json.dumps(data[key], ensure_ascii=False))
    print(f"  {key}: {size:,} bytes ({size/1024:.1f} KB)")
```

---

## 相关文件

- `src/qing_investment/stock_monitor.py` — `_agent_context_data()` 位置
- `scripts/hermes_stock_monitor_agent.py` — timeout 配置（默认 180s）
- `src/qing_investment/agent/tools/qdrant_client.py` — Qdrant 客户端
- `references/qdrant-concurrency-lock.md` — Qdrant 锁冲突详细说明
