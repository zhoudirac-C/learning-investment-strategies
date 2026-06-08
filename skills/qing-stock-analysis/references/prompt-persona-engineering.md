# Prompt Persona Engineering — 从风控机器人到AI交易助手

> 日期：2026-06-08
> 背景：用户诊断系统被设计成"风控巡检机器人"而非"AI交易助手"，LLM过于保守，很少建议买入/加仓
> 方案：通过prompt层改造（不改代码）重塑LLM思维方式

## 核心诊断

| 症状 | 根因 |
|------|------|
| 定时任务基本都是提醒减仓 | system prompt偏向风控，累积效果让LLM默认选择"不动" |
| 金安国纪启动时无推送 | 系统只有reduce_zone/risk_zone，无buy_zone触发 |
| LLM结论通常是"继续观察" | 安全对齐+训练数据偏差+对称风险思维+无利益绑定 |
| 450字限制压缩思考深度 | 微信格式限制+4段模板 → LLM被迫输出极简化 |

## 最高杠杆修复：Prompt层改造（Phase 1）

**原则：不改代码，只改prompt。效果可能最大。**

### 1. 独立人格文件模式 (`trader_mindset.txt`)

将交易者人格定义从各prompt中抽离为独立文件：

```
prompts/system/trader_mindset.txt      ← 人格定义（一处修改全局生效）
prompts/system/market_analyst.txt      ← 自动注入trader_mindset
prompts/system/stock_analyst.txt       ← 自动注入trader_mindset
```

注入机制（`_load_prompt`中自动prepend）：
```python
def _load_prompt(name: str) -> str:
    content = path.read_text()
    if name in ("market_analyst", "stock_analyst"):
        mindset = (_PROMPT_DIR / "trader_mindset.txt").read_text()
        content = f"{mindset}\n\n---\n\n{content}"
    return content
```

### 2. 反保守自检指令（Anti-Conservatism Self-Check）

LLM天生保守："持有/观望"比"买入"更安全。必须在每次输出前强制执行自检：

```
□ 自检1：我是否因为"怕错"而默认选择了"继续观察"？
□ 自检2：我是否只分析了风险，没有分析机会？
□ 自检3：我的结论是否是"因为…所以…"的因果链？
□ 自检4：如果我是空仓，今天会买什么？
□ 自检5：持仓票是否触发了加仓条件？
```

**关键设计**：不是"建议"LLM做这些检查，而是"必须执行"。在prompt中用"□"符号和强制语气。

### 3. 赔率思维强制框架

每次分析涉及具体标的时，必须显式计算：
- 错了亏多少？（基于技术支撑位）
- 对了赚多少？（基于产业逻辑目标位）
- 赔率是否 >= 2:1？（低于2:1不参与）
- 当前是否处于"分歧回踩"位置？（加速段赔率差，不参与）

### 4. 角色不是"15年交易员"，而是UP本人

**错误做法**：凭空捏造一个"15年职业交易员"人格
**正确做法**：从 `reasoning-patterns.yaml` + claims 中提炼UP真实的思维模式

UP的8大核心原则：
1. 赔率思维（错了亏小钱，对了赚大钱）
2. 产业逻辑驱动（供需缺口、技术升级、国产替代、BOM扩散）
3. 阶段判断优先于个股选择
4. 方向优先级+核心矛盾
5. 不追高，等分歧回踩
6. 做T思维
7. 关键点位锚定
8. 敢于认错，也敢于坚持

## Phase 2：Context Builder — Claims实时注入

**问题**：LLM收到的上下文缺少UP的机会判断。607条claims中有大量方向判断和赔率分析，但cron触发时LLM只收到"当前价格+涨跌幅+规则信号"。

### 架构

```
retrieve_knowledge 节点
    → 识别目标标的（持仓 + active entry_points + high priority watchlist）
    → Neo4j 检索每只标的的 claims（ABOUT 边）
    → Qdrant 语义召回补充 claims
    → 相关性评分排序（代码匹配+介入信号+角色定义+时效性）
    → 浓缩为结构化摘要（每条≤50字，每只标的≤3条）
    → 注入 AgentState: stock_contexts + direction_signals
```

### 浓度控制（防止上下文溢出）

| 控制点 | 规则 |
|--------|------|
| 每只标的最多 | 3条claims摘要 |
| 每条摘要最多 | 50字 |
| 总stock_contexts | 通常10-15只标的 |
| 注入时机 | retrieve_knowledge节点，自动构建 |

### Claims摘要结构

```json
{
  "stock_code": "000534",
  "stock_name": "万泽股份",
  "claim_count": 5,
  "claim_summary": [
    {
      "id": "claim-20260604-003",
      "summary": "燃气轮机方向最看好，回调即是买点",
      "intensity": "🔥🔥🔥",
      "freshness": "最新",
      "entry_signal": "建议介入",
      "role_definition": "燃气轮机核心标的"
    }
  ],
  "overall_signal": "UP近期看好，建议回调介入",
  "latest_date": "2026-06-04"
}
```

## 关键设计决策

1. **不用虚构"7大机会模式"** → 用 `reasoning-patterns.yaml` 中真实的10个推理框架
2. **Prompt层是最高杠杆改动** → Phase 1只改prompt文件，不改代码
3. **不删观察池票** → 用"热度排序"替代删减（Phase 4）
4. **机会发现是默认模式** → 风控是安全网，不是主模式

## 实施顺序

| Phase | 内容 | 时间 | 杠杆 |
|-------|------|------|------|
| 1 | Prompt层改造（人格+赔率+反保守） | 1-2天 | 最高 |
| 2 | Context Builder（claims注入） | 2-3天 | 高 |
| 3 | Cron差异化+daily_state状态机 | 2-3天 | 中 |
| 4 | 观察池热度+claims自动化 | 3-5天 | 中 |

## 验收标准

- [ ] LLM输出包含"机会扫描"段落，给出3-5只关注标的
- [ ] 涉及具体标的时包含赔率分析（错了亏多少/对了赚多少/赔率比）
- [ ] 持仓票价格下跌到add_zone且逻辑没变时，建议加仓而非只写"持有"
- [ ] 空仓时也给"今日最值得关注的标的"，不说"继续等待"
- [ ] 结论使用"因为…所以…"因果链，不说"市场存在不确定性"
