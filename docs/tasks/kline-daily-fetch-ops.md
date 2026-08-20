# K 线每日拉取调度备忘（2026-08-08 建，2026-08-13 云端调度重构）

> 用途：记录 K 线缓存与影子双轨的每日调度现状，供后续会话/云部署核对。

## 现状（云端 Hermes cron，2026-08-13 起）

本机 Mac 的 crontab 是旧形态（测试期），正式运行态在云端，走 Hermes cron + `~/.hermes/scripts/` wrapper。

| 时点 | 任务 | 脚本 | 说明 |
|------|------|------|------|
| 6-8 点（`0,30 6-8 * * 1-5`） | 个股日K预拉取 | `qing_pre_fetch_klines.py` | watchlist+positions+stock_pool 全标的 90 根日K，写 `stocks_kline` |
| 08:20（`20 8 * * 1-5`） | 隔夜外盘映射 | `qing_overnight_us_fetch.py` | 美股映射股涨跌，落盘 `infra/data/overnight_us/` |
| 09:10（`10 9 * * 1-5`） | 全球宏观快照（盘前） | `qing_global_macro_fetch.py` | 隔夜美股/美债/美元收盘 + 亚太昨收，落盘 `infra/data/global_macro/`，供 9:28 早盘盲判 |
| 9-15 点（`*/30 9-15 * * 1-5`） | 指数K线盘中增量 | `update_index_klines_intraday.sh` | 7 指数多级别K线，写 `index_klines`（收盘后那次覆盖成收盘价） |
| 9:28（`28 9 * * 1-5`） | 影子双轨早盘盲判 | `qing_shadow_premarket.py` | 预测当日（T-1 收盘 + 隔夜外盘） |
| 15:35（`35 15 * * 1-5`） | 个股日K收盘后补拉 | `qing_pre_fetch_klines.py` | 补当日收盘日K（早盘那次只拉到前一日） |
| 16:35（`35 16 * * 1-5`） | 全球宏观快照刷新（盘后） | `qing_global_macro_refresh.py` | `--force` 重拉补亚太当日收盘，供 22:00 复盘盲判归因 |
| 22:00（`0 22 * * 1-5`） | 影子双轨复盘盲判 | `qing_shadow_daily.py` | 判当日 + 到期结算 + 归因 |

KPL 拉取（本机 17:45）在云端未挂 cron——缺 `kpl_user_id/kpl_token/kpl_device_id` 凭据，
云端盲判数据包 KPL 块降级为 `missing` 标注，不阻断。

## 架构变更（2026-08-13）：指数数据源统一到 index_klines 表

- 盲判/评分/真值标签的指数**统一读 `index_klines` 表**（不再读 `stocks_kline` 的 IDX 别名）。
- 新增 `history.get_index_daily()` + `INDEX_ALIAS_TO_CODE` 映射（IDX000300→sh000300 等）。
- 原因：写 IDX 别名的 `fetch_index_klines.py` 从未挂 cron（数据会断），而 index_klines 有盘中 cron 持续更新。
- `update_index_klines_intraday.py` 的 `INDICES` 扩充为 7 个（加沪深300 `sh000300`、中证1000 `sh000852`）。
- 修复了 `index_klines` daily 收盘价覆盖 bug（早盘快照永远覆盖不了收盘价），
  细节见 skill `qing-shadow-dual-track/references/index-klines-daily-override-bug.md`。

## 2026-08-16 增补：LHB/初调/研报 cron 与披露边界

- **新挂 3 条 cron**（jobs.json 已登记，wrapper 在 `~/.hermes/scripts/`）：
  `50 17 * * 1-5` 东财龙虎榜（qing_eastmoney_lhb_fetch.py）、
  `55 17 * * 1-5` KPL 资讯初调摘要（qing_kpl_news_digest.py）、
  `10 18 * * 1-5` 东财研报/公告（qing_fetch_research_reports.py）。
- **修正上文**：KPL 凭据（kpl_user_id/kpl_token/kpl_device_id）已配置进 `.env`，
  17:45 拉取 cron 在挂（此前"云端未挂"已过时）。
- **东财 LHB 披露边界**：历史任意日可回溯（2026-08-16 实测回填 2026-04-27 起全量）。
  实盘披露时点**从未实测**——contract-v2 spec 假设的"17:50 cron 首周观察"实际从未挂载，
  本次为首次挂载；17:50 可能早于当日完整披露。下周首个实盘周观察后补记实际边界；
  若 17:50 拿到空/不全，22:00 影子盲判前需补拉一次。
- **KPL 资讯分页**：实测不可得（分页/游标参数全被忽略），见
  `docs/design/kpl-api-inventory.md`「资讯列表分页实测」节；日产量≈窗口大小，维持单拉。

## 注销义务（用户明确要求）

本机 Mac crontab 是测试用临时措施。云部署完成（已确认等效调度）后注销：

```bash
crontab -l | grep -v 'pre_fetch_klines\|shadow_daily\|kpl_daily_fetch' | crontab -
```

## 相关变更

- 2026-08-08：`.venv` 装了 `pytdx 1.72`（TDX 链路，可选增强，未入 pyproject）。pre_fetch 缺 pytdx 时走腾讯 API 降级。
- 2026-08-10：KPL 每日拉取（15:45→17:45）。接口细节见 `docs/design/kpl-api-inventory.md`。云端缺凭据未挂。
- 2026-08-10：cron 读权限事件（MDM 收回 cron 的完全磁盘访问权限）。再发先查 `/var/mail/$USER`。
- 2026-08-11：复盘时序推后 18 点档（KPL 15:45→17:45、shadow 15:40→18:05），盲判包接入 KPL 三块。
- 2026-08-13：**云端调度重构**——指数统一 index_klines + 修 daily 覆盖 bug + 早盘盲判（9:28）+
  复盘盲判 22:00（原 18:05，尽量贴近 UP 复盘时间）+ 收盘后个股补拉（15:35）+ 隔夜外盘（08:20）。
