# Qing-Agent REST API 调用参考

## 服务状态

```bash
# 健康检查
curl -s http://127.0.0.1:8000/health
# → {"status":"ok","version":"0.1.0"}

# 无响应或 503 → 服务未启动
```

## 端点

| 端点 | 方法 | 用途 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/chat` | POST | 一般性股票问答 |
| `/analyze/trigger` | POST | Hermes cron 触发（含行情快照注入） |
| `/memory/add` | POST | 追加用户记忆 |

## `/chat` 调用

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "分析一下安泰科技，现在能买吗？",
    "session_id": "user-001"
  }'
```

**返回格式**：
```json
{
  "reply": "【核心判断】...【持有逻辑】...【多空证据】...【失效条件】...",
  "memories_used": []
}
```

**注意**：`reply` 已经是 UP 风格完整文本，直接呈现给用户。

## `/analyze/trigger` 调用（完整持仓+行情）

```bash
curl -s -X POST http://127.0.0.1:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{
    "query": "每日收盘复盘",
    "analysis_type": "market",
    "trigger": {"type": "scheduled", "time": "15:05"},
    "alerts": [...],
    "market_snapshot": {...},
    "positions": [...],
    "watchlist": [...],
    "sector_strengths": [...],
    "external_sector_boards": {"available": true, ...}
  }'
```

此端点需要注入大量上下文数据，适合 cron 任务调用，不适合用户直接对话。

## 常见错误码

| 错误 | 原因 | 处理 |
|------|------|------|
| `Provider 'kimi' requires KIMI_API_KEY` | `.env` 未配置或 provider 不对 | 配 `.env` + 重启服务 |
| `Connection refused` | 服务未启动 | 启动 `uvicorn` |
| `500 Internal Server Error` | LLM API 异常或知识库连接失败 | 检查 Neo4j/Qdrant 状态 |
| 超时 (>60s) | LLM 响应慢或知识库检索慢 | 重试或查 API key 配额 |

## 静默降级检测（Cron 场景）

Qing-Agent 挂了不会触发任何告警——cron 任务会**静默降级**为 LLM fallback 路径。检测方法：

**症状**：微信收到的 cron 消息质量明显下降
- 方向关键词过期（还在说几周前的旧方向）
- 缺失 UP 框架感（无「赔率思维」「修复质量推演」等）
- 只分析上证不分析全A

**根因**：Qing-Agent 挂 → hermes_stock_monitor_agent.py fallback → LLM 直调（无 claims/Qdrant）

**一线命令**：
```bash
curl -s http://localhost:8000/health   # 确认是否挂了
cd ~/learning-investment-strategies
pkill -f 'uvicorn.*qing_investment'
PYTHONPATH=src .venv/bin/python -m uvicorn qing_investment.agent.main:app --host 127.0.0.1 --port 8000 &
sleep 3 && curl -s http://localhost:8000/health   # 验证恢复
```

详见 `skills/qing-stock-monitor-update/references/config-cron-alignment-debugging.md` Step 0。

## 降级路径

```
REST API (:8000) ←健康检查失败→ CLI (scripts/cli_qing_agent.py) ←也失败→ Hermes 自身分析（读本地文件）
```
