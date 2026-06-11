---
name: qing-stock-monitor-update
description: |
  配置一致性驱动的看盘系统更新。基于 UP 最新观点 + config 交叉检查，输出差异报告后执行修改。
  Use when: "更新观察池"、"更新持仓"、"更新策略"、"检查配置"
---

# qing-stock-monitor-update

## 设计原则

**每次更新必须交叉检查全部 config**。不按文件分步，而是一个 checklist 覆盖 watchlist + strategy_pack + positions + cron 的一致性。

**Claims→Config 管线止于生成建议，不自动执行。** `sync_claims_to_config.py` 只输出 diff 报告和修改建议，所有 config 修改必须经用户确认后才能执行。`--auto-merge` 仅供测试，不应用在生产流程中。

## 触发条件

- "更新观察池" / "更新方向" / "更新策略"
- "更新持仓" / "清仓" / "减仓"
- "检查配置" / "config review"
- "加标的" / "新增方向"
- "检查定时任务" / "检查调度" / "cron review"

## 必读参考

| 场景 | 文件 |
|------|------|
| MCP 驱动方向更新 | `references/mcp-powered-directional-update.md` |
| 数据源降级 | `references/data-source-fallback-chain.md` |
| Claims 一致性校验 | `references/claims-consistency-check.md` |
| Entry points 增强字段分析工作流 | `references/entry-points-enhancement-workflow.md` |
| Entry points 生成 | `references/entry-points-generation.md` |
| **Curl K线批量拉取（轻量替代）** | `references/curl-kline-batch-fetch.md` |
| 配置健康检查 | `references/config-health-check.md` |
| Watchlist 字段校验 | `scripts/validate_watchlist.py` |
| P3-观察标的介入区间计算 | `references/p3-kline-entry-zone-workflow.md` |
| Poll 字段读取路径 | `references/poll-field-lineage.md` |
| 持仓观察池区分修复记录 | `references/position-watchlist-distinction-fix.md` |
| 腾讯→新浪→东财降级链详情 | `references/tencent-sina-eastmoney-fallback-chain.md` |
| 早盘驱动 Config 更新清单 | `references/morning-briefing-update-checklist.md` |
| **Cron 静默失败排查清单** | `references/cron-silent-failure-checklist.md` |
| **Hermes Cron 包装器设计约定** | `references/hermes-cron-wrapper-conventions.md` |
| **买入信号检测系统设计** | `references/buy-signal-detection-design.md` → `docs/design/buy-signal-detection-system.md` |
| **买入信号实施任务清单** | `docs/tasks/buy-signal-implementation.md`（Phase 0-4 状态追踪） |
| **框架过期自锁闭环（4033案例）** | `references/framework-staleness-self-lock.md` |
| **K线缓存 + 预拉取基础设施** | `src/qing_investment/kline_cache.py` + `scripts/pre_fetch_klines.py` |
| Agent-UP 矛盾处理 | 本 SKILL §陷阱 |
| Cron pipeline 架构 | `references/cron-pipeline-architecture.md` |
| **Cron 调度优化** | `references/cron-schedule-optimization.md` |
| **设计文档 vs 代码实现差距核查** | `references/design-doc-vs-implementation-gap.md` |
| **Config-cron 架构设计差距审计（2026-06-10）** | `references/design-doc-gap-audit-20260610.md` |
| Qing-Agent 服务运维速查 | `references/qing-agent-service-operations.md` |
| Qing-Agent 服务架构（uvicorn→gunicorn 单 worker） | `references/qing-agent-gunicorn-migration.md` |
| 系统问题修复记录（2026-06-10） | `references/fix-monitor-system-issues-20260610.md` |
| Qdrant 本地模式并发锁机制 | `references/qdrant-concurrency-lock.md` |
| Cron 脚本超时诊断手册 | `references/cron-script-timeout-diagnosis.md` |
| **Agent 时间限制绕过** | `references/agent-any-time-bypass.md` |
| **Cron 超时外部化配置** | `references/cron-timeout-external-config.md` |
| **条件驱动轮询消息丰富化** | `references/condition-driven-alert-message-enrichment.md` |
| **Skill 文档维护卫生** | `references/skill-doc-maintenance-hygiene.md` |
| **实时数据降级模式** | `references/realtime-data-degradation-pattern.md` |
| **daily_state 链路断裂根因** | `references/daily-state-pipeline-root-cause.md` |
| **daily_state 持久化实现细节** | `references/daily-state-persist-implementation.md` |
| **Qing-Agent 完整链路耗时基准** | `references/qing-agent-timing-benchmark.md` |
| **LLM 结构化输出管线调试（通用）** | `references/debugging-structured-output-pipeline.md` |

---

## 工作流程（4 步）

### Step 1: 门禁检查

```bash
cd ~/learning-investment-strategies
```

**⚠️ 注意**：`check_config_consistency.py` 在陷阱 15 中被标记为 "❌ 不存在"——它是设计文档中的计划文件，尚未创建。以下为实际可用的替代检查：

| 检查维度 | 可用工具 | 说明 |
|---------|---------|------|
| Watchlist 字段完整性 | `python scripts/validate_watchlist.py` | ✅ 已实现（2026-06-11）——校验 code/priority/price_range/hard_stop |
| Watchlist 字段详情 | `python scripts/validate_watchlist.py --json` | JSON 输出，供 LLM 消费 |
| Config YAML 语法 | `python -c "import yaml; yaml.safe_load(open('config/stock_monitor/watchlist.yaml'))"` | 基础语法校验 |
| 轮询脚本不崩溃 | `PYTHONPATH=src timeout 30 .venv/bin/python scripts/stock_monitor.py --ignore-trading-time` | 端到端运行验证 |

**设计中的 8 维差异报告**（待实现，见陷阱 15）：
1. strategy_pack 过期（日期、点位、方向词）
2. watchlist 缺口（claims 提到的标的未在 watchlist）
3. watchlist ↔ strategy_pack 对齐
4. positions 缺失（无 risk_zone 等）
5. invalidation 点位过期
6. cron focus 过期
7. claims 引用完整性
8. watchlist 字段校验（code 格式/priority/lifecycle/linked_claims/sentiment）

### Step 2: 收集变化源

**变化源检测——找到「什么变了」：**

| 来源 | 方法 | 产出 |
|------|------|------|
| UP 最新 claims | `mcp_neo4j_get_recent_claims(days=2)` | 新观点列表 |
| B站动态 | `sources/original/bilibili/` → unprocessed 时转录 raw | raw 文件 |
| 用户操作 | 用户明确说的清仓/建仓/减仓 | 持仓变动 |
| 市场行情 | 腾讯 API 拉全A + 关键标的（仅 full update） | 实时价格 |

### Step 2.5: Claims→Config 建议生成

**当 Step 2 检测到新 claims 可能影响 config（watchlist/strategy_pack/positions）时：**

1. **只生成建议，不修改 config。** 运行 `sync_claims_to_config.py` 输出 diff 报告：
   ```bash
   cd ~/learning-investment-strategies
   python3 scripts/sync_claims_to_config.py
   # 输出：linked_claims 建议 + entry_points 更新建议 + 人工审核要点
   ```
2. **将建议放入 Step 3 的差异报告**，标注为 P1/P2（⚠️ 需要人工审核观点准确性）
3. **用户确认后再执行修改**（回到 Step 4）
4. **重点审核项**：观点时效性、方向判断是否与当前市场阶段一致、介入区间合理性

### Step 3: 差异报告 → 用户确认

合并 Step 1 门禁输出 + Step 2 变化源 → **一份统一差异报告**：

```
## Config 一致性报告

### 🔴 P0（必须修复）
- strategy_pack focus 含过期方向"燃气轮机" → 更新为当前主线
- positions 万泽 missing risk_zone → 补配

### 🟡 P1（建议修复）
- watchlist 缺 立昂微(605358)：claim-005-b 提及硅片方向
- invalidation 含数字点位 4000，已过期

### 🟢 P2（可选）
- sector_groups 有 12 个组不在 watchlist
```

**用户确认后执行修改。** 不要直接改 config——先展示报告。

### Step 4: 执行修改 + 验证

用户确认后：
1. 逐项修改（优先 P0 → P1 → P2）
2. 运行 `python scripts/validate_watchlist.py` 确认 P0 清零（Watchlist 字段）**
3. 运行 no-agent 轮询脚本确认不崩溃：`PYTHONPATH=src timeout 30 .venv/bin/python scripts/stock_monitor.py --ignore-trading-time`
4. 更新 strategy_pack.updated_at
5. Git 提交

---

## 早盘快捷模式

当变化源是**早盘（09:17 发布）**而非晚间复盘时，使用快速清单而非完整 4-step workflow。详细清单见 `references/morning-briefing-update-checklist.md`。

**速记**：早盘 = 战术微调，复盘 = 战略重构。

| 早盘可做 | 早盘不可做 |
|---------|-----------|
| 更新 market_framework（情景分支） | 重写全部优先级（优先级来自复盘） |
| 新增 P3-观察 标的（连板/情绪映射） | 为 confidence=low 的标的设介入区间 |
| 补充方向 positioning 的验证框架 | 为「仅观察」标的拉 K 线计算技术位 |
| 添加操作规则（板块级微调） | 修改 positions 的建仓目标 |
| 更新 intraday_schedule 观察点 | 大幅重写 strategy_pack 框架 |

**执行流**：\n1. 读早盘 raw + claims → 对照 `references/morning-briefing-update-checklist.md` 的 5 项必查\n2. 输出差异报告（P0/P1/P2 分级）\n3. 用户确认后逐项 patch\n4. `python scripts/validate_watchlist.py` 确认 P0 清零
5. **`PYTHONPATH=src timeout 30 .venv/bin/python scripts/stock_monitor.py --ignore-trading-time`** → 确认 no-agent 脚本不崩溃
6. Git 提交

