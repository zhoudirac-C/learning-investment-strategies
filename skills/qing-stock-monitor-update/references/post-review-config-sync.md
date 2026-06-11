# Post-Review Config 同步工作流

## 概述

17:00 收盘复盘 cron 的输出被 `sync_config_from_review.py` 自动解析，写回 3 个配置文件。无需手动更新。

## 数据流

```
17:00  收盘复盘 Agent → 分析正文 + ```daily_state JSON 代码块
                           （含 risk_reminder, today_key_signals,
                            tomorrow_scenarios, entry_zone_updates）
17:05  qing_sync_config_from_review.sh → sync_config_from_review.py
        ├─ 扫描 fc7d8a270d84 的最新输出文件
        ├─ 正则提取 ```daily_state JSON 块
        ├─ 写回 strategy_pack.yaml (market_framework.current_stage)
        ├─ 写回 positions.yaml (strategy_summary/risk_reminder/signals)
        └─ 写回 watchlist.yaml (各标的 entry_zone.current_ref)
```

## 涉及的组件

| 组件 | 路径 | 说明 |
|---|---|---|
| Sync 脚本 | `scripts/sync_config_from_review.py` | 核心逻辑 |
| Hermes 包装器 | `~/.hermes/scripts/qing_sync_config_from_review.sh` | cron 入口 |
| Cron job | `107ba7957ed7` | 工作日 17:05 单次触发, no-agent, deliver=local |

## 字段映射

### strategy_pack.yaml

| daily_state 字段 | 目标路径 |
|---|---|
| `market_stage.phase` + `.detail` | `market_framework.current_stage` |
| `direction_priority` | `market_framework.direction_priority` |

### positions.yaml

| daily_state 字段 | 目标路径 |
|---|---|
| `position_stance` | `strategy_summary.current_stage` (追加) |
| `risk_reminder` | `risk_reminder` |
| `today_key_signals` | `today_key_signals` |
| `tomorrow_scenarios` | `tomorrow_scenarios` |

### watchlist.yaml

| daily_state 字段 | 目标路径 |
|---|---|
| `entry_zone_updates[].current_ref` | 匹配 `stocks[].entry_zone.current_ref` |

## 运行模式

```bash
# 正常同步（从最新 17:00 cron 输出读）
PYTHONPATH=src python3 scripts/sync_config_from_review.py

# 仅打印变更，不写入
PYTHONPATH=src python3 scripts/sync_config_from_review.py --dry-run

# 强制从 daily_state.json 同步（不依赖 cron 输出）
PYTHONPATH=src python3 scripts/sync_config_from_review.py --force
```

## 注意事项

1. **positions.yaml 被 .gitignore** — sync 脚本写它没问题（本地文件），但 git 不会跟踪变更
2. **entry_zone_updates 是新增字段** — 如果 daily_state 中没有 entry_zone_updates，watchlist 跳过
3. **17:00 prompt 需要包含输出格式要求** — 见 `cronjob act=update job_id=fc7d8a270d84`
4. **追踪文件** — `config/stock_monitor/.sync_config_last.json` 防止重复扫描
