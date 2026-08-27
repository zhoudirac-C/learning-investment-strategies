# M6 策略特征层与回测 — 立项设计文档

> 版本: v1.0 | 日期: 2026-08-27 | 前置: `chanlun-quant-engine.md`（M1 校准门 / M2 fork 校准 / M3 递归层 / M4 补丁评估 / M5 适配器补偿，全部收官）
>
> **编号说明**：本文档立项的即设计文档 §九 里程碑表的「**M4（另立项）策略特征层/回测（is_sure 严格+T+1+成本+样本外）**」。执行序中 M4=补丁评估（2026-08-02）、M5=适配器补偿（2026-08-26）已占用编号，本里程碑顺延为 **M6**；设计文档 §九 表格已同步改标。

---

## 一、定位与诚实声明

M1–M5 交付的是**口径严谨的结构分析引擎**（校准矩阵 chanpy 25 / czsc 25 / recursion 18，202 单测全绿，is_sure 语义全程透传）。M6 是策略线起点：把引擎输出变成可回测的信号，用市场数据回答一个问题——**缠论买卖点结构有没有统计边际**。

诚实声明（沿用设计文档 §1.3，不变）：公开渠道无任何"纯缠论买卖点信号+完整成本假设"的可复现正收益记录。M6 的产出是**证据**，不是盈利承诺。两种结论都有价值：有边际 → 作为特征/过滤器嵌入更大策略体系；没边际 → 如实记录，引擎回归"结构分析工具"定位。**禁止为了出正收益结论做参数寻优。**

## 二、目标与非目标

### 2.1 目标

1. **数据接入（M6-1）**：长历史日线本地库（降级链双源），直供引擎 `Bar` 序列，幂等可增量
2. **特征层（M6-2）**：NormalizedChart 五表 → 信号流（一/二/三类买卖点 + 背驰确认），is_sure 严格过滤
3. **回测层（M6-3）**：T+1 撮合 + 成本模型 + 指标体系（胜率/盈亏比/最大回撤/相对基线超额）
4. **样本外验证（M6-4）**：样本内/外切分，对照基线（买入持有、沪深300），只报样本外结论

### 2.2 非目标（本期不做）

- 实盘接入、实时信号推送
- 参数寻优 / 网格搜索（防过拟合；结构参数取校准门既定口径，不引入策略侧可调参数）
- 分钟级数据与 T+0 语义（数据层预留，本期仅日线）
- 选股（universe 人工给定；不做全市场扫描，避免幸存者偏差被掩盖）

## 三、总体架构

```
akshare / baostock ──降级链──▶ infra/data/chan_bars.db（SQLite，前复权日线，gitignored）
                                      │ data.store.load_bars
                                      ▼
                    ChanPyAdapter / RecursionEngine（M1–M5 既有，零改动）
                                      │ NormalizedChart 五表（含 sure）
                                      ▼
                    特征层 signals.py：sure=True 且确认日明确的 bsp/背驰 → 信号
                                      ▼
                    回测层 backtest.py：T+1 成交、成本、净值、指标
                                      ▼
                    报告 logs/chan-backtest-*.md（含 universe、区间、成本假设声明）
```

目录落位（遵循 PYTHONPATH=src 约定）：

- `src/chan_engine/data/` — 数据层（fetch 降级链 / store SQLite / Bar 适配）
- `scripts/fetch_chan_bars.py` — 回填与增量续拉 CLI
- `tests/chan_engine/test_data_fetch.py` / `test_data_store.py` — 单测（不碰网络）
- 特征层与回测层（M6-2/3/4）另立 plan，落 `src/chan_engine/strategy/`

## 四、数据接入设计（M6-1，本次实施范围）

### 4.1 数据源降级链（2026-08-27 spike 实证，附录 A）

| 源 | 接口 | 实测结果 |
|---|---|---|
| akshare | `stock_zh_a_hist`（东财，个股 qfq） | ❌ ConnectionError（本机到东财历史接口连接被断，重试同） |
| akshare | `stock_zh_index_daily`（新浪，指数） | ✅ 上证指数 1990-12-19 → 2026-08-26，8712 行 |
| baostock | `query_history_k_data_plus`（个股，adjustflag=2 前复权） | ✅ 600519 上市日 2001-08-27 → 2026-08-26，6065 行 |
| baostock | 同上（指数 sh.000001） | ✅ 1990-12-19 → 2026-08-26，8712 行（与新浪行数一致） |

