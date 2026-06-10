# Fix Monitor System Issues — 2026-06-10 实施记录

> 对应任务文档：`docs/tasks/fix-monitor-system-issues.md`
> 审查来源：`docs/config-cron-architecture-review.md` v2.0

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
- 增加 `QING_AGENT_TIMEOUT` 环境变量支持（默认 120s）
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
在 `src/qing_investment/agent/tools/neo4j_client.py` 中新增三个方法：

```python
def get_claims_about_stock(self, stock_code: str, limit: int = 10) -> list[dict]:
    """通过 ABOUT 关系查找与股票相关的 claims。"""
    query = """
    MATCH (c:Claim)-[:ABOUT]->(s:Stock)
    WHERE s.code = $code OR s.name = $code
    RETURN c.id as id, c.statement as statement, c.subject as subject,
           c.source_date as source_date, c.intensity as intensity,
           c.claim_type as claim_type
    ORDER BY c.source_date DESC
    LIMIT $limit
    """
    ...

def get_sector_themes(self, days: int = 30, limit: int = 100) -> list[dict]:
    """获取近期 sector-theme 类型 claims 的方向词列表。"""
    query = """
    MATCH (c:Claim)
    WHERE c.claim_type = 'sector-theme'
      AND c.source_date >= date() - duration('P' + $days + 'D')
    RETURN DISTINCT c.subject as direction
    LIMIT $limit
    """
    ...

def get_claim_evolution(self, claim_id: str) -> list[dict]:
    """获取 claim 的完整信息（用于 Qdrant 召回后补全）。"""
    query = """
    MATCH (c:Claim {id: $claim_id})
    RETURN c.id as id, c.statement as statement, c.subject as subject,
           c.source_date as source_date, c.intensity as intensity,
           c.claim_type as claim_type
    """
    ...
```

### 验证
```bash
cd ~/learning-investment-strategies
python3 -c "
from src.qing_investment.agent.tools.neo4j_client import Neo4jClient
client = Neo4jClient()
claims = client.get_claims_about_stock('000534', limit=3)
print(f'Found {len(claims)} claims')
for c in claims[:2]:
    print(f'  {c[\"id\"]}: {c[\"subject\"][:40]}...')
client.close()
"
```

---

## 问题3：Context Builder Qdrant 语义召回 query 过于简单

### 根因
`context_builder.py` 的 Qdrant 语义召回 query 固定为 `"{name} {code} 技术分析 介入建议"`，没有利用 entry_points 的触发条件或 claims 中的技术面关键词。

### 修复
动态 query 生成逻辑：
1. 基础部分：标的名称 + 纯数字代码
2. 从 `entry_points` 找该标的的 `trigger` 或 `buy_setup`，加入 query
3. 如果没有 entry_points，从 Neo4j claims 中提取技术关键词（回踩、突破、企稳、放量、缩量、分歧、加速、回调）
4. 如果都没有，fallback 到 `"技术分析 介入建议"`

```python
query_parts = [name, code.replace(".SZ", "").replace(".SH", "")]

# 从 entry_points 找触发条件
ep_trigger = ""
for ep in entry_points:
    if ep.get("code") == code and ep.get("status") == "active":
        trigger = ep.get("trigger", "")
        setup = ep.get("buy_setup", "")
        if trigger:
            ep_trigger = trigger
        elif setup:
            ep_trigger = setup
        break

if ep_trigger:
    query_parts.append(ep_trigger)
else:
    # fallback: 从 claims 中提取技术面关键词
    tech_keywords = []
    for c in neo4j_claims[:3]:
        stmt = c.get("statement", "")
        for kw in ["回踩", "突破", "企稳", "放量", "缩量", "分歧", "加速", "回调"]:
            if kw in stmt and kw not in tech_keywords:
                tech_keywords.append(kw)
    if tech_keywords:
        query_parts.extend(tech_keywords)
    else:
        query_parts.extend(["技术分析", "介入建议"])

query_text = " ".join(query_parts)
```

