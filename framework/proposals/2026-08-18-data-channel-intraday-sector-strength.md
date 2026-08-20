---
date: 2026-08-18
type: data-channel
status: implemented（2026-08-19，见下方实施记录）
source: evals/shadow/attributions/2026-08-18.json
---

# 板块分时强度接入盲判数据包（拉升时段定位）

## 分析

2026-08-18 UP 核心推理「下午拉升由银行完成 = 避险资金抬指数 = 诱多嫌疑」依赖**分时段**的
板块强度：拉升发生在哪个时段、由哪类板块完成。现有通道：

- `fund_flow`（东财行业/概念资金流）：只有当日累计值，无法定位拉升发生的时段；
- `intraday_amount`：只有两市总量的分时形态（冲量滑落等），无板块维度；
- `limit_pool` / `emotion`：情绪口径，无板块分时。

该缺口直接阻断同日「拉升资金性质定性」模式提案（pattern-lift-fund-nature）的机械化执行——
模式成立所需的关键观察变量不在数据包内。

## 处置建议

1. 评估东财/新浪板块行情接口（行业板块指数分时 K 线，或分时段资金流），盘后拉取主要行业板块
   分时涨跌幅，压缩为「午后加强 / 午后转弱 / 全天强势」标记入 pack（如
   `sector_intraday: {银行: 午后加强, 科技: 午后转弱}`），缺失如实省略；
2. 过渡期降级方案：用 fund_flow 行业即时净流入方向 + 高股息板块（银行/煤炭/石油）当日
   相对涨跌幅近似防御拉升判定，并在 pack 中标注近似口径；
3. 防泄漏边界不变：仅客观行情数据，出厂仍由 `assert_no_leakage` 终检。

## 实施记录（2026-08-19）

- 通道变更：东财板块分钟接口（akshare）本机实测拒连，改用 **TDX 880 板块指数
  60min K线**（与 intraday_amount 同通道，已生产可用）。880 代码映射取通达信二级
  行业指数公开对照表 + 2026-08-18 涨跌幅行为核验（pct 指纹在 TDX/东财分类口径
  差异下不可靠，已如实记录误配教训）；
- 新增 `src/investment_engine/sector_intraday.py`：11 个板块（防御 6：银行/煤炭/
  石油/电力/农林牧渔/医疗保健；进攻 5：半导体/通信设备/软件服务/元器件/证券），
  全日/上午/下午涨跌幅分解 + 强弱标记（真强势=上午不弱+午后走强；超跌反弹=
  上午深跌+午后回升）+ `pm_lead_camp` 阵营拉升定性（比真强势只数）；
- 关键设计修正：初版按午后均值定性会把 8-18 误判为「均衡/进攻」（全板块午后
  普升）；改按真强势只数后输出「防御」，与 UP「下午拉升由银行完成」一致；
- 落盘 `infra/data/sector_intraday/{yyyymmdd}.json` + `scripts/sector_intraday_fetch.py`
  （幂等；cron 已注册 2026-08-19：job `5acc325e7cda`，`42 15 * * 1-5`，
  包装 `~/.hermes/scripts/qing_sector_intraday_fetch.py`，与 fund_flow 同窗口错峰 2 分钟）；
  dataset 入包 `sector_intraday` 块（缺失登记 missing）；
- 8-18 实测：pm_lead_camp=防御，与 UP 复盘一致；测试
  `tests/investment_engine/test_sector_intraday.py` 9 用例 + dataset fixture 全绿（42 passed）。
- 盘前守卫（2026-08-19 08:52 踩坑记录）：盘前/盘中拉取时部分板块会带出当日
  stub bar（close=昨收 → 0.0% 假行，实测 4/11 板块中招），落盘 `20260819.json`
  后幂等机制会挡住收盘后的真实重拉。已加两道守卫：①最新日末根必须是 15:00
  bar 否则剔除该板块；②跨板块日期取众数（并列取最新），杜绝混合交易日文件。