降级链（与设计文档 §七"akshare 主力、baostock 备用"一致，链的意义即环境自适应；本机个股历史接口实测不可达，自动落 baostock）：

```
个股日线:  akshare stock_zh_a_hist → baostock → DataFetchError（明确报错，禁止编造）
指数日线:  akshare stock_zh_index_daily → baostock → DataFetchError
```

每行落库带 `source` 列溯源；baostock 需 login/logout，封装在 fetcher 内部，单测不触网。

### 4.2 复权口径决策

**前复权（qfq）为唯一分析口径**。理由：除权缺口会伪造分型/笔结构（结构连续性要求），且前复权收益率可直接用于净值计算（分红再投资口径）。

风险如实记录：前复权历史价随未来除权事件漂移 → 回测结论只断言**相对收益与信号统计**，不断言"当时的绝对价位"；跨期复跑同一窗口，价格序列可能因期间新除权而不同（信号统计层面影响极小，但报告须声明）。金标用例（GOLD-001/002）的不复权口径是课文保真需求，与本层无关。

### 4.3 存储

`infra/data/chan_bars.db`（`infra/data/` 已 gitignored）。**独立于监控 `kline_cache.db` 的理由**：`kline_cache.save_klines` 是 per-code 覆盖写（DELETE+INSERT），每日 cron 续拉会销毁长历史；两套数据生命周期与写语义不同，分库隔离。

```sql
CREATE TABLE IF NOT EXISTS daily_bars (
    code       TEXT NOT NULL,              -- 个股裸码 '600519'；指数带前缀 'sh000001'
    trade_date TEXT NOT NULL,              -- YYYY-MM-DD
    open REAL, high REAL, low REAL, close REAL,
    volume REAL,                           -- 统一归一到"股"（akshare 手×100）
    amount REAL,                           -- 元；源缺省为 NULL
    adjust TEXT NOT NULL DEFAULT 'qfq',
    source TEXT NOT NULL,                  -- 'akshare' / 'baostock'
    updated_at TEXT,
    PRIMARY KEY (code, trade_date, adjust)
);
```

- 幂等：`INSERT OR REPLACE`，不 DELETE 全量；同区间重拉结果一致
- 增量：按 `coverage()` 的 max(trade_date) 续拉
- 成交量单位：akshare 个股/指数历史接口为"手"，×100 归一到"股"；baostock 原生为"股"。（新浪指数源单位未逐字段核实，附录 A 存疑登记；缠论结构分析不依赖绝对量，vol 仅辅助）
- 内部格式对齐设计文档 §七：`[(ts,o,h,l,c,vol)]`，不接 czsc/chanpy 各自 connector

### 4.4 Bar 适配

- `load_bars(code, start, end) -> list[Bar]`：`ts` 取窗口内递增序号 0..n-1（对齐 `spec/model.py` Bar 约定"ts 为递增序号或时间戳，由构造方决定"），直供 `ChanPyAdapter.run` / `RecursionEngine`
- `load_daily(...) -> list[dict]`：带 `trade_date` 的原始行，回测撮合层（M6-3）按日期对齐成交

### 4.5 T+1 语义位置

设计文档附录 A.4："T+1 语义在数据层预留、引擎层不耦合"。落点 = **回测撮合层（M6-3）**：信号确认日 t（结构 sure 翻转所在 bar）→ t+1 开盘价成交。数据层的义务仅是提供完整、连续、无未来数据的交易日序列。

## 五、特征层设计（M6-2 纲要，另立 plan）

- 信号 = `sure=True` 的买卖点（一/二/三类）与背驰确认；`sure=False` 的虚结构一律不进信号流（is_sure 严格，M1–M5 既有资产）
- **反未来函数硬约束**：信号时间戳 = 结构被确认（sure 翻转）的 bar，**不是**形态极值 bar。实现上必须用增量会话（M3-5 `ChanPySession`/`RecursionSession`）逐 bar 重放产生信号；禁止"批量跑完回头取历史 bsp 的极值位置当信号日"——批量终态 ≠ 当时可知
- 这条是 M6 最核心纪律：社区共识"缠论指标本身就是实现了一套未来函数"（设计文档附录 B）；is_sure + 增量重放是我们的系统性对策，回测报告须声明该纪律的落实方式

