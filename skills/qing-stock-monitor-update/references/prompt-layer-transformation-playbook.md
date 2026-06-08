# Prompt 层改造实战手册

> 场景：系统被诊断为"太保守、只减仓不提醒买入"
> 策略：不改代码，只改 prompt——杠杆最高的单项改动
> 案例：2026-06-08 Qing-Agent 从"风控巡检员"到"交易者人格"的 Phase 1 改造

---

## 诊断信号

当系统出现以下症状时，prompt 层改造是首选方案：

| 症状 | 根因 | 为什么 prompt 改造比代码改造更有效 |
|------|------|----------------------------------|
| LLM 只输出"持有/观望"，从不建议买入 | LLM 的安全对齐 + 保守 prompt 双重强化 | 改 prompt 直接重塑 LLM 的默认行为模式 |
| 分析冗长但无 actionable 结论 | Prompt 缺少"必须给出明确判断"的强制指令 | 增加反保守自检指令即可 |
| 机会来了但系统沉默 | Prompt 只要求分析风险，没要求扫描机会 | 增加机会扫描步骤 |
| 持仓跌到位了但不建议加仓 | Prompt 只关注 reduce_zone，没关注 add_zone | 增加赔率计算框架 |

---

## 改造清单（5 个文件）

### 1. 新增 `trader_mindset.txt` — 独立人格定义文件

**为什么独立文件**：
- 一处修改，market_analyst + stock_analyst 同时生效
- 人格定义可独立迭代，不污染业务 prompt
- 便于 A/B 测试（换一个人格文件即可）

**内容结构**：
```
【角色设定：你就是「XXX」】
  └─ 8大交易原则（赔率思维、产业逻辑驱动、阶段判断优先...）
【反保守自检指令 — 必须执行】
  └─ 5条自检（□ 是否因怕错而默认观望？□ 是否只分析了风险？...）
【表达风格规范】
  └─ 6条（先给结论、用数字说话、敢于预判、区分事实判断推测...）
```

**关键设计**：自检指令用 `□` 符号，让 LLM 在输出前"打勾"，形成心理约束。

### 2. 重写 `market_analyst.txt` — 大盘/板块分析

**保留不变**：
- 数据优先级规则（实时数据 > claims > framework）
- 时效性自检（≤7天/8-30天/31-90天分级）
- 禁止行为（不编造、不无条件买卖）

**新增内容**：
- 顶部引用 `trader_mindset.txt`（由代码自动注入）
- 【反保守自检】段落（5条）
- 【推理模式激活规则】——用 reasoning-patterns.yaml 中的真实框架，不是虚构的"7大机会模式"
- 【机会扫描】步骤——每日必须扫描观察池，给出"今日最值得关注的3-5只标的"
- JSON 输出增加 `opportunity_scan` 字段

### 3. 重写 `stock_analyst.txt` — 个股分析

**新增内容**：
- 反保守自检（5条，针对个股场景微调）
- 【赔率分析】强制输出——错了亏多少/对了赚多少/赔率比/是否处于分歧回踩位置
- JSON 输出增加 `odds_analysis` 字段

### 4. 更新 `style_writer.txt` — 风格化输出

**新增段落**：
```
【机会发现表达强化】
当草稿中包含买入/加仓机会时，必须保留并强化表达：
- ✓ "这个位置赔率很高，错了也就亏3%，对了空间15%"
- ✗ 不能把"建议加仓"弱化成"可以留意"或"逢低关注"
```

**目的**：防止 LLM 在风格化阶段把明确的买入信号弱化成模糊措辞。

### 5. 更新 `reviewer.txt` — 事实核查

**新增检查项**：
```
8. [ ] 【反保守检查】是否因为"怕错"而默认选择了"继续观察"？
9. [ ] 【机会扫描检查】分析中是否同时包含了机会扫描和风险评估？
10. [ ] 【赔率检查】涉及具体标的时，是否包含赔率分析？
```

---

## 代码层最小改动（nodes.py）

