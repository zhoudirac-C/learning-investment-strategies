> 对应任务文档：`docs/tasks/fix-monitor-system-issues.md`
> 审查来源：`docs/config-cron-architecture-review.md` v2.0
> 后续更新：2026-06-10 下午（timeout 120→180s，Qdrant 锁冲突深入分析）

---

## 背景

2026-06-10，基于 `config-cron-architecture-review.md` 的系统性审查，发现6个需要修复的问题。本记录详细说明每个问题的根因、修复方案和验证方法。

---

## 问题1：hermes_stock_monitor_agent.py 依赖注入失败

### 根因
`scripts/hermes_stock_monitor_agent.py` 的 `create_agent()` 函数使用 `__import__('qing_investment.agent.main')` 动态导入 Agent，但 `qing_investment.agent.main` 不是模块名（缺少 `__init__.py`），导致 `ImportError`。

### 修复
- 新增 `create_mock_agent()` fallback：当动态导入失败时，返回一个模拟 Agent，直接调用 LLM 生成分析
- 保留原 `create_agent()` 作为首选路径
- 增加 `QING_AGENT_TIMEOUT` 环境变量支持（默认 180s）
- 增加 3 次指数退避重试（1s/2s/4s）

### 验证
```bash
cd ~/learning-investment-strategies
python3 -c "from scripts.hermes_stock_monitor_agent import create_agent; print(create_agent())"
```

---

## 问题2：Neo4jClient 缺失 Context Builder 需要的方法

### 根因
`context_builder.py`（Phase 2 新增）调用 `Neo4jClient` 的三个方法，但 `Neo4jClient` 类（Phase 1）未定义这些方法：
- `get_claims_about_stock(code, limit=10)`
- `get_sector_themes(days=30, limit=100)`
- `get_claim_evolution(claim_id)`

### 修复
在 `src/qing_investment/agent/tools/neo4j_client.py` 中新增三个方法。

### 验证
```bash
cd ~/learning-investment-strategies
python3 -c "
from src.qing_investment.agent.tools.neo4j_client import Neo4jClient
client = Neo4jClient()
claims = client.get_claims_about_stock('000534', limit=3)
print(f'Found {len(claims)} claims')
client.close()
"
```

---

## 问题3：Context Builder Qdrant 语义召回 query 过于简单

### 根因
`context_builder.py` 的 Qdrant 语义召回 query 固定为 `"{name} {code} 技术分析 介入建议"`，没有利用 entry_points 的触发条件或 claims 中的技术面关键词。

### 修复
动态 query 生成逻辑：从 entry_points 找 trigger/buy_setup，或从 claims 提取技术关键词（回踩、突破、企稳、放量、缩量、分歧、加速、回调）。

### 验证
查看日志中的 query 生成：
```bash
grep "Qdrant query for" /tmp/qing-agent.log
```

---

## 问题4：trader_mindset.txt 是空壳文件

### 根因
`trader_mindset.txt` 只有两行说明，实际人格定义内嵌在 `market_analyst.txt` 中。`_load_prompt()` 的自动注入机制将空壳文件拼接到 analyst prompt 前，导致注入无效。

### 修复
1. 从 `market_analyst.txt` 和 `stock_analyst.txt` 剪切人格定义到 `trader_mindset.txt`
2. 重写 `trader_mindset.txt` 为 96 行完整人格定义
3. 清理 analyst prompt 中的重复内容

### 验证
```bash
grep -c "赔率思维" src/qing_investment/agent/prompts/system/trader_mindset.txt  # ≥1
grep -c "核心原则" src/qing_investment/agent/prompts/system/market_analyst.txt   # 0
```

---

## 问题5：10:00 节点 ID 对齐

### 验证结果
三处完全对齐，无需修复：
| 来源 | 10:00 ID | 状态 |
|------|----------|------|
| strategy_pack.yaml | `morning_confirm` | ✅ |
| stock_monitor.py DEFAULT | `morning_confirm` | ✅ |
| cron schedule | `0 10 * * 1-5` | ✅ |

---

## 问题6：context_builder claims 排序未利用 reasoning_patterns