---

## 陷阱

### 陷阱 1: 只更新一个文件忘记交叉检查

**反面案例（2026-06-10）**：加了硅片标的到 watchlist，但没检查 strategy_pack.sector_groups 是否覆盖 → 板块轮动计算遗漏硅片方向。

**正确做法**：Step 3 的差异报告自动检测这个。

### 陷阱 2: Qing-Agent 假在线导致分析退化

**反面案例（2026-06-10）**：Agent 挂了整整一个上午——`/health` 返回 OK，但 `/analyze/trigger` 挂死无响应。全部 cron 静默走 LLM fallback，输出过期方向词且无 claims 引用。

**Cron 脚本超时（2026-06-10 新增）**：`qing_stock_monitor_agent.py` wrapper 在 cron 中 120s 超时。根因通常是 Qing-Agent `/analyze/trigger` 端点无响应，脚本内部 `urlopen` 阻塞直到 cron kill。**不是代码 bug，是服务不可用**。诊断与修复见 `references/cron-script-timeout-diagnosis.md`。

**数据源降级导致的 fallback 连锁反应（2026-06-10 下午）**：

cron job 报告出现持仓幻觉（"景旺电子 +4.18%、鼎龙股份 +2.03%"），但用户实际空仓。根因链：
1. `stock_monitor.py` 的 `fetch_quotes_with_fallback()` **东财优先**，服务器 IP 被东财严格限流
2. 东财返回 0 quotes + errors，但判断条件 `len(em_quotes) >= len(targets)` 不成立时**不会触发降级**
3. 脚本阻塞重试直至超时，cron 静默失败
4. 当 Agent 分析时，部分标的无实时行情 → 分析质量下降 → AI 幻觉（将 watchlist 标的误认为持仓）

**已修复（2026-06-10）**：
1. **数据源优先级反转**：腾讯(gtimg) 优先 → 新浪(hq.sinajs.cn) 备用 → 东财(push2) 兜底
2. **新增 `fetch_sina_quotes()`**：新浪财经批量接口，chunk_size=80
3. **重写 `fetch_quotes_with_fallback()`**：
   - 腾讯成功条件：返回 ≥80% 标的 且 无错误
   - 新浪补充：合并腾讯已获取数据 + 新浪补充缺失标的
   - 兜底合并：所有可用数据源数据合并 + 汇总错误信息
   - 完全失败：返回 `all_failed` + 三源错误摘要
4. **新增 `_merge_quotes()`**：以主源为主，补充缺失 secid

**验证命令**：
```bash
cd ~/learning-investment-strategies
python3 -c "
import sys; sys.path.insert(0, 'src')
from qing_investment.stock_monitor import fetch_quotes_with_fallback, collect_quote_targets, load_monitor_config
config = load_monitor_config()
targets = collect_quote_targets(config)
result = fetch_quotes_with_fallback(targets)
print(f'source={result[\"source\"]}, quotes={len(result[\"quotes\"])}/{len(targets)}, errors={result.get(\"errors\",[])}')
"
# 期望输出：source=tencent_gtimg, quotes=184/184, errors=[]
```

**⚠️ `/health` 通过 ≠ 管线正常**。`/health` 只检查进程存活，不检查 LangGraph 管线。

**根因**：uvicorn 单 worker 串行排队 + 管线 30s+ 耗时 vs 脚本 45s 超时。第一个慢请求触发 worker 忙碌 → 后续请求排队 → 全部超时走 fallback。不是代码 bug，是超时争用。

**已修复（2026-06-10）**：
1. **超时调大**：45s → **180s** + 3 次指数退避重试
2. **uvicorn → gunicorn 单 worker**：进程崩溃自动重启、优雅关闭、统一日志
3. **成功/失败显式标记**：`[Qing-Agent ✓]` / `[Qing-Agent ✗ FALLBACK]`
4. **Qdrant 锁冲突解决**：停止 MCP Qdrant server，让 Qing-Agent 独占 `.qdrant_data` 本地文件访问（Qdrant 本地模式使用排他锁，同一时刻只能有一个进程）

- **QING_AGENT_TIMEOUT 调优**：脚本默认 45s 对 30s+ 管线偏紧。已改为 **180s** + **3 次指数退避重试**（1s/2s/4s）。环境变量可覆盖：
```bash
export QING_AGENT_TIMEOUT=180  # 置入 .bashrc 或 cron 环境
export QING_AGENT_MAX_RETRIES=3
```

- **Cron 外层超时 ≥ 脚本内超时 + 20s**：cron job 的 `timeout` 字段必须 ≥ `QING_AGENT_TIMEOUT + 20`。若脚本内 180s，cron 至少 200s。否则脚本还在重试就被 cron kill。

**正确做法**：Step 1 前置真实端点检测（含 blast radius 扫描 + `/analyze/trigger` 实测，max-time 30s）。运维命令速查见 `references/qing-agent-service-operations.md`。
```bash
# 第一步：扫 blast radius（检查最近 cron 输出标记）
# 成功标记：[Qing-Agent ✓]  失败标记：[Qing-Agent ✗ FALLBACK] 或旧版 [qing-agent fallback
for dir in ~/.hermes/cron/output/*/; do
  latest=$(ls -t "$dir"/*.md 2>/dev/null | head -1)
  [ -n "$latest" ] && grep -lE "Qing-Agent . FALLBACK|qing-agent fallback" "$latest" && echo "  ↳ $(basename $dir)"
done

# 第二步：直接测 /analyze/trigger（非 /health，max-time 30s 匹配 180s 超时 + 管线耗时）
curl -s --max-time 30 -X POST http://127.0.0.1:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"健康检查","session_id":"health-001","analysis_type":"market"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if d.get('final_output') else 'EMPTY')" \
  || echo "Qing-Agent 需要重启"
```

如果 fallback blast radius > 0 或端点测试失败 → **先重启 Qing-Agent 再继续分析**。

**重启命令（gunicorn 单 worker，替代 uvicorn）**：
```bash
# 1. 杀旧进程（同时杀 uvicorn 和 gunicorn，防混用）
kill $(pgrep -f "uvicorn qing_investment") 2>/dev/null
kill $(pgrep -f "gunicorn") 2>/dev/null
# 同时停止 MCP Qdrant server（避免 Qdrant 本地文件锁冲突）
kill $(pgrep -f "mcp_qdrant_server") 2>/dev/null
sleep 2

# 2. 确认端口释放
ss -tlnp | grep 8000 || echo "Port 8000 free"

# 3. 重启动（必须在 repo root，.env 才能被 pydantic 读到）
cd ~/learning-investment-strategies
nohup .venv/bin/gunicorn qing_investment.agent.main:app \
  -w 1 -k uvicorn.workers.UvicornWorker \
  --bind 127.0.0.1:8000 \
  --timeout 120 --keep-alive 5 \
  > /tmp/qing-agent.log 2>&1 &

# 4. 验证（测 /analyze/trigger，非仅 /health，max-time 30s）
sleep 3
curl -s --max-time 5 http://localhost:8000/health && echo ""
curl -s --max-time 30 -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"重启验证","session_id":"restart-check","analysis_type":"market"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('RESTART OK' if d.get('final_output') else 'STILL BROKEN')"
```

> **为什么用 gunicorn 替代 uvicorn？** gunicorn 提供进程管理（崩溃自动重启、优雅关闭、统一日志），但 Qdrant 本地模式不支持多 worker 并发，所以用 `-w 1`。详见 `references/qing-agent-gunicorn-migration.md`。

> **为什么停止 MCP Qdrant server？** Qdrant 本地文件模式使用 `portalocker.EXCLUSIVE` 排他锁，同一时刻只能有一个进程访问 `.qdrant_data`。Qing-Agent 和 MCP 同时运行会导致 `RuntimeError: Storage folder is already accessed`。解决方案：让 Qing-Agent 独占 Qdrant，MCP 查询通过 Qing-Agent API 代理或错峰运行。

> **参数速查**：
> | 参数 | 含义 |
> |---|---|
> | `-w 1` | 1 个 worker（Qdrant 本地模式限制） |
> | `-k uvicorn.workers.UvicornWorker` | 每个 worker 用 Uvicorn 处理 ASGI |
> | `--timeout 120` | worker 处理请求的最大时间（秒） |
> | `--keep-alive 5` | HTTP keep-alive 连接保持 5s |

### 陷阱 2b: 实时数据硬约束导致 cron 静默失败

**反面案例（2026-06-10）**：`market_analyst` 节点在 `analysis_type in ("market", "portfolio")` 且没有实时数据时直接 return 空结果，拒绝生成分析。Cron job 在数据源限流时频繁触发此路径，输出"数据不可用"或无输出。

**根因**：`nodes.py` 第 967-984 行的硬约束设计——认为没有实时数据就不能做市场/持仓分析。但 claims 知识库包含 UP 的周期判断、方向观点、操作框架，足以支撑基础分析。

**已修复（2026-06-10）**：
1. **硬约束改为降级模式**：不再 return 空结果，而是设置 `state["_data_missing_note"]` 降级说明，继续执行
2. **AgentState 增加 `_data_missing_note` 字段**：`state.py`
3. **Prompt 注入降级说明**：`nodes.py` prompt 构建处
4. **`/analyze/trigger` 端点传递 `analysis_type`**：`schemas.py` + `main.py`
5. **`market_snapshot` 加入 JSON 上下文**：`stock_monitor.py` 的 `_agent_context_data()`

**效果**：无实时数据时，Agent 基于 claims 知识库生成分析（约 800-1100 字），不再返回空结果。响应时间约 55-85 秒。

**验证命令**：
```bash
curl -s --max-time 200 -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"测试降级","session_id":"test-001","analysis_type":"market"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK' if d.get('final_output') else 'EMPTY')"
```