### 改动1：`_load_prompt()` 自动注入人格

```python
def _load_prompt(name: str) -> str:
    path = _PROMPT_DIR / f"{name}.txt"
    if not path.exists():
        return f"[Prompt {name} not found]"
    content = path.read_text(encoding="utf-8")
    # 自动注入交易者人格（Phase 1 新增）
    mindset_path = _PROMPT_DIR / "trader_mindset.txt"
    if mindset_path.exists() and name in ("market_analyst", "stock_analyst"):
        mindset = mindset_path.read_text(encoding="utf-8")
        content = f"{mindset}\n\n---\n\n{content}"
    return content
```

### 改动2：fallback JSON 结构扩展

`market_analyst` fallback 增加 `"opportunity_scan": []`
`stock_analyst` fallback 增加 `"odds_analysis": {}`

### 改动3：`synthesize` 节点展示机会扫描

在 draft 中加入 `opportunity_scan` 的格式化展示：
```python
opportunity_scan = market.get("opportunity_scan", [])
if opportunity_scan:
    opportunity_lines.append("【机会扫描】")
    for opp in opportunity_scan:
        opportunity_lines.append(
            f"  · {opp.get('stock')}({opp.get('code')}): "
            f"{opp.get('pattern')} | 触发: {opp.get('trigger')} | "
            f"赔率: {opp.get('odds')} | 置信: {opp.get('confidence')}"
        )
```

---

## 验证方法

改造后必须用相同的市场数据测试新旧 prompt 的输出差异：

### 测试1：机会发现能力
```
输入：大盘调整第17天，某标的回踩到 entry_zone，板块逻辑没变
旧 prompt 输出："继续观察，等待企稳信号"
新 prompt 输出："回踩30.5-31.0企稳后可试探仓位，赔率3:1"
→ 通过
```

### 测试2：赔率计算
```
输入：某持仓票价格下跌10%，逻辑没变
旧 prompt 输出："持有观望"
新 prompt 输出："价格下跌后赔率变好（从2:1变为3:1），建议加仓0.5成"
→ 通过
```

### 测试3：反保守自检
```
输入：市场无明显机会，也无明显风险
旧 prompt 输出："市场存在不确定性，建议继续观察"
新 prompt 输出："今天找不到符合赔率要求的机会，这是主动判断——不是因为没有分析"
→ 通过
```

---

## 常见陷阱

1. **人格定义过于抽象**："你是一名专业的交易员"——太虚，LLM 不会内化。必须具体到"错了亏X%对了赚Y%""等回踩XX-XX区间"。
2. **自检指令被忽略**：LLM 可能跳过自检段落。解决方案：①用 `□` 符号形成视觉约束；②在 reviewer.txt 中增加对应检查项。
3. **机会扫描与风控失衡**：新增机会扫描后，不能丢掉风控。reviewer.txt 中保留原有风控检查项。
4. **JSON 字段未同步**：prompt 中要求输出 `opportunity_scan`，但 fallback 结构没加该字段 → 解析失败。必须同步更新 fallback。
5. **style_writer 弱化信号**：market_analyst 输出了"建议加仓"，但 style_writer 把它改成了"可以留意"。必须在 style_writer prompt 中显式禁止这种弱化。

---

## 与代码层改造的关系

| 层面 | 改造内容 | 复杂度 | 效果 |
|------|---------|--------|------|
| Prompt（Phase 1） | 重写 system prompt | 1-2天 | 立竿见影 |
| Context Builder（Phase 2） | Claims 实时注入 | 2-3天 | 中等 |
| 状态机（Phase 3） | daily_state.json | 2-3天 | 中等 |
| 自动化（Phase 4） | 热度分+桥接脚本 | 3-5天 | 长期 |

**原则**：先改 prompt 验证效果，再决定是否值得投入代码改造。Prompt 改了没效果 → 问题不在 prompt，需要代码层解决。Prompt 改了有效果 → 代码层改造锦上添花。
