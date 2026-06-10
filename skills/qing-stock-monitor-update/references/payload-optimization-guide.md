# Payload 优化指南 — qing-stock-monitor-update

> 当 Qing-Agent 调用 timeout 或 payload 过大时，参考本指南优化 `_agent_context_data()` 的 JSON 输出。

---

## 问题诊断

Qing-Agent timeout 可能有三个原因：

| 原因 | 排查方法 | 解决 |
|------|---------|------|
| **Payload 过大** | `len(json.dumps(data)) > 100KB` | 精简 watchlist / 截断文本 |
| **Qdrant 并发锁** | 日志出现 `Storage folder .qdrant_data is already accessed` | 重启 Qing-Agent 或改用 Qdrant server 模式 |
| **LLM 管线慢** | `/health` 通过但 `/analyze/trigger` 超时 | 增加 timeout（120→180s） |

---

## 优化策略

### 1. 精简 watchlist（最大收益）

**优化前**：180 条 × 484 字节 = 87KB
**优化后**：30 条 × 307 字节 = 9KB

实现：`_build_compact_watchlist()` 函数

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

**效果**：watchlist 大小 -84%，总 payload -46%

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

## 长期方案

当前优化是治标。根本问题是 **Qdrant 本地模式不支持并发访问**（Qing-Agent + MCP 同时访问 `.qdrant_data`）。

**长期方案**：
1. Qing-Agent 使用 Qdrant HTTP API 而非本地文件
2. 或部署独立 Qdrant server（docker run qdrant/qdrant）
3. 或增加 Qing-Agent 和 MCP 的访问协调机制

---

## 相关文件

- `src/qing_investment/stock_monitor.py` — `_build_compact_watchlist()` 实现
- `scripts/hermes_stock_monitor_agent.py` — timeout 配置（默认 180s）
- `src/qing_investment/agent/tools/qdrant_client.py` — Qdrant 客户端
