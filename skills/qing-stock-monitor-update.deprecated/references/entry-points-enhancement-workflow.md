# Entry Points 增强字段分析工作流

当一个 entry_point 缺少 `status`、`opportunity_pattern`、`odds_analysis`、`claim_basis` 等增强字段时，按以下流程补充。

## 数据来源

| 字段 | 来源 | 查询方法 |
|------|------|---------|
| `status` | UP 最新观点判断 | Qdrant 语义搜索标的名称，找最近 claims 判断多空 |
| `opportunity_pattern` | 标的当前技术面状态 | 7大机会模式匹配（见 §4.1）|
| `claim_basis` | claim ID | Qdrant 搜索 + Neo4j 验证 |
| `odds_analysis` | 价格区间 + 60日低/前高 | 从 entry_zone 和技术面推导 |
| `upside_pct` | 前高 - entry_zone 下沿 | 量化计算 |
| `downside_pct` | entry_zone 下沿 - 支撑位 | 量化计算 |

## 7 大机会模式匹配规则

| 模式 | 匹配条件 | 典型场景 |
|------|---------|---------|
| **技术支撑确认** | 缩量回踩均线/前低不破，等企稳信号 | 涨停后回踩5日线、前高突破后回踩 |
| **恐慌超卖策略** | 板块系统性回调(非个股利空)，日内跌>5% | 整体市场调整、板块情绪冰点 |
| **平台突破** | 横盘2+周后放量突破区间上沿 | 底部整理完成、放量首板 |
| **趋势加速** | 行业景气确认+大阳线，等分歧 | PCB/AI硬件景气确认、英伟达供应链 |
| **深度回调+产业逻辑** | 回撤>20%+产业逻辑未破+业绩支撑 | 燃气轮机回撤30%、昇腾链调整 |
| **尾盘条件单** | 14:30后符合技术条件 | 日内回踩不破、放量企稳 |
| **事件驱动** | 突发利好/利空导致赔率突变 | 海外连接器龙头大涨7%、定增收紧 |

## 赔率估算方法

```
upside_pct = round((前高价 - entry_zone下沿) / entry_zone下沿 * 100)
downside_pct = round((entry_zone下沿 - 支撑位) / entry_zone下沿 * 100)
odds_ratio = f"{upside_pct}:{downside_pct}"  # 取整比
estimated_probability_up: 30-55%  # 基于 UP 提及频次和确定度
```

**概率参考**：
- UP 明确点名+强逻辑：55% (如杰瑞股份)
- 行业景气+确定性高：50% (如沪电股份)
- UP 提及但弹性一般：40-45%
- 低概率高弹性（新概念）：30% (如世运电路LPU)

## Claims 依据优先级

1. **UP 直接点名**的 claim（最高优先级，confidence high 最佳）
2. **板块逻辑**提及（标的作为板块一员被列出）
3. **行业逻辑**推断（UP 未直接提及，来自 Qing-Agent + 券商分析）

**无直接 claim 的标的**：标注 `claim_basis: 行业逻辑（无直接claim）`，并在 `note` 字段注明来源。
