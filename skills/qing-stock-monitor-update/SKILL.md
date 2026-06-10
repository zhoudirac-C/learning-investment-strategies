---
name: qing-stock-monitor-update
description: |
  配置一致性驱动的看盘系统更新。基于 UP 最新观点 + config 交叉检查，输出差异报告后执行修改。
  Use when: "更新观察池"、"更新持仓"、"更新策略"、"检查配置"
---

# qing-stock-monitor-update

## 设计原则

**每次更新必须交叉检查全部 config**。不按文件分步，而是一个 checklist 覆盖 watchlist + strategy_pack + positions + cron 的一致性。

## 触发条件

- "更新观察池" / "更新方向" / "更新策略"
- "更新持仓" / "清仓" / "减仓"
- "检查配置" / "config review"
- "加标的" / "新增方向"

## 必读参考

| 场景 | 文件 |
|------|------|
| MCP 驱动方向更新 | `references/mcp-powered-directional-update.md` |
| 数据源降级 | `references/data-source-fallback-chain.md` |
| Claims 一致性校验 | `references/claims-consistency-check.md` |
| Entry points 生成 | `references/entry-points-generation.md` |
| 配置健康检查 | `references/config-health-check.md` |
| 持仓观察池区分修复记录 | `references/position-watchlist-distinction-fix.md` |
| 腾讯→新浪→东财降级链详情 | `references/tencent-sina-eastmoney-fallback-chain.md` |
| Agent-UP 矛盾处理 | 本 SKILL §陷阱 |
| Cron pipeline 架构 | `references/cron-pipeline-architecture.md` |
| **设计文档 vs 代码实现差距核查** | `references/design-doc-vs-implementation-gap.md` |
| **Config-cron 架构设计差距审计（2026-06-10）** | `references/design-doc-gap-audit-20260610.md` |
| Qing-Agent 服务运维速查 | `references/qing-agent-service-operations.md` |
| Qing-Agent 服务架构（uvicorn→gunicorn 单 worker） | `references/qing-agent-gunicorn-migration.md` |
| 系统问题修复记录（2026-06-10） | `references/fix-monitor-system-issues-20260610.md` |
| Qdrant 本地模式并发锁机制 | `references/qdrant-concurrency-lock.md` |
| Cron 脚本超时诊断手册 | `references/cron-script-timeout-diagnosis.md` |
| **Agent 时间限制绕过** | `references/agent-any-time-bypass.md` |
| **Cron 超时外部化配置** | `references/cron-timeout-external-config.md` |
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
python3 scripts/check_config_consistency.py
```

输出 **8 维差异报告**（P0/P1/P2 分级）：
1. strategy_pack 过期（日期、点位、方向词）
2. watchlist 缺口（claims 提到的标的未在 watchlist）
3. watchlist ↔ strategy_pack 对齐
4. positions 缺失（无 risk_zone 等）
5. invalidation 点位过期
6. cron focus 过期
7. claims 引用完整性
8. watchlist 字段校验（code 格式/priority/lifecycle/linked_claims/sentiment）

```bash
# JSON 输出供 LLM 消费
python3 scripts/check_config_consistency.py --json
```

### Step 2: 收集变化源

**变化源检测——找到「什么变了」：**

| 来源 | 方法 | 产出 |
|------|------|------|
| UP 最新 claims | `mcp_neo4j_get_recent_claims(days=2)` | 新观点列表 |
| B站动态 | `sources/original/bilibili/` → unprocessed 时转录 raw | raw 文件 |
| 用户操作 | 用户明确说的清仓/建仓/减仓 | 持仓变动 |
| 市场行情 | 腾讯 API 拉全A + 关键标的（仅 full update） | 实时价格 |

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
2. 运行 `python3 scripts/validate_config.py` 验证
3. 运行 `python3 scripts/check_config_consistency.py --json` 确认 P0 清零
4. 更新 strategy_pack.updated_at
5. Git 提交

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

### 陷阱 16: bare `except: pass` 隐藏了完全失效的功能

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

---

## 关键纪律

- **先报告后修改**：差异报告必须经用户确认；代码改动同样需用户明确说"可以改"后再执行
- **用户说"让我想想" / "等下" / "别改"时立即停止**：回滚未确认改动，不争论
- **全链路检查**：不能只看 watchlist 不看 strategy_pack
- **claims 优先**：UP 直接点名的方向/标的必须补入 watchlist
- **Agent 健康优先**：Qing-Agent 离线时先重启再分析（用 gunicorn 单 worker，非 uvicorn；同时停止 MCP Qdrant server 避免锁冲突）
- **不未经确认提交**：用户说"不要提交"或"让我想想"时，立即停止并回滚未确认改动
- **验证必须跑**：`validate_config.py` + `check_config_consistency.py --json`
- **主板-only**：用户只能交易 sh6xxxxx / sz0xxxxx。非主板标的标记 `tradable: false`
- **不删旧数据**：旧 theme 降级为 monitor_only，不删除
- **不编造价格**：数据源降级时诚实说明
- **文档≠代码**：设计文档中的"新增文件"必须文件系统确认，不能凭文档判断实现状态

---

## 验证清单

- [ ] `check_config_consistency.py` P0 清零
- [ ] `validate_config.py` 退出码 ≤1
- [ ] Qing-Agent `/analyze/trigger` 端点测试通过（非仅 /health）
- [ ] strategy_pack.updated_at 已更新
- [ ] cron prompt 已验证（dry-run）
- [ ] `daily_state.json` 存在且最近 5 分钟有更新（需 Qing-Agent 启动 + `market_analyst` 节点 `_persist_daily_state_from_market_context()` 已部署）
- [ ] `sync_daily_state.py` 能成功解析最近 cron 输出（含 ```daily_state 代码块）
- [ ] `qing_stock_monitor_poll.py` 存在且可独立运行
- [ ] add_zone/reduce_zone/risk_zone 纯规则提醒正常推送
- [ ] **Qing-Agent 完整链路耗时 ≤ 90s**（基准 70-75s，见 `references/qing-agent-timing-benchmark.md`）
- [ ] **超时层级对齐**：`HERMES_CRON_SCRIPT_TIMEOUT` ≥ `QING_AGENT_TIMEOUT` + 60s
- [ ] Git 已提交
