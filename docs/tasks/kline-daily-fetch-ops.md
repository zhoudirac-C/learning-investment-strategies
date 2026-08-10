# K 线每日拉取调度备忘（2026-08-08 建）

> 用途：记录本机 K 线缓存的每日续拉调度现状与注销义务，供后续会话/云部署核对。

## 现状

- **本机 crontab 有一条临时任务**（`crontab -l` 可见）：
  ```
  35 15 * * 1-5 cd /Users/cong.zhou/Documents/quantitative/learning-investment-strategies && .venv/bin/python scripts/pre_fetch_klines.py >> log/pre_fetch_klines.log 2>&1
  ```
  工作日 15:35（在脚本允许的 15:00-16:30 收盘后窗口内）拉取 watchlist+positions+stock_pool 全部标的的最近 90 根日 K，写入 `infra/data/kline_cache.db`。
- **建立背景**：M0 验收时发现 `infra/data/kline_cache.db` 是空库（v2.1 文档假设的"现成积累"不成立），当日 FORCE 回填 217 只（覆盖 2026-04-27 起）；M1 又补拉了指数（`IDX000300`/`IDX000001`，`scripts/fetch_index_klines.py`）。缓存连续性靠每日续拉维持。
- **本机 crontab 另有 M2 影子双轨任务**（2026-08-08 随 M2-T7 挂接）：
  ```
  5 18 * * 1-5 cd /Users/cong.zhou/Documents/quantitative/learning-investment-strategies && set -a && source .env && set +a && .venv/bin/python scripts/shadow_daily.py >> log/shadow_daily.log 2>&1
  ```
  工作日 18:05（KPL 之后 20 分钟）跑影子双轨日更：产出当日预测（`evals/shadow/predictions/`）、到期结算、归因与 `logs/shadow-status.md`。需要 DeepSeek API key，故显式 `source .env`。
- **本机 crontab 另有 KPL 每日拉取任务**（2026-08-10 随 KPL 接入挂接）：
  ```
  45 17 * * 1-5 cd /Users/cong.zhou/Documents/quantitative/learning-investment-strategies && set -a && source .env && set +a && .venv/bin/python scripts/kpl_daily_fetch.py >> log/kpl_daily_fetch.log 2>&1
  ```
  工作日 17:45 拉 KPL 情绪快照（`Index.GetInfo` 全量 View）+ 当日资讯全文 + 龙虎榜游资榜（`UserBusiness.GetDay`），落盘 `infra/data/kpl/`（gitignored）。依赖 `.env` 的 `kpl_user_id/kpl_token/kpl_device_id`；token 失效时脚本退出码 3、日志有重抓指引（`docs/design/kpl-api-inventory.md`）。龙虎榜 T 日收盘后披露，披露未出时 List 为空属正常（落盘 note 标注）。
- **本机无其他调度**：无 hermes wrapper（`~/.hermes/scripts/` 不存在）、无 launchd 任务、`log/agent.pid` 是死进程号。AGENTS.md 描述的 hermes cron 架构是云端形态。

## 注销义务（用户明确要求）

这条 cron 是**本机测试用**临时措施，正式运行态在云端部署。云部署完成（或用户通知测试结束）后必须注销：

```bash
crontab -l | grep -v 'pre_fetch_klines\|shadow_daily\|kpl_daily_fetch' | crontab -
```

注销前确认云端已有等效调度（云端 cron 设 `HERMES_REPO_ROOT` 并走 `~/.hermes/scripts/` wrapper 架构）。

## 相关变更

- 2026-08-08：`.venv` 安装了 `pytdx 1.72`，TDX 链路验证可用（此前 pre_fetch 因缺 pytdx 走腾讯 API 降级）。pytdx 未写入 pyproject 依赖——pre_fetch 对其缺失有优雅降级，属可选增强；云端若要启用 TDX 需 `pip install pytdx`。
- 指数不在 `pre_fetch_klines.py` 的提取范围（它只拉个股 yaml 里的代码）；指数续拉用 `scripts/fetch_index_klines.py`，**该脚本未入 cron**——M2/M3 若需要指数连续数据，应把指数拉取并入每日任务或云端调度。
- 2026-08-10：新增 KPL 每日拉取（15:45）。设计与接口见
  `docs/superpowers/specs/2026-08-10-kpl-data-integration-design.md`、
  `docs/design/kpl-api-inventory.md`。实盘验证结论：`Index.GetInfo` 必须带 H5 请求头
  （Origin/Referer/X-Requested-With），否则收盘后降级为空信息流；付费专栏条目
  （6 位 ID）全文 errcode=1130 无权限，逐篇跳过。
- 2026-08-10：**cron 读权限事件**。当日 15:35 pre_fetch 正常，15:40 起 cron 读仓库
  任意文件均 EPERM（错误进 `/var/mail/$USER`，不落 log）。探针定位：封锁范围精确
  =`~/Documents`（家目录根、/tmp 正常），cron 与 launchd 用户代理同被拦，交互 shell
  不受影响；无系统弹窗。本机为公司 MDM（AirWatch）管理，疑 MDM 静默推送隐私策略。
  修复：系统设置 → 隐私与安全性 → 完全磁盘访问权限 → 添加 `/usr/sbin/cron` 并打开
  （当日 18:21 探针验证读权限与 `source .env` 链恢复）。当日 shadow/KPL 数据已手动补跑。
  **再发排查顺序**：`/var/mail/$USER` 看 cron 邮件 → 探针复测 → 检查 FDA 列表里
  cron 开关是否被 MDM 收回。
- 2026-08-11：**复盘时序推后 18 点档**（用户裁决，配合龙虎榜等收盘后披露数据）：
  KPL 15:45→17:45（脚本内 emotion→news→lhb 顺序，lhb 最接近披露窗口）、
  shadow 15:40→18:05。shadow 盲判数据包自此接入 KPL 情绪/资讯标题/龙虎榜三块
  （spec `docs/superpowers/specs/2026-08-10-shadow-pack-contract-v2.md`）；
  指数扩容（创业板指/深成指/中证1000）由 `fetch_index_klines.py` 回填，
  每日由 `shadow_daily.py` 自补续拉。旧 crontab 备份 `/tmp/crontab.bak.20260811`。
