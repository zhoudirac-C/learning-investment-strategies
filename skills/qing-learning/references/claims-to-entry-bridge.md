# Claims → Entry 桥接

> 参考：`docs/config-cron-architecture-review.md` v2.0 §4.6.2 / §4.8

## 概述

`claims_to_entry.py` 是 qing-learning（claims 生产端）和 qing-stock-monitor-update（config 消费端）之间的桥接管道。它在每次新 claims 入库后，扫描操作建议并生成可执行的 entry_point。

## 触发条件

仅当 ingestion 产生了 `claim_type: operation` 的 claim 时才运行。判断标准：
- claim 的 `statement` 包含介入区间/仓位/止损建议
- claim 明确提到了具体标的和操作方向

## CLI 用法

```bash
cd ~/learning-investment-strategies
PYTHONPATH=src .venv/bin/python scripts/sync_claims_to_config.py

# 指定扫描天数（默认 7）
PYTHONPATH=src .venv/bin/python scripts/sync_claims_to_config.py --days 3

# 自动合并（跳过人工确认，谨慎使用）
PYTHONPATH=src .venv/bin/python scripts/sync_claims_to_config.py --auto-merge
```

## 提取规则

脚本用正则从 claim 的 `statement` 和 `interpretation` 中提取：

| 字段 | 匹配模式 | 示例 |
|------|---------|------|
| `entry_zone` | `30.5-31.0`、`30.5附近`、`回踩30.5` | `"30.5-31.0"` |
| `position_ratio` | `0.5成`、`1成仓`、`50%仓位` | `"0.5成"` |
| `stop_loss` | `跌破30`、`止损30` | `"30.0"` |
| `stock_code` | 6位数字 | `"000534"` |

## 合并策略

与 `strategy_pack.yaml` 的现有 `entry_points` 合并时：

- **code 已存在 + status=active** → 更新 `claim_basis`、`odds_analysis`
- **code 已存在 + status=triggered/executed** → 不覆盖
- **code 不存在** → 新增（`status: suggested`，需人工确认）

## 同时执行的操作

- 回写 `watchlist.yaml` 的 `linked_claims` 字段
- 刷新匹配标的的 `lifecycle.last_activity`

## 人工确认流程

1. 脚本输出文件：`config/stock_monitor/entry_suggestions/entry_suggestions_YYYYMMDD.yaml`
2. Agent 告知用户："生成了 N 条 entry_point 建议"
3. 用户确认后：复制 `suggestions` 条目到 `strategy_pack.yaml` → `entry_points`
4. 确认完成后：删除建议文件（避免重复处理）
5. 运行 `scripts/validate_config.py` 确认格式正确

## 与 qing-stock-monitor-update 的衔接

qing-stock-monitor-update skill 的 Step 1 前置检查会扫描 `entry_suggestions/` 目录——如果发现待确认文件，优先处理后再执行其他更新。

## 常见问题

**Q: 脚本运行返回 0 条建议？**
A: 正常。说明最近没有 operation 类型的 claim，或 claims 中不包含可量化的介入建议。

**Q: linked_claims 仍为空？**
A: 检查 Neo4j 是否在线（`curl http://localhost:7474`），确认 claim 的 `related_stocks` 字段已填写。
