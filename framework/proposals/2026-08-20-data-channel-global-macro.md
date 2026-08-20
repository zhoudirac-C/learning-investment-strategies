---
date: 2026-08-20
type: data-channel
status: implemented（2026-08-20，见下方实施记录；激活依赖姊妹提案主轨）
source: framework/proposals/2026-08-19-pattern-patch-note.md（根因 2）+ evals/shadow/attributions/2026-08-19.json
---

# 全球宏观数据通道：global_macro 块接入盲判数据包

## 分析

2026-08-19 判错根因 2：复盘盲判判「调整/内生瓦解」，UP 定性「外力扰动」
（美债长端 → 美股半导体/存储链 → 韩股熔断 → A股第四棒），而盲判数据包没有任何
全球宏观维度，判错是结构性的：

- `build_daily_pack`（`src/investment_engine/blindtest/dataset.py`）无美债收益率、
  无费城半导体指数、无存储链 ADR、无亚太股指；
- `overnight_us` 仅含美股映射个股，且只在盘前路径注入
  （`src/investment_engine/shadow/premarket.py:149`）；复盘路径
  （`src/investment_engine/shadow/predict.py`）完全不加载——复盘盲判要答
  「外力/内生」题却没有外部数据。

同日 UP 跟踪清单前五条中三条是外部变量（今夜美股/费半/存储 ADR 收盘位置、
30Y 美债能否守 5.33%、震中能否率先企稳），外力驱动日的关键观察变量全部
不在数据包内。

## 处置建议

1. 新增 `global_macro` 块，盘后落盘 `infra/data/global_macro/{yyyymmdd}.json`，
   dataset 入包（缺失登记 missing），字段：
   - 美股三指数（道指/纳指/标普）涨跌幅；
   - 费城半导体指数（SOX）涨跌幅；
   - 存储链 ADR/个股：铠侠、闪迪、希捷、西数、美光（美光已在 overnight_us，
     其余为增量）；
   - 亚太股指：KOSPI、日经 225、恒生（当日收盘涨跌幅，韩股熔断/Sidecar 类
     事件无法从行情推出，如实缺省，靠 news 通道补）；
   - 美债 10Y/30Y 收益率水平与变动（bp）。
2. 复盘路径补注入 `overnight_us`（与盘前同一精简结构），使「隔夜外盘」对
   22:00 复盘盲判可见。
3. 数据源分档（2026-08-20 本机直连实测）：
   - **可用，直接复用现有通道**：腾讯 `qt.gtimg.cn`（usDJI/usIXIC/hkHSI 实测有数，
     与 `overnight_us.py` 同通道同鉴权）；新浪 `hq.sinajs.cn`
     （int_nasdaq/int_dji/int_nikkei/int_hangseng 实测有数，需 Referer 头、
     GBK 解码）；
   - **本机无直接免费通道，列为评估项**：费城半导体（腾讯 usSOX、新浪 int_sox
     均空）、韩股 KOSPI（新浪 int_kospi/int_kospi200 空、腾讯 krKOSPI 无匹配）、
     美债收益率（腾讯 wh 系无匹配、Yahoo v8 本机限流 Too Many Requests、
     stooq 404）；东财 push2 全球接口此前已实测云 IP 反爬弃用
     （见 `overnight_us.py` 模块 docstring）。评估方向：东财另一组全球指数
     接口、akshare 宏观接口（注意 08-18 实施记录中 akshare 分钟接口本机拒连
     的教训，先本机实测再接线）；
   - **过渡期降级**：以「美股三指数 + 已在包存储链个股（美光等）+ 亚太可得的
     日经/恒生」近似外力监测，缺口字段在 pack 中如实标注
     「数据缺失，信息差风险」（规则 11(c) 已有降级机制）；
   - **代理通道补充实测（2026-08-20 晚，sakura 代理 mihomo 127.0.0.1:7890）**：
     前述「无直接免费通道」缺口经代理全部打通——Yahoo v8
     `query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d`
     （免费无 key；本机直连 403，须走代理）：`^TNX`（10Y 收 4.653）、`^TYX`
     （30Y 收 5.194，与 UP 复盘「5.196%」吻合）、`^FVX`、`DX-Y.NYB`（美元指数
     98.81）、`^KS11`（KOSPI）/`^KQ11`、`^IXIC`/`^NDX`、`^GSPC`/`^DJI`、
     `^SOX`（费半收 11738.23）、`^N225`/`^HSI`、存储链 `MU/SNDK/STX/WDC`
     全部实测有数；备份通道 CNBC
     `quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=US10Y|US30Y|.DXY|.KS11|.IXIC`
     实测有数（10Y 实时 4.641%）；stooq 代理下仍反爬（PoW 验证/404）、FRED
     fredgraph.csv 代理下超时，均弃用。工程注意：fetch 脚本须显式挂代理
     （`HTTPS_PROXY=http://127.0.0.1:7890`）+ UA 头 + 串行限速；节点可能半死
     （mihomo 测速通但中继断，本次「香港-直连」即此态，切「香港-中转 01」后通），
     接口失败先切节点再下结论；