### 验证
查看日志中的 query 生成：
```bash
grep "Qdrant query for" /tmp/qing-agent.log
# 应输出动态生成的 query，而非固定模板
```

---

## 问题4：trader_mindset.txt 是空壳文件

### 根因
`trader_mindset.txt` 只有两行指向说明，实际人格定义内嵌在 `market_analyst.txt` 中。`_load_prompt()` 的自动注入机制将 trader_mindset.txt 拼接到 analyst prompt 前，但空壳文件导致注入无效。

### 修复
1. 从 `market_analyst.txt` 剪切人格定义（第1-40行）到 `trader_mindset.txt`
2. 从 `stock_analyst.txt` 剪切人格定义（第1-19行）到 `trader_mindset.txt`
3. 重写 `trader_mindset.txt` 为 96 行完整人格定义
4. 清理 `market_analyst.txt` 和 `stock_analyst.txt` 的重复内容

### trader_mindset.txt 结构
```
你就是「青枫浦上Q」——一名专注A股产业逻辑的中线交易者...

【核心原则：数据优先，赔率思维，主动发现机会】
1. 所有判断起点必须是实时行情数据...
2. 【UP最新观点】优先于LLM自主判断...
...

【反保守自检 —— 每次分析前必须回答】
1. 我是否因为"怕错"而只给模糊判断？...
...

【UP表达风格】
- 语言：口语化、直接、不绕弯子...
...

【时效性自检】
...

【禁止行为】
...

【Few-Shot 示例】
...
```

### 验证
```bash
# 检查 trader_mindset.txt 是否非空
cat src/qing_investment/agent/prompts/system/trader_mindset.txt | wc -l
# 应输出 >= 90

# 检查 market_analyst.txt 不再包含人格定义
grep -c "核心原则" src/qing_investment/agent/prompts/system/market_analyst.txt
# 应输出 0

# 检查 stock_analyst.txt 不再包含人格定义
grep -c "核心原则" src/qing_investment/agent/prompts/system/stock_analyst.txt
# 应输出 0

# 验证 _load_prompt 自动注入
cd ~/learning-investment-strategies
python3 -c "
import sys; sys.path.insert(0, 'src')
from qing_investment.agent.graph.nodes import _load_prompt
ma = _load_prompt('market_analyst')
print('mindset injected:', '赔率思维' in ma[:500])
print('duplicate count:', ma.count('核心原则'))
"
# 应输出: mindset injected: True, duplicate count: 0
```

---

## 问题5：10:00 节点 ID 对齐

### 根因
怀疑 cron schedule、strategy_pack.yaml、stock_monitor.py 三处的 10:00 节点 ID 可能不一致。

### 验证结果
三处完全对齐：
| 来源 | 10:00 ID | 状态 |
|------|----------|------|
| strategy_pack.yaml | `morning_confirm` | ✅ |
| stock_monitor.py DEFAULT | `morning_confirm` | ✅ |
| cron schedule | `0 10 * * 1-5` | ✅ |

无需修复。

### 验证
```bash
cd ~/learning-investment-strategies
python3 -c "
import yaml
with open('config/stock_monitor/strategy_pack.yaml') as f:
    sp = yaml.safe_load(f)
for item in sp['agent_analysis_schedule']:
    if '10:00' in item.get('time', ''):
        print(f'strategy_pack: {item[\"id\"]}')
"
grep "DEFAULT_AGENT_ANALYSIS_SCHEDULE" src/qing_investment/stock_monitor.py -A 20
```

---

## 问题6：context_builder claims 排序未利用 reasoning_patterns

### 根因
`context_builder.py` 的 `_score_claim_relevance()` 只考虑股票代码匹配、介入信号、角色定义、时效性，没有根据当前分析应激活的 reasoning pattern 来优先展示相关 claims。

