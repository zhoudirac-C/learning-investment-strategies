# 集合竞价后（09:26）分析 — 实时数据端点速查

2026-08-17 09:39-09:57 实战验证；2026-08-21 09:41-09:45 复证并新增降级通道。
用于竞价后 cron 任务独立拉取实时数据，
避免引用预运行脚本的竞价时点快照（见 SKILL.md 类型C子模式）。

## ⚠️ 2026-08-21 复证：竞价快照 vs 开盘后实时（再次确认方向性反转）

09:30 预跑脚本快照：涨停 6 / 跌停 5 / 涨跌 947:3994 / 连板高度 3，自称"普跌冰点、看个寂寞"。
09:41 独立实时：涨停 **39** / 跌停 8 / 涨跌 **1754:3606**，指数全绿（创业板 +1.56% 领涨，上证 +0.16%），两市成交 7623 亿（昨日全天 20793 亿的 36.7%）。
11 分钟内涨停 6→39、涨跌比从 1:4 修复到 1:2 —— 竞价冰点 ≠ 全天冰点，低开高走 V 型在竞价后立刻展开。
**教训（已在 SKILL.md 类型C子模式）再次成立：竞价后 09:26-09:40 窗口，一切结论以独立实时拉取为准。**

## 涨停池（东财 push2ex）

```bash
# 今日（date=YYYYMMDD），pagesize 300 拿全量
curl -s --max-time 8 "https://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt&Pageindex=0&pagesize=300&sort=fbt%3Aasc&date=20260817" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); pool=d.get('data',{}).get('pool',[]) or []; print(f'涨停 {len(pool)} 家'); [print(f\"  {s.get('c')} {s.get('n')} 连板{s.get('lbc')} 封单{s.get('fund')} 首封{s.get('fbt')}\") for s in pool[:15]]"
```

- 字段：`c`=代码 `n`=名称 `p`=涨停价 `lbc`=连板数 `fund`=封单额 `fbt`=首次封板时间（92500=09:25 竞价封板）
- **环比昨日**：date 换昨日，对比 pool 长度即可判断情绪（如 45 vs 63 = 涨停数环比 -29%）
- 历史文件备份：`infra/data/limit_pool/YYYYMMDD.json`（如 20260814.json）

## 板块涨幅排名（东财 clist）

```bash
# 行业板块 fs=m:90+t:2；概念板块 fs=m:90+t:3；fid=f3 按涨幅降序
curl -s --max-time 8 "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=15&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2&fields=f2,f3,f4,f8,f12,f14" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); [print(f\"  {x.get('f14')} {x.get('f3')}% 涨跌家数比{x.get('f8')}\") for x in d.get('data',{}).get('diff',[]) or []]"
```

- 字段：`f14`=名称 `f3`=涨跌幅% `f8`=涨跌家数比
- 若返回空/rc!=0：加 `Referer: https://quote.eastmoney.com/` 头重试 2-3 次（11:20-11:30 窗口高发，见 SKILL.md 触发条件A）
- **⚠️ push2 主站被重置时（2026-08-21 实测：clist/get 与 stock/get 均 `Remote end closed connection`，但 push2ex 涨停池同机正常）**：板块榜改走新浪 newFLJK，用项目自带函数：
  ```python
  from qing_investment.agent.tools.sector_data import fetch_sina_boards
  ind = fetch_sina_boards('industry', top_n=10)   # 行业板块
  con = fetch_sina_boards('concept', top_n=10)    # 概念板块
  ```
  - ⚠️ `get_sector_strength_snapshot()` 此时可能返回 `False`（bool 守卫失败，provider 链头是 push2）——**不要死磕它，直接调 `fetch_sina_boards`**（东财→新浪级联的另一端）
  - ⚠️ sina 板块返回的 amount 字段单位失真（天文数字），**只取 pct_change 排序**，不用成交额
  - 新浪板块涨幅与涨停池行业分布（hybk 字段）可交叉验证主线（08-21：通信设备/化学制药涨停簇 ↔ 5G/华为/宽带提速概念领涨）

## 开盘量能对比（集合竞价后 09:40 窗口）

- **两市成交额**（腾讯简版，`qt.gtimg.cn/q=sh000001,sz399001` 全量报价）：上证 parts[37]=沪市成交额(万元)、深证 parts[37]=深市成交额(万元)，相加 = 两市成交额；对比昨日全天基准（daily_state 或 shadow 预测文件 `evals/shadow/predictions/YYYY-MM-DD-pre.json` 的昨成交额）
- **线性外推**：09:41 已达昨日全天 36.7% → 全天节奏 ≈ 2.2-2.5x 昨日（放量低开判断依据）；注意竞价撮合量（~150-300 亿）只反映竞价活跃度，不是全天量能
- **⚠️ kline_cache 30min bar 不可用于跨指数量能对比（2026-08-21 实测）**：`index_klines` 的 30min bar ①bar_time 是 bar 结束时刻（9:30-10:00 记作 `10:00`）②volume/amount 单位在指数间不一致（混有累计值/增量、量级错乱）。做"今日开盘量 vs 昨日同时段量"一律用腾讯指数 amount 字段（见上），不要用 kline_cache 日内 bar

