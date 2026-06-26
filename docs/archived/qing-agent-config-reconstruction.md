# Qing Agent + Config 重构方案

> 背景：基于 UP 6/8-6/16 一周逐日验证的发现  
> 核心发现：当前 Agent 的"价格入区间=买入信号"链路与 UP 的"方向预判→等分歧→低吸"框架存在根本性架构错配

---

## 一、当前架构诊断

### 1.1 当前 Agent 的数据流

```
UP复盘点名标的
    ↓ (用户手动)
watchlist.yaml (设 entry_zone，基于涨停回踩法)
    ↓
stock_monitor.py 每N分钟轮询
    ↓
BuySignalRuleEngine._evaluate_candidates()
    → 检查：价格是否在 entry_zone 区间？
    → 6条件：价格入区间 + 非大跌 + 未涨停 + UP看好 + 缩量 + MA20上方
    → 4/6条件满足 → "机会候选" 告警
    ↓
ContextAssembler 格式化 → 注入 LLM prompt
    ↓
LLM 判断 → 微信提醒用户
```

### 1.2 三个架构级问题

#### 问题1：触发条件错位

```
当前触发：价格进入 entry_zone → 提醒
应该触发：板块首次分歧 + 大盘处于可操作窗口 + 价格到区间
```

**证据**：风华高科 6/15 设了 entry_zone（57.8~62.7），但 6/16 开盘直接涨停+10%，价格跳过了整个区间。Agent 如果在 6/15 看到价格快到了就提醒，用户第二天追进去就是追涨停。正确的逻辑应该是：6/16 板块还在连续大涨→触发"不提醒"前置条件。

#### 问题2：Config 是"后视镜"设计的

当前 watchlist 里的 entry_zone 几乎都是 `涨停回踩法` 算出来的：
- 雅克科技：涨停134.81后设125-130 ← 回踩只到129，没到位
- 风华高科：涨停后设57.8-62.7 ← 直接跳空涨停，根本没回踩
- 昊华科技：涨停后设42.4-51 ← 6/12先跌停，等企稳

**这本质是在"等一个可能永远不会发生的回踩"。** 这是 UP 方法论的副产品——UP 自己也是回踩法，但 UP 能实时调整，你的 Config 是死的。

#### 问题3：缺少市场级前置过滤

Agent 在 6/12（昊华跌停日）如果价格到了42.4-51区间，就会提醒买入。但它不会检查：
- 今天全A指数是上涨还是破位？
- 这个板块是第一次分歧还是在退潮？
- 今天量能是放量还是缩量？

这导致 Agent 可能在最不应该买的时候提醒你买。

---

## 二、Config 重构方案

### 2.1 从"标的池"改为"两层结构"

```
当前 (v1)                          重构后 (v2)
┌────────────────┐                ┌─────────────────────┐
│ watchlist.yaml │                │ direction_pool.yaml  │ ← 方向层（新）
│  themes:       │                │  - 方向名称          │
│    - stocks:   │                │  - UP点名时间        │
│      entry_zone│                │  - 产业链图谱        │
│                │                │  - 扩散路径          │
│                │                │  - 当前阶段          │
│                │                │  - 前置条件          │
│                │                ├─────────────────────┤
│                │                │ stock_pool.yaml      │ ← 标的层
│                │                │  - 所属方向          │
│                │                │  - 产业链位置        │
│                │                │  - UP提及类型        │
│                │                │  - 介入区间+条件     │
└────────────────┘                └─────────────────────┘
```

### 2.2 direction_pool.yaml 结构

```yaml
# config/stock_monitor/direction_pool.yaml
directions:
  - id: mlcc_super_cycle
    name: MLCC超级周期
    up_first_mentioned: 2026-06-14
    up_mention_type: signal_confirmation  # direction_call | signal_confirmation | risk_warning
    current_stage: divergence_verification  # early_direction | first_pump | diverging | resuming | ending
    industry_chain:
      upstream:    # 上游 — 优先寻找低位标的
        - segment: 陶瓷粉体
          stocks: [国瓷材料, ...]
          pumped: false
        - segment: 镍电极粉
          stocks: [...]
          pumped: false
      midstream:   # 中游 — UP已点名，大概率已涨
        - segment: MLCC制造
          stocks: [风华高科, 三环集团, 火炬电子]
          pumped: true
      downstream:  # 下游
        - segment: 消费电子/汽车
          stocks: [...]
          pumped: false
    diffusion_path:  # UP的扩散预测
      - "MLCC → 被动元件整体 → PCB上游材料"
    pre_condition:
      market: "全A量能>2.5万亿+非破位状态"
      sector: "板块首次分歧（连续上涨后出现1-2日调整）"
      timing: "非连续涨停日（涨停家数<板块内30%）"
    max_active_candidates: 3  # 同一方向最多同时关注3个标的
```

### 2.3 stock_pool.yaml 结构

