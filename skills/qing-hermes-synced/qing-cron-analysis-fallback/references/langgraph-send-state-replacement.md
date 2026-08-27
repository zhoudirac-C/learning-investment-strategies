# LangGraph Send 状态替换与 qing-agent shard 诊断案例（2026-08-24）

## 事件时间线

1. cron job（开盘15分钟确认）报 900s 超时，类型 D：数据层完好、分析层失败
2. 用户质疑"是不是大模型没回复/超 token"
3. 排查结论：都不是——每个 shard LLM 调用正常返回，prompt 仅 ~4.2K tokens
4. 第一层根因：`WATCHLIST_CORE_ONLY=1` 只在 cron wrapper subprocess 生效，常驻 uvicorn agent 进程没有该 env → `core_only=False` → 73 只全量切 22-23 个 shard → 总耗时 1609s 击穿 900s
5. 第二层根因（用户追问后深挖）：所有 shard 的输入数据全空

## 根因：LangGraph Send 替换节点 state

```python
# shard_router (nodes.py)
return [Send("stock_scanner_shard", {"watchlist_shard": shard_to_context(s)}) for s in shards]
# → 节点收到的 state 只有 {"watchlist_shard": ...} 一个 key！
```

LangGraph 文档原话："invoke a node with a custom state... the sent state can differ from the core graph's state"。
实测迷你图确认：worker 内 `state.get("watchlist")` 返回 None。

### 日志证据链

```
stock_scanner_input: market_summary_len=2 stock_contexts=0 watchlist_summary=0 ...
stock_scanner_shard_llm: duration=80.4s prompt_len=4266 content_len=1405
stock_scanner_shard failed to parse LLM output as JSON: 输入数据全空——market_snapshot 行情为空数组...
```

`market_summary_len=2` = `"{}"` 的长度，是状态为空的直接指纹。

### LLM 拒答行为（正面教材）

模型在空输入下按 prompt 纪律拒绝编造：
> "输入数据全空……按核心原则第1条和禁止行为第3条，我不会给紫金矿业虚构一个价格、一个止损位或一个赔率数字"

这导致 JSON 解析失败而非错误输出——行为正确但暴露了上游 bug。

## 修复代码模式

```python
def _make_send(shard_payload: dict) -> Send:
    ctx_keys = ("parsed_intent", "market_summary_context", "market_snapshot",
                "positions", "watchlist", "stock_contexts", "direction_signals", ...)
    ctx = {k: state.get(k) for k in ctx_keys}
    ctx.update(shard_payload)
    return Send("stock_scanner_shard", ctx)
```

二级防御（Send 后缺 key 是 None 不是 missing）：
```python
stock_contexts = state.get("stock_contexts") or []   # 不能写 state.get("k", [])
```

## 并发度测量技巧

日志只有完成时间戳 + duration，用重叠区间计数测真实并行度：

```python
events = [(finish_time - duration, duration), ...]
concurrency_at_t = sum(1 for (t2, d2) in events if t2 <= t < t2 + d2)
```

本例 22 shards 实测 max_concurrency≈9 —— Send fan-out 本来就是并行的，
瓶颈不在客户端并行而在 shard 数量过多。

## 相关修复（同日）

| 修复 | 文件 | commit |
|------|------|--------|
| payload 显式传 core_only | scripts/hermes_stock_monitor_agent.py | 41f3d2e |
| _make_send 打包上下文 + None 防御 | src/qing_investment/agent/graph/nodes.py | 未提交（会话结束时） |

验证结果：core_only=True 时同一份 73 只 watchlist 只产出 1 个 priority shard（4 items）；
13 个相关 pytest 全部通过。
