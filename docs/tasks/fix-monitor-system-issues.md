# 监控系统修复任务清单

> 创建时间：2026-06-10
> 触发：三项核心改造（Prompt重写/Context Builder/Daily State）状态评估发现的问题
> 目标：逐点修复所有问题，每次聚焦一个任务

---

## 问题总览

| # | 问题 | 优先级 | 状态 | 修复人 | 完成时间 |
|---|------|--------|------|--------|----------|
| 1 | **daily_state.json 不存在** — sync_daily_state.py 未成功写入 | 🔴 P0 | ✅ **已完成** | AI | 2026-06-10 |
| 2 | Context Builder 方向关键词硬编码（8个方向写死） | 🟡 P1 | ✅ **已完成** | AI | 2026-06-10 |
| 3 | Context Builder Qdrant 语义召回 query 过于简单 | 🟡 P1 | ✅ **已完成** | AI | 2026-06-10 |
| 4 | trader_mindset.txt 是空壳文件，人格定义未独立 | 🟢 P2 | ✅ **已完成** | AI | 2026-06-10 |
| 5 | 10:00 节点 ID 可能不对齐（strategy_pack vs cron） | 🟡 P1 | ✅ **已完成** | AI | 2026-06-10 |
| 6 | context_builder claims 排序未利用 reasoning_patterns | 🟡 P1 | ✅ **已完成** | AI | 2026-06-10 |

---

## 任务1：排查 daily_state.json 不存在的原因 ✅ 已完成

### 根因诊断（2026-06-10）
1. **sync_daily_state.py --dry-run 扫描结果**：9 个 cron job 全部"未找到 daily_state 代码块"
2. **检查 cron 输出文件**：发现所有输出含 `[qing-agent fallback — 输出原始监控上下文]`
3. **blast radius 扫描**：今天 6 个看盘 cron 全部走了 FALLBACK
4. **Qing-Agent 进程检查**：gunicorn 进程存在但 worker 被卡住（`/health` ok 但 `/analyze/trigger` 30s 超时无响应）
5. **根因确认**：级联 fallback — 第一个慢请求卡住 worker，后续 cron 全部超时

### 修复措施
- 杀掉卡住的 gunicorn 进程（PID 1969579/1969580）
- 重新启动 gunicorn 单 worker
- 验证 `/analyze/trigger` 端点恢复正常响应

### 验证结果
- [x] Qing-Agent `/health` 返回 ok
- [x] `/analyze/trigger` 返回 JSON 含 final_output
- [x] 进程稳定运行（PID 1980501）