4. 实施形态对齐 `sector_intraday` 先例：独立模块
   `src/investment_engine/global_macro.py`（compute/save/load 三件套）+
   `scripts/global_macro_fetch.py`（幂等落盘，cron 盘后窗口与现有任务错峰），
   盘前路径在 `overnight_us` 注入处一并注入，复盘路径新增注入；
   防泄漏边界不变：仅客观行情数据，出厂 `assert_no_leakage` 终检。
5. 验收：2026-08-19 回放——复盘盲判 stage_reason 应能引用外盘链条数据，
   nature 具备判「外力扰动」的数据基础（判断对错不论，数据在场与否可机械核验）。

## 证据

- `evals/shadow/predictions/2026-08-19.json`（调整/内生瓦解，stage_hit=false）；
- `sources/original/bilibili/2026-08-19-2243-专栏-今天这根大阴线….md`（UP 复盘：
  四棒传导链、跟踪清单外部变量优先）；
- 2026-08-20 本机实测记录（见处置建议 3）。

## 实施记录（2026-08-20）

- **模块**：`src/investment_engine/global_macro.py`（compute/save/load 三件套，
  对齐 sector_intraday 先例）+ `scripts/global_macro_fetch.py`（幂等落盘，
  `--date` 支持历史日重算）。通道 = Yahoo v8 chart 经 sakura 代理
  （`GLOBAL_MACRO_PROXY` 可覆盖，默认 127.0.0.1:7890），串行限速 0.4s、
  单品种失败记 errors 不阻断、全败返回 None 不落盘。
- **as-of 防泄漏规则**：只保留「交易所收盘时刻 ≤ min(拉取时刻, 当日 22:00 北京)」
  的 session bar（美股 16:00 ET / 日韓 15:30 / 港 16:00，按 meta.gmtoffset 换算）。
  A股日 D 的文件：美股到 session D-1、亚太到 session D；历史日重算同一规则，
  不混入未来 session（有测试守护）。
- **品种**（15 个，中文键入包）：美股三指数（^DJI/^IXIC/^GSPC）、费半（^SOX）、
  存储链（MU/SNDK/STX/WDC + 铠侠 285A.T——无美股 ADR，用东京上市主体）、
  亚太（^KS11/^N225/^HSI）、美债 10Y/30Y（^TNX/^TYX，yield + chg_bp）、
  美元指数（DX-Y.NYB）。
- **坑**：Yahoo 边缘按 UA 分桶限流——完整 Chrome UA → 429，短 "Mozilla/5.0" → 200
  （模块内注释警告别改回）；代理节点半死时 mihomo 测速仍通，接口失败先切节点。
- **接线**：`dataset.build_daily_pack` 新增 `global_macro` 块（GM_ROOT 落盘读取，
  fetched_at 不进包，缺失登记 missing）——盘前/复盘两路自动携带；另按提案 2，
  复盘路径 `predict.run_predict` 补注入 `overnight_us`（premarket 抽出
  `slim_overnight` 共用，精简结构与打码规则不变）。
- **验收**（`logs/global-macro-acceptance-20260820.log`）：回灌 20260819.json
  15/15 有数，与 UP 四棒链逐项吻合（费半 -4.98%、美光 -7.02%、铠侠 -12.6%、
  KOSPI -5.8%、30Y 5.285）；pack 在场性、防泄漏、overnight_us 注入均机械核验
  通过。DeepSeek 08-19 回放（独立于真实预测记录）：validation passed，但
  stage_reason 仍全引内部指标、未引外盘链条——**数据在场 ≠ 数据被用**，激活
  依赖姊妹提案主轨（`2026-08-19-pattern-patch-note.md` 归因步骤前置）。
- **测试**：`test_global_macro.py` 9 用例（as-of 完整性/亚太当日计入/收益率 bp/
  回灌封顶/全败 None/部分失败 errors/None-close 跳过/落盘往返/品种覆盖）；
  `test_dataset.py` 增补 global_macro 块断言与 missing 清单；`test_predict.py`
  增补复盘 overnight_us 注入/缺文件不注入 2 用例。
- **cron 待挂**：建议工作日 16:35（与 sector_intraday 15:40、intraday_amount
  15:35 错峰），wrapper 形态对齐 `~/.hermes/scripts/qing_intraday_amount_fetch.py`。
