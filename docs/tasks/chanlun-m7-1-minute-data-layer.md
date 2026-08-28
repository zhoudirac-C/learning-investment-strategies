# M7-1 分钟数据层实施计划

> 设计依据：`docs/design/chanlun-m7-multitimeframe-skill.md` §四（M7-1 设计）。
> 验收（§十一）：单测全绿（不触网）；真实拉取 512400 60m/30m 落库复读一致；既有测试零回归。

## 范围

1. `src/chan_engine/data/fetch.py` 扩展：新浪 → TDX 分钟线降级链（60m/30m）
2. `src/chan_engine/data/store.py` 扩展：`minute_bars` 表 + 读写 + `load_bars(tf)` 适配
3. `scripts/fetch_chan_bars.py` 扩展：`--tf 60/30` 分钟快照入口
4. 测试：`tests/chan_engine/test_data_fetch_minute.py`、`test_data_store_minute.py`（不触网）

## 关键口径（设计 §4 锁定）

- 降级链：新浪 `CN_MarketDataService.getKLineData(scale=60/30)` → TDX(`60min/30min`) → `DataFetchError`；
  库内既有快照即天然 stale 层（调用方复读库即可，数据层不另设缓存文件）。
- 继承 skill 实证坑：腾讯分钟线不可用必须新浪；curl + 完整 UA（urllib 默认 UA 被限流）；datalen=260 上限。
- 归一行：`{"dt": "YYYY-MM-DD HH:MM", "open", "high", "low", "close", "volume"}`，
  dt 截断到分钟（str[:16]）。
- 未收盘 bar 纪律：盘中最后一根 bar `complete=0` 入库保留；判定规则 = `dt > now`（截断到分钟比较，
  now 可注入便于测试）；`load_bars/load_minute` 默认剔除，`include_partial=True` 才返回。
- 窗口声明：260 根 ≈ 60m 2.6 个月 / 30m 1.4 个月；只做滑动窗口快照，不做历史回填。
- `load_bars(code, tf=...)`：tf=None 走既有日线（签名兼容）；tf=60/30 走 minute_bars。
  tf 非法值明确 `ValueError`。

## 任务拆分（TDD：每步先红后绿）

1. **fetch 归一化纯函数**：`normalize_sina_minute_records`（day→dt 截断、volume 原样）、
   `normalize_tdx_minute_records`（datetime→dt）；`mark_complete(rows, now)`。
2. **fetch 降级链**：`fetch_minute(code, tf)` → `_fetch_sina_minute` / `_fetch_tdx_minute`
   （触网，测试全 mock）；tf 校验（仅 30/60）；空结果=成功不降级；双挂报错含明细。
3. **store**：`minute_bars` 建表（设计 §4.2 SQL）；`save_minute` 幂等 upsert；
   `load_minute`（dt 升序、范围过滤、include_partial）；`load_bars` 增 `tf`/`include_partial` 参数；
   `coverage_minute`（per code+tf 范围）。
4. **脚本**：`fetch_chan_bars.py --tf 60 --codes sh512400` 快照入口（真实拉取验收用）。
5. **验收**：pytest 全量（182 绿 + 15 环境 error 基线不回退）；
   `.venv/bin/python scripts/fetch_chan_bars.py --tf 60 --codes sh512400` 与 `--tf 30`
   真实落库 → `load_bars` 复读行数/首尾 dt 一致。

## 非目标（本期）

- 周线/1m/5m；全量历史回填；盘中实时推送；M7-2 对齐层（切片映射）。

## 评审记录（2026-08-28，双 subagent 独立评审：规格符合性 + 代码质量）

**规格符合性结论：符合，无 Critical/Major**（降级链/存储 schema/未收盘 bar 纪律/
验收三证据/M6 兼容逐条核对通过；评审员独立复跑测试与真实库复核）。

**代码质量评审发现 3 Major + 若干 Minor，已全部修复（TDD，新增 14 用例）**：

| # | 发现 | 修复 |
|---|---|---|
| Major-1 | `load_minute` end 传纯日期静默丢当天全部 bar（字符串比较） | end 为 10 字符纯日期自动归一 `+ " 23:59"`，docstring 写明界口径 |
| Major-2 | 脏行（o/h/l/c 为 None）可入库但 `load_bars` 读出即崩 | 双道防线：fetch 层 `validate_minute_rows`（脏行=源端异常 → DataFetchError 触发降级）+ `save_minute` 写入侧拒绝 |
| Major-3 | dt 零校验：缺键产出 `dt="None"` 塌缩主键；纯日期 dt 盘中误判 complete=1（反未来函数） | 同上校验：dt 必须 `%Y-%m-%d %H:%M` 可解析 |
| Minor | `_get_tdx_market` 吞异常丢根因 | 改为抛原始异常，调用方包 DataFetchError 带根因 |
| Minor | `complete=None` 抛裸 TypeError | 缺键/None 均按 1，显式 0 保持 0 |
| Minor | `load_minute` 不校验 tf | 补齐 ValueError（与 save_minute/load_bars 一致） |
| Minor | 验收证据不可重放 | 固化 `tests/chan_engine/test_data_minute_live.py`（`@pytest.mark.live`，常规套件不跑） |

**登记跟进（不阻塞 M7-2）**：
- stale-age 提示（"快照距今 N 分钟，盘中勿当实时结构"）归 M7-5 报告层——数据层只存 `updated_at`。
- TDX 空结果=成功时脚本仅打印"空"（exit 0），告警语义弱，自动链路需人眼复核；数据安全（不覆盖旧快照）。
- 设计文档 §4.1 链末级"stale 缓存"已同步为落地口径（库内快照承载）。

**修复后回归**：`pytest tests/chan_engine/`（排除 2 个环境依赖文件）233 passed（=182 基线 + 51 数据层）+ 2 live deselected + 15 环境 error 基线一致；live 用例真实跑通（60m/30m 各 1 例）；真实快照脚本复跑 260/260 行不变。

## 验收记录（2026-08-28，全部通过）

- **单测全绿（不触网）**：`pytest tests/chan_engine/`（排除 2 个环境依赖收集错误文件）
  219 passed = 基线 182 + 新增 37（test_data_fetch_minute 23 + test_data_store_minute 14）；
  15 个 czsc/Chan 环境依赖 error 与基线一致，零回归。
- **真实拉取落库复读一致**：`fetch_chan_bars.py --tf 60/30 --codes sh512400` 源=sina，
  60m 260 行 2026-05-29 10:30~2026-08-28 15:00；30m 260 行 2026-07-15 13:30~2026-08-28 15:00
  ——与设计文档附录 A spike 窗口精确一致；load_minute/load_bars 复读行数、首尾 dt、
  OHLC、ts 序列全对得上；收盘后 complete 全 1；重拉重存行数不变（幂等）。
- **既有测试零回归**：日线 fetch/store 21 用例原样通过；load_bars 日线路径签名兼容。