## ⚠️ 2026-08-25 实测补充：腾讯通道 GBK 解码陷阱 + 美股端点 + push2 部分降级

**腾讯通道 Python 抓取必须 bytes 解码（2026-08-25 首次踩坑，表现为静默空结果）**：
- ❌ `subprocess.run(cmd, capture_output=True, text=True)`：locale 默认 UTF-8，腾讯 GBK 返回直接抛 `UnicodeDecodeError`，被 except 吞掉后表现为 "index/hk/fx 全空"——极易误判为接口挂了，实际是解码失败
- ✅ `subprocess.run(cmd, capture_output=True)` 拿 bytes → 手动 `.decode('gbk', errors='replace')`
- 终端 curl 场景继续用 `| iconv -f GBK -t UTF-8`；Python 脚本场景用 bytes 解码，两条路径并存

**美股隔夜（三通道实测排序，08-25 唯腾讯可用）**：
- ① 腾讯 `qt.gtimg.cn/q=usDJI,usIXIC,usINX`（GBK；parts[3]=现价 parts[32]=涨跌幅；parts[30]=时间戳，16:xx = 隔夜收盘数据）——**本次唯一可用**
- ② 新浪 `hq.sinajs.cn/list=s_usDJI,s_usIXIC,s_usINX`（带 Referer）——本次返回空
- ③ 东财 `push2 ulist.np get secids=100.DJIA,100.NDX,100.SPX`——本次返回空（push2 ulist 端点被重置，但同主机 clist 板块榜正常）

**push2 部分降级模式（clist 正常 vs ulist/push2his 空）**：08-25 实测 `clist/get`（板块榜，带 Referer）正常返回，但 `ulist.np/get`（指数批量行情）与 `push2his kline`（日K）返回**空字符串**（非连接错误）。→ 不要因一个 push2 端点失败就整体降级：指数实时改走腾讯，昨日量能基准改走新浪日K（见下）。

**昨日全天量能基准（push2his 挂时的替代链）**：
- 新浪日K：`https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_=/CN_MarketDataService.getKLineData?symbol=sh000001&scale=240&ma=no&datalen=3`（需 Referer）
- ⚠️ 该 API 只有 volume（单位=**股**），**无 amount 字段**；腾讯 ifzq 日K volume 单位=**手**（×100=股）
- 量能进度口径：今日累计成交量（腾讯实时 parts[6]，手）÷ 昨日全天成交量（腾讯 ifzq 日K k[5]，手）→ 08-25 09:44 实测进度 15-16% = 平量偏缩（对照 08-21 放量日同时点 36.7%）

## 修复质量指标（竞价后判断情绪修复成色）

- **晋级率** = 今日 2 板家数 ÷ 昨日首板家数（昨首板 = 昨日涨停池中 lbc==1 的家数；今日 2 板家数从今日涨停池 ladder 数出）。健康线 15%，<10% 为"外强中干"
- **昨日涨停今表现**：拉昨日涨停池（push2ex date=昨日）全部代码 → 腾讯批量行情 → 算平均涨跌幅/涨跌家数/延续涨停数。08-21 实测：昨日 79 家涨停今日平均 **-0.92%**（涨 26/跌 52、延续 12 只）+ 昨日 4 板独苗断板 → 判定"宽度修复、链上退潮"（切换型行情，非情绪全面回暖）
- **竞价一字家数**：涨停池中 `fbt` 以 `92500` 开头 = 竞价一字封板（08-21：竞价 6 家中 4 家一字，其中汉森制药 3 板为最高板）
- 注意：09:30 竞价快照的"昨日连板 +5.4% / 昨日打板 +9.2%"类瞬时概念涨幅，09:41 即可能消失（昨涨停平均转负）——**不要用竞价快照的概念榜判断修复持续性**

## 港股 / A50 / 汇率

```bash
# 港股（腾讯 r_ 前缀，GBK）— 恒指/国企/恒生科技
curl -s --max-time 8 "https://qt.gtimg.cn/q=r_hkHSI,r_hkHSCEI,r_hkHSTECH" | iconv -f GBK -t UTF-8
#   parts[3]=现价 parts[4]=昨收 parts[5]=今开 parts[31]=涨跌 parts[32]=涨跌幅
# A50 三级通道（2026-08-21 实测，按优先级）：
#   ① 东财 push2 secid=100.XIN9（富时中国A50；push2 主站可用时首选）
curl -s --max-time 8 "https://push2.eastmoney.com/api/qt/stock/get?secid=100.XIN9&fltt=2&invt=2&fields=f43,f57,f58,f170"
#   ② 新浪外盘期货 hf_CHA50CFD（push2 被重置/断连时可用；⚠️ 代码必须带 hf_ 前缀）
curl -s --max-time 8 "https://hq.sinajs.cn/list=hf_CHA50CFD" -H "Referer: https://finance.sina.com.cn"
#   返回: "14857.720,,14857.000,14858.000,14866.000,14640.000,10:16:32,14658.000,14657.000,800082,..."
#   字段: [0]最新价 [2]买价 [3]卖价 [4]最高 [5]最低 [6]时间 [7]昨收/昨结 [8]今开 → 涨跌幅=(最新-昨收)/昨收
#   ⚠️ 2026-08-17 记录"新浪 CHA50CFD 不可用"指不带 hf_ 前缀的裸代码；hf_CHA50CFD 是有效通道
#   ③ akshare index_global_spot_em() 依赖 push2，push2 挂时同挂，不用重试
# 汇率（三通道任选，均实测可用）：
#   腾讯 whUSDCNY；⚠️ 不要用 usCNH——那是荷兰公司 Cnh Industrial 的股价，不是离岸人民币
curl -s --max-time 8 "https://qt.gtimg.cn/q=whUSDCNY" | iconv -f GBK -t UTF-8
#   新浪 fx_susdcny（在岸）/ fx_susdcnh（离岸）：hq.sinajs.cn/list=fx_susdcny,fx_susdcnh（需 Referer 头）
#   parts[8]=现价 parts[0]=买价 parts[1]=卖价
```

