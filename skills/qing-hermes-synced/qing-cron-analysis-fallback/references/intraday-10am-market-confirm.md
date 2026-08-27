# 10:00 盘面确认（intraday market confirm）数据源速查

实测日期：2026-08-06（10:00 cron，预跑 Qing-Agent 分析脚本输出"白卷"，但本地数据完好，最终完整产出报告）。

## 核心教训

**预跑脚本输出"数据缺失/白卷/未配置" ≠ 本地数据缺失。**
Qing-Agent 的 LLM 分析路径失败（周期定位未配置、LLM未返回结果、情绪信号 `{}`、引用覆盖率 50%）时，
底层 stock scanner 数据通常完全正常。**先查本地 state 文件再下结论**，不要照抄"数据缺失"声明。

## 数据源清单（按优先级）

### 1. `config/stock_monitor/state.json` → `last_quote_snapshot`（实时行情真相源）
- `source: tencent_gtimg`，~10min 刷新（实测 10:19 快照，elapsed_ms≈73）
- `quotes`：10 个指数（上证/深成/创业板/科创50/中证全指/上证50/沪深300/中证500/中证1000/国证2000）+ watchlist 个股
- 字段：`latest / previous_close / open / high / low / volume / amount / pct_change / change`
- **两市成交额估算**：上证 `amount` + 深证 `amount`（单位万元；10:19 时约 1.07 万亿）
- 用指数高低开 + 现价即可还原"开盘一小时走势"（低开高走/V型等），无需额外接口

### 2. `config/stock_monitor/daily_state.json`（scanner 分析产物）
- `market_stage.phase` + `.detail`（六步分析；⚠️ detail 可能截断在 ~200 字符，以 state.json 实时快照为准）
- `direction_priority`（贵金属/白银、稀土/小金属、印制电路板…）— 用于验证盘面主线是否吻合
- `position_stance`（如"4成仓内，滚动操作"）— 操作提示的纪律锚点
- `active_opportunities`（entry_zone / matched_conditions / price_bucket / stop_loss）— 已进入区间的候选
- ⚠️ 读取坑位：文件含控制字符，read_file 工具会抛 JSONDecodeError，用 Python `json.loads(raw, strict=False)`

### 3. `config/stock_monitor/positions.yaml` — 持仓真相源
- 预跑脚本可能显示"持仓 0 股"（错误），以 YAML 为准（如恩捷股份 100 股、成本 55.171）
- 浮盈亏 = (现价-成本)/成本，直接可算

### 4. 板块排名 → `sector_data.py`（东财→新浪级联）
```python
PYTHONPATH=src .venv/bin/python -c \
"from qing_investment.agent.tools.sector_data import get_sector_strength_snapshot; print(get_sector_strength_snapshot(top_n=10))"
```
- 返回 `{available, concept:{leaders,laggards}, industry:{leaders,laggards}}`，条目含 name/pct_change/amount
- 缓存 `~/.kimi-code-im-bot/cache/sector_boards.json`，TTL 20min，失败可回退过期缓存
- provider：concept=eastmoney、industry=sina
- **⚠️ 坑位**：`laggards` 在部分 top_n 下排序失真（可能全是正涨幅），用 watchlist 个股快照交叉验证板块强弱
- **东财 push2 直连 RemoteDisconnected 是常态**：不要反复重试直连，直接用本函数或新浪/腾讯替代

### 5. 量能对比（同比昨日）→ 腾讯日K API
```
http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000001,day,,,5,qfq   # 上证
http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sz399001,day,,,5,qfq   # 深成
```
- gbk 解码；`data.<code>.qfqday` 或 `.day`；k[0]=date k[2]=close k[5]=volume
- **放量判定法**：盘中累计量 / 昨日全天量 vs 时间进度。
  10:20 时间进度 = 50/240min ≈ 21%；若量能进度（实测沪 43%、深 44%）明显高于时间进度 → 放量承接
- ⚠️ 昨日同时刻精确值无免费接口 → 结论标注"估算"，但方向（放量/缩量）可信

### 6. 北向资金：实时净买入不可得（2024-08 起交易所不再实时披露）
- 腾讯 gtimg 返回 `v_pv_none_match`，东财 push2 kamt 常断连
- **应对：如实声明不可得，不编造数字**；替代信号 = 权重 vs 小盘相对强弱（如 上证50 vs 国证2000）

## 板块排名 — 直连 API 备选路径（2026-08-26 实测）

当 `sector_data.py` import 路径断裂（如 `ModuleNotFoundError: fetcher_factory`）或
`Remote end closed connection` 反复出现时，**直连 HTTP API** 是更快更稳的降级路径。