**详细文档**：`references/realtime-data-degradation-pattern.md`

### 陷阱 3: Agent vs UP 矛盾

**反面案例（2026-06-10）**：万泽跌停，Qing-Agent 建议清仓，UP 10:04 说"直接砍不合适"。

**处理流程**：
1. 时序判断：UP 观点在 Agent 分析之后 → 以 UP 为准
2. 归类：信息不对称（Agent 缺 claim-007）→ 补 claims → 重新分析
3. 写入 strategy_pack 时标注来源 claim ID

### 陷阱 3b: AI 持仓幻觉（观察池 vs 持仓池混淆）

**反面案例（2026-06-10）**：用户实际空仓（positions.yaml: `positions: []`），但 cron 报告输出"景旺电子(CCL) +4.18%、鼎龙股份(材料) +2.03%"，仿佛这些标的是持仓。

**根因链**：
1. `format_analysis_context()` 中"持仓："标题后无明确空仓标注
2. AI 将 watchlist.yaml 中的标的误认为持仓
3. 9个 cron prompt 均无"持仓池 vs 观察池"区分说明

**已修复（2026-06-10）**：
1. **`format_analysis_context()` 明确标注**：
   ```
   === 持仓池（positions.yaml）===
   状态：【空仓】当前无持仓
   
   重要区分：
   - 持仓池 = 你当前实际持有的股票（来自 positions.yaml）
   - 观察池 = 你关注但尚未买入的股票（来自 watchlist.yaml）
   - 严禁将观察池标的当作持仓分析！
   
   持仓明细：
     （无持仓）
   
   === 观察池（watchlist.yaml）===
   这些标的尚未买入，仅作观察：
   ```
2. **`format_live_analysis_context()` 注入提醒**：
   ```
   【重要】当前持仓状态：空仓
   【重要】观察池标的 ≠ 持仓，严禁混淆！
   ```
3. **9个 cron prompt 增加区分说明**：每个 prompt 开头插入
   ```
   【持仓池 vs 观察池 区分说明】
   - 持仓池 = positions.yaml 中列出的股票，是你当前实际持有的仓位
   - 观察池 = watchlist.yaml 中列出的股票，是你关注但尚未买入的标的
   - 【严禁】将观察池标的当作持仓分析或给出持仓操作建议！
   - 当前持仓状态已在上下文顶部标明，分析前务必确认
   ```

**涉及文件**：
- `src/qing_investment/stock_monitor.py`（`format_analysis_context()` + `format_live_analysis_context()`）
- `src/qing_investment/agent/prompts/system/cron_*.txt`（9个文件）

**验证命令**：
```bash
cd ~/learning-investment-strategies
python3 -c "
import sys; sys.path.insert(0, 'src')
from qing_investment.stock_monitor import format_analysis_context, load_monitor_config
from datetime import datetime
from zoneinfo import ZoneInfo
config = load_monitor_config()
ctx = format_analysis_context(config, datetime.now(ZoneInfo('Asia/Shanghai')))
assert '【空仓】当前无持仓' in ctx, '空仓标注缺失'
assert '严禁将观察池标的当作持仓分析' in ctx, '区分说明缺失'
assert '持仓池（positions.yaml）' in ctx, '持仓池标题缺失'
assert '观察池（watchlist.yaml）' in ctx, '观察池标题缺失'
print('✓ 持仓/观察池区分验证通过')
"
```

### 陷阱 4: invalidation 点位过期

数字点位（如"收盘跌破4000"）和当前指数偏离 >3% 时自动检测。Step 1 门禁覆盖。

### 陷阱 5: 未经用户确认直接修改代码

**反面案例（2026-06-10）**：用户说"payload 过大怎么优化"，AI 直接修改了 `_agent_context_data()` 添加 `_build_compact_watchlist()`，用户发现后要求回滚。

**根因**：AI 没有等待用户确认就执行代码修改，违反了"先报告后修改"原则。

**正确做法**：
1. 先分析问题和可能的解决方案
2. 展示方案给用户，等待明确确认（"可以改" / "按方案A执行"）
3. 用户确认后再修改代码
4. 如果用户说"让我想想"、"等下"、"别改"——立即停止，回滚未确认改动

### 陷阱 6: Cron prompt 空改

改了 cron prompt 但没验证 → 下次 cron 执行才发现不生效。

**正确做法**：Step 4 验证时 dry-run：
```bash
python3 scripts/hermes_stock_monitor_agent.py
# 检查输出是否含新框架关键词
```

### 陷阱 7: Neo4jClient 方法缺失导致 Context Builder 失效

**反面案例（2026-06-10）**：`context_builder.py` 调用 `neo4j_client.get_claims_about_stock()` 和 `neo4j_client.get_sector_themes()`，但 `Neo4jClient` 类中不存在这两个方法 → `AttributeError` → Context Builder 完全失效 → claims 无法注入 Agent 分析。

**根因**：context_builder.py 是 Phase 2 新增组件，但 Neo4jClient 是 Phase 1 的类，新增调用点时未同步添加方法。

**已修复（2026-06-10）**：在 `Neo4jClient` 中新增：
- `get_claims_about_stock(code, limit=10)` — 通过 `ABOUT` 关系查找标的相关 claims
- `get_sector_themes(days=30, limit=100)` — 获取近期 sector-theme 类型 claims 的方向词
- `get_claim_evolution(claim_id)` — 获取 claim 的完整信息（含 statement、subject、claim_type）

**正确做法**：新增调用 Neo4jClient 的代码时，先检查类定义是否已有该方法。没有的话先补方法再调代码。

### 陷阱 8: trader_mindset.txt 是空壳，人格定义重复内嵌

**反面案例（2026-06-10）**：`trader_mindset.txt` 只有两行说明文字，实际人格定义（核心原则、反保守自检、UP表达风格）全部内嵌在 `market_analyst.txt` 和 `stock_analyst.txt` 中。导致：
1. 人格定义无法独立迭代
2. 两个 analyst prompt 重复相同内容
3. `_load_prompt()` 的自动注入机制（将 trader_mindset.txt 拼接到 analyst prompt 前）导致人格定义出现两次

**已修复（2026-06-10）**：
1. 将 `market_analyst.txt` 和 `stock_analyst.txt` 中的人格定义剪切到 `trader_mindset.txt`
2. 重写 `trader_mindset.txt` 为 96 行完整人格定义（核心原则、反保守自检、UP表达风格、时效性自检、禁止行为、Few-Shot示例）
3. 清理 `market_analyst.txt` 和 `stock_analyst.txt` 的重复内容
4. `_load_prompt()` 自动注入机制保持不变，现在 analyst prompt 只包含分析特有的内容

**验证命令**：
```bash
# 检查 trader_mindset.txt 是否非空且包含核心关键词
grep -c "赔率思维" src/qing_investment/agent/prompts/system/trader_mindset.txt
# 应输出 >=1

# 检查 market_analyst.txt 不再包含人格定义（避免重复）
grep -c "核心原则" src/qing_investment/agent/prompts/system/market_analyst.txt
# 应输出 0
```

### 陷阱 9: Context Builder 未根据 reasoning pattern 优先展示 claims

**反面案例（2026-06-10）**：`context_builder.py` 的 `_score_claim_relevance()` 只考虑股票代码匹配、介入信号、角色定义、时效性，没有根据当前分析应激活的 reasoning pattern 来优先展示相关 claims。导致：用户问"MLCC 怎么看"时，涉及"涨价"、"周期位置"的 claims 没有获得额外加分，可能排在不相关的 claims 后面。

**已修复（2026-06-10）**：
1. `_score_claim_relevance()` 新增 `active_patterns` 参数
2. 如果 claim 的 subject/statement 匹配到 active pattern 的 `applicable_themes`，额外 +4 分
3. `build_stock_context()` 和 `build_market_context()` 透传 `active_patterns`
4. `retrieve_knowledge()` 在调用 `build_market_context()` 前预计算 `_load_reasoning_patterns(state)`

**效果**：当查询"MLCC 怎么看"时，`upstream_cycle` pattern 被激活，涉及"MLCC"、"被动元件"、"涨价题材"的 claims 获得 +4 分额外加分，优先展示给 LLM。

**验证命令**：
```bash
# 检查 _score_claim_relevance 是否包含 pattern 匹配逻辑
grep -c "active_patterns" src/qing_investment/agent/tools/context_builder.py
# 应输出 >=3（函数签名 + 调用处 + 循环体）
```

### 陷阱 10: Agent Analysis Schedule 时间限制导致静默跳过

**反面案例（2026-06-10）**：用户要求"把 agent_analysis_schedule 的时间点限制删了"，因为 cron job 在非 schedule 时间点触发时，`find_agent_analysis_trigger()` 返回 `None`，导致 Agent 分析静默跳过，用户看到空输出。

**根因**：`stock_monitor.py` 的 `find_agent_analysis_trigger()` 严格匹配 `agent_analysis_schedule` 中的时间。cron schedule 和 agent_analysis_schedule 不同步时，出现"cron 触发但无输出"。

**已修复（2026-06-10）**：
1. 新增 `find_any_agent_analysis_trigger()` 函数：绕过时间限制，任何时间都能触发
2. 新增 `--agent-any-time` CLI 参数
3. `hermes_stock_monitor_agent.py` wrapper 自动传递 `--agent-any-time`

**正确做法**：
- wrapper 脚本（cron 调用）使用 `--agent-any-time` 绕过限制
- 手动测试时保留默认行为（检查 schedule）
- 修改 cron 时间时无需同步更新 strategy_pack.yaml 的 schedule

**相关文件**：
- `src/qing_investment/stock_monitor.py`
- `scripts/hermes_stock_monitor_agent.py`

**参考文档**：`references/agent-any-time-bypass.md`

### 陷阱 11: Hermes cron scheduler 默认 120s 脚本超时导致静默 kill

