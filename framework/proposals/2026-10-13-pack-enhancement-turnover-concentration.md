---
date: 2026-10-13
type: pack-enhancement
status: implemented
source: 盲判vsUP对比 2026-10-13（10-09~10-12窗口）
gap_class: ③pack计算项缺失（数据源本地已有 → 实测证伪，改东财快照）
resolved_by: shadow/concentration.py + dataset._load_concentration + fetch_turnover_concentration.py（cron fa9d22b79940，工作日15:45）
---

# pack 新增成交集中度指标（筹码出清进度代理变量）

## ⚠️ 实施偏差记录（2026-10-13 实测）

原提案前提「stocks_kline 已有全市场日K 5364 只」**实测不成立**：TDX 成分股裸码
已全部清空，当前 stocks_kline 仅覆盖 617~1467 只/日（pre_fetch 池），且 turnover
列为 NULL。**本地无法回算 6-10 月历史序列，UP 的 54%→43% 无法离线验证**。

改为：东财 push2 clist 全A快照（5562 只，实测可用）**前向积累**，今日起每日收盘后
落盘；UP 口径只能前向对照，不做历史回填。冒烟（10-13 盘中）读数 44.24%，
与 UP 10-12 的「约43%」量级吻合，口径可信度初步成立。

## 已落地

1. `src/investment_engine/shadow/concentration.py::compute_concentration`（纯函数，
   top5% 口径，脏数据剔除，5562只→top_n=278）
2. `dataset.py::_load_concentration` + build_daily_pack 接入（块名
   `turnover_concentration`，含 as_of/stale_days/ma20_pct；无数据登记 missing）
3. `scripts/fetch_turnover_concentration.py`（分页拉取 + 覆盖度护栏 n<4000 拒落盘
   + 同日幂等）
4. cron「成交集中度快照拉取」工作日 15:45（job fa9d22b79940，no_agent）
5. 测试 10 用例（compute 5 + load 5，含回放安全/陈旧标注/20日均值）

## 后续（观察项）

- 积累 20 个交易日后 ma20_pct 才有意义；与 UP 后续集中度读数做前向口径对照
- prompt 规则化暂缓（慢变量，LLM 自主引用即可）——与原提案一致

## 差距事实

UP 10-12 复盘（004-f）给出了本轮调整最关键的筹码结构量化：

> 成交额前5%个股交易集中度已从六七月接近 54% 回落至约 43% 的历史中枢；核心卖压来自保险和固收+资金被动去化；二季度新增科技暴露可能已消化七至八成，尚有两至三成需要处理。

这是 UP 判断「出清进入后段但不等于完成」的锚。盲判完全无此维度——**但该指标可用本地数据确定性复算，无需新数据源**。

## 可行性论证

- 计算口径：全市场个股当日成交额排序，top 5% 个股的成交额占全市场比例
- 数据：`infra/data/kline_cache.db` 的 stocks_kline 表已有全市场日K（TDX 成分股池 5364 只持续续拉，含 amount 字段）
- 历史序列：可回算 6-7 月至今的集中度曲线，直接验证 UP 的 54%→43% 读数（验证 UP 数据源口径的一致性，顺便检验本地数据覆盖质量）
- 回放安全：纯当日截面计算，无未来函数

## 处置建议

1. **计算模块**：`shadow/pack` 层新增 `_load_concentration(day)`——top5% 成交额占比 + 20 日均值 + 60 日分位，注入 pack 的 `market_structure` 块（与量能分位并列）。
2. **先验证后接入**：第一步先离线回算 6 月~10 月序列，与 UP 的 54%/43% 两个读数对口径；偏差 >3pct 时先在提案下记录口径差异（如是否含北交所/科创），不急于接入。
3. **prompt 规则暂不加**：集中度是慢变量（周级变化），先在 watch_next 由 LLM 自主引用即可；待验证其与「出清进度」判断的相关性后再考虑规则化。
4. 可选延伸：若验证通过，「集中度回落速率」可作为 crash_loop_attribution 框架（两融/机构互爆归因）的辅助输入。

## 风险

- 口径风险：UP 的「成交额前5%」基数定义未知（全A？沪深？），对不上的话只作趋势参考不作绝对值对标
- stocks_kline 全市场覆盖依赖 TDX 续拉不断档（已有 21:00 cron 守护）