```yaml
# config/stock_monitor/stock_pool.yaml
stocks:
  - code: 000636.SZ
    name: 风华高科
    direction: mlcc_super_cycle
    chain_position: midstream  # upstream | midstream | downstream
    up_mention:
      date: 2026-06-15
      type: signal_confirmation  # direction_call | signal_confirmation
      context: "MLCC情绪核心候选"
    entry:
      primary_zone: [57.8, 62.7]
      method: "MA10-MA20回踩"
      hard_stop: 54.0
    pre_condition:
      sector_diverged: true   # 必须板块分歧后
      market_actionable: true # 必须大盘可操作窗口
      no_consecutive_limit_up: true  # 非连续涨停中
    fallback:  # 如果风华高科买不到
      - code: 300285.SZ
        name: 国瓷材料
        reason: "MLCC上游陶瓷粉体，风华高科涨停买不到时的替代"
```

---

## 三、Agent 重构方案

### 3.1 新的四层过滤架构

```
当前架构:
  价格入区间 → 6条件 → 告警

重构后:
  Layer 1: 市场门控（Market Gate）
    ├── 全A指数是否在可操作窗口？（非破位+量能达标）
    ├── 今天是进攻日还是防守日？
    └── 不通过 → 今天不扫描任何标的，直接返回"今日观望"
         ↓
  Layer 2: 板块门控（Sector Gate）  
    ├── 该方向当前处于什么阶段？（early/first_pump/diverging/resuming/ending）
    ├── 板块是否在首次分歧中？（非连续涨停）
    └── 处于 ending 或 first_pump → 跳过该方向所有标的
         ↓
  Layer 3: 标的条件检查（Stock Conditions）
    ├── 价格是否在介入区间？
    ├── 是否满足技术条件（缩量/MA上方/非涨停）？
    └── 是否为主板可交易标的？
         ↓
  Layer 4: LLM 终判（LLM Final Judgment）
    ├── 综合市场+板块+标的三个层面的信息
    ├── 判断风险收益比
    └── 输出：买入/观望/放弃 + 理由
```

### 3.2 新增规则引擎：MarketGate

```python
# src/qing_investment/monitor/gates.py (新增)

class MarketGate:
    """市场门控 — 判断今天是否适合开新仓"""
    
    def evaluate(self, market_data: dict) -> GateResult:
        checks = {
            "全A非破位": self._check_index_ok(market_data),
            "量能达标": self._check_volume(market_data),      # >2.5万亿
            "非连续恐慌": self._check_not_panicking(market_data),
            "非防守日": self._check_not_defense_day(market_data),  # 银行保险领涨→防守日
        }
        passed = [k for k, v in checks.items() if v]
        return GateResult(
            passed=len(passed) >= 3,
            checks=checks,
            bias="观望" if len(passed) < 3 else "可操作"
        )

class SectorGate:
    """板块门控 — 判断该方向是否处于可介入阶段"""
    
    def evaluate(self, direction: DirectionConfig, sector_data: dict) -> GateResult:
        stage = direction.current_stage
        
        # 不同阶段的介入策略
        if stage == "first_pump":
            return GateResult(passed=False, reason="板块首次拉升中——等分歧")
        if stage == "diverging":
            return GateResult(passed=True, reason="板块分歧中——可找低位标的")
        if stage == "ending":
            return GateResult(passed=False, reason="板块接近尾声——不参与")
        if stage == "early_direction":
            return GateResult(passed=True, reason="方向早期——可提前研究埋伏")
```

### 3.3 新增：ChainAwareScanner（产业链感知扫描）

```python
# 当 UP 点名风华高科(MLCC制造)时
# 自动扫描 MLCC 产业链上游：

class ChainAwareScanner:
    """基于产业链关系的智能扫描器"""
    
    def find_alternatives(self, pumped_stock: str, direction: DirectionConfig):
        """找一个已经涨了的标的，推荐同链还没涨的"""
        chain = direction.industry_chain
        for segment_id, segment in chain.items():
            if pumped_stock in segment.stocks and segment.pumped:
                # 这个环节已经涨了 → 找其他还没涨的环节
                for other_id, other_segment in chain.items():
                    if other_id != segment_id and not other_segment.pumped:
                        yield other_segment.stocks  # 推荐这些标的
```

---

## 四、全链路重构后的数据流

```
┌──────────────────────────────────────────────────────────┐
│                    UP 内容输入                             │
│  复盘/早盘/资讯 → 自动提取（或手动标记）                    │
│    ├── 方向预判 → direction_pool（方向池）                 │
│    ├── 信号确认 → stock_pool（标的池）+ 标记"已涨"         │
│    ├── 扩散路径 → direction.diffusion_path                │
│    └── 操作纪律 → strategy_pack（更新market_framework）    │
└──────────────────────┬───────────────────────────────────┘
                       ↓
┌──────────────────────────────────────────────────────────┐
│ 每N分钟 Cron 轮询                                        │
│                                                          │
│ Step 1: MarketGate.evaluate()                            │
│   → 全A破位？量能不足？防守日？                            │
│   → 不通过 → 输出"今日观望"，结束本轮                     │
│                                                          │
│ Step 2: 遍历 direction_pool 中所有方向                    │
│   → SectorGate.evaluate(direction)                       │
│   → 板块在连续涨停？→ 跳过                                 │
│   → 板块在分歧中？→ 继续                                   │
│                                                          │
│ Step 3: 对通过门控的方向，遍历 stock_pool                  │
│   → 检查：价格是否在介入区间？                             │
│   → 检查：pre_condition 是否满足？                         │
│   → 如果是"已涨"标的，同时扫描 fallback 替代标的           │
│                                                          │
│ Step 4: 候选标的 → LLM 终判                               │
│   → 输入：市场状态 + 板块状态 + 标的技术面 + claims背景    │
│   → 输出：具体操作建议                                    │
└──────────────────────────────────────────────────────────┘
```