**反面案例（2026-06-10）**：`QING_AGENT_TIMEOUT=180s`、`CRON_WRAPPER_TIMEOUT=200s`，但 cron 仍然频繁超时。完整链路实测 173s（stock_monitor 行情 15s + HTTP API 119s + 开销 39s），但输出为空。

**根因（2026-06-10 发现）**：超时层级未对齐，且存在一个未知的**外层限流**。深入排查后发现 Hermes agent 源码 `/home/ubuntu/.hermes/hermes-agent/cron/scheduler.py` 第 813 行硬编码：

```python
_DEFAULT_SCRIPT_TIMEOUT = 120  # seconds
```

Hermes scheduler 在**最外层**执行脚本时强制 120s 超时。脚本内的 `QING_AGENT_TIMEOUT=180` 和 `CRON_WRAPPER_TIMEOUT=200` 完全无效——脚本在 120s 就被 scheduler kill，根本没机会跑完。

**完整的超时层级（从内到外）**：

| 层级 | 超时值 | 配置位置 |
|------|--------|---------|
| LLM 推理 | 30-60s | 模型自身 |
| gunicorn worker | 120s | gunicorn --timeout |
| 脚本 HTTP `urlopen` | 180s | QING_AGENT_TIMEOUT 环境变量 |
| 脚本 wrapper | 200s | CRON_WRAPPER_TIMEOUT 环境变量 |
| **Hermes scheduler** | **120s (默认)** | **`scheduler.py` 第 813 行** ← 最外层杀手 |

**已修复（2026-06-10）**：
1. 脚本新增 `CRON_WRAPPER_TIMEOUT` 环境变量（默认 200s）——但此变量对最外层无效
2. 文档化超时层级关系
3. **发现了真正根因：Hermes scheduler 的 `_DEFAULT_SCRIPT_TIMEOUT = 120`**

**三种覆盖方式（优先级从高到低）**：

| 优先级 | 方式 | 配置 |
|--------|------|------|
| 1（最高） | 环境变量 | `export HERMES_CRON_SCRIPT_TIMEOUT=300` |
| 2 | config.yaml | `cron:\n  script_timeout_seconds: 300` |
| 3 | 模块 monkeypatch | `scheduler._SCRIPT_TIMEOUT = 300`（仅测试用） |

**Source 源码 `_get_script_timeout()` 确定机制（`scheduler.py` 第818-848行）**：
1. 检查模块级 `_SCRIPT_TIMEOUT` 是否被 monkeypatch
2. 检查环境变量 `HERMES_CRON_SCRIPT_TIMEOUT`
3. 检查 `config.yaml` 的 `cron.script_timeout_seconds`
4. 回退到 `_DEFAULT_SCRIPT_TIMEOUT = 120`

**正确做法**：
- **必须同时设置 `HERMES_CRON_SCRIPT_TIMEOUT` ≥ 300（覆盖 120s 默认）**
- 确保超时层级递增：LLM(60s) < gunicorn(120s) < 脚本 HTTP(180s) < Hermes scheduler(300s)
- 验证：`hermes cron run <job_id>` 观察是否被 120s 提前 kill
- 通过环境变量外部化配置，避免硬编码

**参考文档**：`references/cron-timeout-external-config.md`

### 陷阱 12: calc_hot_scores.py 重复计算跨 theme 股票

**反面案例（2026-06-10）**：`calculate_all_hot_scores()` 没有去重逻辑，10 只股票出现在多个 theme 中（如风华高科同时在 `mlcc_passive_cycle` 和 `upstream_price_increase`），被计算了两次。导致：
- 总股票数虚高（180 vs 实际 170）
- 重复票取首次出现的 theme 数据，后续 theme 的 claims/权重被忽略
- `watchlist_hot_scores.json` 中同一只股票出现多条记录

**已修复（2026-06-10）**：在 `calculate_all_hot_scores()` 中增加 `seen_codes` 集合去重：
```python
seen_codes = set()
for theme in watchlist_data.get("themes", []):
    for stock in theme.get("stocks", []):
        code = stock.get("code", "")
        if code in seen_codes:
            continue  # 去重：同一标的只计算一次（取首次出现的 theme）
        seen_codes.add(code)
        ...
```

**涉及文件**：
- `src/qing_investment/agent/tools/hot_score.py`

**验证命令**：
```bash
cd ~/learning-investment-strategies
python3 -c "
import sys; sys.path.insert(0, 'src')
from qing_investment.agent.tools.hot_score import calculate_all_hot_scores, load_watchlist
w = load_watchlist()
results = calculate_all_hot_scores(w)
seen = set()
dups = [r['code'] for r in results if r['code'] in seen or seen.add(r['code'])]
print(f'Total: {len(results)}, Duplicates: {len(dups)}')
assert len(dups) == 0, f'Duplicates found: {dups}'
print('✓ 去重验证通过')
"
```

### 陷阱 13: daily_state 写回链断裂（sync_daily_state.py 已存在但无法工作）

**反面案例（2026-06-10）**：`sync_daily_state.py` 已存在（250 行）且已注册为 cron job（`0a62d01fbd45`，每 5 分钟），但 `daily_state.json` 从未被创建。

**根因链（四层断裂）**：

```
1. Qing-Agent 服务未启动（8000 端口无监听）
   → hermes_stock_monitor_agent.py 走 fallback 路径
2. Fallback 输出是 stock_monitor.py 的文本上下文
   → Hermes cron 用 prompt 字段让 LLM 直接生成微信提醒
3. Hermes cron prompt 里没有 daily_state 输出要求
   → LLM 输出不含 ```daily_state 代码块
4. sync_daily_state.py 扫描不到代码块
   → daily_state.json 永远不会被创建
```

**即使 Qing-Agent 启动后，仍有第二层断裂**：
- `market_analyst` 节点要求 LLM 输出 JSON + ```daily_state 代码块
- 但节点只解析 JSON 部分作为 `market_context`，代码块被丢弃
- `synthesize` → `style_writer` → `reviewer` 链路中没有任何节点提取或保存 daily_state
- **Qing-Agent 内部没有任何节点调用 `save_daily_state()`**

**修复方案（已实施方案 A）**：
1. ✅ 在 Qing-Agent `market_analyst` 节点 LLM 返回后，提取 ````daily_state` 代码块并调用 `save_daily_state()`
2. ✅ 从 `market_context` 规范化字段推导 fallback（当 LLM 未输出代码块时）
3. ✅ 本地单节点测试通过：`daily_state.json` 可被正常创建并更新
4. ⏳ **待交易时段实测验证**：09:26 集合竞价后 cron 触发，确认端到端写入

**测试发现的问题**（2026-06-10 本地单节点测试）：

| 发现 | 影响 | 状态 |
|------|------|------|
| `Persisted daily_state from market_analyst:None` 执行成功 | ✅ `daily_state.json` 正常创建 | 已确认 |
| 完整链路 ~66s（parse_query 2.4s → retrieve_knowledge 6.0s → market_analyst 36.8s → synthesize 0.0s → style_writer 12.4s → reviewer 14.3s） | ✅ 性能在预期范围内 | 已确认 |
| `review_passed=False`（测试 query 无持仓/板块数据） | ✅ 期望行为，reviewer 未通过走 fallback | 已确认 |
| `Context Builder failed: '>' not supported between instances of 'Date' and 'str'` | ⚠️ retrieve_knowledge 中日期比较失败，影响 claim 时效性过滤 | ✅ **2026-06-10 已修复** |

**⚠️ 跟进项：Context Builder 日期比较 Bug（已在 2026-06-10 修复）**：

```
Context Builder failed: '>' not supported between instances of 'Date' and 'str'
```

**根因**：`context_builder.py` 中 `source_date` 来自 Neo4j 时为 `neotime.Date` 对象，但代码用 `datetime.strptime(str_val, "%Y-%m-%d")` 或裸 `max(dates)` 比较时，Date 对象 vs str 不兼容 → `TypeError`。

涉及 4 处：
1. `_summarize_claim()` — `datetime.strptime(source_date, ...)` 传入 Date 对象
2. `_score_claim_relevance()` — 同上
3. `build_stock_context()` — `max(dates)` 列表中混入 Date 对象
4. `build_market_context()` — `max(claims, key=lambda c: c.get("source_date"))` key 返回 Date 对象

**已实施修复（2026-06-10）**：
1. 新增 `_to_date_str()` 工具函数：Date 对象 → `"%Y-%m-%d"` 字符串
2. 新增 `_parse_date()` 工具函数：统一先转字符串再 `strptime`，支持 `neotime.Date` / `datetime.date` / str
3. 4 处调用点全部改用上述工具函数
4. `_summarize_claim()` 返回 `source_date` 已归一化为字符串

**验证**：3 只标的（北方华创、杰瑞股份、科力尔）全部成功检索到 claims，时效标签正确。无异常。

**Qing-Agent 完整链路耗时基准（2026-06-10 实测）**：

| 阶段 | 耗时 | 说明 |
|------|------|------|
| 行情拉取 | ~15s | `fetch_quotes_with_fallback()` 腾讯+新浪+东财 |
| HTTP API 调用 | ~50-55s | `/analyze/trigger` 端到端（含 LangGraph 管线） |
| 脚本开销 | ~5-10s | JSON 序列化、文件写入、日志 |
| **总计** | **~70-75s** | 完整链路 |

> **关键推论**：`QING_AGENT_TIMEOUT` 必须 ≥ 90s（留 20s 缓冲），推荐 120-180s。`HERMES_CRON_SCRIPT_TIMEOUT` 必须 ≥ 150s（覆盖完整链路 + 20s 缓冲），推荐 200-300s。

**验证命令**：
```bash
# 1. 检查 daily_state.json 是否存在且最近有更新
ls -la ~/learning-investment-strategies/config/stock_monitor/daily_state.json
# 期望：文件存在，mtime 在 5 分钟内