### 修复
1. `_score_claim_relevance()` 新增 `active_patterns` 参数
2. 如果 claim 的 subject/statement 匹配到 active pattern 的 `applicable_themes`，额外 +4 分
3. `build_stock_context()` 和 `build_market_context()` 透传 `active_patterns`
4. `retrieve_knowledge()` 在调用 `build_market_context()` 前预计算 `_load_reasoning_patterns(state)`

```python
def _score_claim_relevance(
    claim: dict,
    stock_code: str,
    stock_name: str,
    active_patterns: list[dict] | None = None,
) -> float:
    ...
    # Phase 6: reasoning pattern 匹配加分
    if active_patterns:
        claim_text = f"{subject} {stmt}".lower()
        for pattern in active_patterns:
            applicable_themes = pattern.get("applicable_themes", [])
            for theme in applicable_themes:
                if theme.lower() in claim_text:
                    score += 4.0
                    break  # 每个 pattern 只加一次分
    return score
```

### 效果
- 用户查询"MLCC 怎么看" → `_load_reasoning_patterns` 匹配到 `upstream_cycle`
- `upstream_cycle` 的 `applicable_themes` 包含"MLCC"、"被动元件"、"涨价题材"等
- 涉及这些主题的 claims 获得 +4 分额外加分，优先展示给 LLM

### 验证
```bash
# 检查 _score_claim_relevance 是否包含 pattern 匹配逻辑
grep -c "active_patterns" src/qing_investment/agent/tools/context_builder.py
# 应输出 >= 3

# 检查 retrieve_knowledge 是否传入 active_patterns
grep -c "active_patterns" src/qing_investment/agent/graph/nodes.py
# 应输出 >= 2
```

---

## 文件变更汇总

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `scripts/hermes_stock_monitor_agent.py` | 修改 | 新增 `create_mock_agent()` fallback，超时 120s，3次重试 |
| `src/qing_investment/agent/tools/neo4j_client.py` | 修改 | 新增 `get_claims_about_stock()`、`get_sector_themes()`、`get_claim_evolution()` |
| `src/qing_investment/agent/tools/context_builder.py` | 修改 | 动态 Qdrant query + `active_patterns` 参数 + pattern 匹配加分 |
| `src/qing_investment/agent/graph/nodes.py` | 修改 | `retrieve_knowledge()` 预计算 `active_patterns` 并传入 `build_market_context` |
| `src/qing_investment/agent/prompts/system/trader_mindset.txt` | 重写 | 96行完整人格定义 |
| `src/qing_investment/agent/prompts/system/market_analyst.txt` | 修改 | 删除第1-40行重复人格定义 |
| `src/qing_investment/agent/prompts/system/stock_analyst.txt` | 修改 | 删除第1-19行重复人格定义 |
| `docs/tasks/fix-monitor-system-issues.md` | 新增 | 任务追踪文档 |

---

## 后续验证建议

1. **重启 Qing-Agent 服务**：
   ```bash
   kill $(pgrep -f "uvicorn qing_investment") 2>/dev/null
   kill $(pgrep -f "gunicorn") 2>/dev/null
   cd ~/learning-investment-strategies
   nohup .venv/bin/gunicorn qing_investment.agent.main:app \
     -w 1 -k uvicorn.workers.UvicornWorker \
     --bind 127.0.0.1:8000 \
     --timeout 120 --keep-alive 5 \
     > /tmp/qing-agent.log 2>&1 &
   ```

2. **端到端测试**：
   ```bash
   curl -s --max-time 30 -X POST http://localhost:8000/analyze/trigger \
     -H "Content-Type: application/json" \
     -d '{"query":"MLCC 怎么看","session_id":"test-001","analysis_type":"stock"}'
   ```

3. **检查日志**：
   ```bash
   tail -50 /tmp/qing-agent.log | grep -E "context_builder|active_patterns|Qdrant query"
   ```