### 关键坑位：EastMoney `f3` 字段单位

**`f3` 不是百分比，是"基点"（百分之一百分比）**。例如 `f3=620` → 实际 +6.20%。
必须先 `/100` 再显示。错误示例：之前 session 把 620 直接显示成 +620.00%，完全失真。

### 上证/深证/创业板/科创50 — 腾讯 gtimg 直连（可靠）

```
GET https://qt.gtimg.cn/q=sh000001,sz399001,sz399006,sh000688,sh000300,sz399673,sh000016
```

返回逐行 `v_代码="字段0~字段88"`。关键字段（**按 f[2]=6 位纯数字** 做 key）：
- `[1]` 名称，`[2]` 6位纯数字代码（不带 sh/sz 前缀）
- `[3]` 现价，`[4]` 昨收，`[5]` 今开
- `[33]` 最高，`[34]` 最低，`[36]` 成交量(手)，`[57]` 成交额(万元)
- 一行一条指数，用 `'"'[1].split('~')` 解析

**⚠️ 涨跌幅不要硬读 f[31]/f[32]（实测 2026-08-26 踩坑）**：`v_xxx="51` 前缀会使字段整体偏移 +1，硬读 f[31] 会得到 +28%~+45% 的荒谬值。正确做法二选一：

1. **推荐（最稳）**：`pct = (f[3]/f[4] - 1) * 100`，从 close/prev_close 反算。
2. 使用 `state.json` 中已解析好的 `pct_change` 字段（若本任务同时加载 state.json）。

**绝对不要**用 `f[2]` 拼接 sh/sz 前缀做 dict key——gtimg 返回 f[2] 是 6 位纯数字（`000001`），查询时 `c[2:]` 去前缀；两边必须配对。

**实测：100% 成功率，毫秒级响应，HTTPS 也正常。**

### 概念/行业板块排名 — 东财 push2 HTTP 直连

```
概念涨幅 TOP8:  http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=8&po=1&fid=f3&fs=m:90+t:2&fields=f12,f14,f3,f2
概念跌幅 TOP5:  http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&po=0&fid=f3&fs=m:90+t:2&fields=f12,f14,f3,f2
行业涨幅 TOP8:  http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=8&po=1&fid=f3&fs=m:90+t:3&fields=f12,f14,f3,f2
行业跌幅 TOP5:  http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&po=0&fid=f3&fs=m:90+t:3&fields=f12,f14,f3,f2
```

要点：
- **必须用 HTTP 不用 HTTPS**（HTTPS 在本机环境稳定返回 `RemoteDisconnected`）
- `po=1` 涨排序，`po=0` 跌排序，`fid=f3` 按涨跌幅排序
- `fs=m:90+t:2`=概念板块，`fs=m:90+t:3`=行业板块
- `diff` 是 `dict[str, dict]`（key 为序号字符串）或 `list`，两种格式都处理
- **必做 retry 循环（3-4 次，间隔 1.5s）**，东财有 102 限流码
- 解析：`item.get('f3') / 100` 才是实际涨跌幅（%），`item.get('f14')` 是名称

**⚠️ 一次最多只查一个 fs 后必须 sleep 2s 再查下一个**，否则 102 限流打挂后续请求。

### 北向资金实时 — 确认不可得

- 东财 `push2.eastmoney.com/api/qt/kamt.rtmin/get` 返回全零（2026-08-26 实测）
- 腾讯 gtimg 返回 `v_pv_none_match`
- **结论不变**：2024-08 起交易所不再实时披露，如实声明不可得，替代信号=权重vs小盘相对强弱

### 个股快照 — 腾讯 gtimg

```
GET https://qt.gtimg.cn/q=sh588170,sz159516,sz002812,...
```
字段同指数。涨跌幅 = (现价 - 昨收) / 昨收 × 100%。

## 报告结构（5 段，任务强制）

1. **开盘一小时走势总结**：指数表（开/现/涨跌幅/走势特征）+ 事实与推断分离（"低开高走是事实，是否企稳需量能确认"）
2. **量能对比（同比昨日）**：量能进度 vs 时间进度，估算标注
3. **板块涨幅/跌幅排名**：行业+概念 leader/laggard + 监控池个股佐证（涨停数、主线确认）
4. **北向资金**：不可得时声明 + 替代信号
5. **操作提示**：条件性建议（非买卖指令）——引用 position_stance 纪律 + active_opportunities 区间（已进入/未到位/涨停不追）+ 持仓状态

每段带**数据时间戳 + 来源**；区分事实/估算；不做无条件买卖指令（AGENTS.md 纪律）。