# 2. 检查文件内容结构
python3 -c "
import json
with open('config/stock_monitor/daily_state.json') as f:
    d = json.load(f)
assert 'timestamp' in d, '缺少 timestamp'
assert 'market_status' in d, '缺少 market_status'
assert 'sector_rotations' in d, '缺少 sector_rotations'
print(f'✓ daily_state 结构正确，timestamp={d[\"timestamp\"]}')
"

# 3. 触发一次 Qing-Agent 分析并检查输出
curl -s --max-time 200 -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"测试daily_state","session_id":"test-ds","analysis_type":"market"}' \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
output = d.get('final_output', '')
has_block = 'daily_state' in output
print(f'final_output length={len(output)}, has_daily_state_block={has_block}')
"
# 期望：length > 500, has_daily_state_block=True

# 4. 检查 sync_daily_state.py 是否能解析最近 cron 输出
python3 scripts/sync_daily_state.py --dry-run
# 期望：找到至少一个含 daily_state 代码块的 cron 输出文件
```

**详细文档**：
- `references/daily-state-pipeline-root-cause.md` —— 四层断裂根因分析
- `references/daily-state-persist-implementation.md` —— `market_analyst` 节点持久化实现
- `references/qing-agent-timing-benchmark.md` —— 完整链路耗时基准数据
**详细文档**：`references/daily-state-pipeline-root-cause.md`

### 陷阱 14: 条件驱动轮询未部署

**反面案例（2026-06-10）**：`stock_monitor.py::evaluate_position_alerts()` 已实现 add_zone 触发逻辑，但 9 个看盘 cron 都走 `--agent-json-context`（LLM 路径，消耗 token），不经过 `run_tick()`（纯规则路径）。

**根因**：缺少独立的 no-agent cron job 调用纯规则检查。

**修复方案**：
1. 实现 `scripts/qing_stock_monitor_poll.py`：调用 `stock_monitor.run_tick()` 或独立实现行情拉取 + add_zone/reduce_zone/risk_zone 检查
2. 纯规则推送微信消息，0 token
3. 注册 Hermes cron job：`*/5 9-15 * * 1-5`，no-agent 模式

**与 LLM 路径的分工**：
- 轮询路径（no-agent）：价格触发提醒、风控告警、机会触发通知
- LLM 路径（agent）：深度分析、方向判断、策略更新

### 陷阱 15: 设计文档 vs 代码实现差距

**反面案例（2026-06-10）**：用户要求"根据 config-cron-architecture-review.md 检查 skill 需要哪些更新"。AI 初判"大部分已落地"，但深入核查后发现多个关键文件缺失。

**根因**：设计文档（`docs/config-cron-architecture-review.md` §7.2）列出了"新增文件"和"新增 cron job"，但**文件系统检查确认它们不存在**。这是典型的"文档先行、代码滞后"。

**缺失文件清单**（截至 2026-06-10）：
| 文件 | 文档状态 | 实际状态 |
|------|---------|---------|
| `scripts/sync_claims_to_config.py` | ✅ 新增 | ❌ 不存在 |
| `scripts/sync_daily_state.py` | ✅ 新增 | ❌ 不存在 |
| `scripts/qing_stock_monitor_poll.py` | ✅ 新增 | ❌ 不存在 |
| `scripts/backfill_linked_claims.py` | ✅ 新增 | ⚠️ 需核实（linked_claims 已回填但脚本位置不明）|
| `config/stock_monitor/daily_state.json` | ✅ 状态机 | ❌ 从未被创建 |

**正确做法**：
1. 不要凭文档判断实现状态——**必须文件系统检查**
2. 对设计文档中的"新增文件"逐项 `ls` 或 `search_files` 确认
3. 区分"代码已写"和"文档已写"——后者不等于前者
4. Skill 更新时必须标注：✅ 已落地 / ❌ 未实现 / ⚠️ 部分实现

**验证命令**：
```bash
cd ~/learning-investment-strategies
echo "=== 核查设计文档中的新增文件 ==="
for f in scripts/sync_claims_to_config.py scripts/sync_daily_state.py \
         scripts/qing_stock_monitor_poll.py scripts/backfill_linked_claims.py; do
  if [ -f "$f" ]; then echo "✅ $f"; else echo "❌ $f"; fi
done
echo "=== daily_state.json ==="
ls -la config/stock_monitor/daily_state.json 2>/dev/null || echo "❌ 不存在"
```

### 陷阱 17: UP 复盘源文件搜索漏了 `sources/original/bilibili/`

**反面案例（2026-06-11）**：用户要求「根据 UP 昨天晚上复盘的观点梳理观察方向和核心标的」，AI 先搜了 `sources/raw/财经/` 里的 6/10 早盘和动态，又搜了 claims，但错过了关键信息 — 全板块研判、组合策略、具体标的都在 **`sources/original/bilibili/`** 的 6/10 22:54 复盘原文中（claims 已从此提取，但 AI 没有沿着 `source_path` 追回原文）。

**根因**：搜索优先级错了 — 先 raw 后 claims，唯独没搜 `sources/original/bilibili/`。

**正确的数据源优先级（构建 watchlist 时）**：
1. **`sources/original/bilibili/`** — 自动抓取的原始专栏/动态（最完整，含全板块研判 + 组合策略 + 标的清单）
2. **`knowledge/claims/`** — 从上面提取的结构化 claims（有 `source_path` 指针、stock codes、置信度）
3. **`sources/raw/财经/`** — 手动转录的 markdown（不一定有所有内容）
4. **关键纪律**：读取 claims 时，检查 `source_path` 字段 → 如果指向 `sources/original/bilibili/`，**先追回去读原文**。Claims 是摘要，原文才有完整语境。

**「构建观察池」任务的强制搜索清单（防止再次漏搜）**：

```
Step A: 获取近期 claims
  mcp_neo4j_get_recent_claims(days=2)
  → 获取全部 claim_type（sector-theme + operation + market-cycle）

Step B: 找到晚间复盘原文（22:54 附近）
  ls -lt sources/original/bilibili/ | head -5
  → 找到最近一期标题含「复盘」的文件
  → 如果 claims source_path 指向了它，直接 read_file

Step C: 读取原文全文
  → 原文 = 全板块研判 + 具体标的 + 组合策略 + 操作总纲
  → 不要只依赖 claims 摘要

Step D: 补充早盘和动态
  ls -lt sources/raw/财经/ | head -10
  → 读取同期「早盘」「动态」文件（原文可能不在 original 中）

Step E: 按优先级生成
  → 原文全板块排序 = 第一梯队/第二梯队/规避清单
  → 过滤主板（sh6xxxxx/sz0xxxxx）
  → 计算介入价位（curl 腾讯 API → 按涨跌幅分策略）
```

**反面案例（2026-06-11 两次被纠正）**：
1. 第一次纠正：用户说「你这复盘搜的不对，复盘里有核心策略…你用了知识库没？」→ AI 只搜了 raw 早盘和动态，没读 22:54 的原文
2. 第二次纠正：「是6-10号的复盘？不是6/9的，知识库里没有吗？」→ AI 把 6/9 复盘当成了 6/10 复盘，没注意到 claims 的 source_date 是 6/10 且 source_path 指向 original/bilibili

**教训**：当用户问「根据 UP 昨晚复盘」时，必须执行 Step A→B→C 完整链路，不能跳到 raw 就停止。

### 陷阱 18: bare `except: pass` 隐藏了完全失效的功能

**反面案例（2026-06-10）**：`context_builder.py`（429行）完整实现了 Neo4j 图遍历 + Qdrant 语义召回 + 浓度控制，但从第一天起 4 处 `max(dates)` / `datetime.strptime()` 因 Neo4j 返回 `neotime.Date` 对象统一抛 `TypeError`。所有调用点都用裸 `except: pass` 捕获，**日志无警告、无崩溃、无提示**。

结果：429 行代码全部落地，但**没有一行真正工作过**。SKILL.md 标记 ✅"已实现"，但实际效果等于 ❌。

**根因链**：
```
Neo4j 返回 neotime.Date 类型（非 Python datetime.date，非 str）
  → context_builder.py 用 strptime() / max(dates) 直接处理
  → TypeError: '>' not supported between instances of 'Date' and 'str'
  → except Exception: pass 吞掉异常
  → build_market_context() 返回空 stock_contexts + direction_signals
  → LLM 收不到任何 claims 增强上下文