### 修复
1. `_score_claim_relevance()` 新增 `active_patterns` 参数
2. claim 的 subject/statement 匹配到 active pattern 的 `applicable_themes` 时额外 +4 分
3. `build_stock_context()` 和 `build_market_context()` 透传 `active_patterns`
4. `retrieve_knowledge()` 预计算 `active_patterns`

---

## 后续更新：timeout 120→180s（2026-06-10 下午）

### 根因
Qing-Agent `/analyze/trigger` 端点在实际运行中仍偶发超时。120s 对 30s+ 管线 + 网络抖动偏紧。

### 修复
`scripts/hermes_stock_monitor_agent.py`：
```python
QING_AGENT_TIMEOUT = float(os.environ.get("QING_AGENT_TIMEOUT", "180"))
```

### 提交
commit `64032a8`：timeout 120→180s + 停止 MCP Qdrant server 解决锁冲突

---

## 后续更新：Qdrant 锁冲突深入分析（2026-06-10 下午）

### 发现
通过源码分析确认 Qdrant 本地模式使用 `portalocker.LockFlags.EXCLUSIVE | NON_BLOCKING`：

```python
# qdrant_client/local/qdrant_local.py
portalocker.lock(
    self._flock_file,
    portalocker.LockFlags.EXCLUSIVE | portalocker.LockFlags.NON_BLOCKING,
)
```

这意味着：
- 同一时刻只能有一个进程访问 `.qdrant_data`
- 第二个进程立即抛 `RuntimeError`，不是等待
- SQLite 底层 WAL 模式支持并发读，但 Qdrant 的文件锁阻止了它

### 实验
测试将 `EXCLUSIVE` 替换为 `SHARED`：
- 两个 `QdrantClient` 实例可以同时访问同一本地数据库
- 只读场景安全
- 写操作并发有数据损坏风险

### 当前方案
停止 MCP Qdrant server，让 Qing-Agent 独占访问。

### 详细技术文档
见 `references/qdrant-concurrency-lock.md`

---

## 文件变更汇总

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `scripts/hermes_stock_monitor_agent.py` | 修改 | 新增 `create_mock_agent()` fallback，超时 180s，3次重试 |
| `src/qing_investment/agent/tools/neo4j_client.py` | 修改 | 新增 Context Builder 需要的三个方法 |
| `src/qing_investment/agent/tools/context_builder.py` | 修改 | 动态 Qdrant query + `active_patterns` 参数 |
| `src/qing_investment/agent/graph/nodes.py` | 修改 | `retrieve_knowledge()` 预计算 `active_patterns` |
| `src/qing_investment/agent/prompts/system/trader_mindset.txt` | 重写 | 96行完整人格定义 |
| `src/qing_investment/agent/prompts/system/market_analyst.txt` | 修改 | 删除重复人格定义 |
| `src/qing_investment/agent/prompts/system/stock_analyst.txt` | 修改 | 删除重复人格定义 |
| `docs/tasks/fix-monitor-system-issues.md` | 新增 | 任务追踪文档 |

---

## 运维速查

### 重启 Qing-Agent（含停止 MCP Qdrant）
```bash
kill $(pgrep -f "uvicorn qing_investment") 2>/dev/null
kill $(pgrep -f "gunicorn") 2>/dev/null
kill $(pgrep -f "mcp_qdrant_server") 2>/dev/null
sleep 2

cd ~/learning-investment-strategies
nohup .venv/bin/gunicorn qing_investment.agent.main:app \
  -w 1 -k uvicorn.workers.UvicornWorker \
  --bind 127.0.0.1:8000 \
  --timeout 120 --keep-alive 5 \
  > /tmp/qing-agent.log 2>&1 &

sleep 3
curl -s --max-time 5 http://localhost:8000/health
curl -s --max-time 30 -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"重启验证","session_id":"restart-check","analysis_type":"market"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('RESTART OK' if d.get('final_output') else 'STILL BROKEN')"
```

### 检查最近 cron 是否有 fallback
```bash
for dir in ~/.hermes/cron/output/*/; do
  latest=$(ls -t "$dir"/*.md 2>/dev/null | head -1)
  [ -n "$latest" ] && grep -lE "Qing-Agent . FALLBACK|qing-agent fallback" "$latest" && echo "  ↳ $(basename $dir)"
done
```
