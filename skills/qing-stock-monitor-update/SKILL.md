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
| Agent-UP 矛盾处理 | 本 SKILL §陷阱 |
| Cron pipeline 架构 | `references/cron-pipeline-architecture.md` |
| 实施状态核查 | `references/implementation-audit-checklist.md` |
| Qing-Agent 服务运维速查 | `references/qing-agent-service-operations.md` |
| Qing-Agent 服务架构（uvicorn→gunicorn 单 worker） | `references/qing-agent-gunicorn-migration.md` |
| 系统问题修复记录（2026-06-10） | `references/fix-monitor-system-issues-20260610.md` |

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

**⚠️ `/health` 通过 ≠ 管线正常**。`/health` 只检查进程存活，不检查 LangGraph 管线。

**根因**：uvicorn 单 worker 串行排队 + 管线 30s+ 耗时 vs 脚本 45s 超时。第一个慢请求触发 worker 忙碌 → 后续请求排队 → 全部超时走 fallback。不是代码 bug，是超时争用。

**已修复（2026-06-10）**：
1. **超时调大**：45s → **180s** + 3 次指数退避重试
2. **uvicorn → gunicorn 单 worker**：进程崩溃自动重启、优雅关闭、统一日志
3. **成功/失败显式标记**：`[Qing-Agent ✓]` / `[Qing-Agent ✗ FALLBACK]`
4. **Qdrant 锁冲突解决**：停止 MCP Qdrant server，让 Qing-Agent 独占 `.qdrant_data` 本地文件访问（Qdrant 本地模式使用排他锁，同一时刻只能有一个进程）

**QING_AGENT_TIMEOUT 调优**：脚本默认 45s 对 30s+ 管线偏紧。已改为 **180s** + **3 次指数退避重试**（1s/2s/4s）。环境变量可覆盖：
```bash
export QING_AGENT_TIMEOUT=180  # 置入 .bashrc 或 cron 环境
export QING_AGENT_MAX_RETRIES=3
```

**正确做法**：Step 1 前置真实端点检测（含 blast radius 扫描 + `/analyze/trigger` 实测，max-time 30s）。运维命令速查见 `references/qing-agent-service-operations.md`。
```bash
# 第一步：扫 blast radius（检查最近 cron 输出标记）
# 成功标记：[Qing-Agent ✓]  失败标记：[Qing-Agent ✗ FALLBACK] 或旧版 [qing-agent fallback
for dir in ~/.hermes/cron/output/*/; do
  latest=$(ls -t "$dir"/*.md 2>/dev/null | head -1)
  [ -n "$latest" ] && grep -lE "Qing-Agent . FALLBACK|qing-agent fallback" "$latest" && echo "  ↳ $(basename $dir)"
done

# 第二步：直接测 /analyze/trigger（非 /health，max-time 30s 匹配 120s 超时 + 管线耗时）
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

> **参数速查**：
> | 参数 | 含义 |
> |---|---|
> | `-w 1` | 1 个 worker（Qdrant 本地模式限制） |
> | `-k uvicorn.workers.UvicornWorker` | 每个 worker 用 Uvicorn 处理 ASGI |
> | `--timeout 120` | worker 处理请求的最大时间（秒） |
> | `--keep-alive 5` | HTTP keep-alive 连接保持 5s |

### 陷阱 3: Agent vs UP 矛盾

**反面案例（2026-06-10）**：万泽跌停，Qing-Agent 建议清仓，UP 10:04 说"直接砍不合适"。

**处理流程**：
1. 时序判断：UP 观点在 Agent 分析之后 → 以 UP 为准
2. 归类：信息不对称（Agent 缺 claim-007）→ 补 claims → 重新分析
3. 写入 strategy_pack 时标注来源 claim ID

### 陷阱 4: invalidation 点位过期

数字点位（如"收盘跌破4000"）和当前指数偏离 >3% 时自动检测。Step 1 门禁覆盖。

### 陷阱 5: Cron prompt 空改

改了 cron prompt 但没验证 → 下次 cron 执行才发现不生效。

**正确做法**：Step 4 验证时 dry-run：
```bash
python3 scripts/hermes_stock_monitor_agent.py
# 检查输出是否含新框架关键词
```

### 陷阱 6: Neo4jClient 方法缺失导致 Context Builder 失效

**反面案例（2026-06-10）**：`context_builder.py` 调用 `neo4j_client.get_claims_about_stock()` 和 `neo4j_client.get_sector_themes()`，但 `Neo4jClient` 类中不存在这两个方法 → `AttributeError` → Context Builder 完全失效 → claims 无法注入 Agent 分析。

**根因**：context_builder.py 是 Phase 2 新增组件，但 Neo4jClient 是 Phase 1 的类，新增调用点时未同步添加方法。

**已修复（2026-06-10）**：在 `Neo4jClient` 中新增：
- `get_claims_about_stock(code, limit=10)` — 通过 `ABOUT` 关系查找标的相关 claims
- `get_sector_themes(days=30, limit=100)` — 获取近期 sector-theme 类型 claims 的方向词
- `get_claim_evolution(claim_id)` — 获取 claim 的完整信息（含 statement、subject、claim_type）

**正确做法**：新增调用 Neo4jClient 的代码时，先检查类定义是否已有该方法。没有的话先补方法再调代码。

### 陷阱 7: trader_mindset.txt 是空壳，人格定义重复内嵌

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

### 陷阱 8: context_builder claims 排序未利用 reasoning_patterns

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

---

## 关键纪律

- **先报告后修改**：差异报告必须经用户确认
- **全链路检查**：不能只看 watchlist 不看 strategy_pack
- **claims 优先**：UP 直接点名的方向/标的必须补入 watchlist
- **Agent 健康优先**：Qing-Agent 离线时先重启再分析（用 gunicorn 单 worker，非 uvicorn）
- **验证必须跑**：`validate_config.py` + `check_config_consistency.py --json`
- **主板-only**：用户只能交易 sh6xxxxx / sz0xxxxx。非主板标的标记 `tradable: false`
- **不删旧数据**：旧 theme 降级为 monitor_only，不删除
- **不编造价格**：数据源降级时诚实说明

---

## 验证清单

- [ ] `check_config_consistency.py` P0 清零
- [ ] `validate_config.py` 退出码 ≤1
- [ ] Qing-Agent `/analyze/trigger` 端点测试通过（非仅 /health）
- [ ] strategy_pack.updated_at 已更新
- [ ] cron prompt 已验证（dry-run）
- [ ] Git 已提交