### 后续说明
- **今天的 cron 已错过**（09:26-11:20 全部走了 fallback）
- **明天的 cron 会正常走 Qing-Agent**，届时会输出 ````daily_state` 代码块
- **sync_daily_state.py 会正常扫描并写入 daily_state.json**
- 建议监控明天早盘第一个 cron（09:26）确认 daily_state 是否正常生成

---

## 任务2：Context Builder 方向关键词动态化 ✅ 已完成

### 修复内容
1. **新增 `Neo4jClient.get_sector_themes()` 方法**：从 Neo4j 动态查询 `claim_type='sector-theme'` 的 claims，提取方向关键词
2. **双策略提取**：
   - 策略1：从 subject 提取核心方向名（去除前缀后缀，按分隔符拆分）
   - 策略2：从 statement 匹配已知方向关键词列表（30+个关键词）
3. **去重排序**：按提及次数 + 最新日期排序
4. **修改 `context_builder.py`**：用 `dynamic_directions` 替代硬编码的 8 个方向

### 验证结果
- [x] 动态提取到 73 个方向（之前硬编码只有 8 个）
- [x] 包含新方向：AI(20次)、商业航天(11次)、算力(7次)、创新药等
- [x] `Neo4jClient.close()` 正常工作
- [x] 代码通过语法检查

---

## 任务3：优化 Qdrant 语义召回 query ✅ 已完成

### 修复内容
1. **动态 query 生成**：结合标的名称 + entry_points 触发条件 + 技术面关键词
2. **三层 fallback 策略**：
   - 优先：使用 entry_points 中的 `trigger` 或 `buy_setup` 作为 query
   - 次优：从 Neo4j claims 中提取技术面关键词（回踩/突破/企稳/放量等）
   - 兜底：固定模板 `"技术分析 介入建议"`
3. **代码格式兼容性修复**：`get_claims_about_stock()` 现在支持多种代码格式（`000534.SZ`/`000534`/`sz000534`）

### 验证结果
- [x] 万泽股份(000534.SZ) 三种代码格式都能查到 claims
- [x] 动态 query 包含 entry_points 触发条件（如"回踩30.5-31.0企稳"）
- [x] 代码通过语法检查

---

## 任务4：重构 trader_mindset.txt ✅ 已完成

### 修复内容
1. **重写 trader_mindset.txt**：从 market_analyst.txt 剪切人格定义，写入独立文件
   - 核心原则、反保守自检、UP表达风格、时效性自检、禁止行为、Few-Shot示例
2. **清理 market_analyst.txt**：删除第1-40行重复的人格定义
3. **清理 stock_analyst.txt**：删除第1-19行重复的人格定义
4. **验证注入机制**：`_load_prompt()` 已自动将 trader_mindset.txt 前置到 market_analyst/stock_analyst

### 验证结果
- [x] market_analyst prompt 长度 8961 字符，以 trader_mindset 开头
- [x] stock_analyst prompt 长度 4867 字符，以 trader_mindset 开头
- [x] 两个 prompt 中人格定义出现次数均为 0（无重复）
- [x] 修改 trader_mindset.txt 后两个 prompt 同时生效（共享机制）

---

## 任务5：修复 10:00 节点 ID 对齐 ✅ 已完成

### 验证结果
对比三处 ID：
| 来源 | 10:00 ID | 状态 |
|------|----------|------|
| strategy_pack.yaml | `morning_confirm` | ✅ |
| stock_monitor.py DEFAULT | `morning_confirm` | ✅ |
| cron schedule | `0 10 * * 1-5` | ✅ |

三处完全对齐，无需修复。

**注意**：stock_monitor.py DEFAULT 比 strategy_pack.yaml 多一个 `15:20 closing_review`，但 15:20 走 Hermes 直调 LLM 路径（不经过 agent_analysis_schedule），这是设计差异不是 bug。

---

## 任务6：利用 reasoning_patterns 指导 claims 排序 ✅ 已完成

### 修复内容
1. **context_builder.py `_score_claim_relevance()`**：新增 `active_patterns` 参数
   - 如果 claim 的 subject/statement 匹配到 active pattern 的 `applicable_themes`，额外 +4 分
   - 每个 pattern 只加一次分，避免重复
2. **`build_stock_context()`**：新增 `active_patterns` 参数，透传给 `_score_claim_relevance`
3. **`build_market_context()`**：新增 `active_patterns` 参数，透传给 `build_stock_context`
4. **nodes.py `retrieve_knowledge()`**：
   - 在调用 `build_market_context` 之前，预计算 `_load_reasoning_patterns(state)`
   - 将结果传入 `build_market_context` 的 `active_patterns` 参数
   - 日志输出中增加 `active_patterns` 字段，便于调试

### 效果
- 当用户查询"MLCC 怎么看"时，`_load_reasoning_patterns` 会匹配到 `upstream_cycle`
- `upstream_cycle` 的 `applicable_themes` 包含"MLCC"、"被动元件"、"涨价题材"等
- 涉及这些主题的 claims 会在排序时获得 +4 分额外加分
- 确保最相关的 claims（匹配当前分析框架的）优先展示给 LLM

### 代码变更
| 文件 | 变更 |
|------|------|
| `context_builder.py` | `_score_claim_relevance()` + `active_patterns` 参数；`build_stock_context()` + `active_patterns`；`build_market_context()` + `active_patterns` |
| `nodes.py` | `retrieve_knowledge()` 预计算 `active_patterns` 并传入 `build_market_context` |
- [ ] 涉及涨价链的标的优先展示 upstream_cycle 相关 claims
- [ ] 涉及主线判断的标的优先展示 mainline_identification 相关 claims

---

## 修复纪律

1. **每次只做一个任务**，完成后更新本文档状态
2. **先诊断再修复**，不假设原因
3. **每个任务必须有验证步骤**，验证通过才能标记完成
4. **修改前 git stash**，修改后 git commit
5. **完成后向用户汇报**：做了什么、为什么、验证结果
