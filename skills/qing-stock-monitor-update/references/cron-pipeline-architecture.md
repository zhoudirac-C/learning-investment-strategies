# Cron 管线架构（2026-06-09 澄清）

> **触发**：本次会话中 Agent 误以为修改 cron job 的 `prompt` 字段能传递给 qing-agent，用户纠正。

## 实际调用链

```
cron job (prompt: 简洁 fallback 文本)
  → qing_stock_monitor_agent.py
    → stock_monitor.py --agent-json-context  拉行情 + 组装JSON
    → POST qing-agent /analyze/trigger       调本地 LangGraph Agent
      → parse_query → retrieve_knowledge → market_analyst → ...
      → market_analyst 节点使用 market_analyst.txt 作为 system prompt
      → style_writer 节点使用 style_writer.txt
      → 返回 final_output
    → 输出微信消息
```

## 关键陷阱

❌ **cron job 的 `prompt` 字段不传给 qing-agent。**
   qing-agent 通过 HTTP API 调用，使用自己的 LangGraph system prompt（`prompts/system/*.txt`）。
   cron prompt 只在 qing-agent 不可用时的 **fallback 文本路径** 生效。

✅ **修改 qing-agent 行为 → 改 `prompts/system/market_analyst.txt`（或对应节点 prompt）**

✅ **修改 cron 调用参数（如触发标题/原因）→ 改 `strategy_pack.yaml` 的 `agent_analysis_schedule`**

## 三条管线

| 管线 | 触发方式 | LLM | 改哪里 |
|------|---------|-----|--------|
| 手动更新 | 用户说"更新观察池" | qing-agent /chat | `qing-stock-monitor-update` SKILL.md |
| 定时分析 | 9个Cron定点触发 | qing-agent /analyze/trigger | `market_analyst.txt` + `agent_analysis_schedule` |
| 条件轮询 | Cron每5分钟no-agent | 无 | `stock_monitor.py` run_tick() 纯规则 |

## daily_state 写入链

```
market_analyst.txt 末尾要求输出 ```daily_state 代码块
  → qing-agent 在回复中生成
  → cron output 落盘 ~/.hermes/cron/output/<job_id>/
  → sync_daily_state.py 每5分钟扫描提取JSON
  → 写入 config/stock_monitor/daily_state.json
  → 下一节点 format_agent_analysis_context() 读取注入
```

## 相关文件

- `prompts/system/market_analyst.txt` — qing-agent 的 market_analyst system prompt
- `scripts/sync_daily_state.py` — daily_state 扫描写回
- `scripts/sync_claims_to_config.py` — claims→config 桥接
- `scripts/qing_stock_monitor_poll.py` — 条件驱动轮询入口