---

## 五、实施优先级

### P0: 立即可做（不改代码结构，只改配置+Prompt）

| 改动 | 影响 | 工作量 |
|---|---|---|
| watchlist 加 `pre_condition` 字段 | Agent 检查前置条件 | 30min |
| strategy_pack 加 `market_gate_rules` | Agent Prompt 可引用 | 20min |
| Agent Prompt 加"市场门控"逻辑 | LLM 判断时先检查大盘 | 15min |

### P1: 本周可做（新增配置文件，代码改动小）

| 改动 | 影响 | 工作量 |
|---|---|---|
| 新建 `direction_pool.yaml` | 方向层配置 | 1h |
| `BuySignalRuleEngine` 加 `pre_condition` 检查 | 5个条件→8个条件，加入板块分歧判断 | 2h |
| `ContextAssembler` 输出加入方向和板块状态 | LLM 能感知全局 | 1h |

### P2: 下个迭代（重构引擎，新增模块）

| 改动 | 影响 | 工作量 |
|---|---|---|
| 新增 `gates.py`（MarketGate + SectorGate） | 结构化的门控逻辑 | 3h |
| 新增 `chain_scanner.py`（产业链感知） | 自动找替代标的 | 2h |
| 重构 `BuySignalRuleEngine` 为四层架构 | 根本性解决触发条件错位 | 4h |

---

## 六、直接回答你的问题

### Q: Qing Agent 应该重构吗？

**是的，但不是推倒重来。** 核心问题是触发条件错位——当前"价格入区间"是触发条件，但正确的触发条件应该是"板块分歧+大盘配合"。这需要在 `BuySignalRuleEngine` 前面加两层门控，不需要动数据获取和消息发送层。

### Q: Config 设计应该重构吗？

**是的，而且比 Agent 重构更优先。** 当前 `watchlist.yaml` 是一个"标的列表"，但它应该是"方向→产业链→标的"的三层结构。没有产业链关系，Agent 就只能是盲人摸象——只看到一只票，看不到整个板块在干什么。

**建议先从 P0+P1 开始**：加 pre_condition + 新建 direction_pool，让 Agent 在下一次提醒你买入前先问三个问题：
1. 今天大盘能动手吗？
2. 这个板块是分歧还是连涨？
3. 这个标的是龙头还是替代标的？

---

## 七、Gap 补齐记录（2026-06-16）

### Gap 1：数据契约缺失

**【问题】** 文档定义了 data schema，但没有定义 data exposure contract——哪些字段进 LLM prompt，哪些只停留在代码层。

**【修复】**
- 新建 `docs/config-data-contract.md`，定义了每个字段的消费端映射和 LLM 可见性
- 标记 `human_only` 字段（`stock_pool[].human_note`），在 `format_agent_json_context()` 中过滤，不进 LLM

### Gap 2：entry_zone 消费端断链

**【问题】** `entry.primary_zone` / `hard_stop` 字段存在、被填充、被认为重要，但 `_build_direction_state()` 的返回值中没有它们。LLM 只能通过原始 JSON 自己翻。

**【修复】**
- `_build_direction_state()` 新增返回 3 个字段：`entry_zone`、`hard_stop`、`stock_pre_condition`
- LLM 在 direction_state 中直接可见这些信息，不再需要自己从原始 JSON 翻

### Gap 3：fallback 两套协议无仲裁

**【问题】** 文档中 `stock_pool[].fallback`（手动指定替代标的）与 `ChainAwareScanner` 的 `industry_chain` 动态扫描两套方案并存，没有明确取舍关系。

**【修复】**
- 删除 `stock_pool[].fallback` 字段（包括所有 stock 上的手动 fallback 配置）
- 统一使用 `ChainAwareScanner` 的 `industry_chain` 动态扫描作为替代标的推荐方案
- `chain_scanner.py` 的实现在设计文档 §3.3 基础上已上线

### 附加清理

| 清理项 | 原因 |
|-------|------|
| 删除 `direction_pool[].up_first_mentioned` | 元数据，无代码消费，LLM 不需要 |
| 删除 `direction_pool[].up_mention_type` | 同左 |
| 删除 `direction_pool[].max_active_candidates` | 方向级仓位控制引擎未实现 |
| 删除 `stock_pool[].cross_directions` | 无设计，无代码消费 |
| 删除 `stock_pool[].chain_alternatives` | scanner 运行时生成，不是静态数据 |
| `up_mention` 重命名为 `human_note` | 语义更明确：人类参考，不进 LLM |

### 新增文件

`docs/config-data-contract.md` — 完整字段定义、消费端映射、LLM 可见性表。