## 两市成交额（三源交叉验证，口径一致才采信）

| 源 | 端点 | 口径 |
|----|------|------|
| 东财 | `push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&fields=f2,f3,f6,f12,f14&secids=1.000001,0.399001` | f6 单位**元**，÷1e8 得亿元 |
| 腾讯简版 | `qt.gtimg.cn/q=s_sh000001,s_sz399001`（GBK） | parts[6]=成交量(手) parts[7]=成交额(万) |
| 新浪 | `hq.sinajs.cn/list=s_sh000001,s_sz399001`（需 `Referer: https://finance.sina.com.cn`） | parts[8]=成交量(手) parts[9]=成交额(元)÷1e8 |

- 昨日全天基准：东财 push2his kline（`fields2=f51..f57`，f56=成交额元）或腾讯 ifzq 日K（`web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000001,day,,,3,qfq`，k[5]=成交量手）
- **线性外推预警**：早盘 27 分钟已达昨日全天 35%+ 时，全天可能冲 3 万亿（对照 claim-20260805-046：量能 >3 万亿防过热）
- 竞价量能（09:26 快照 ~188 亿）是撮合量，只用于对比竞价活跃度，**不是全天量能**，不要误判为异常

## 口径陷阱汇总

1. **`usCNH` ≠ 离岸人民币**：腾讯行情里返回 Cnh Industrial N.V.（荷兰工业公司）。汇率一律用 `whUSDCNY`（或新浪 `fx_susdcny`/`fx_susdcnh`）。
2. **A50 通道修正（2026-08-21）**：新浪 A50 有效代码是 **`hf_CHA50CFD`**（外盘期货 hf_ 前缀，需 Referer 头）；`hq.sinajs.cn/list=CHA50CFD`（裸代码）与东财 `101.CHA50CFD` 不可用。东财 `100.XIN9` 是 push2 通道首选，但 push2 整体被重置时只剩 hf_ 通道。
3. **push2 主站 ≠ push2ex**：`push2.eastmoney.com`（clist/stock/ulist）被重置时，`push2ex.eastmoney.com`（涨停/炸板/跌停池）可能完全正常——先分别探测，不要一锅端降级。
4. **新浪板块榜 amount 字段单位失真**：`fetch_sina_boards` 返回的成交额是天文数字，只可用于涨幅排序，不可用于量能分析。
5. **kline_cache 指数 30min bar 单位不可靠**：bar_time 为 bar 结束时刻；volume/amount 跨指数不一致（累计/增量混杂）。开盘量能对比用腾讯指数 amount 字段。
6. **positions.yaml 结构**：顶层是 `accounts: [{broker, positions: [{code, name, quantity, cost}]}]`，不是扁平 positions 列表；部分仓位 cost 为负（T+0 翻转仓，成本已回补），此时盈亏 % 无意义，直接跳过不算。
7. **东财 push2his 偶发 `Remote end closed`**：带 `end=YYYYMMDD&lmt=N` 重试或改用腾讯 ifzq 兜底。
8. **深证成指(399001) 与深证综指(399106) 的 f6 成交额相同**（都是深市全市场口径），用深证成指即可代表深市。
9. **竞价时点涨停数 vs 开盘后**：9:25 竞价涨停 6 家 → 11 分钟后 39 家（08-21）；情绪修复强度只能靠开盘后实时数据判断。
10. **腾讯美股代码 usDJI/usIXIC/usINX**：`us` 前缀 + GBK；新浪 `s_us*` 与东财 ulist 可能同时挂，按 腾讯→新浪→东财 顺序探测（08-25 实测唯腾讯可用）。
11. **新浪日K volume 单位=股、腾讯日K=手（差 100 倍）**；新浪 `CN_MarketDataService` 无 amount 字段——量能基准用 volume 比值即可，不要找不存在的金额字段。
12. **腾讯接口 Python 抓取必须 `.decode('gbk')`**：`text=True` 会抛 UnicodeDecodeError 且被 except 吞掉，表现为静默空结果，勿误判接口挂（08-25 踩坑）。
