# K 线每日拉取调度备忘（2026-08-08 建）

> 用途：记录本机 K 线缓存的每日续拉调度现状与注销义务，供后续会话/云部署核对。

## 现状

- **本机 crontab 有一条临时任务**（`crontab -l` 可见）：
  ```
  35 15 * * 1-5 cd /Users/cong.zhou/Documents/quantitative/learning-investment-strategies && .venv/bin/python scripts/pre_fetch_klines.py >> log/pre_fetch_klines.log 2>&1
  ```
  工作日 15:35（在脚本允许的 15:00-16:30 收盘后窗口内）拉取 watchlist+positions+stock_pool 全部标的的最近 90 根日 K，写入 `infra/data/kline_cache.db`。
- **建立背景**：M0 验收时发现 `infra/data/kline_cache.db` 是空库（v2.1 文档假设的"现成积累"不成立），当日 FORCE 回填 217 只（覆盖 2026-04-27 起）；M1 又补拉了指数（`IDX000300`/`IDX000001`，`scripts/fetch_index_klines.py`）。缓存连续性靠每日续拉维持。
- **本机无其他调度**：无 hermes wrapper（`~/.hermes/scripts/` 不存在）、无 launchd 任务、`log/agent.pid` 是死进程号。AGENTS.md 描述的 hermes cron 架构是云端形态。

## 注销义务（用户明确要求）

这条 cron 是**本机测试用**临时措施，正式运行态在云端部署。云部署完成（或用户通知测试结束）后必须注销：

```bash
crontab -l | grep -v 'pre_fetch_klines' | crontab -
```

注销前确认云端已有等效调度（云端 cron 设 `HERMES_REPO_ROOT` 并走 `~/.hermes/scripts/` wrapper 架构）。

## 相关变更

- 2026-08-08：`.venv` 安装了 `pytdx 1.72`，TDX 链路验证可用（此前 pre_fetch 因缺 pytdx 走腾讯 API 降级）。pytdx 未写入 pyproject 依赖——pre_fetch 对其缺失有优雅降级，属可选增强；云端若要启用 TDX 需 `pip install pytdx`。
- 指数不在 `pre_fetch_klines.py` 的提取范围（它只拉个股 yaml 里的代码）；指数续拉用 `scripts/fetch_index_klines.py`，**该脚本未入 cron**——M2/M3 若需要指数连续数据，应把指数拉取并入每日任务或云端调度。