```

**核查清单**（遇到 `except Exception: pass` 时必查）：
1. 这个 `try` 块内的逻辑是否真的被完整执行过？不只是"import 不报错"
2. 如果失败，fallback 是功能受限还是功能消失？
3. 有没有办法给这个功能加一个独立的测试/验证路径？

**正确做法**：
- 宁可在临界点写多行类型处理，也不要裸 `except: pass`
- `except` 必须标注具体异常类型（`TypeError`, `ValueError` 等），至少 `except Exception as e: logger.warning(...)`
- 对跨数据源（Neo4j vs Qdrant vs mem0）的字段，必须统一类型后再操作
- 新增功能必须做端到端验证（如 `build_market_context()` 传入真实数据测试输出），不能只测"import 不报错"

**详细参考**：`references/architecture-review-framework.md` §陷阱5

### 陷阱 19: sector_rotation_rules YAML dict-in-list 导致 poll cron 崩溃

**反面案例（2026-06-11）**：修改 watchlist/strategy_pack 后，no-agent 轮询 job（`qing_stock_monitor_poll.py`）报 `TypeError: unhashable type: 'dict'`，崩溃在 `_aggregate_sector_strength()` 第 526 行。

**根因**：`strategy_pack.yaml` 的 `sector_rotation_rules` 中 `offensive_groups`/`defensive_groups` 写成了**内嵌股票列表的 dict 格式**：
```yaml
# ❌ 错误格式
offensive_groups:
- pricing_power: [雅克科技, 昊华科技, 中钨高新, 风华高科]
```
YAML 解析为 `[{pricing_power: [...]}]` — list of dicts。但 `_aggregate_sector_strength(strengths, group_ids)` 期望 `group_ids: list[str]`，把 dict 当 str 做 hash lookup → `TypeError`。

**这个格式是 pre-existing 的**（早于我们本次 config 修改），但因为 no-agent 轮询 job 是近期才部署的，此前从未触发过此代码路径。LLM-based cron job 不走 `evaluate_sector_rotation_alerts()` 所以未暴露。

**正确格式**：offensive_groups 只需字符串列表——group ID 在 `sector_groups` 中已有定义，内嵌的股票列表从未被代码使用。
```yaml
# ✅ 正确格式
offensive_groups:
- pricing_power
```

**排查方法**：cron job 报错后，直接复现脚本调用链：
```bash
cd ~/learning-investment-strategies
PYTHONPATH=src .venv/bin/python scripts/stock_monitor.py --ignore-trading-time
# 看完整 traceback → 定位实际崩溃行 → 对照 YAML 格式
```

**教训**：
1. **修改 config 后必须至少跑一次 no-agent 脚本验证**，不能只跑 `validate_config.py`（它不检查 dict vs list 类型错误）
2. **YAML 中嵌入 dict 做 key 映射是反模式**：宁可用 `{id: xxx, members: [...]}` 扁平结构，也不要用 `{key: value}` 做 list 元素
3. **「改了 config 后 cron 崩了」时**：先不要假设是自己改坏的，用脚本直接复现看完整 traceback，根因可能在 pre-existing 格式问题

### 陷阱 20: Cron script 文件名不匹配 → 全静默空输出

**反面案例（2026-06-11）**：修改 config 之后，用户发现「所有看盘定时任务都没有发过微信消息」。排查发现全部 9 个 agent cron job 当天输出都是 **0 字节空文件**，但 cron status 全部显示 `ok`——无任何 error 信号。

**根因**：
```
cron script 字段 = "qing_stock_monitor_agent.py"（文件不存在）
  实际文件 = "hermes_stock_monitor_agent.py"
  → Hermes scheduler 找不到脚本 → 静默跳过，无 error
  → 输出 0 字节空文件 + status "ok"
```

**为什么之前能工作**：文件可能曾以旧名称存在（或软链接），在 git 操作中被移除后 cron job 定义未同步更新。昨天的输出有内容，今天全是空的。

**如何排查静默失败**：
```bash
# 1. 检查 cron 输出文件大小
ls -lt ~/.hermes/cron/output/<job_id>/ | head -3
stat -c%s ~/.hermes/cron/output/<job_id>/<latest>
# 0 字节 + status=ok → 极可能是脚本不存在

# 2. 检查 script 字段引用的文件是否存在
ls -la scripts/<script_field_value>
```

**教训**：
1. **cron status "ok" ≠ 脚本执行成功**：scheduler 在脚本不存在时可能不报 error
2. **重命名脚本时必须同步更新所有引用它的 cron job**
3. **Config 修改后验证应包括 cron 端到端**：至少 dry-run 一个 agent job 和一个 no-agent job

### 陷阱 21: subprocess 调用使用硬编码文件路径 → 文件重命名/移动后静默失败

**反面案例（2026-06-11，多次发生）**：`hermes_stock_monitor_agent.py`、`qing_stock_monitor_poll.py`、`hermes_stock_monitor_daily_review.py` 等脚本通过 `subprocess.run(["python", "scripts/stock_monitor.py", ...])` 调用 `stock_monitor.py`。文件名/路径一旦变化（重命名、重构、移动），脚本内部 subprocess 调用全部静默失败——**外层 cron status=ok + 0字节输出**，与陷阱 20 的表象完全相同。

**根因**：
```python
# ❌ 硬编码文件路径 — 脚本重命名后全部失效
command = [python_cmd, "scripts/stock_monitor.py", *extra_args]

# ✅ 模块路径 — 不依赖文件名
command = [python_cmd, "-m", "qing_investment.stock_monitor", *extra_args]
```

**涉及的所有脚本（2026-06-11 批量修复）**：
| 脚本 | 硬编码调用 | 修复 |
|------|-----------|------|
| `hermes_stock_monitor_agent.py` | `scripts/stock_monitor.py` (×2) | `-m qing_investment.stock_monitor` |
| `hermes_stock_monitor_daily_review.py` | `scripts/stock_monitor.py` (×2) | `-m qing_investment.stock_monitor` |
| `qing_stock_monitor_poll.py` | `REPO_ROOT/"scripts"/"stock_monitor.py"` | `-m qing_investment.stock_monitor` |

**教训**：
1. **subprocess 调用项目内模块永远用 `-m`**，不要用文件路径
2. **`-m` 的前提**：目标模块必须有 `if __name__ == "__main__"` 入口
3. **排查时先确认 subprocess 调用链**：外层 cron → 脚本 A → subprocess 脚本 B，B 路径失效时外层无感知
4. **Hermes 包装器规则（2026-06-11 补充）**：`~/.hermes/scripts/` 下的包装器调用项目脚本时，统一用 `PYTHONPATH=scripts:src python -m <module>`，不要用 `python scripts/xxx.py`。跨文件系统边界的文件路径在 cron 环境下极易失效

### 陷阱 22: `git add -f` 绕过 .gitignore 导致隐私文件被推送

**反面案例（2026-06-11）**：用户更新持仓后，AI 用 `git add -f config/stock_monitor/positions.yaml` 强制添加了 .gitignore 中已显式排除的文件，导致持仓隐私数据被推送到 GitHub。用户发现后要求立即回滚。

**根因**：
```bash
# ❌ -f 绕过 .gitignore 保护
git add -f config/stock_monitor/positions.yaml

# ✅ 普通 add 尊重 .gitignore
git add config/stock_monitor/positions.yaml    # 会被忽略
git add -A                                       # 不会添加 gitignored 文件
git add .                                        # 同上
```

**教训**：
1. **永远不要对 gitignored 文件使用 `-f` / `--force`**：`.gitignore` 的存在本身就是意图声明
2. **`positions.yaml` 是最高敏感级别**：包含实盘持仓成本、股数、账户名，已在 `.gitignore` + `positions.example.yaml` 模板模式保护下
3. **提交前检查**：`git status` 中不应出现 positions.yaml，出现时说明 gitignore 有问题，不是去 `-f`

### 陷阱 23: Cron script 字段指向 project/scripts/ 的文件 → Hermes 找不到 → LLM fallback

**反面案例（2026-06-11）**：用户发现定时任务的输出内容异常——不是 Qing-Agent 的分析结果，而是 LLM 直接处理 cron prompt 后生成的通用回答。排查后发现 cron 的 script 字段指向了项目目录下的文件，但 Hermes scheduler 只在 `~/.hermes/scripts/` 下查找。

```
# ❌ Hermes 找不到 → 静默 fallback 到 LLM 模式
script: "hermes_stock_monitor_agent.py"

# ✅ Hermes 能找到 → 执行脚本
script: "qing_stock_monitor_agent.py"
```

**根因**：Hermes cron scheduler 的 script 字段**始终相对于 `~/.hermes/scripts/` 解析**，不受 workdir 影响。当 script 文件不存在时，Hermes **不报 error**，而是将 cron prompt 直接交给 LLM 处理——这就是为什么 cron 输出"有内容"但内容不对。

**为什么容易踩**：
- 项目 `scripts/` 下有 `hermes_*` 文件，直觉上 cron 应该能引用
- LLM fallback 输出**有内容**（不像陷阱 20 的 0 字节），更容易误判为"正常工作"
- **判断标准**：输出是不是 Qing-Agent 的分析格式（含介入价位、技术分析），还是 LLM 的通用投资建议

**与陷阱 20/21 的区别**：

| 陷阱 | 症状 | 根因 |
|------|------|------|
| 20 | 0 字节 + status=ok | `~/.hermes/scripts/` 下文件名写错了，完全找不到 |
| 21 | 0 字节 + status=ok | 脚本存在但内部 subprocess 路径失效 |
| **23** | **有内容但不对** + status=ok | 脚本根本不在 `~/.hermes/scripts/`（在 project 里），Hermes 静默回退 LLM |

**架构约束**（已写入 AGENTS.md）：
```
~/.hermes/scripts/qing_*.py   ← 稳定入口（cron script 字段引用，永不改名）
    │ delegate/subprocess
    ▼
project/scripts/hermes_*.py   ← 实际逻辑（可演进，可重命名）
```

**教训**：
1. **cron script 字段只能引用 `~/.hermes/scripts/` 下的文件**，不能引用 project 目录下的
2. **判断 cron 是否走了 LLM fallback**：看输出内容——Qing-Agent 分析有固定的结构化格式，LLM fallback 是通用投资建议
3. **架构分离**：`~/.hermes/scripts/` 是稳定接口层，project `scripts/` 是实现层。修改实现层文件不需要改 cron，改接口层才需要

### 陷阱 24: "可买"标签误导 + Agent 永远在等，从不给买入信号

**反面案例（2026-06-11）**：用户看到 cron 输出中「✅ 可买 — 昊华科技，等缩量企稳信号再动手」后以为可以买了，结果当天该股涨停。用户质问：「这个可买是怎么判断的？我以为现在可以买了。」

**根因是两个层面的问题**：

**层面 A — 标签混淆**：「✅ 可买」这个标题让人以为是买入信号，但正文写的是「等缩量企稳」。标题和正文语义矛盾。

**层面 B — 核心断层**：用户真正想要的是 Agent 能**主动检测条件满足并给出二值化买入信号**：
> 「我希望 Qing Agent 做到和 UP 同样的思维逻辑，分析之后，直接给我买入信号。比如他自己观察观察池里的票，已经缩量企稳了，然后告诉我今天这个点位可以买入了。」

但现状是：
```
cron 定时触发 → Qing-Agent 分析 → 输出："昊华科技，等缩量企稳信号再动手"
                                    ↑
                              永远在"等"，永远不说"就是现在"
