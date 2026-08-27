# 2026-08-25 持仓成本计算错误排查 — cron 报告 P&L 全错

## 症状

尾盘条件单 cron（job 4e52348bc00f）报告的持仓 P&L 表大面积错误：
1. **负成本丢负号**：positions.yaml 里 `-10.786` / `-15.855`（做T摊薄后的合法负成本）被显示为正数
2. **现价×10 错位**：512400 显示 18.96（实际 1.896）、517520 显示 22.17（实际 2.217）、159992 显示 8.68（实际 0.868）
3. LLM 在报告里自行脑补解释"历史拆仓/分红后成本未同步更新"——错误数据引发的二次幻觉

## 根因链（三层）

### 层1：数据源全挂，quote_snapshot 为空
`fetch_json_context()` → `run_tick()` 返回的 context 中 `quote_snapshot.quotes = 0 条`。
东财 push2 反爬断连（Remote end closed）、TDX 超时、腾讯/新浪在 run_tick 路径也失败。

### 层2：quote_lookup 空 → _enrich_stock_with_quote 静默不注入
`_enrich_stock_with_quote(pos, quote_lookup)` 查不到代码就 `return`，**不报错、不留痕**。
positions 里没有 current_price → 下游 LLM 只拿到 cost 和数量。

### 层3：LLM 拿到无现价的持仓 + 自己抓的行情 → 字段错位拼接
qing-agent 的 LLM 收到只有 cost 的持仓行，自己找行情数字拼 P&L 表：
- 把负号丢了（或把 -10.786 当 10.786）
- 现价小数点错位（1.896→18.96），因为不同来源的行情精度/单位不一致

## 排查路径（复用价值高）

```python
# 1. 直接复刻 cron 数据流，看 quote_snapshot 是否为空
sys.path.insert(0, 'src'); sys.path.insert(0, 'scripts')
from pathlib import Path
from qing_investment.stock_monitor import load_monitor_config
from qing_investment.monitor.scheduler import run_tick
config = load_monitor_config(Path('config/stock_monitor'))
msg = run_tick(config, datetime.now(ZoneInfo("Asia/Shanghai")), emit_status=False,
               ignore_trading_time=True,
               state_path=Path('config/stock_monitor/state.json'),
               agent_json_context=True, agent_any_time=True)
data = json.loads(msg)
len(data['quote_snapshot']['quotes'])   # =0 即层1坐实

# 2. 检查请求日志确认发给 agent 的 positions 是否带 price
logs/qing-agent-request.<date>.log   # _log_request_payload 记录完整 payload

# 3. 单测 fetch_quotes 注意参数语义陷阱（见下）
```

## fetch_quotes 参数语义陷阱

`fetch_quotes(targets: dict[str, str])` 的 dict 是 **{label: secid}** 不是 {secid: label}！
`_build_code_maps` 循环 `for label, secid in targets.items()` 后对 secid 做 `_to_tencent_code`。
传反了会得到空 tencent_map → "no valid codes" → all_failed，且错误信息极具误导性
（tdx 会拿 label 当股票代码报"无法识别的代码: '有色金属ETF'"）。

正确用法：
```python
fetch_quotes({'有色金属ETF': '512400.SH', '恩捷股份': '002812.SZ'})  # {label: secid}
```

## 修复方向（未完成，下次继续）

1. **enrich 失败要显式告警**：`_enrich_stock_with_quote` 查不到行情时应打日志/标记，
   不能静默让 LLM 拿残缺数据自由发挥
2. **P&L 计算应代码化而非交给 LLM**：浮盈亏 = 数量×(现价−成本) 是确定性算术，
   应在 `_format_fallback_text` 或 payload 构建阶段算好注入，LLM 只负责解读不负责计算
   （与盲判架构"LLM只推理不计算"原则一致）
3. **负成本是合法状态**：下游展示和 LLM prompt 都要明确"cost 可为负（做T摊薄）"，
   禁止 abs() 或重新解释
4. quote_snapshot 空时应拒绝输出 P&L 表而非降级猜测

## 关联

- 用户原话："我看这里计算的持仓成本完全不对呀"
- 排查会话：2026-08-25 尾盘条件单任务
- 相关架构：`src/qing_investment/monitor/context/__init__.py`（position_rows/_enrich）、
  `scripts/hermes_stock_monitor_agent.py`（call_qing_agent payload 构建）、
  `src/qing_investment/monitor/fetchers/__init__.py`（fetch_quotes/TencentFetcher）
