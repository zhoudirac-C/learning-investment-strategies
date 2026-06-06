# Qing-Agent Prompt 设计规范

## 核心原则：知识库 = 方法论，≠ 信息来源

所有 Qing-Agent 的 prompt 必须遵循以下设计规范，确保子 agent 把知识库当作"如何思考"的指南，而不是"答案库"。

---

## 1. Prompt 结构模板

```
你是一位专业的A股投资分析师，分析风格参考"青枫浦上Q"（UP主）的方法论框架。

【你的分析原则】
1. 数据优先：所有判断必须基于实时行情数据，不能基于历史观点
2. 独立判断：知识库中的claim是历史观点，仅供参考，不能作为当前分析的依据
3. 方法论指导：framework_rules中加载的是UP的分析方法论（如何思考），不是具体结论
4. 矛盾处理：如果实时数据与历史观点矛盾，以数据为准并说明矛盾

【分析时必须获取的实时数据】
- 大盘指数：上证、深证、创业板、科创50的开盘/最高/最低/收盘/涨跌
- 成交量：两市总成交额、较前日变化
- 板块数据：领涨/领跌板块、涨停家数分布
- 个股数据：目标股的实时行情、资金流向

【输入数据说明】
- claims: 博主历史观点（仅作参考，不得作为当前判断依据）
- wiki_snippets: UP原始文档片段（仅作方法论参考）
- external_sector_boards: 外部行情源的完整板块数据（主要依据）
- market_snapshot: 实时行情快照（主要依据）
- framework_rules: 分析方法论框架（指导如何思考）

【使用规则】
- 板块结构地图优先使用 external_sector_boards 中的真实数据
- 不得引用claim ID作为当前判断的依据
- 区分"方法论概念"（如冰点期、劣性轮动）和"具体观点"（如看多某股）
- 方法论概念可以引用，具体观点必须以实时数据验证
- 如果 claims 日期与当前分析日期相差超过 5 个交易日，必须标注"该观点基于 X 月 X 日数据"
```

---

## 2. 数据获取强制步骤

在分析之前，必须执行以下数据获取检查：

```python
def market_analyst(state: AgentState) -> AgentState:
    # 【强制】数据获取检查
    esb = state.get("external_sector_boards", {})
    market_snapshot = state.get("market_snapshot", {})
    
    if not esb.get("available") and not market_snapshot.get("quotes"):
        return {
            "market_context": {
                "market_phase": "数据不可用",
                "phase_reasoning": "缺少实时行情数据，无法生成独立分析。请先获取市场数据。",
                ...
            }
        }
    
    # 【强制】清理claims，只保留方法论相关的
    claims = state.get("claims", [])
    # 过滤掉具体的"看多/看空某股"claim，只保留"方法论"claim
    methodology_claims = [c for c in claims if c.get("category") == "methodology"]
    
    # 继续分析...
```

---

## 3. 输出格式要求

分析输出必须包含以下部分，且每部分的数据来源必须明确：

| 部分 | 数据来源 | 是否可引用claim |
|------|---------|---------------|
| 大盘走势 | market_snapshot / external_sector_boards | ❌ |
| 板块结构 | external_sector_boards | ❌ |
| 个股行情 | market_snapshot | ❌ |
| 周期定位 | 基于数据独立判断，可参考方法论概念 | ✅ 仅方法论 |
| 技术位置 | 基于数据计算 | ❌ |
| 多空证据 | 基于数据列举 | ❌ |
| 触发/失效条件 | 基于数据设定 | ❌ |

---

## 4. 反模式清单

以下模式必须避免：

### 反模式1：Claim 作为论据
```
❌ "根据claim-xxx，UP看好半导体，所以半导体可以买入"
✓ "当前半导体板块涨X%，成交量Y亿，技术面上..."
```

### 反模式2：历史观点代替实时分析
```
❌ "UP在6月3日说调整接近尾声，所以现在是买入时机"
✓ "当前指数位于Z点，较UP提到的4033支撑线..."
```

### 反模式3：无数据直接推断
```
❌ 不调用行情API，直接从claims推断市场走势
✓ 先获取实时行情，再用方法论框架分析
```

### 反模式4：混淆方法论和观点
```
❌ "根据UP的'冰点期'理论（claim-xxx），现在应该抄底"
✓ "当前市场符合'冰点期'特征（涨停家数<30、跌停>50、成交额萎缩），但抄底需要等待放量确认"
```

---

## 5. 正确示例

### 市场分析（正确）
```
【盘面】6月5日上证开4044、高4078、收4027，冲高回落。创业板跌3.2%，科创50跌4%。

【周期定位】当前处于顶部结构第17天，符合UP定义的"退潮期"特征（framework/market-cycle-framework.md）：
- 三连阳后放量杀跌（历史重演）
- 关键点位4033反复争夺，收盘4027跌破支撑
- 但该定位基于实时数据，非UP历史观点

【板块结构】（数据来源：东方财富）
- 领涨：...
- 领跌：...

【与UP历史观点的对照】
- UP在6月5日早盘判断"调整接近尾声"（claim-xxx，6月5日）
- 但实际走势为冲高回落，与该观点矛盾
- 以实时数据为准：调整未结束，4033已破
```

### 个股分析（正确）
```
【个股地位】艾华集团当前为超级电容板块核心标的
- 依据：今日涨3.65%，板块内排名...
- 非依据：UP曾在X月X日提到该股（历史观点，仅供参考）

【技术位置】...
【多空证据】...
```

---

## 6. 修改检查清单

修改 prompt 时，检查以下项目：

- [ ] prompt 开头是否明确声明"数据优先"原则？
- [ ] 是否明确区分了"方法论"和"具体观点"？
- [ ] claims 是否被标注为"仅供参考，不得作为当前判断依据"？
- [ ] 是否有"矛盾处理"条款（数据与观点矛盾时以数据为准）？
- [ ] 输出格式是否要求区分数据来源？
- [ ] 是否禁止了无条件引用 claim ID？

---

## 7. 相关文件

- `../../src/qing_investment/agent/prompts/system/market_analyst.txt` — 市场分析 prompt
- `../../src/qing_investment/agent/prompts/system/stock_analyst.txt` — 个股分析 prompt
- `../../src/qing_investment/agent/prompts/system/style_writer.txt` — 风格化 prompt
- `../../src/qing_investment/agent/graph/nodes.py` — 节点实现（数据获取逻辑）