```

**与 poll 脚本的职责边界**：

| 组件 | 现在做的事 | 应该做的事 |
|------|-----------|-----------|
| poll 脚本（no-agent） | 价格进入 add_zone 提醒 | + 量价配合检测（缩量→放量转折、均线支撑） |
| Qing-Agent（agent） | 大盘+板块+全标的分析 | + 单票精准买入信号（二值化：买/不买，因为X） |

**缺失的能力**：
1. **买入信号检测**：poll 脚本只知道价格进入 add_zone，不知道量价配合是否到位
2. **单票深度研判**：Agent 收到 poll 触发后，应该只分析这一只票，用完整方法论给结论
3. **二值化输出**：Agent 的输出格式必须是「买，现价X，止损Y」或「不买，因为Z条件不满足」，不允许模糊空间

**教训**：
1. **UI 标签必须和正文结论一致**：标题写「等信号」就别用 ✅ 可买，改用「📋 条件单待触发」或「🎯 接近买入区间」
2. **Agent 输出必须是可执行的二值化结论**：买/不买 + 原因，不允许「等」「观察」「关注」这些安全词
3. **用户要的是替他去等的系统**，不是替他列出等什么的系统
4. **买入信号检测是 poll 脚本的第一优先级功能**，比风控提醒更重要 — 现在是反过来的
5. **完整设计方案**：见 `docs/design/buy-signal-detection-system.md`

### 陷阱 25: 框架过期自锁闭环 — 配置文件中的过期点位被 Agent 反复引用

**反面案例（2026-06-11）**：`daily_state.json` 和 `strategy_pack.yaml` 以 4033 作为操作锚，但 UP 已在 6/9 将生命线下调至 4000、6/11 完全不用 4033 了。Agent 每次分析都说"上证收盘3962<4033清仓线"——一个 12 天前就被跌破且 UP 已抛弃的数字。

**自锁机制**：
```
strategy_pack.yaml 含过期框架
  → Agent prompt 注入过期框架
  → Agent 输出："上证收盘3962<4033清仓线"
  → market_analyst 写入 daily_state.json
  → 下次 Agent 又从 daily_state.json 读到 4033
  → 循环
```

**打破方法**：手动更新 strategy_pack.yaml → 重启 Agent → 重写 daily_state.json。

**判断过期的信号**：
- 点位引用连续多天被实际行情大幅偏离（>3% 且持续 >5 天）
- claims 中同一主题的 statement 已出现修正/降级
- UP 最新早盘/复盘完全不再提该数字

**修复流程**：
1. `mcp_neo4j_search_claims_graph(keyword="点位")` → 找到最新相关 claim + 后续修正
2. 对比 `daily_state.json` / `strategy_pack.yaml` → 识别过期引用
3. 更新：点位 → `deprecated: true` + 演化说明；操作锚 → 对齐最新 UP 观点
4. 记录框架迁移到 `daily_state.json._meta.framework_migration`

**详细案例**：见 `references/framework-staleness-self-lock.md`

### 陷阱 26: 配置文件修改后 Agent 未重启 → 仍用旧框架分析

**反面案例（2026-06-11）**：清理 4033 过期引用后，`strategy_pack.yaml` 和 `daily_state.json` 已更新，但 Qing-Agent 的 gunicorn worker 持有旧代码缓存在内存中，下次 cron 分析仍可能引用过期框架。

**正确做法**：修改 Agent prompt 或配置文件后，**必须重启 Qing-Agent**：
```bash
kill $(pgrep -f "gunicorn") 2>/dev/null
sleep 2
cd ~/learning-investment-strategies
nohup .venv/bin/gunicorn qing_investment.agent.main:app \
  -w 1 -k uvicorn.workers.UvicornWorker \
  --bind 127.0.0.1:8000 --timeout 120 --keep-alive 5 \
  > /tmp/qing-agent.log 2>&1 &
```

---

## 关键纪律

- **先报告后修改**：差异报告必须经用户确认；代码改动同样需用户明确说"可以改"后再执行
- **用户说"让我想想" / "等下" / "别改"时立即停止**：回滚未确认改动，不争论
- **全链路检查**：不能只看 watchlist 不看 strategy_pack
- **claims 优先**：UP 直接点名的方向/标的必须补入 watchlist
- **Agent 健康优先**：Qing-Agent 离线时先重启再分析（用 gunicorn 单 worker，非 uvicorn；同时停止 MCP Qdrant server 避免锁冲突）
- **不未经确认提交**：用户说"不要提交"或"让我想想"时，立即停止并回滚未确认改动
- **验证必须跑**：`validate_config.py` + `check_config_consistency.py --json` + **no-agent 轮询脚本 dry-run**（`stock_monitor.py --ignore-trading-time`）
- **cron 健康必查**：config 修改后至少验证一个 agent cron job（`hermes_stock_monitor_agent.py`）和一个 no-agent cron job（`stock_monitor.py`）能正常执行，输出文件非 0 字节
- **主板-only**：用户只能交易 sh6xxxxx / sz0xxxxx。非主板标的标记 `tradable: false`
- **不删旧数据**：旧 theme 降级为 monitor_only，不删除
- **不编造价格**：数据源降级时诚实说明
- **区分设计决策 vs 遗留问题**：文档标 ❌ 的项，必须先确认是「设计如此」还是「尚未实现」。意图上保留人工审核门禁的流程不应列为"全链路自动化缺失"。差距报告必须区分 P0（真正缺失）、P1（可优化）、以及「已知设计约束」三类。
- **文档≠代码**：设计文档中的"新增文件"必须文件系统确认，不能凭文档判断实现状态
- **Agent 输出必须二值化**：买/不买 + 原因 + 价位，不允许「等」「观察」「关注」等安全词模糊结论。标题和正文结论必须一致 — 「等」就不要用「✅ 可买」
- **买入信号 > 风控提醒**：poll 脚本的第一优先级是检测量价配合 + 介入区间确认，推买入信号；风控告警是第二优先级
- **`parents[n]` 深度校验**：新增文件在 `src/qing_investment/agent/tools/`（深度4）vs `src/qing_investment/`（深度2）vs `scripts/`（深度1）时，`Path(__file__).resolve().parents[n]` 的 n 不同。加新文件时必须确认 n 指向 repo root，否则数据文件会写到错误目录（如 `kline_cache.py` 的 `parents[3]→parents[2]` 修复案例）
- **poll 静默输出 ≠ 失败**：poll cron 输出 0 字节 + status=ok 时，先确认是否"无规则触发"的正常状态，再排查脚本可用性。区分"全天全 0"（故障）和"间歇性 0"（正常）。（见陷阱 27）
- **改 config 必须同步改 cron prompt**：Agent cron job 的 prompt 字段是创建时的快照，不会随 config 更新自动同步。config 框架变更后必须对照更新 cron prompt，否则 Agent 仍用旧框架分析。（见陷阱 28）
- **测试 cron 避开已有时间点**：同一 HH:MM 的去重 key 为 `scheduled:{id}:{date}`，第二个 job 会被跳过。测试用一次性 cron 必须使用不同的分钟数。（见陷阱 29）
- **Cron 调度优化三原则**：移动（move）盘前/盘后任务、偏移（offset）分钟位避开 Agent 整点、降频（reduce）非关键轮询。**不删除有功能价值的任务**，用户说"很重要"时保留并偏移，不要直接删除。（见 `references/cron-schedule-optimization.md`）

---

### 陷阱 27: poll 静默输出 ≠ 失败 — 无提醒时是正常行为

**反面理解（2026-06-11 澄清）**：用户和 AI 看到 poll cron 输出 0 字节 + status=ok，第一反应是"又静默失败了"。但 poll 脚本（`d343f89ef487`）的 0 字节输出在**没有规则触发条件满足时是正常状态**——代表没有 add_zone/risk_zone/板块轮动 触发。

**与陷阱 20/21/23 的区别**：

| 陷阱 | 症状 | 持续性 | 性质 |
|------|------|--------|------|
| 20 | 0 字节 + status=ok | 全天才 0 | 💥 脚本文件不存在 |
| 21 | 0 字节 + status=ok | 全天才 0 | 💥 subprocess 路径失效 |
| 23 | 有内容但不对 | 全天才误报 | 💥 LLM fallback |
| **27** | **0 字节 + status=ok** | **间歇性（有时有内容）** | ✅ **正常** |

**判断方法**：不要只看单次输出的字节数。查 poll 的最近 10 次输出——如果有内容输出和 0 字节输出交替出现 → 正常（市场没有触发条件）。如果全天所有输出都是 0 → 排查脚本可用性。

**教训**：
1. **poll 输出 0 字节 ≠ 静默失败**，先确认是否有规则触发条件
2. **区分"全天全 0"和"间歇性 0"**：前者排查脚本可用性，后者是正常行为
3. **验证方法**：手动跑 `stock_monitor.py --ignore-trading-time` 看事件日志

### 陷阱 28: cron prompt 过期 — 改 config 不改 prompt → Agent 仍用旧框架

**反面案例（2026-06-11）**：清理了 `strategy_pack.yaml` 和 `daily_state.json` 中 4033 过期引用后，14:00 cron 的 Agent 分析仍输出"第三次修复观察期"框架关键词，而非新的"地量信号+情景A/B"。

**根因**：Agent cron job 的 `prompt` 字段在创建时写入固定文本，不会被 `strategy_pack.yaml` 修改自动更新。Agent 收到的 prompt 是 cron 创建时的快照。config 框架演进多轮，cron prompt 停在创建时。

**修复流程**：
1. 修改 `strategy_pack.yaml` market_framework → 同步更新 cron job 的 `prompt` 字段
2. 用 `cronjob(action='list')` 列出所有 agent cron 的 prompt → 对照新框架
3. 用 `cronjob(action='update', job_id=..., prompt=...)` 逐个更新
4. 验证：下一个 cron 触发时 Agent 输出是否含新框架关键词

**教训**：
1. **改 config ≠ 改 cron prompt**：cron prompt 是独立快照，不会自动同步
2. **Agent 输出的框架关键词是"金丝雀"**：看到旧框架词（"4033清仓""第三次修复观察期"）→ prompt 过期
3. **config 框架更新后必须检查 cron prompt 一致性**

### 陷阱 29: 同 HH:MM 测试 cron 被去重 — 测试 job 需避开已有时间点

**反面案例（2026-06-11）**：13:55 创建了 14:00 测试 job（`df4609ef3de4`），但已有日常 cron（`41c8e6da0e65`）在 14:00 触发。测试 job 输出为空。

**根因**：`find_agent_analysis_trigger()` 的去重 key 为 `scheduled:{id}:{date}`。同一 HH:MM 的第二个 job 即使 job_id 不同，也被判定为"今日已分析过"。

**正确做法**：测试用一次性 cron 必须使用**与现有 cron 不同的 HH:MM**，如 14:05、14:10。现有 cron 时间点见 `agent_analysis_schedule` 或 `cronjob list`。

### 陷阱 30: _normalize_code 后缀处理 — .replace('sz','') 吃掉 .SZ

**反面案例（2026-06-11）**：`pre_fetch_klines.py` 拉取 13 只标的全部失败（`'list' object has no attribute 'get'`），但 `fetch_stock_kline('600378')` 手动测试正常。根因：`_extract_stock_codes()` 返回带后缀代码（如 `000636.SZ`），`_normalize_code()` 用 `.replace("sz", "")` 逐层清洗 → `000636.SZ` → `000636.S` → `000636S` → API 收到 `sz000636S` → `param error` → `data["data"]` 返回空 list → `.get()` 失败。

**根因链**：
```python
# ❌ 顺序替换 = 灾难
"000636.SZ".replace("sh", "").replace("sz", "").replace(".", "")
# → "000636SZ" → "000636.S" → "000636S"
# full_code = "sz000636S"  ← API 不认识

