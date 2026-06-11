# 早盘驱动 Config 更新清单

> 早盘（09:17发布）与晚间复盘（22:54发布）的更新模式不同。此清单用于快速交叉检查而非替代完整 4-step workflow。

## 早盘 vs 复盘：差异

| 维度 | 晚间复盘 | 早盘 |
|------|---------|------|
| 内容特点 | 全板块排名、组合策略、标的清单、操作总纲 | 隔夜事件、开盘情景、催化更新、操作预案微调 |
| 市场框架 | 给出新的定性（筑底/修复/退潮） | 在复盘框架上做情景分支（缩量→修复 / 放量→防守） |
| 标的 | 新增方向 + 完整优先级 | 偶尔提新催化映射（如 SK海力士ADR→太极实业），confidence 通常较低 |
| 操作规则 | 新的总纲（右侧进场、控仓比例） | 板块级微调（如"半导体持股待涨→区间交易"） |

## 早盘更新清单（5 项必查）

### 1. market_framework.current_stage
对比早盘 claim-*-001-a（market-cycle 类型）。如果出现新信号词（地量、放量承接、高切低），更新 current_stage，增设 opening_scenarios 字段。

### 2. 新标的缺口
早盘 claim 的 related_stocks → 筛选主板 → 对照 watchlist。注意：
- 连板票（圣泉集团、和远气体）→ P3-观察，不设介入区间
- 情绪映射票（太极实业、百润股份）→ 看 confidence 字段，low confidence → P3
- 不追板、不追涨停 = 不变纪律

### 3. 方向 positioning 更新
早盘可能不给新方向，但会给已有方向加「验证框架」。如"MLCC昨日抗跌→今日领涨=高低切换成立"→ 更新对应 theme 的 up_positioning。

### 4. strategy_pack 操作规则
早盘的 claim-*-001-e（operation 类型）通常含当日具体预案：
- 板块策略微调（区间交易、做T、不追涨）
- 防御方向拥挤警示
- 低位板块等右侧信号
→ 逐条对照 strategy_pack.position_rules 是否有。

### 5. intraday_schedule / agent_analysis_schedule
早盘的核心观察点（如"MLCC是否领涨"）需要进入 09:26-10:00 窗口的 rules/focus 字段。agent_analysis_schedule 的聚焦描述同步更新。

## 不应执行的操作

- ❌ 不应因早盘提到就重写全部 watchlist 优先级（优先级来自复盘，早盘只是战术微调）
- ❌ 不应为 confidence=low 的标的设介入区间
- ❌ 不应为「仅观察」标的拉 K 线计算技术位
- ❌ 不应修改 positions 的建仓目标（建仓决策来自复盘框架+右侧信号，非早盘催化）

## 执行后验证

```bash
# P0 必须清零
python3 scripts/check_config_consistency.py --json | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['p0_count']==0, f'P0={d[\"p0_count\"]}'; print('✓ P0=0')"
# 结构校验
python3 scripts/validate_config.py
```
