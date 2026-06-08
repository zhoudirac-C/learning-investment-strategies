# 设计文档 vs 实现核对工作流

> 场景：用户要求"核对一下你所有的改动是否和文档里一样"——验证代码实现是否匹配设计文档（如 `docs/config-cron-architecture-review.md`）。

## 核对方法

### Step 1: 读取设计文档

设计文档通常很长（500+ 行），按章节分段读取：
```bash
wc -l docs/xxx.md          # 看总行数
read_file offset=1 limit=200
read_file offset=201 limit=200
# ... 逐段读完
```

### Step 2: 提取设计要点

对每个章节，提取：
- **新增文件**（如 `trader_mindset.txt`、`context_builder.py`）
- **新增字段**（如 `lifecycle`、`hot_score`、`linked_claims`）
- **改造点**（如 `entry_points` 加 `status` 字段）
- **架构变化**（如 9 个差异化 cron 节点）

### Step 3: 逐项检查实现

用 `git diff` 看改动范围：
```bash
git diff <doc-commit>..HEAD --stat
```

然后对每个设计点，用以下方法验证：

| 检查类型 | 命令/方法 |
|----------|----------|
| 文件是否存在 | `ls path/to/file` |
| 字段是否在代码中 | `grep -n "field_name" file.py` |
| 字段是否在 YAML 中 | `grep -n "field_name" config/*.yaml` |
| Prompt 内容检查 | 读取 `.txt` 文件，关键词匹配 |
| 函数/类存在性 | `grep -c "def " file.py` |

### Step 4: 结构化输出对比表

输出格式：
```
| 设计项 | 状态 | 说明 |
|--------|------|------|
| xxx | ✅/❌ | 简短说明 |
```

按层级分组（Prompt层 / 代码层 / Config层），方便用户快速定位差距。

## 常见陷阱：Config 层漏更新

**症状**：代码和 prompt 都写好了，但配置文件还是旧结构。

**典型案例**（2026-06-08）：
- 设计文档要求 `watchlist.yaml` 新增 `lifecycle`、`hot_score`、`linked_claims`、`opportunity_patterns`
- 代码实现了 `hot_score.py`、`claims_to_entry.py` 能计算和读取这些字段
- 但实际 `watchlist.yaml` 中这些字段**一个都没有**
- 结果：`hot_score` 只能写入旁路 JSON 文件，无法与 watchlist 原生集成

**另一个案例**：
- `positions.yaml` 设计新增 `add_zone`、`entry_decision`、`trade_log`
- `stock_monitor.py` 代码已能读取 `add_zone` 并触发加仓提醒
- 但 `positions.yaml` 中没有 `add_zone` 字段 → 加仓触发逻辑**永远跑不到**

**根因**：
1. 实现时分阶段推进（先代码后配置）
2. 配置文件的修改需要人工编辑 YAML，容易被遗漏
3. 没有自动化脚本将设计文档的新字段同步到 YAML

**修复方法**：
```bash
# 1. 检查 YAML 中是否真的有设计要求的字段
grep -E "lifecycle|hot_score|linked_claims|opportunity_patterns" config/stock_monitor/watchlist.yaml
grep -E "add_zone|entry_decision|trade_log" config/stock_monitor/positions.yaml

# 2. 如果没有，手动追加（保持现有结构不变，增量添加）
# 或使用 Python 脚本批量注入新字段
```

## 核对清单模板

当用户要求核对时，按以下清单执行：

- [ ] 读取完整设计文档（分段读取，确认所有章节）
- [ ] 提取所有"新增文件"要求 → 检查文件是否存在
- [ ] 提取所有"新增字段"要求 → 检查代码中是否读取 + YAML 中是否定义
- [ ] 提取所有"改造"要求 → 检查旧结构是否按新设计更新
- [ ] 提取所有"架构变化" → 检查数量/结构是否匹配
- [ ] 对 ❌ 项，区分是"未实现"还是"实现但数据层未更新"
- [ ] 输出分层对比表（Prompt / 代码 / Config）
- [ ] 给出实现度百分比估计
- [ ] 明确下一步需要补什么
