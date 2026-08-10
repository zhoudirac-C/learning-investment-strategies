# 东财龙虎榜日榜接入 spec（盲判包 lhb 块补强）

日期：2026-08-11
状态：done（2026-08-11 实施完毕，验收全过）
前置：2026-08-11 实测确认 KPL `UserBusiness.GetDay` 对本账号不返回席位明细
（抓包样本+3 次实测一致，见 `docs/design/kpl-api-inventory.md` §5），
盲判包 lhb 块将持续 `count=0`，需独立数据源补强。

## 目标

每个交易日傍晚自动拉取当日龙虎榜：**日榜股票清单（含上榜原因、买卖净额）+
逐股买卖席位（营业部名称、金额）**，落盘本地并进入 18:05 shadow 盲判数据包，
让"游资/机构席位动向"在盲判中可见。

## 数据源（2026-08-11 实测可用，无需鉴权）

东财数据中心公开接口 `https://datacenter-web.eastmoney.com/api/data/v1/get`：

| 用途 | reportName | 实测 |
|---|---|---|
| 日榜清单 | `RPT_DAILYBILLBOARD_DETAILS`，filter `TRADE_DATE='<day>'` | 08-10 共 70 条，字段含 SECURITY_CODE/SECURITY_NAME_ABBR/EXPLANATION(上榜原因)/CLOSE_PRICE/CHANGE_RATE/BILLBOARD_NET_AMT/BUY_AMT/SELL_AMT/TURNOVERRATE |
| 逐股买席 | `RPT_BILLBOARD_DAILYDETAILSBUY`，filter `(TRADE_DATE)(SECURITY_CODE)` | 08-10 风华高科 5 席：OPERATEDEPT_NAME/BUY/SELL/NET |
| 逐股卖席 | `RPT_BILLBOARD_DAILYDETAILSSELL`，同上 | 同上结构 |

## 设计

### 新模块 `src/investment_engine/eastmoney_lhb.py`

- `fetch_daily_list(day) -> list[dict]`：日榜清单（分页 pageSize=500 一页拿完）
- `fetch_seats(day, code) -> {"buy": [...], "sell": [...]}`：单股买卖席位
- `fetch_lhb(day) -> dict`：组装 `{trade_date, stock_count, items:[{code,name,reason,
  close,change_pct,net_amt,buy_amt,sell_amt,turnover,buy_seats,sell_seats,seat_error?}],
  fetched_at, note}`
- `save_lhb(data, out_root, day)`：写 `<out_root>/lhb/<day>.json`
- HTTP 收敛在一个 `_get_json(url)`，测试 monkeypatch 它；请求间隔 sleep 0.15s，
  单股席位失败不阻断整体（该股记 `seat_error`，note 汇总）
- 席位拉取范围：全部上榜股（08-10 规模 70 股 × 2 请求 ≈ 140 请求 + 间隔 ≈ 30s，可接受）

### 新脚本 `scripts/eastmoney_lhb_fetch.py`

- `--date`（默认今日）`--out-root`（默认 `infra/data/eastmoney`）`--force`
- 幂等：目标文件已存在则跳过；退出码沿用 kpl_daily_fetch 约定（0 成功/1 失败）
- 防御：返回清单为空或 `TRADE_DATE` 非目标日 → 落盘 `note` 标注"披露未出"，
  退出码 0（次日可 `--date` 补拉）

### cron

现行：`15:35 pre_fetch` / `17:45 KPL` / `18:05 shadow`。
新增 `17:50 eastmoney_lhb_fetch`（KPL 之后 5 分钟，东财日榜一般 17:00-18:00 出齐；
若 17:50 未出全，当日 shadow 包 note 如实标注，次日手动补拉）。

### 盲判包接入（`blindtest/dataset.py`）

- `build_daily_pack` 新增 `em_root=None` 参数（默认 `infra/data/eastmoney`）
- `_load_lhb` 改为：**优先东财**（`em_root/lhb/<day>.json`，块加 `source: "eastmoney"`，
  items 封顶 `_LHB_ITEM_CAP` 条按 `|net_amt|` 排序，席位每股买卖各封顶 5 席）；
  东财缺失回退 KPL 文件（`source: "kpl"`）；两者皆无 → `missing` 标注 `kpl_lhb`
  （missing 代号不变，避免破坏既有分析口径）
- `PROMPT_VERSION` 不变（prompt 文本未改）；记录内 `lhb.source` 可辨识数据形态

### KPL 交叉验证（可选，本期不做）

KPL `Stock.GetNewOneStockInfo` 含"知名游资"图标标注（YouZiIcon 等），
后续可对东财席位名单做游资身份增强。本期仅保留东财原始字段。

## 范围外

- 不改 KPL `GetDay` 拉取（继续落盘，保留观察）
- 不改 `PROMPT_VERSION`、不改 shadow 输出契约字段
- 不做历史回填（东财支持按日查询，需要时 `--date` 逐日补）

## 验收

1. `tests/investment_engine/test_eastmoney_lhb.py`：清单解析/席位解析/空披露容忍/
   单股席位失败不阻断/落盘往返，全 fake HTTP
2. `test_dataset.py` 增补：东财优先、KPL 回退、双缺失标注
3. 手动 `--date 2026-08-10` 拉取落盘，肉眼核对股票数与东财网页一致（70 只）
4. 用 08-10 数据 `build_daily_pack` 拼包，`pack["lhb"]["source"]=="eastmoney"`，
   防泄漏断言通过，prompt 体量可控（席位封顶后估算 < 6KB）
5. `.venv/bin/pytest tests/investment_engine -q` 全绿
6. crontab 更新（改前备份）
