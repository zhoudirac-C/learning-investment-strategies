# Prompt-Config 关键点位同步陷阱

## 问题
Agent 提示词文件中硬编码了指数关键点位（如 support/resistance/index_discipline），
而 `strategy_pack.yaml` 的 `index_rules` 是这些点位的单一来源。

当 UP 框架更新关键点位时（如 4033→3950/4000），若只改 strategy_pack.yaml 而不改 prompt 文件，
Agent 会持续输出过期数据。

## 受影响文件（4个prompt文件，必须同步修改）

| 文件 | 字段 | 位置 |
|------|------|------|
| `src/qing_investment/agent/prompts/system/market_analyst.txt` | `index_discipline.support` / `resistance` / `action_below` / `action_above` / `middle_zone` | ~L137-141 |
| `src/qing_investment/agent/prompts/system/market_analyst.txt` | 「事件驱动段—异常检测」中的指数破位条件 | ~L207 |
| `src/qing_investment/agent/prompts/system/market_analysis_framework.txt` | 第7条「指数纪律」的举例 | ~L119 |
| `src/qing_investment/agent/prompts/system/trader_mindset.txt` | 第2条「用数字说话」的举例 | ~L33 |

## 同步流程

1. 修改 `config/stock_monitor/strategy_pack.yaml` 的 `index_rules`
2. grep 搜索所有 prompt 文件中旧的 key level 值
3. 同步修改上述4个文件中的对应值
4. restart Qing Agent

## 检查命令
```bash
cd ~/learning-investment-strategies
grep -n "4033\|4130" src/qing_investment/agent/prompts/system/*.txt
```

## 历史案例
- 2026-06-12: 4033 清仓线已降级为 3950 月线支撑 + 4000 心理关口 12 天，
  strategy_pack.yaml 已更新（index_rules 中 4033 标记为 deprecated: true），
  但 4 个 prompt 文件仍硬编码 4033，导致 Agent 每日分析仍引用过期数据。
  → 修复：搜 grep "4033" 发现 4 处，全部替换为最新值。
