# 框架过期自锁闭环 — 陷阱 25

> 对应 `qing-stock-monitor-update` SKILL.md 陷阱 25。

## 问题

配置文件中的 UP 框架引用过期 → Agent 基于过期框架分析 → 输出过期的结论 → 写回 `daily_state.json` → 下次 Agent 又读到它 → 形成自锁闭环。Agent 不是在犯错——它是在正确执行过期的指令。

## 演化案例：4033 框架

```
6/3: UP 引入 4033/4130 纪律线（清仓/满仓，120日线支撑）
6/5: UP 评论修正：4033 是"科技清仓线"非"指数清仓线"（到4033清科技，不是抄底）
6/9: UP 将生命线从 4033 下调至 4000，态度从"4033清仓"转为"观望不杀跌"
6/11: UP 早盘框架：地量信号初现 + 情景A/B（缩量修复/放量防守），4033 完全消失
```

但系统文件（`strategy_pack.yaml`、`daily_state.json`）仍以 4033 作为操作锚，导致 Agent 每次分析都说"上证仍在4033下方"——一个 12 天前就被跌破且 UP 已不再使用的数字。

## 自锁机制

```
strategy_pack.yaml 含过期框架
  → Agent prompt 注入过期框架
  → Agent 输出："上证收盘3962<4033清仓线"
  → market_analyst 写入 daily_state.json
  → 下次 Agent 又从 daily_state.json 读到 4033
  → 循环
```

打破方法：**手动更新 strategy_pack.yaml → 重启 Agent → 重写 daily_state.json**。

## 判断过期的信号

- 点位引用连续多天被实际行情大幅偏离（>3% 且持续 >5 天）
- claims 中同一主题的 statement 已出现修正/降级
- UP 最新早盘/复盘完全不再提该数字

## 修复流程

1. `mcp_neo4j_search_claims_graph(keyword="点位")` → 找到最新相关 claim + 后续修正
2. 对比 `daily_state.json` / `strategy_pack.yaml` → 识别过期引用
3. 更新：点位 → `deprecated: true` + 演化说明；操作锚 → 对齐最新 UP 观点
4. 记录框架迁移到 `daily_state.json._meta.framework_migration`

## 更新 checklist

```
[ ] strategy_pack.yaml index_rules — 过期点位 → deprecated + 演化说明
[ ] strategy_pack.yaml key_levels — 修复确认标准对齐最新观点
[ ] daily_state.json market_stage — 阶段描述更新
[ ] daily_state.json._meta — 记录框架迁移
[ ] Agent 重启（清除缓存的过期框架）
```
