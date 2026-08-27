# index_klines 表 daily 收盘价覆盖 bug（2026-08-13 实测 + 修复）

## 症状

`index_klines` 表里 `timeframe='daily'` 的 **close 全部是早盘盘中快照，不是收盘价**。

| 日期 | index_klines 存的 close | 腾讯权威收盘 | 偏差 |
|------|----------------------|------------|------|
| 8/12 | 3938.1 | 3946.68 | -8.6 点 |
| 8/11 | 3959.18 | 3934.09 | **+25 点（方向反了）** |
| 8/10 | 3958.81 | 3966.59 | -7.8 点 |

## 根因

`scripts/update_index_klines_intraday.py` 的 `update_one()` 用了这段判断：

```python
if db_latest and db_latest >= newest_bar:
    return {"status": "up_to_date", ...}   # 直接跳过
```

daily 级别 `bar_time` **只有日期**（`'2026-08-12'`，无时分）。早盘 9:52 写入盘中快照后，
`db_latest == '2026-08-12'`。收盘 15:30 再拉，`newest_bar` 还是 `'2026-08-12'`，
`db_latest >= newest_bar` 成立 → 判定"已最新"跳过 → **收盘价永远覆盖不了早盘快照**。

分钟级（30/60/120min）不受影响，因为它们的 `bar_time` 带时分（`'2026-08-12 14:30'`），
每根 bar 天然不同。

## 修复（TDD）

新增 `tests/investment_engine/test_index_klines_intraday_update.py`：

1. `test_close_override_when_same_bar_time`：早盘快照 close=3938.1，收盘 API 返回同 bar_time
   close=3946.68 → 断言 DB 里被覆盖为 3946.68，`status == 'updated'`
2. `test_no_change_returns_up_to_date`：close 不变 → 不重复写

改 `update_one()` 逻辑：

```python
# 判断从 >= 改 > （同 bar_time 允许继续走覆盖逻辑）
if db_latest and db_latest > newest_bar:
    return up_to_date

# 找出「同 bar_time 但 close 变化」的 bar → 视为待覆盖更新
existing_close = {r["bar_time"]: r["close"] for r in existing_bars}
override_bars = [
    k for k in latest
    if k["bar_time"] in existing_times
    and k["bar_time"] == newest_bar
    and abs((existing_close[k["bar_time"]] or 0) - (k["close"] or 0)) > 1e-6
]

if not new_bars and not override_bars:
    return up_to_date

# 覆盖 bar 先移除旧值再并入新值，重算 MACD 后 INSERT OR REPLACE
replace_times = {k["bar_time"] for k in override_bars}
base_bars = [b for b in existing_bars if b["bar_time"] not in replace_times]
all_bars = base_bars + new_bars + override_bars
```

`test_close_override_when_same_bar_time` 会先 RED（返回 up_to_date 而非 updated），改完 GREEN。

## 回填正确收盘价（腾讯接口，非东财盘中接口）

东财 `push2his` 盘中接口当前连不上（`Remote end closed connection without response`），
但腾讯 `web.ifzq.gtimg.cn/appstock/app/fqkline/get` 稳定，且能拉 `sh000300`/`sh000852`：

```python
# 腾讯日K字段：日期, 开盘, 收盘, 最高, 最低, 成交量（qfqday / day 数组）
url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={full_code},day,{start},{end},{n},qfq"
# 返回 data[full_code]["qfqday"] or ["day"]，每项 [date, open, close, high, low, volume]
```

7 个指数一次回填（DELETE 后 INSERT 覆盖写 daily）：`sh000001/sh000300/sh000852/sh000985/
sz399001/sz399006/sh000932`，各 147 根（2026-01-05 ~ 08-12）。

## 相关架构决策（同一会话）

指数数据源**统一到 index_klines 表**（不再用 stocks_kline 的 IDX 别名）：

- 新增 `src/investment_engine/backtest/history.py::get_index_daily()`：读 index_klines daily，
  code 接受 IDX 别名或实际代码，内部 `INDEX_ALIAS_TO_CODE` 映射，pct_change 由 close 序列补算
- `INDEX_ALIAS_TO_CODE = {IDX000300: sh000300, IDX000001: sh000001, IDX399006: sz399006,
  IDX399001: sz399001, IDX000852: sh000852}`
- 消费方改接：`dataset.build_daily_pack`（指数块）、`truth.load_truth`、`score._forward`
  （bench 指数走 get_index_daily，个股仍走 get_klines_range）、`limit_pool` 偏离基准
- `update_index_klines_intraday.py` 的 `INDICES` 加 `sh000300`/`sh000852`（东财 secid `1.000300`/`1.000852`）
- `kline_cache.py` 新增 `save_index_klines()`（测试夹具/回填共用写 index_klines）

## 复用给其他会话的要点

1. 判断"某表数据缺失"前，先 `cronjob list` 核对现有定时任务——用户明确纠正过
   "我记得有拉指数日K和个股日K的定时任务呀"，数据拉取任务往往在，只是**没对齐消费方口径**。
2. 两张 K 线表永远先分清 `stocks_kline`（trade_date + 个股 + 旧指数别名）vs
   `index_klines`（bar_time + timeframe 多级别 + 指数实际代码），盲判/监控各读其一。
3. 手动补跑 pre_fetch 必须 `FORCE_KLINE_FETCH=1`，否则脚本会因「非预拉取窗口」静默跳过。
