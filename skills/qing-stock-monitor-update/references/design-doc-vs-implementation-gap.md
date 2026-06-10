# 设计文档 vs 代码实现差距核查手册

> 场景：用户要求"根据设计文档检查 skill 需要哪些更新"。
> 核心教训：文档写了 ≠ 代码实现了。必须文件系统逐项确认。

---

## 核查方法论

### 步骤 1：读取设计文档的"修改清单"

设计文档通常有"新增文件""新增 cron job""Config 更新"等章节。逐条提取。

### 步骤 2：文件系统逐项确认

对每条"新增文件"，运行：
```bash
ls -la <文件路径> 2>/dev/null || echo "❌ 不存在"
```

对每条"新增 cron job"，运行：
```bash
hermes cron list 2>/dev/null | grep -i "<job 关键词>" || echo "❌ 未注册"
```

### 步骤 3：区分三种状态

| 状态 | 含义 | 标记 |
|------|------|------|
| 已落地 | 文件存在且功能完整 | ✅ |
| 部分实现 | 文件存在但功能不完整 / 有占位代码 | ⚠️ |
| 未实现 | 文件不存在 | ❌ |

### 步骤 4：更新 skill 的"遗留问题"

将所有 ❌ 和 ⚠️ 项写入 skill 的"遗留问题"或"陷阱"章节，明确标注差距。

---

## 本案例的核查结果（2026-06-10）

### 设计文档来源

`docs/config-cron-architecture-review.md` v2.0 §7.2 "修改清单"

### 新增文件核查

| 文件 | 文档声称 | 实际状态 | 差距 |
|------|---------|---------|------|
| `prompts/system/trader_mindset.txt` | Phase 1.3 占位 | ✅ 89 行完整实现 | 无差距 |
| `scripts/sync_claims_to_config.py` | Claims→Entry 桥接 CLI | ❌ 不存在 | 完全未实现 |
| `scripts/sync_daily_state.py` | 扫描 cron 输出提取 daily_state | ❌ 不存在 | 完全未实现 |
| `scripts/qing_stock_monitor_poll.py` | 条件驱动轮询 | ❌ 不存在 | 完全未实现 |
| `scripts/backfill_linked_claims.py` | 从 YAML 回填 linked_claims | ⚠️ 需核实 | linked_claims 已回填但脚本位置不明 |

### 新增 cron job 核查

| Job | 文档声称 | 实际状态 | 差距 |
|------|---------|---------|------|
| Daily State 同步扫描 | `*/5 9-15 * * 1-5` no-agent | ❌ 未注册 | sync_daily_state.py 不存在 → 无法注册 |
| A股条件驱动轮询 | `*/5 9-15 * * 1-5` no-agent | ❌ 未注册 | qing_stock_monitor_poll.py 不存在 → 无法注册 |

### Config 更新核查

| 文件 | 文档声称 | 实际状态 | 差距 |
|------|---------|---------|------|
| `strategy_pack.yaml` | 新增 `position_rules` | ✅ 已落地 | 无差距 |
| `watchlist.yaml` | 21 只票回填 `linked_claims` | ✅ 已回填 | 无差距（但回填方式不明） |
| `daily_state.json` | 状态机持久化 | ❌ 从未创建 | sync_daily_state.py 缺失 |

---

## 常见根因

1. **文档先行**：设计评审通过后文档即更新，但代码开发滞后
2. **PR 合并但未部署**：代码在分支中，未合并到主分支
3. **脚本手动运行过一次**：回填脚本运行后即删除，未保留在 repo 中
4. **cron 注册遗漏**：代码写了但 `hermes cron create` 未执行

---

## 验证命令模板

```bash
cd ~/learning-investment-strategies

echo "=== 核查设计文档中的新增文件 ==="
for f in scripts/sync_claims_to_config.py \
         scripts/sync_daily_state.py \
         scripts/qing_stock_monitor_poll.py \
         scripts/backfill_linked_claims.py; do
  if [ -f "$f" ]; then
    echo "✅ $f ($(wc -l < "$f") 行)"
  else
    echo "❌ $f"
  fi
done

echo ""
echo "=== 核查 daily_state.json ==="
ls -la config/stock_monitor/daily_state.json 2>/dev/null || echo "❌ 不存在"

echo ""
echo "=== 核查 cron job 注册 ==="
hermes cron list 2>/dev/null | grep -iE "daily.state|poll|sync" || echo "❌ 未找到相关 cron job"

echo ""
echo "=== 核查 Context Builder 集成 ==="
grep -c "context_builder" src/qing_investment/agent/graph/nodes.py
# 应输出 >=1

echo ""
echo "=== 核查 daily_state 注入 ==="
grep -c "daily_state" src/qing_investment/stock_monitor.py
# 应输出 >=3
```