# ✅ 先剥离已知后缀
if code.endswith(".sz") or code.endswith(".sh"):
    code = code[:-3]
pure = code.replace("sh", "").replace("sz", "")
```

**为什么人工测试能过**：手动传入无后缀代码（`'600378'`），绕过了后缀清洗路径。

**教训**：
1. **字符串清洗必须按结构处理**：先剥离已知后缀，再清洗残余前缀。裸 `replace()` 无法区分上下文
2. **测试要覆盖带后缀的输入**：如果 test 只用无后缀码（`'600378'`），永远发现不了 `'000636.SZ'` 的 bug
3. **API 返回空 list ≠ 网络失败**：`'list' object has no attribute 'get'` 这个错误信息暗示的是数据形状变化，不是网络不通
4. **涉及文件**：`src/qing_investment/agent/tools/stock_data.py`，修复在 `f8d37b4`

### 陷阱 31: poll 读 watchlist 时用了错误字段 — `buy_setup` vs `entry_zone.price_range`

**反面案例（2026-06-11）**：用户问 poll 为什么从不检测 watchlist 中的买入机会。排查发现：poll 的 watchlist 回退路径读的是 `stock["buy_setup"]`，但所有 P1/P2 标的的价格区间写在 `stock["entry_zone"]["price_range"]` 里。两个字段表达同一含义，但写入者和读取者各指各的。

**根因链**：
```
写入者/手动编辑: entry_zone.price_range: "118.0 ~ 122.0"
  ↓
poll 读取: buy_setup = stock.get("buy_setup", "")  → 大部分标的没有此字段
  ↓
parse_price_zone("") → None
  ↓
poll 静默跳过该票（无日志，无警告）
  ↓
用户以为 poll 在看，实际上该票从不在候选列表里
```

**涉及代码** (`stock_monitor.py:403-418`)：
```python
# ❌ 当前（读 buy_setup）
buy_setup = stock.get("buy_setup", "")       # 大部分标的没有这个字段
zone = parse_price_zone(buy_setup)           # → None → 该票永远不被 poll 看到

# ✅ 正确（读 entry_zone.price_range）
ez = stock.get("entry_zone", {}) or {}
pr = ez.get("price_range", "")
zone = parse_price_zone(pr)                  # "118.0~122.0" → (118.0, 122.0)
```

**为什么 entry_points 路径能触发但 watchlist 路径不能**：`strategy_pack.entry_points[]` 的读取路径是对的（读 `entry_zone` 字段），`positions.add_zone` 的读取路径也是对的，唯独 watchlist 回退路径读错了字段。所以 entry_points 生成的候选能触发，watchlist 标的从不触发——表面上它在监控，实际它在冷宫。

**正确做法**：
1. **修复 poll 读取路径**：`stock_monitor.py:407-409` 从 `stock.get("buy_setup")` 改为 `stock.get("entry_zone", {}).get("price_range")`
2. **废除 `buy_setup` 作为价格区间字段**：`buy_setup` 仅作为"买入条件补充说明"（如"等昊华科技企稳"），poll 不应从中提取数字。**唯一的区间字段 = `entry_zone.price_range`**，格式 `"低~高"` 或 `"低-高"`
3. **P3-观察标的写 `price_range: null`**，取代 `"不设介入区间（仅观察）"` 这类描述字符串（parse_price_zone 解析失败无警告）
4. **在 `save_watchlist()` 中加字段完整性校验**：P1/P2 标的必须有 `entry_zone.price_range`，格式是数字范围

**验证命令（修复后）**：
```bash
cd ~/learning-investment-strategies
python3 -c "
import sys; sys.path.insert(0, 'src')
stock = {'entry_zone': {'price_range': '118.0 ~ 122.0'}}
ez = stock.get('entry_zone', {}) or {}
from qing_investment.stock_monitor import parse_price_zone
z = parse_price_zone(ez.get('price_range', ''))
assert z == (118.0, 122.0), f'→ {z}'
print('✅ poll 读取 entry_zone.price_range 正常')
"
```

**与陷阱 30 的区别**：陷阱 30 是代码清洗逻辑的 bug（字符串 replace 顺序），陷阱 31 是**架构层面的字段映射不一致**——写入者和读取者用了不同的字段名表达同一概念。前者是「怎么写错了」，后者是「用哪个字段来写/读根本没定」。

**子案例：P3-观察标的 price_range 语义矛盾**

同一次修复中发现的和远气体(002971)案例：P3-观察标的，`price_range: "48.0 ~ 50.0（仅供参考，不建议主动介入）"`。注释写「不建议介入」，但 parse_price_zone 提取数字 (48.0, 50.0)，poll 视为有效的介入区间，每天参与 6 条件评估。——代码不读注释。

**规则**：P3-观察标的的 price_range **必须为 null**。禁止写数字区间（哪怕带说明文字）。`validate_watchlist.py` 的 `--fix-null` 修复文本描述，但对含数字的混合文本需要手动处理。

**修复（2026-06-11）**：6 只 P3 标的的 price_range 统一清理为 null。`scripts/validate_watchlist.py` 增加对 P3+数字 price_range 的 ⚠️ 警告。


## 验证清单

- [ ] `check_config_consistency.py` P0 清零
- [ ] `validate_config.py` 退出码 ≤1
- [ ] Qing-Agent `/analyze/trigger` 端点测试通过（非仅 /health）
- [ ] strategy_pack.updated_at 已更新
- [ ] cron prompt 已验证（dry-run）
- [ ] `daily_state.json` 存在且最近 5 分钟有更新（需 Qing-Agent 启动 + `market_analyst` 节点 `_persist_daily_state_from_market_context()` 已部署）
- [ ] `sync_daily_state.py` 能成功解析最近 cron 输出（含 ```daily_state 代码块）
- [ ] `qing_stock_monitor_poll.py` 存在且可独立运行
- [ ] **no-agent 轮询脚本 dry-run 通过**：`PYTHONPATH=src timeout 30 .venv/bin/python scripts/stock_monitor.py --ignore-trading-time`（exit 0, 无 TypeError/KeyError）
- [ ] add_zone/reduce_zone/risk_zone 纯规则提醒正常推送
- [ ] **Qing-Agent 完整链路耗时 ≤ 90s**（基准 70-75s，见 `references/qing-agent-timing-benchmark.md`）
- [ ] **超时层级对齐**：`HERMES_CRON_SCRIPT_TIMEOUT` ≥ `QING_AGENT_TIMEOUT` + 60s
- [ ] Git 已提交，且 **未使用 `-f` 强制添加 gitignored 文件**（`git status` 不出现 positions.yaml 等隐私文件）
- [ ] **K线缓存初始化**：`infra/data/kline_cache.db` 存在且有数据（`python3 -c "from qing_investment.kline_cache import get_cache_stats; print(get_cache_stats())"`）
- [ ] **pre_fetch cron 已部署**：`~/.hermes/scripts/qing_pre_fetch_klines.py` 存在 + cron job `44bce96fa7a7` 已调度（06:30 周一到周五）
- [ ] **买入信号检测可用**：`evaluate_buy_signal_candidates()` 可正常运行（`PYTHONPATH=src .venv/bin/python -c "from qing_investment.stock_monitor import evaluate_buy_signal_candidates, load_monitor_config; print(evaluate_buy_signal_candidates(load_monitor_config(), {}))"`）
- [ ] **Watchlist 字段校验**：`python scripts/validate_watchlist.py` 退出码=0
