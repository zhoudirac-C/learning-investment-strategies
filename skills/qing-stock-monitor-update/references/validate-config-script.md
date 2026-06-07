# validate_config.py — 配置一致性校验脚本

> 独立运行，不依赖实时行情。用于 config 更新后的完整性校验。

## 用法

```bash
cd ~/learning-investment-strategies
python scripts/validate_config.py           # 完整检查（含 claims 一致性）
python scripts/validate_config.py --quiet   # 只输出问题，干净时不输出
python scripts/validate_config.py --positions  # 也检查 positions.yaml
```

## 退出码

| 码 | 含义 |
|----|------|
| 0 | 全部干净 |
| 1 | 有警告（如 sector 覆盖不完整） |
| 2 | 有错误（如 code 格式错误、claims 矛盾） |

## 检查项

| # | 检查 | 类型 | 说明 |
|---|------|------|------|
| 1 | code 格式 | 错误 | 所有 code 必须是 `XXXXXX.SZ`/`XXXXXX.SH`，不是 `shXXXXXX`/`szXXXXXX` |
| 2 | entry 去重 | 错误 | 按 `code + name` 检查 entry_points 重复 |
| 3 | sector 覆盖 | 警告 | 哪些 watchlist themes 在 sector_groups 中缺失 |
| 4 | today_snapshot 位置 | 错误 | 只应在 strategy_pack 中存在 |
| 5 | claims 一致性 | 错误 | UP 说"不追高/韭菜"但 entry_points 配了介入区间 |
| 6 | 持仓区间 | 错误 | 持仓是否缺少 reduce_zone/risk_zone（需 --positions） |

## 集成

推荐在每次 `qing-stock-monitor-update` skill 的 Step 6（验证）中运行：

```bash
python scripts/validate_config.py
```

Cron 每日复盘前也可运行以捕获配置退化：

```bash
python scripts/validate_config.py --quiet || echo "Config issues found"
```

## 已知的限制

- **sector 覆盖警告**：大量历史/过期 watchlist themes 会触发警告，属于预期行为
- **claims 一致性**：最近 7 天内的 claims 才会被检查；超出 7 天的不在检查范围内
- **持仓区间检查**：需要 `--positions` 标志且 positions.yaml 存在时才执行
