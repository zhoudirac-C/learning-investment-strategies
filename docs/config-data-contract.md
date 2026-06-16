# Config 数据契约

> 定义 `config/stock_monitor/` 下每个配置文件的字段结构、消费端映射、LLM 可见性。
>
> 关联设计文档：[qing-agent-config-reconstruction.md](qing-agent-config-reconstruction.md)
>
> 最后更新：2026-06-16

---

## 核心规则

1. **代码消费优先**：字段必须有一级消费方（代码类/函数），否则不纳入 schema
2. **LLM 层保底**：所有代码消费的字段自动进 LLM prompt，但代码不读的字段不得进入 LLM 上下文
3. **human_only 标记**：人类参考用的备注数据，显式标记 `human_only`，不进 LLM

---

## 一、direction_pool.yaml

### schema

```yaml
directions:
  - id: str                          # 唯一标识
    name: str                        # 人类可读名称
    current_stage: str               # early_direction | first_pump | diverging | resuming | ending
    industry_chain:                  # 产业链结构
      upstream/midstream/downstream:
        - segment: str               # 环节名（如"陶瓷粉体"）
          stocks:
            - code: str              # 股票代码
              name: str
          pumped: bool               # 是否已涨
          note: str | null           # 人工备注
    diffusion_path: list[str]        # UP 扩散预测路线
    pre_condition:                   # LLM 终判用的入场条件
      market: str
      sector: str
      timing: str
```

### 消费层映射

| 字段 | 代码消费者 | LLM 可见 | 说明 |
|------|-----------|---------|------|
| `id` | `_build_direction_state()`、`SectorGate.evaluate()` | ✅ | 方向匹配键 |
| `name` | `_build_direction_state()` | ✅ | 方向显示名 |
| `current_stage` | `_build_direction_state()`、`SectorGate.evaluate()` | ✅ | SectorGate 用此判断是否可介入 |
| `industry_chain` | `ChainAwareScanner.find_alternatives()` | ✅ (经由 scanner) | scanner 读 upstream/midstream/downstream + pumped |
| `diffusion_path` | `_build_direction_state()` | ✅ | LLM 判断扩散节奏 |
| `pre_condition` | `_build_direction_state()` | ✅ | LLM 判断入场时机 |
| `industry_chain[].segment.note` | ❌ 代码不读 | ✅ LLM 自主读取 | **设计允许**：完整 YAML 随 JSON 传入 qing-agent，LLM 可自主查阅 |

### 不纳入 schema 的字段（已删除）

| 字段 | 原因 |
|------|------|
| `up_first_mentioned` | 元数据，无代码消费，LLM 不需要 |
| `up_mention_type` | 元数据，无代码消费 |
| `max_active_candidates` | 引擎层未实现方向级仓位控制，数据预埋过早 |

---

## 二、stock_pool.yaml

### schema

```yaml
stocks:
  - code: str                        # 股票代码
    name: str                        # 股票名称
    direction: str                   # 所属方向 id
    chain_position: str              # upstream | midstream | downstream
    entry:                           # 设计消费端：Stock Conditions 层（P1 待实现）
      primary_zone: list[float]      # 介入价格区间 [低, 高]
      method: str                    # 介入方法描述
      hard_stop: float               # 硬止损价
    pre_condition:                   # 设计消费端：BuySignalRuleEngine（P1 待实现）
      sector_diverged: bool          # 板块必须分歧过
      market_actionable: bool        # 大盘必须可操作
      no_consecutive_limit_up: bool  # 非连续涨停中
    fallback:                        # 已废弃 — 被 ChainAwareScanner 替代
      - code: str
        name: str
        reason: str
    human_note: dict | null          # 人类参考备注，__不进 LLM__
```

### 消费层映射

| 字段 | 代码消费者 | LLM 可见 | 说明 |
|------|-----------|---------|------|
| `code` | `_build_direction_state()`、`rules.get_direction_for_stock()` | ✅ | 标的键 |
| `name` | `_build_direction_state()` | ✅ | 显示用 |
| `direction` | `_build_direction_state()`、`rules.get_direction_for_stock()` | ✅ | 标的方向归属 |
| `chain_position` | `_build_direction_state()` | ✅ | 产业链位置 |
| `entry.primary_zone` | `_build_direction_state()` | ✅ **（新增）** | 原设计为 Stock Conditions 层，现阶段注入 direction_state 供 LLM |
| `entry.hard_stop` | `_build_direction_state()` | ✅ **（新增）** | 同上 |
| `entry.method` | ❌ 代码不读 | ✅ LLM 自主读取 | 说明文字，LLM 参考 |
| `pre_condition.*` (sector_diverged/market_actionable/no_consecutive_limit_up) | `_build_direction_state()` | ✅ **（新增）** | 原设计为 BuySignalRuleEngine 的条件检查，现阶段注入 direction_state 供 LLM |
| `human_note` | ❌ 代码不读 | ❌ **不进 LLM** | 纯人类参考。在 format_agent_json_context 中被过滤 |
| `fallback` | ❌ 代码不读 | ❌ **已删除** | 被 ChainAwareScanner 的 industry_chain 动态扫描替代 |
| `cross_directions` | ❌ 代码不读 | ❌ **已删除** | 无设计，无消费 |
| `chain_alternatives` | ❌ 代码不读 | ❌ **已删除** | scanner 运行时生成，不是静态数据 |

### human_note 字段格式

```yaml
human_note:
  date: '2026-06-15'         # UP 提及日期
  type: signal_confirmation  # direction_call | signal_confirmation
  context: "MLCC情绪核心候选" # UP 原文摘要
```

---

## 三、当前引擎 P1 待实现项

| 待实现 | 依赖字段 | 影响 |
|-------|---------|------|
| `BuySignalRuleEngine` 加 `pre_condition` 检查 | stock_pool[].pre_condition.* | 代码级拦截而非仅 LLM 判断 |
| Stock Conditions 层（价格区间检查） | stock_pool[].entry.primary_zone | 价格未到区间不生成候选 |
| `format_agent_json_context` 过滤 `human_only` 字段 | stock_pool[].human_note | 减少 LLM token 浪费 |

---

## 四、数据流示意图

```
direction_pool.yaml / stock_pool.yaml
    │
    ├── load_monitor_config()  ──→  MonitorConfig（Python 对象）
    │                                   │
    │                                   ├── _build_direction_state()    ─────→  LLM context
    │                                   │       │                             (id, name, stage,
    │                                   │       └── entry.primary_zone         industry_chain*,
    │                                   │           entry.hard_stop            diffusion_path,
    │                                   │           pre_condition              pre_condition,
    │                                   │           chain_position             entry_zone,
    │                                   │                                     hard_stop)
    │                                   │
    │                                   ├── SectorGate.evaluate()      ─────→  方向门控
    │                                   ├── ChainAwareScanner          ─────→  替代标的推荐
    │                                   └── format_agent_json_context() ─────→  qing-agent JSON
    │                                           │
    │                                           ├── human_note → ❌ 过滤
    │                                           └── 其余字段   → ✅ 传 LLM
    │
    └── P1 待实现:
        BuySignalRuleEngine.pre_condition 检查
        Stock Conditions 层价格区间检查
```

> **图例：** `_build_direction_state` 是当前代码消费入口。`P1` 项目尚未实现，但数据已预埋。
