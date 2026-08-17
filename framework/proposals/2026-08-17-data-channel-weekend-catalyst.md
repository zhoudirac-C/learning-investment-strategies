---
date: 2026-08-17
type: data-channel
status: proposed
source: evals/shadow/attributions/2026-08-17.json
---

# 周末/节假日催化接入盘前盲判数据包

## 分析

盘前盲判 `run_predict_premarket` 的数据包是 `build_daily_pack(prev_day)`——只含前一交易日当日的数据块。周末/节假日期间的产业事件因此物理缺席。2026-08-17 实例：基药目录 9/1 实施（周末报道）、盛科通信亿元交换芯片合同（财联社 8-16）、中际旭创受让中石科技 10.47% 股权（8-13 公告周末发酵）、霍尔木兹通行变量——UP 早盘以这批周末事件为方向理由，盲判只能靠"昨日涨幅+隔夜美股"做价格追随。当日中石科技 20cm 二连板，缺口直接兑现为方向理由质量差。

现有通道的两个孔：

1. `build_daily_pack` 的 `news_titles` 块只取 `day`（=前一交易日）当日，不覆盖 `prev_trading_day..target_day` 区间；
2. `infra/data/kpl/news/` 目录仅覆盖交易日（2026-08-15/08-16 无目录），fetch 调度本身不含周末——周末新闻是否可拉需先确认（财联社周末有发布，KPL 侧待验证）。

防泄漏边界不变：注入内容限中性事件源（公告/资讯标题与摘要），UP 言论类内容（bilibili raw、claims、wiki）不得入盲判包；出厂仍由 `assert_no_leakage`（边界=预测日）终检。

## 处置建议

1. premarket 打包时扫描 `prev_trading_day..target_day` 区间的新闻产物（复用 `_load_news_titles` 语义化输出或 `scripts/kpl_news_digest.py` 的摘要），注入 `pack["catalysts_since_prev_day"]`，缺失如实省略；
2. fetch 侧确认 KPL 周末新闻可得性：可拉则 cron 增加周末拉取，不可拉则盘前补拉或降级为隔夜美股映射 + 公告源；
3. 拥挤度（前5%个股成交集中度）与融资余额：本地无数据源，本次仅备案，不开通道。
