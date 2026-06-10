# Implementation Audit Checklist

> 快速核查设计文档中的改造项是否真正落地。
> 场景：用户问"XX做完了吗""现在还有问题吗"——不要凭记忆回答，跑一遍这个 checklist。

---

## 一、Prompt 层改造核查

```bash
cd ~/learning-investment-strategies

echo "=== 1.1 market_analyst.txt 人格定义 ==="
grep -c "青枫浦上Q" src/qing_investment/agent/prompts/system/market_analyst.txt
grep -c "反保守自检" src/qing_investment/agent/prompts/system/market_analyst.txt
grep -c "赔率思维" src/qing_investment/agent/prompts/system/market_analyst.txt

echo "=== 1.2 stock_analyst.txt 赔率分析 ==="
grep -c "odds_analysis" src/qing_investment/agent/prompts/system/stock_analyst.txt

echo "=== 1.3 style_writer.txt 机会强化 ==="
grep -c "机会发现表达强化" src/qing_investment/agent/prompts/system/style_writer.txt

echo "=== 1.4 trader_mindset.txt 是否空壳 ==="
wc -l src/qing_investment/agent/prompts/system/trader_mindset.txt
# 如果 <= 5 行 → 空壳，人格定义内嵌在 market_analyst.txt
```

## 二、Context Builder 核查

```bash
echo "=== 2.1 context_builder.py 是否存在 ==="
ls -la src/qing_investment/agent/tools/context_builder.py

echo "=== 2.2 是否被 retrieve_knowledge 调用 ==="
grep -c "context_builder" src/qing_investment/agent/graph/nodes.py

echo "=== 2.3 方向关键词是否硬编码 ==="
grep -n "for direction in" src/qing_investment/agent/tools/context_builder.py
# 如果看到硬编码列表 → 需改为动态提取

echo "=== 2.4 Qdrant query 是否利用技术面 ==="
grep -n "query_text =" src/qing_investment/agent/tools/context_builder.py
# 如果看到固定模板 f"{name} {code} 技术分析" → 未利用当前技术面描述
```

## 三、Daily State 状态机核查

```bash
echo "=== 3.1 daily_state.json 是否存在 ==="
ls -la config/stock_monitor/daily_state.json 2>/dev/null || echo "❌ 文件不存在"

echo "=== 3.2 sync_daily_state.py 能否解析 ==="
python3 scripts/sync_daily_state.py --dry-run 2>&1 | tail -20

echo "=== 3.3 daily_state 是否注入 cron 上下文 ==="
grep -n "daily_state" src/qing_investment/stock_monitor.py | head -10

echo "=== 3.4 cron 差异化 prompt 文件数量 ==="
ls src/qing_investment/agent/prompts/system/cron_*.txt 2>/dev/null | wc -l
# 应为 9 个（对应 9 个看盘节点）

echo "=== 3.5 sync_daily_state cron job 是否运行 ==="
hermes cron list 2>/dev/null | grep -i "daily state" || echo "需检查 cron list"
```

## 四、Qing-Agent 健康核查

```bash
echo "=== 4.1 进程检查 ==="
pgrep -a -f "gunicorn" || pgrep -a -f "uvicorn qing_investment"

echo "=== 4.2 /health 端点 ==="
curl -s --max-time 5 http://localhost:8000/health | head -1

echo "=== 4.3 /analyze/trigger 端点（真实工作端点）==="
curl -s --max-time 30 -X POST http://localhost:8000/analyze/trigger \
  -H "Content-Type: application/json" \
  -d '{"query":"健康检查","session_id":"health-001","analysis_type":"market"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('✓ OK' if d.get('final_output') else '❌ EMPTY')"

echo "=== 4.4 最近 cron 是否走 fallback ==="
for dir in ~/.hermes/cron/output/*/; do
  latest=$(ls -t "$dir"/*.md 2>/dev/null | head -1)
  [ -n "$latest" ] && grep -lE "Qing-Agent . FALLBACK|qing-agent fallback" "$latest" && echo "  ↳ $(basename $dir)"
done
```

## 五、快速分级判断

| 检查项 | 通过标准 | 失败影响 |
|--------|---------|---------|
| daily_state.json 存在 | `ls` 成功 | 🔴 P0：观点连续性完全失效 |
| sync_daily_state 解析成功 | `--dry-run` 显示合并记录 | 🔴 P0：状态机不工作 |
| gunicorn 进程存活 | `pgrep` 有输出 | 🔴 P0：Agent 完全离线 |
| /analyze/trigger 返回 JSON | `final_output` 非空 | 🔴 P0：Agent 管线故障 |
| market_analyst 含人格定义 | `grep -c` >= 3 | 🟡 P1：LLM 保守倾向未纠正 |
| trader_mindset 非空壳 | `wc -l` > 5 | 🟢 P2：设计意图未达成 |
| 方向关键词非硬编码 | 无 `for direction in ["..."]` | 🟡 P1：新方向无法自动捕获 |

## 六、诊断决策树

```
用户问"XX改造还有问题吗"
  ├─ 先跑本 checklist 的对应章节
  ├─ 按"五、快速分级判断"标记 P0/P1/P2
  ├─ P0 项 > 0 → 回答："有 X 个 P0 问题，核心功能是..."
  ├─ P0 = 0, P1 > 0 → 回答："核心功能正常，有 X 个限制..."
  └─ P0 = P1 = 0 → 回答："三项改造均已实现，仅 P2 优化项..."
```