## 六、回测层设计（M6-3 纲要，另立 plan）

- 撮合：t 日信号确认 → t+1 开盘价成交（T+1）；卖出对称信号或规则退出（固定持有窗/止损，plan 阶段定）
- 成本模型（集中可配，默认值）：佣金万 2.5 双边（最低 5 元）、印花税卖出千 0.5（现行）、滑点千 0.1 双边
- 指标：信号数、胜率、平均盈亏、盈亏比、最大回撤、相对基线（买入持有 / 沪深300）超额
- 样本外（M6-4）：时间序切分（如 ≤2021 样本内 / ≥2022 样本外）或 walk-forward；**只报样本外结论**，样本内仅作 sanity check；universe 人工给定并在报告头声明构成

## 七、里程碑拆分与验收

| 子里程碑 | 内容 | 验收 |
|---|---|---|
| **M6-1 数据接入**（本 plan） | fetch 降级链 + SQLite store + Bar 适配 + CLI | 单测全绿（不触网，mock 双源）；真实拉取上证指数 + 1 只个股落库、复读一致；校准矩阵 25/25/18 与既有测试零回归 |
| M6-2 特征层 | 增量重放信号流 | 信号时间戳全部 = sure 翻转日（有测试证明无未来函数） |
| M6-3 回测引擎 | T+1 + 成本 + 指标 | synthetic 案例手算可复核；成本开关前后结果差异方向正确 |
| M6-4 样本外报告 | 切分 + 基线对照 | 报告含 universe/区间/成本声明；样本不足时如实报 insufficient |

## 八、风险

| 风险 | 等级 | 对策 |
|---|---|---|
| 东财历史接口本机不可达，个股退化为 baostock 单源 | 中 | 降级链保留 akshare 首试（换环境可自愈）；source 列溯源；双源皆挂明确报错 |
| 前复权历史价漂移 | 低 | §4.2 已声明；不断言绝对价位 |
| 幸存者偏差（universe 人工给定） | 中 | 报告头声明 universe 构成；不声称全市场结论 |
| 信号稀疏（日线 bsp 本就低频） | 中 | universe × 区间要够大；样本不足如实报 insufficient，不硬出结论 |
| 范围蔓延（顺手做分钟线/选股/寻优） | 中 | §2.2 非目标白纸黑字；M6-2/3/4 另立 plan 逐个评审 |

---

## 附录 A：spike 记录（2026-08-27，本机实测）

```text
akshare 1.18.94:
  stock_zh_a_hist("600519", daily, 2001-01-01~2026-08-27, qfq)
    → ConnectionError: RemoteDisconnected（重试同）——东财历史接口本机不可达
  stock_zh_index_daily("sh000001")
    → 8712 行，1990-12-19 → 2026-08-26 ✅（新浪源）
baostock（login success）:
  sh.600519 日线 qfq(adjustflag=2): 6065 行，2001-08-27（上市日）→ 2026-08-26 ✅
  sh.000001 日线: 8712 行，1990-12-19 → 2026-08-26 ✅（与新浪行数一致，交叉验证通过）
```

存疑登记：新浪指数历史接口 volume 单位（手/股）未逐字段核实；baostock 指数 amount 字段口径未核实。两者均不影响结构分析（o/h/l/c 两源交叉一致）。

## 附录 B：关键假设（待 UP 确认，不阻塞 M6-1）

1. 前复权为唯一分析口径（§4.2）；若你有既定口径（如分段不复权+因子表），改 ADR
2. M6-1 universe 不做默认全市场：指数默认集 = 上证/深成/创业板/沪深300，个股由 CLI `--codes` 显式指定
3. 成本默认值（佣金万 2.5 / 印花税千 0.5 卖出 / 滑点千 0.1）在 M6-3 plan 评审时可调
4. 特征层只用 chanpy 列（25 PASS）与 recursion 列（18 PASS）的并集能力；czsc 列保持对照定位不进策略线
