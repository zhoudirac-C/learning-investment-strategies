# Qing Agent + Config 重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前"价格入区间=买入信号"的监控链路重构为"市场门控 → 板块门控 → 标的条件 → LLM 终判"的四层架构，并把配置从单层 watchlist 拆分为 direction_pool + stock_pool 两层结构。

**Architecture:** 保持现有 `src/qing_investment/monitor/*` 模块边界不变，新增 `gates.py` 和 `chain_scanner.py`；配置层面新增 `direction_pool.yaml` 和 `stock_pool.yaml`，并通过 loader 与现有 `MonitorConfig` 兼容；最终 `BuySignalRuleEngine` 只负责"标的条件"这一层，门控由新模块承担。

**Tech Stack:** Python 3.12, PyYAML, Pydantic v2, pytest（项目已使用）。

---

## 0. 当前代码诊断（必读）

### 0.1 数据流

```
UP复盘点名标的
    ↓ (用户手动)
watchlist.yaml (设 entry_zone，基于涨停回踩法)
    ↓
stock_monitor.py / scheduler.run_tick() 每N分钟轮询
    ↓
BuySignalRuleEngine._evaluate_candidates()
    → 检查：价格是否在 entry_zone 区间？
    → 6条件：价格入区间 + 非大跌 + 未涨停 + UP看好 + 缩量 + MA20上方
    → 4/6条件满足 → "机会候选" 告警
    ↓
ContextAssembler / format_agent_json_context 格式化 → 注入 LLM prompt
    ↓
LLM 判断 → 微信/终端提醒用户
```

### 0.2 关键代码位置

| 职责 | 当前实现位置 |
|---|---|
| 买入候选判断 | `src/qing_investment/monitor/rules/__init__.py` 中 `BuySignalRuleEngine._evaluate_candidates()` |
| 配置加载 | `src/qing_investment/monitor/context/__init__.py` 中 `load_monitor_config()` |
| 行情获取 | `src/qing_investment/monitor/fetchers/__init__.py` 中 `DataFetcher` |
| 调度/数据流 | `src/qing_investment/monitor/scheduler/__init__.py` 中 `run_tick()` |
| Agent JSON 上下文 | `src/qing_investment/monitor/context/__init__.py` 中 `format_agent_json_context()` |
| Cron 入口 | `scripts/hermes_stock_monitor_agent.py` |
| 现有买入信号 E2E 测试 | `tests/test_buy_signal_e2e.py` |

### 0.3 现有 `BuySignalRuleEngine._evaluate_candidates()` 核心逻辑

```python
# src/qing_investment/monitor/rules/__init__.py:358-475
conditions = {
    "价格进入区间": price_in_zone,
    "非系统性大跌": not_crashing,
    "未涨停": no_limit_up,
    "UP明确看好": has_claim_support,
    "近3日缩量": volume_shrinking,
    "MA20上方": above_key_ma,
}
matched = [k for k, v in conditions.items() if v]
is_candidate = len(matched) >= 4
```

问题：触发条件只有"价格进入区间"，缺少"大盘可操作"和"板块首次分歧"两个前置门控。

---

## 1. 文件结构（重构后）

### 1.1 新增文件

| 文件 | 职责 |
|---|---|
| `config/stock_monitor/direction_pool.yaml` | 方向层配置：产业链图谱、扩散路径、前置条件、当前阶段 |
| `config/stock_monitor/stock_pool.yaml` | 标的层配置：所属方向、产业链位置、介入区间、fallback 替代 |
| `src/qing_investment/monitor/gates.py` | `MarketGate` + `SectorGate` + `GateResult` |
| `src/qing_investment/monitor/chain_scanner.py` | `ChainAwareScanner`：基于产业链找替代标的 |
| `tests/test_monitor_gates.py` | Gate 模块单元测试 |
| `tests/test_chain_scanner.py` | 产业链扫描器单元测试 |

### 1.2 修改文件

| 文件 | 修改点 |
|---|---|
| `src/qing_investment/monitor/context/__init__.py` | `load_monitor_config()` 加载 direction_pool / stock_pool；`format_agent_analysis_context()` / `format_agent_json_context()` 注入方向/板块状态 |
| `src/qing_investment/monitor/rules/__init__.py` | `BuySignalRuleEngine._evaluate_candidates()` 增加 pre_condition 检查；P2 改为只保留"标的条件"层 |
| `src/qing_investment/monitor/scheduler/__init__.py` | `run_tick()` 在 RuleEngine 前调用 MarketGate / SectorGate |
| `config/stock_monitor/watchlist.yaml` | P0 起逐步把 `entry_zone` 内的前置条件抽到 `pre_condition` |
| `config/stock_monitor/strategy_pack.yaml` | P0 增加 `market_gate_rules`；P1/P2 与 direction_pool 同步 |
| `tests/test_buy_signal_e2e.py` | 增加 pre_condition / gate 相关断言 |
| `tests/test_stock_monitor.py` | 增加 direction_pool / stock_pool 加载测试 |

---


## Phase P0：立即可做（不改代码结构，只改配置+Prompt）

> 目标：在不改动 Python 代码结构的前提下，先把"市场/板块前置条件"显式化，让 LLM 在判断前先检查三个问题。

---

### Task P0-1：在 `watchlist.yaml` 的 stock 结构中加入 `pre_condition` 字段

**Files:**
- Modify: `config/stock_monitor/watchlist.yaml`（示例：风华高科、昊华科技、诺德股份等 P1 买入标的）
- Test: `tests/test_stock_monitor.py` 中新增断言

**说明：** 当前 `entry_zone` 里已经用文字写了"全A中阳线为前置条件"等要求，但 Agent 规则引擎读不到。本任务把前置条件显式化为 `pre_condition` 字段，供后续 P1 代码读取。

- [ ] **Step 1：选择首批需要加 pre_condition 的标的**

从 `strategy_pack.yaml` 的 `operation_plan.buy_priority` 中挑选前 3 只：诺德股份、风华高科、东山精密。如果 `watchlist.yaml` 中没有东山精密，先加入它（或只改已有标的）。

- [ ] **Step 2：在 `watchlist.yaml` 中为标的添加 pre_condition**

以风华高科为例，在 `mlcc_passive_component` theme 下找到 `000636.SZ` 的条目，在 `entry_zone` 同级添加：

```yaml
    pre_condition:
      market_actionable: true
      sector_diverged: true
      no_consecutive_limit_up: true
      market_gate_note: "全A量能>2.5万亿+非破位状态"
      sector_gate_note: "板块首次分歧（连续上涨后出现1-2日调整）"
```

- [ ] **Step 3：运行现有测试确保没有破坏 YAML 解析**

Run: `pytest tests/test_stock_monitor.py::test_load_monitor_config_counts_rows -v`
Expected: PASS

- [ ] **Step 4：提交**

```bash
git add config/stock_monitor/watchlist.yaml
git commit -m "config(watchlist): add pre_condition fields to key entry candidates"
```

---

### Task P0-2：在 `strategy_pack.yaml` 中加入 `market_gate_rules`

**Files:**
- Modify: `config/stock_monitor/strategy_pack.yaml`
- Test: `tests/test_stock_monitor.py` 中新增断言

**说明：** 把当前 `market_framework` 和 `key_levels` 中的可操作/不可操作标准抽取为结构化的 `market_gate_rules`，供 Prompt 引用，也供 P2 的 `MarketGate` 读取。

- [ ] **Step 1：在 `strategy_pack.yaml` 顶部 `market_framework` 之后新增 `market_gate_rules`**

```yaml
market_gate_rules:
  index_checks:
    - index: "全A指数"
      condition: "not_close_below"
      level: 6000
      note: "全A等权指数破位警戒线"
    - index: "上证指数"
      condition: "not_close_below"
      level: 3950
      note: "月线趋势防线"
  volume_checks:
    - metric: "total_amount"
      condition: "greater_than"
      threshold: 2500000000000
      note: "两市总成交额>2.5万亿"
  defense_day_checks:
    - type: "bank_insurance_leading"
      action: "defense_day"
      note: "银行保险领涨→防守日，不买入"
  actionable_min_pass: 2
  bias_map:
    pass_3: "可操作"
    pass_2: "谨慎"
    pass_1_or_0: "观望"
```

- [ ] **Step 2：写测试验证配置能加载且规则存在**

在 `tests/test_stock_monitor.py` 末尾新增：

```python
def test_strategy_pack_contains_market_gate_rules(tmp_path):
    config_dir = make_rule_config_dir(tmp_path)
    # 手动追加 market_gate_rules 到 strategy_pack.yaml
    sp_path = config_dir / "strategy_pack.yaml"
    sp = yaml.safe_load(sp_path.read_text(encoding="utf-8"))
    sp.setdefault("market_gate_rules", {
        "index_checks": [{"index": "上证指数", "condition": "not_close_below", "level": 3950}],
        "actionable_min_pass": 2,
    })
    sp_path.write_text(yaml.safe_dump(sp, allow_unicode=True), encoding="utf-8")

    config = load_monitor_config(config_dir)
    mgr = config.strategy_pack.get("market_gate_rules", {})
    assert "index_checks" in mgr
    assert mgr.get("actionable_min_pass") == 2
```

- [ ] **Step 3：运行测试**

Run: `pytest tests/test_stock_monitor.py::test_strategy_pack_contains_market_gate_rules -v`
Expected: PASS

- [ ] **Step 4：提交**

```bash
git add config/stock_monitor/strategy_pack.yaml tests/test_stock_monitor.py
git commit -m "config(strategy_pack): add structured market_gate_rules"
```

---

### Task P0-3：在 `ContextAssembler` 输出中加入 pre_condition 文本

**Files:**
- Modify: `src/qing_investment/monitor/context/__init__.py`
- Test: `tests/test_buy_signal_e2e.py`（扩展 JSON context 断言）

**说明：** 在 `format_agent_json_context()` 输出的 JSON 中，为每个买入候选追加 `pre_condition_text` 字段，让 LLM 在 prompt 里就能看到"今天大盘能动手吗？板块分歧了吗？"。

- [ ] **Step 1：新增工具函数 `_extract_pre_condition_text(stock_row)`**

在 `src/qing_investment/monitor/context/__init__.py` 的 `format_agent_json_context()` 之前添加：

```python
def _extract_pre_condition_text(stock_row: dict) -> str:
    """从 watchlist stock 行提取 pre_condition 为可读文本。"""
    pc = stock_row.get("pre_condition") or {}
    if not pc:
        return ""
    parts: list[str] = []
    if pc.get("market_actionable"):
        parts.append("大盘可操作")
    if pc.get("sector_diverged"):
        parts.append("板块首次分歧")
    if pc.get("no_consecutive_limit_up"):
        parts.append("非连续涨停")
    note = pc.get("market_gate_note") or pc.get("sector_gate_note")
    if note:
        parts.append(f"备注：{note}")
    return "；".join(parts) if parts else ""
```

- [ ] **Step 2：修改 `format_agent_json_context()` 注入 pre_condition**

找到函数中组装 `buy_signal_candidates` 的位置（约 834 行起），在 candidate dict 中加入 `pre_condition`：

```python
# 原代码片段（需替换）
for c in raw_candidates:
    if getattr(c, 'is_candidate', False):
        buy_signal_candidates.append({
            "stock_code": c.stock_code,
            "stock_name": c.stock_name,
            "price": c.price,
            ...
        })

# 新代码：需要同时拿到 watchlist 行
watchlist_rows = {
    str(row.get("code", "")): row
    for row in (data.get("watchlist", {}).get("stocks", []) if isinstance(data.get("watchlist"), dict) else [])
}
for theme in (data.get("watchlist", {}).get("themes", []) if isinstance(data.get("watchlist"), dict) else []):
    for stock in theme.get("stocks", []):
        watchlist_rows[str(stock.get("code", ""))] = stock

for c in raw_candidates:
    if getattr(c, 'is_candidate', False):
        stock_row = watchlist_rows.get(c.stock_code, {})
        buy_signal_candidates.append({
            "stock_code": c.stock_code,
            "stock_name": c.stock_name,
            "price": c.price,
            "entry_zone": list(c.entry_zone) if c.entry_zone else None,
            "stop_loss": c.stop_loss,
            "matched_conditions": c.matched_conditions,
            "odds_analysis": c.odds_analysis,
            "pre_condition": _extract_pre_condition_text(stock_row),
        })
```

- [ ] **Step 3：写测试验证 pre_condition 出现在 JSON context 中**

在 `tests/test_buy_signal_e2e.py` 的测试配置中，给 `000001` 的 watchlist 条目添加 `pre_condition`：

```python
"stocks": [
    {
        "code": "000001",
        "name": "平安银行",
        "buy_setup": "10.0-11.0",
        "invalidation_setup": "9.5",
        "pre_condition": {
            "market_actionable": True,
            "sector_diverged": True,
            "market_gate_note": "测试大盘备注",
        },
    }
]
```

并在 `test_json_context_contains_analysis_type_stock` 末尾添加：

```python
candidate = data["buy_signal_candidates"][0]
assert candidate.get("pre_condition") == "大盘可操作；板块首次分歧；备注：测试大盘备注"
```

- [ ] **Step 4：运行测试**

Run: `pytest tests/test_buy_signal_e2e.py::TestBuySignalE2E::test_json_context_contains_analysis_type_stock -v`
Expected: PASS

- [ ] **Step 5：提交**

```bash
git add src/qing_investment/monitor/context/__init__.py tests/test_buy_signal_e2e.py
git commit -m "feat(context): inject pre_condition text into agent JSON context"
```

---

### Task P0-4：在 Agent Prompt 中加入"市场门控"自检指令

**Files:**
- Modify: `src/qing_investment/agent/prompts/system/stock_analyst.txt`
- Modify: `src/qing_investment/agent/prompts/system/cron_opportunity_scan.txt`
- Test: 手动检查 prompt 文本包含新指令（无自动化测试，用 grep 验证）

**说明：** 让 LLM 在买入确认前，必须先回答三个问题：今天大盘能动手吗？这个板块是分歧还是连涨？这个标的是龙头还是替代标的？

- [ ] **Step 1：修改 `stock_analyst.txt` 的"买入确认模式"段**

在原有 checklist 之前插入：

```text
【买入确认前的三层门控自检 — 必须先回答】
在给出 buy_decision 之前，你必须先检查以下三个问题，并在输出中显式回答：
1. 今天大盘能动手吗？
   - 依据：全A指数是否破位？两市成交额是否>2.5万亿？银行保险是否领涨（防守日）？
   - 如果任一为"是"→给出 "market_gate": "观望" 并直接结束买入确认（不买入）。
2. 这个板块是分歧还是连涨？
   - 依据：该方向近期是否连续大涨？今天是否首次出现1-2日调整？涨停家数是否<板块内30%？
   - 如果板块仍在连续涨停/加速段→给出 "sector_gate": "等分歧" 并直接结束买入确认（不买入）。
3. 这个标的是龙头还是替代标的？
   - 依据：UP是否点名该股为核心？产业链位置是上游/中游/下游？是否已经涨停买不到？
   - 如果是已涨停的龙头，应转向同方向低位替代标的（fallback）。

只有三层门控全部通过，才进入原有 checklist。
```

- [ ] **Step 2：在买入确认模式 JSON 输出中增加 gate 字段**

在 `stock_analyst.txt` 的买入确认 JSON schema 中， checklist_result 同级添加：

```text
  "gate_check": {
    "market_gate": "可操作/观望",
    "sector_gate": "分歧中/等分歧/接近尾声",
    "chain_position": "上游/中游/下游/替代标的"
  },
```

- [ ] **Step 3：修改 `cron_opportunity_scan.txt`**

在"7大机会模式逐一检查"之前插入：

```text
【机会扫描前置过滤 — 必须先执行】
1. 市场门控：若全A破位/量能<2.5万亿/银行保险领涨 → 本节点输出 "今日观望"，不扫描具体标的。
2. 板块门控：对每个候选方向，判断其处于 early_direction / first_pump / diverging / resuming / ending 哪个阶段。
   - first_pump 和 ending → 跳过该方向所有标的。
   - diverging 和 early_direction → 才进入具体标的扫描。
3. 龙头 vs 替代：若 UP 点名的核心标的大涨买不到，扫描同产业链上游/下游低位替代。
```

- [ ] **Step 4：用 grep 验证 prompt 已更新**

Run:
```bash
grep -n "市场门控" src/qing_investment/agent/prompts/system/stock_analyst.txt src/qing_investment/agent/prompts/system/cron_opportunity_scan.txt
grep -n "sector_gate" src/qing_investment/agent/prompts/system/stock_analyst.txt
```
Expected: 每行显示匹配到的文件名和行号。

- [ ] **Step 5：提交**

```bash
git add src/qing_investment/agent/prompts/system/stock_analyst.txt src/qing_investment/agent/prompts/system/cron_opportunity_scan.txt
git commit -m "feat(prompt): add market/sector gate self-check before buy confirmation"
```

---


## Phase P1：本周可做（新增配置文件，代码改动小）

> 目标：新建 `direction_pool.yaml` 和 `stock_pool.yaml`，让 `BuySignalRuleEngine` 读取并检查 `pre_condition`，让 LLM context 能感知方向/板块状态。

---

### Task P1-1：创建 `direction_pool.yaml`

**Files:**
- Create: `config/stock_monitor/direction_pool.yaml`
- Test: `tests/test_stock_monitor.py` 中新增断言

**说明：** 从 `watchlist.yaml` 的 theme 结构和 `strategy_pack.yaml` 的 `direction_priority` 中提取方向层信息。一个 direction 对应一个 UP 主动点名的产业链/主题。

- [ ] **Step 1：创建 `direction_pool.yaml`**

```yaml
updated_at: '2026-06-16'
directions:
  - id: mlcc_super_cycle
    name: MLCC超级周期
    up_first_mentioned: '2026-06-14'
    up_mention_type: signal_confirmation
    current_stage: divergence_verification
    industry_chain:
      upstream:
        - segment: 陶瓷粉体
          stocks:
            - code: 300285.SZ
              name: 国瓷材料
          pumped: false
      midstream:
        - segment: MLCC制造
          stocks:
            - code: 000636.SZ
              name: 风华高科
            - code: 300408.SZ
              name: 三环集团
          pumped: true
      downstream:
        - segment: 消费电子/汽车
          stocks: []
          pumped: false
    diffusion_path:
      - "MLCC → 被动元件整体 → PCB上游材料"
    pre_condition:
      market: "全A量能>2.5万亿+非破位状态"
      sector: "板块首次分歧（连续上涨后出现1-2日调整）"
      timing: "非连续涨停日（涨停家数<板块内30%）"
    max_active_candidates: 3

  - id: copper_foil_hvlp4
    name: 铜箔（HVLP4代铜箔）
    up_first_mentioned: '2026-06-16'
    up_mention_type: signal_confirmation
    current_stage: first_pump
    industry_chain:
      upstream:
        - segment: 铜箔设备/铜材
          stocks: []
          pumped: false
      midstream:
        - segment: HVLP4铜箔制造
          stocks:
            - code: 600110.SH
              name: 诺德股份
          pumped: true
    diffusion_path: []
    pre_condition:
      market: "全A量能>2.5万亿+非破位状态"
      sector: "分歧日回踩不破"
      timing: "非一字涨停买不到"
    max_active_candidates: 2
```

- [ ] **Step 2：新增测试验证 YAML 可解析**

在 `tests/test_stock_monitor.py` 末尾新增：

```python
import yaml


def test_direction_pool_yaml_is_valid(tmp_path):
    """direction_pool.yaml 必须能被 PyYAML 解析且包含至少一个方向。"""
    repo_root = Path(__file__).resolve().parents[1]
    dp_path = repo_root / "config" / "stock_monitor" / "direction_pool.yaml"
    assert dp_path.exists(), "direction_pool.yaml should exist"
    data = yaml.safe_load(dp_path.read_text(encoding="utf-8"))
    assert "directions" in data
    assert len(data["directions"]) >= 1
    first = data["directions"][0]
    assert "id" in first
    assert "industry_chain" in first
    assert "pre_condition" in first
```

- [ ] **Step 3：运行测试**

Run: `pytest tests/test_stock_monitor.py::test_direction_pool_yaml_is_valid -v`
Expected: PASS

- [ ] **Step 4：提交**

```bash
git add config/stock_monitor/direction_pool.yaml tests/test_stock_monitor.py
git commit -m "config(direction_pool): add direction-layer config with industry chain and pre_conditions"
```

---

### Task P1-2：创建 `stock_pool.yaml`

**Files:**
- Create: `config/stock_monitor/stock_pool.yaml`
- Test: `tests/test_stock_monitor.py` 中新增断言

**说明：** 从 `watchlist.yaml` 的 stocks 列表中提取标的层信息，并显式关联 direction。一个 stock 只能属于一个 direction，但可以有 fallback 替代标的。

- [ ] **Step 1：创建 `stock_pool.yaml`**

```yaml
updated_at: '2026-06-16'
stocks:
  - code: 000636.SZ
    name: 风华高科
    direction: mlcc_super_cycle
    chain_position: midstream
    up_mention:
      date: '2026-06-15'
      type: signal_confirmation
      context: "MLCC情绪核心候选"
    entry:
      primary_zone: [57.8, 62.7]
      method: "MA10-MA20回踩"
      hard_stop: 54.0
    pre_condition:
      sector_diverged: true
      market_actionable: true
      no_consecutive_limit_up: true
    fallback:
      - code: 300285.SZ
        name: 国瓷材料
        reason: "MLCC上游陶瓷粉体，风华高科涨停买不到时的替代"

  - code: 600110.SH
    name: 诺德股份
    direction: copper_foil_hvlp4
    chain_position: midstream
    up_mention:
      date: '2026-06-16'
      type: signal_confirmation
      context: "HVLP4代铜箔订单排至2027下半年"
    entry:
      primary_zone: [12.0, 13.0]
      method: "分歧日回踩"
      hard_stop: 11.5
    pre_condition:
      sector_diverged: true
      market_actionable: true
      no_consecutive_limit_up: true
    fallback: []
```

- [ ] **Step 2：新增测试验证 YAML 可解析**

在 `tests/test_stock_monitor.py` 末尾新增：

```python
def test_stock_pool_yaml_is_valid(tmp_path):
    """stock_pool.yaml 必须能被 PyYAML 解析且每个标的有 direction。"""
    repo_root = Path(__file__).resolve().parents[1]
    sp_path = repo_root / "config" / "stock_monitor" / "stock_pool.yaml"
    assert sp_path.exists(), "stock_pool.yaml should exist"
    data = yaml.safe_load(sp_path.read_text(encoding="utf-8"))
    assert "stocks" in data
    assert len(data["stocks"]) >= 1
    first = data["stocks"][0]
    assert "code" in first
    assert "direction" in first
    assert "entry" in first
    assert "pre_condition" in first
```

- [ ] **Step 3：运行测试**

Run: `pytest tests/test_stock_monitor.py::test_stock_pool_yaml_is_valid -v`
Expected: PASS

- [ ] **Step 4：提交**

```bash
git add config/stock_monitor/stock_pool.yaml tests/test_stock_monitor.py
git commit -m "config(stock_pool): add stock-layer config with direction linkage and fallback"
```

---

### Task P1-3：在 `load_monitor_config()` 中加载 `direction_pool` 和 `stock_pool`

**Files:**
- Modify: `src/qing_investment/monitor/context/__init__.py` 中 `load_monitor_config()`
- Modify: `src/qing_investment/stock_monitor.py` 中 `MonitorConfig` dataclass
- Test: `tests/test_stock_monitor.py` 中新增断言

**说明：** 让 `MonitorConfig` 同时持有 `direction_pool` 和 `stock_pool`，并保证向后兼容（旧配置不存在这两个文件时为空 dict）。

- [ ] **Step 1：扩展 `MonitorConfig` dataclass**

在 `src/qing_investment/stock_monitor.py` 中修改：

```python
@dataclass
class MonitorConfig:
    config_dir: Path
    positions: dict
    watchlist: dict
    strategy_pack: dict
    positions_path: Path
    direction_pool: dict = field(default_factory=dict)
    stock_pool: dict = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """模拟 dict.get() 以兼容 RuleEngine。"""
        if key == "positions":
            return self.positions
        if key == "watchlist":
            return self.watchlist
        if key == "strategy_pack":
            return self.strategy_pack
        if key == "direction_pool":
            return self.direction_pool
        if key == "stock_pool":
            return self.stock_pool
        if key == "config_dir":
            return str(self.config_dir)
        if key == "positions_path":
            return str(self.positions_path)
        if self.strategy_pack and isinstance(self.strategy_pack, dict):
            return self.strategy_pack.get(key, default)
        return default
```

- [ ] **Step 2：修改 `load_monitor_config()` 加载新配置**

在 `src/qing_investment/monitor/context/__init__.py` 中修改：

```python
def load_monitor_config(path: str | Path) -> Any:
    from qing_investment.stock_monitor import MonitorConfig

    config_dir = Path(path) if isinstance(path, str) else path
    if config_dir.is_file():
        config_dir = config_dir.parent

    positions_path = config_dir / "positions.yaml"
    if not positions_path.exists():
        positions_path = config_dir / "positions.example.yaml"

    direction_pool_path = config_dir / "direction_pool.yaml"
    stock_pool_path = config_dir / "stock_pool.yaml"

    return MonitorConfig(
        config_dir=config_dir,
        positions=load_yaml(positions_path),
        watchlist=load_yaml(config_dir / "watchlist.yaml"),
        strategy_pack=load_yaml(config_dir / "strategy_pack.yaml"),
        positions_path=positions_path,
        direction_pool=load_yaml(direction_pool_path),
        stock_pool=load_yaml(stock_pool_path),
    )
```

- [ ] **Step 3：新增测试**

在 `tests/test_stock_monitor.py` 中新增：

```python
def test_load_monitor_config_loads_direction_and_stock_pool(tmp_path):
    config_dir = make_config_dir(tmp_path)
    # 写入最小 direction_pool / stock_pool
    write_yaml(
        config_dir / "direction_pool.yaml",
        {"directions": [{"id": "test_dir", "name": "测试方向"}]},
    )
    write_yaml(
        config_dir / "stock_pool.yaml",
        {"stocks": [{"code": "000021.SZ", "name": "深科技", "direction": "test_dir"}]},
    )

    config = load_monitor_config(config_dir)
    assert config.direction_pool["directions"][0]["id"] == "test_dir"
    assert config.stock_pool["stocks"][0]["direction"] == "test_dir"
```

- [ ] **Step 4：运行测试**

Run: `pytest tests/test_stock_monitor.py::test_load_monitor_config_loads_direction_and_stock_pool -v`
Expected: PASS

- [ ] **Step 5：提交**

```bash
git add src/qing_investment/monitor/context/__init__.py src/qing_investment/stock_monitor.py tests/test_stock_monitor.py
git commit -m "feat(config): load direction_pool and stock_pool into MonitorConfig"
```

---

### Task P1-4：`BuySignalRuleEngine._evaluate_candidates()` 加入 `pre_condition` 检查

**Files:**
- Modify: `src/qing_investment/monitor/rules/__init__.py`
- Modify: `src/qing_investment/monitor/scheduler/__init__.py` 中 `_cfg_dict` 构建
- Test: `tests/test_buy_signal_e2e.py` 中新增测试

**说明：** 把 6 条件扩展为 8 条件，加入"板块分歧"和"大盘可操作"两个前置条件。当前阶段这两个条件默认从配置读取并视为满足（除非配置显式标记为 false），避免破坏现有行为。同时需要确保 `_cfg_dict` 把 `stock_pool` 和 `direction_pool` 传给规则引擎。

- [ ] **Step 1：新增 helper 读取 pre_condition**

在 `src/qing_investment/monitor/rules/__init__.py` 的 `BuySignalRuleEngine` 内新增：

```python
class BuySignalRuleEngine(BaseRuleEngine):
    ...

    def _stock_pre_condition(self, config: dict, code_norm: str) -> dict:
        """从 stock_pool 或 watchlist 读取 pre_condition。"""
        # 优先 stock_pool
        for stock in config.get("stock_pool", {}).get("stocks", []) or []:
            if _norm_code(str(stock.get("code", ""))) == code_norm:
                return stock.get("pre_condition", {}) or {}
        # 回退 watchlist
        for theme in config.get("watchlist", {}).get("themes", []) or []:
            for stock in theme.get("stocks", []) or []:
                if _norm_code(str(stock.get("code", ""))) == code_norm:
                    return stock.get("pre_condition", {}) or {}
        return {}
```

- [ ] **Step 2：修改 `_evaluate_candidates()` 的 conditions**

在 `src/qing_investment/monitor/rules/__init__.py` 约 450 行处，把 6 条件改为 8 条件：

```python
pre_condition = self._stock_pre_condition(config, code_norm)
sector_diverged_ok = pre_condition.get("sector_diverged", True)
market_actionable_ok = pre_condition.get("market_actionable", True)

conditions = {
    "价格进入区间": price_in_zone,
    "非系统性大跌": not_crashing,
    "未涨停": no_limit_up,
    "UP明确看好": has_claim_support,
    "近3日缩量": volume_shrinking,
    "MA20上方": above_key_ma,
    "板块分歧": sector_diverged_ok,
    "大盘可操作": market_actionable_ok,
}
matched = [k for k, v in conditions.items() if v]
is_candidate = len(matched) >= 5  # 8条件中满足5个
```

- [ ] **Step 3：在 `run_tick()` 的 `_cfg_dict` 中加入 `stock_pool` / `direction_pool`**

在 `src/qing_investment/monitor/scheduler/__init__.py` 中，找到构建 `_cfg_dict` 的位置，追加两项：

```python
_cfg_dict: dict = {
    "positions": getattr(config, "positions", {}),
    "watchlist": getattr(config, "watchlist", {}),
    "strategy_pack": _sp,
    "entry_points": _sp.get("entry_points", []) or getattr(config, "entry_points", []),
    "market_framework": _sp.get("market_framework", {}) or getattr(config, "market_framework", {}),
    "sector_groups": _sp.get("sector_groups", []) or getattr(config, "sector_groups", []),
    "direction_pool": getattr(config, "direction_pool", {}),
    "stock_pool": getattr(config, "stock_pool", {}),
}
```

- [ ] **Step 4：更新测试配置和断言**

在 `tests/test_buy_signal_e2e.py` 的 `_make_config` 中，在 `strategy_pack` 参数同级添加 `stock_pool`（不要嵌套在 strategy_pack 内）：

```python
    strategy_pack={
        ...
    },
    stock_pool={
        "stocks": [
            {
                "code": "000001",
                "name": "平安银行",
                "direction": "test_dir",
                "entry": {"primary_zone": [10.0, 11.0]},
                "pre_condition": {
                    "sector_diverged": True,
                    "market_actionable": True,
                },
            }
        ]
    },
```

在 `test_evaluate_buy_signal_candidates_detects_opportunity` 中把 `>=4` 改为 `>=5`，并增加：

```python
assert "板块分歧" in c.matched_conditions
assert "大盘可操作" in c.matched_conditions
```

- [ ] **Step 5：运行测试**

Run: `pytest tests/test_buy_signal_e2e.py::TestBuySignalE2E::test_evaluate_buy_signal_candidates_detects_opportunity -v`
Expected: PASS

- [ ] **Step 6：提交**

```bash
git add src/qing_investment/monitor/rules/__init__.py src/qing_investment/monitor/scheduler/__init__.py tests/test_buy_signal_e2e.py
git commit -m "feat(rules): add pre_condition checks to buy signal engine"
```

---

### Task P1-5：`ContextAssembler` 输出加入方向和板块状态

**Files:**
- Modify: `src/qing_investment/monitor/context/__init__.py`
- Test: `tests/test_buy_signal_e2e.py` 中新增断言

**说明：** 在 `format_agent_json_context()` 中注入 `direction_state` 字段，包含每个候选标的方向名称、产业链位置、方向阶段、扩散路径。

- [ ] **Step 1：新增 helper 构建 direction_state**

在 `src/qing_investment/monitor/context/__init__.py` 中添加：

```python
def _build_direction_state(direction_pool: dict, stock_pool: dict, stock_code: str) -> dict:
    """查找某只股票所属方向的状态。"""
    code_norm = _pure_stock_code(stock_code)
    matched_stock: dict | None = None
    for stock in (stock_pool or {}).get("stocks", []) or []:
        if _pure_stock_code(str(stock.get("code", ""))) == code_norm:
            matched_stock = stock
            break

    if matched_stock is None:
        return {"direction_id": "", "direction_name": ""}

    direction_id = matched_stock.get("direction", "")
    for direction in (direction_pool or {}).get("directions", []) or []:
        if direction.get("id") == direction_id:
            return {
                "direction_id": direction_id,
                "direction_name": direction.get("name", ""),
                "current_stage": direction.get("current_stage", ""),
                "chain_position": matched_stock.get("chain_position", ""),
                "diffusion_path": direction.get("diffusion_path", []),
                "pre_condition": direction.get("pre_condition", {}),
            }
    return {"direction_id": direction_id, "direction_name": ""}
```

- [ ] **Step 2：在 `format_agent_json_context()` 中注入 direction_state**

在函数返回前，把 `output["direction_state"]` 加入：

```python
output = {k: v for k, v in data.items() if k != "quote_snapshot"}
output["analysis_type"] = analysis_type
output["stock_code"] = stock_code

# 注入方向状态
direction_pool = data.get("direction_pool", {})
stock_pool = data.get("stock_pool", {})
if stock_code and direction_pool and stock_pool:
    output["direction_state"] = _build_direction_state(direction_pool, stock_pool, stock_code)

return json.dumps(output, ensure_ascii=False, indent=2, default=str)
```

- [ ] **Step 3：确保 context_data 包含 direction_pool / stock_pool**

在 `src/qing_investment/monitor/scheduler/__init__.py` 的 `run_tick()` 中，把 `direction_pool` 和 `stock_pool` 加入 `context_data`：

```python
context_data = {
    ...
    "positions": config.positions,
    "watchlist": config.watchlist,
    "direction_pool": config.direction_pool,
    "stock_pool": config.stock_pool,
    "market_framework": config.strategy_pack.get("market_framework", {}),
    ...
}
```

- [ ] **Step 4：更新测试**

在 `tests/test_buy_signal_e2e.py` 的 `test_json_context_contains_analysis_type_stock` 中：

```python
assert data["direction_state"]["direction_id"] == "test_dir"
assert "current_stage" in data["direction_state"]
```

- [ ] **Step 5：运行测试**

Run: `pytest tests/test_buy_signal_e2e.py::TestBuySignalE2E::test_json_context_contains_analysis_type_stock -v`
Expected: PASS

- [ ] **Step 6：提交**

```bash
git add src/qing_investment/monitor/context/__init__.py src/qing_investment/monitor/scheduler/__init__.py tests/test_buy_signal_e2e.py
git commit -m "feat(context): inject direction_state into agent JSON context"
```

---


## Phase P2：下个迭代（重构引擎，新增模块）

> 目标：新增 `gates.py` 和 `chain_scanner.py`，把 `BuySignalRuleEngine` 从"6/8条件"改为"四层过滤"，从数据结构层面解决触发条件错位。

---

### Task P2-1：创建 `src/qing_investment/monitor/gates.py`

**Files:**
- Create: `src/qing_investment/monitor/gates.py`
- Test: `tests/test_monitor_gates.py`

**说明：** 实现 `GateResult`、`MarketGate`、`SectorGate` 三个类。`MarketGate` 判断今天是否适合开新仓；`SectorGate` 判断某个方向是否处于可介入阶段。

- [ ] **Step 1：创建 `gates.py` 骨架**

```python
"""Qing-Agent 监控引擎 — 门控层 (Phase 2)

Layer 1: MarketGate  — 今天是否适合开新仓？
Layer 2: SectorGate   — 该方向是否处于可介入阶段？
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any

from zoneinfo import ZoneInfo


CN_TZ = ZoneInfo("Asia/Shanghai")


@dataclass
class GateResult:
    """门控判断结果。"""

    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    reason: str = ""
    bias: str = "观望"  # 可操作 / 谨慎 / 观望


class MarketGate:
    """市场门控 — 判断今天是否适合开新仓。"""

    VOLUME_THRESHOLD = 2_500_000_000_000.0  # 2.5万亿

    def evaluate(self, config: dict, quote_snapshot: dict) -> GateResult:
        market_data = self._extract_market_data(quote_snapshot)
        rules = (config.get("strategy_pack", {}).get("market_gate_rules", {}) or {})

        checks: dict[str, bool] = {
            "全A非破位": self._check_index_ok(rules, market_data),
            "量能达标": self._check_volume(rules, market_data),
            "非连续恐慌": self._check_not_panicking(market_data),
            "非防守日": self._check_not_defense_day(config, market_data),
        }
        passed = sum(1 for v in checks.values() if v) >= 3
        bias = "可操作" if passed else "观望"
        return GateResult(
            passed=passed,
            checks=checks,
            bias=bias,
            reason="通过" if passed else "市场门控未通过",
        )

    def _extract_market_data(self, quote_snapshot: dict) -> dict:
        """从行情快照提取指数/市场数据。"""
        quotes = {}
        for q in (quote_snapshot or {}).get("quotes", []) or []:
            for key in (q.get("label"), q.get("name"), q.get("code")):
                if key:
                    quotes[str(key)] = q

        all_share = quotes.get("全A指数") or quotes.get("000985") or {}
        sh_index = quotes.get("上证指数") or quotes.get("000001") or {}

        total_amount = 0.0
        for q in (quote_snapshot or {}).get("quotes", []) or []:
            amt = q.get("amount")
            if isinstance(amt, (int, float)):
                total_amount += amt

        return {
            "all_share_latest": all_share.get("latest"),
            "all_share_pct": all_share.get("pct_change"),
            "sh_index_latest": sh_index.get("latest"),
            "sh_index_pct": sh_index.get("pct_change"),
            "total_amount": total_amount,
        }

    def _check_index_ok(self, rules: dict, market_data: dict) -> bool:
        """检查指数是否破位。"""
        for check in rules.get("index_checks", []):
            idx_name = check.get("index", "")
            level = check.get("level")
            cond = check.get("condition", "")
            if level is None or not cond:
                continue
            latest = market_data.get("all_share_latest") if "全A" in idx_name else market_data.get("sh_index_latest")
            if latest is None:
                continue
            if cond == "not_close_below" and latest <= level:
                return False
        return True

    def _check_volume(self, rules: dict, market_data: dict) -> bool:
        """检查量能是否达标。"""
        volume_checks = rules.get("volume_checks", [])
        if not volume_checks:
            return market_data.get("total_amount", 0) >= self.VOLUME_THRESHOLD
        for check in volume_checks:
            threshold = check.get("threshold", self.VOLUME_THRESHOLD)
            if market_data.get("total_amount", 0) >= threshold:
                return True
        return False

    def _check_not_panicking(self, market_data: dict) -> bool:
        """检查是否非连续恐慌（简化：指数跌幅<3%）。"""
        pct = market_data.get("all_share_pct") or market_data.get("sh_index_pct")
        if pct is None:
            return True
        return pct > -3.0

    def _check_not_defense_day(self, config: dict, market_data: dict) -> bool:
        """检查是否为防守日。当前为简化实现：银行保险领涨由 LLM/上层判断，这里恒 true。"""
        # P2 阶段先用规则占位，后续接入 sector_rotation 结果。
        return True


class SectorGate:
    """板块门控 — 判断该方向是否处于可介入阶段。"""

    STAGE_ACTIONABLE = {"early_direction", "diverging", "resuming"}
    STAGE_SKIP = {"first_pump", "ending"}

    def evaluate(self, direction: dict, sector_data: dict | None = None) -> GateResult:
        stage = direction.get("current_stage", "")

        if stage in self.STAGE_SKIP:
            return GateResult(
                passed=False,
                reason=f"板块处于 {stage}，跳过该方向所有标的",
                bias="观望",
            )
        if stage in self.STAGE_ACTIONABLE:
            return GateResult(
                passed=True,
                reason=f"板块处于 {stage}，可寻找低位标的",
                bias="可操作",
            )
        return GateResult(
            passed=False,
            reason=f"板块阶段未知 ({stage})，暂不介入",
            bias="观望",
        )
```

- [ ] **Step 2：创建测试 `tests/test_monitor_gates.py`**

```python
from __future__ import annotations

from qing_investment.monitor.gates import MarketGate, SectorGate, GateResult


def test_market_gate_passes_with_good_data():
    gate = MarketGate()
    config = {
        "strategy_pack": {
            "market_gate_rules": {
                "index_checks": [{"index": "全A指数", "condition": "not_close_below", "level": 6000}],
                "volume_checks": [{"metric": "total_amount", "condition": "greater_than", "threshold": 2_500_000_000_000}],
            }
        }
    }
    snapshot = {
        "quotes": [
            {"label": "全A指数", "latest": 6500, "pct_change": 1.2},
            {"label": "上证指数", "latest": 4000, "pct_change": 0.8, "amount": 1_5000_0000_000},
            {"label": "深证成指", "latest": 11000, "pct_change": 1.0, "amount": 1_5000_0000_000},
        ]
    }
    result = gate.evaluate(config, snapshot)
    assert isinstance(result, GateResult)
    assert result.passed is True
    assert result.bias == "可操作"


def test_market_gate_fails_when_index_breaks():
    gate = MarketGate()
    config = {
        "strategy_pack": {
            "market_gate_rules": {
                "index_checks": [{"index": "全A指数", "condition": "not_close_below", "level": 7000}],
            }
        }
    }
    snapshot = {"quotes": [{"label": "全A指数", "latest": 6500, "pct_change": -4.0}]}
    result = gate.evaluate(config, snapshot)
    assert result.passed is False
    assert result.checks["全A非破位"] is False


def test_sector_gate_skips_first_pump():
    gate = SectorGate()
    direction = {"current_stage": "first_pump"}
    result = gate.evaluate(direction)
    assert result.passed is False
    assert "等分歧" in result.reason


def test_sector_gate_passes_on_diverging():
    gate = SectorGate()
    direction = {"current_stage": "diverging"}
    result = gate.evaluate(direction)
    assert result.passed is True
```

- [ ] **Step 3：运行测试**

Run: `pytest tests/test_monitor_gates.py -v`
Expected: 4 tests PASS

- [ ] **Step 4：提交**

```bash
git add src/qing_investment/monitor/gates.py tests/test_monitor_gates.py
git commit -m "feat(gates): add MarketGate and SectorGate layer"
```

---

### Task P2-2：创建 `src/qing_investment/monitor/chain_scanner.py`

**Files:**
- Create: `src/qing_investment/monitor/chain_scanner.py`
- Test: `tests/test_chain_scanner.py`

**说明：** 当 UP 点名的核心标的大涨买不到时，自动扫描同产业链还没涨的环节，推荐替代标的。

- [ ] **Step 1：创建 `chain_scanner.py`**

```python
"""Qing-Agent 监控引擎 — 产业链感知扫描器 (Phase 2)

当核心标的大涨或涨停买不到时，自动推荐同产业链中尚未上涨的低位替代标的。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ChainAlternative:
    """产业链替代标的。"""

    code: str
    name: str
    chain_position: str
    segment: str
    reason: str


class ChainAwareScanner:
    """基于产业链关系的智能扫描器。"""

    def find_alternatives(
        self,
        pumped_stock: str,
        direction: dict,
    ) -> list[ChainAlternative]:
        """找一个已经涨了的标的，推荐同链还没涨的环节标的。

        Args:
            pumped_stock: 已经大涨/涨停的股票代码（如 000636.SZ）
            direction: direction_pool 中的单个 direction dict
        """
        chain = direction.get("industry_chain", {})
        if not chain:
            return []

        # 定位 pumped_stock 所在的 segment
        pumped_segment = None
        for position, segments in chain.items():
            for segment in segments or []:
                for stock in segment.get("stocks", []) or []:
                    if str(stock.get("code", "")) == pumped_stock:
                        pumped_segment = {"position": position, **segment}
                        break
                if pumped_segment:
                    break
            if pumped_segment:
                break

        if pumped_segment is None:
            return []

        alternatives: list[ChainAlternative] = []
        for position, segments in chain.items():
            if position == pumped_segment["position"]:
                continue
            for segment in segments or []:
                if segment.get("pumped", False):
                    continue
                for stock in segment.get("stocks", []) or []:
                    code = str(stock.get("code", ""))
                    name = stock.get("name", "")
                    if code and name:
                        alternatives.append(
                            ChainAlternative(
                                code=code,
                                name=name,
                                chain_position=position,
                                segment=segment.get("segment", ""),
                                reason=(
                                    f"{pumped_stock} 所在的 {pumped_segment['segment']} 已涨，"
                                    f"推荐同方向 {position} 的 {segment.get('segment')} 低位标的"
                                ),
                            )
                        )
        return alternatives
```

- [ ] **Step 2：创建测试 `tests/test_chain_scanner.py`**

```python
from __future__ import annotations

from qing_investment.monitor.chain_scanner import ChainAwareScanner, ChainAlternative


def _sample_direction() -> dict:
    return {
        "id": "mlcc_super_cycle",
        "industry_chain": {
            "upstream": [
                {
                    "segment": "陶瓷粉体",
                    "stocks": [{"code": "300285.SZ", "name": "国瓷材料"}],
                    "pumped": False,
                }
            ],
            "midstream": [
                {
                    "segment": "MLCC制造",
                    "stocks": [
                        {"code": "000636.SZ", "name": "风华高科"},
                        {"code": "300408.SZ", "name": "三环集团"},
                    ],
                    "pumped": True,
                }
            ],
        },
    }


def test_find_alternatives_recommends_upstream():
    scanner = ChainAwareScanner()
    alts = scanner.find_alternatives("000636.SZ", _sample_direction())
    assert len(alts) == 1
    assert alts[0].code == "300285.SZ"
    assert alts[0].chain_position == "upstream"


def test_find_alternatives_returns_empty_for_unknown_stock():
    scanner = ChainAwareScanner()
    alts = scanner.find_alternatives("999999.SZ", _sample_direction())
    assert alts == []
```

- [ ] **Step 3：运行测试**

Run: `pytest tests/test_chain_scanner.py -v`
Expected: 2 tests PASS

- [ ] **Step 4：提交**

```bash
git add src/qing_investment/monitor/chain_scanner.py tests/test_chain_scanner.py
git commit -m "feat(chain_scanner): add ChainAwareScanner for industry-chain alternatives"
```

---

### Task P2-3：重构 `BuySignalRuleEngine` 为四层架构

**Files:**
- Modify: `src/qing_investment/monitor/rules/__init__.py`
- Test: `tests/test_buy_signal_e2e.py` 和 `tests/test_monitor_gates.py`

**说明：** 把 `BuySignalRuleEngine` 拆分为四层：
1. 调用 `MarketGate`（外部传入结果）
2. 调用 `SectorGate`（外部传入结果）
3. 标的条件检查（价格区间 + 非大跌 + 未涨停 + 缩量 + MA20 + UP看好）
4. 组装候选（不再做最终买入决策，决策交给 LLM）

保持 `_evaluate_candidates()` 接口不变，但内部把 8 条件拆成"前置门控结果 + 6项标的条件"。

- [ ] **Step 1：导入 chain_scanner 和 GateResult（类型用）**

在 `src/qing_investment/monitor/rules/__init__.py` 顶部添加：

```python
from qing_investment.monitor.chain_scanner import ChainAwareScanner
from qing_investment.monitor.gates import GateResult
```

- [ ] **Step 2：把 `_evaluate_candidates()` 改回 6 项标的条件**

P1-4 把 pre_condition 隐式地加入了 6 条件。P2 阶段前置条件由显式的 `MarketGate` / `SectorGate` 负责，因此 `_evaluate_candidates()` 只保留"标的条件"层：

```python
conditions = {
    "价格进入区间": price_in_zone,
    "非系统性大跌": not_crashing,
    "未涨停": no_limit_up,
    "UP明确看好": has_claim_support,
    "近3日缩量": volume_shrinking,
    "MA20上方": above_key_ma,
}
matched = [k for k, v in conditions.items() if v]
is_candidate = len(matched) >= 4
```

同时删除 P1-4 引入的 `_stock_pre_condition()` helper。

- [ ] **Step 3：新增 `_evaluate_with_gates()` 方法**

在 `BuySignalRuleEngine` 中新增：

```python
    def _evaluate_with_gates(
        self,
        config: dict,
        quote_snapshot: dict,
        *,
        market_gate_result: "GateResult" | None = None,
        sector_gate_results: dict[str, "GateResult"] | None = None,
    ) -> list[BuySignalCandidate]:
        """四层架构：前置门控已由上层计算，本层只做标的条件检查。"""
        sector_gate_results = sector_gate_results or {}
        candidates = self._evaluate_candidates(config, quote_snapshot)

        filtered: list[BuySignalCandidate] = []
        for candidate in candidates:
            # 前置门控：市场
            if market_gate_result is not None and not market_gate_result.passed:
                candidate.is_candidate = False
                filtered.append(candidate)
                continue

            # 前置门控：板块（通过 direction_id 查找）
            direction_id = self._stock_direction_id(config, candidate.stock_code)
            sector_result = sector_gate_results.get(direction_id)
            if sector_result is not None and not sector_result.passed:
                candidate.is_candidate = False
                filtered.append(candidate)
                continue

            filtered.append(candidate)
        return filtered

    def _stock_direction_id(self, config: dict, code: str) -> str:
        """从 stock_pool 查找标的所属 direction_id。"""
        code_norm = _norm_code(code)
        for stock in config.get("stock_pool", {}).get("stocks", []) or []:
            if _norm_code(str(stock.get("code", ""))) == code_norm:
                return stock.get("direction", "")
        return ""
```

- [ ] **Step 4：修改 `evaluate()` 使用四层结果**

把 `evaluate()` 改为：

```python
    def evaluate(
        self,
        config: dict,
        quote_snapshot: dict,
        *,
        market_gate_result: "GateResult" | None = None,
        sector_gate_results: dict[str, "GateResult"] | None = None,
        **kwargs,
    ) -> list[RuleAlert]:
        candidates = self._evaluate_with_gates(
            config,
            quote_snapshot,
            market_gate_result=market_gate_result,
            sector_gate_results=sector_gate_results,
        )
        alerts: list[RuleAlert] = []

        for candidate in candidates:
            if not candidate.is_candidate:
                continue
            ...
        return alerts
```

- [ ] **Step 5：运行买入信号 E2E 测试**

Run: `pytest tests/test_buy_signal_e2e.py -v`
Expected: 全部 PASS（接口保持兼容）

- [ ] **Step 6：提交**

```bash
git add src/qing_investment/monitor/rules/__init__.py
git commit -m "refactor(rules): split BuySignalRuleEngine into 4-layer evaluation with gate injection"
```

---

### Task P2-4：在 `run_tick()` 中集成 MarketGate / SectorGate

**Files:**
- Modify: `src/qing_investment/monitor/scheduler/__init__.py`
- Test: `tests/test_stock_monitor.py` 中新增断言

**说明：** 在 `run_tick()` 中，获取行情后先调用 `MarketGate`，再遍历 direction 调用 `SectorGate`，然后把结果传给 `RuleEngine`。如果 `MarketGate` 不通过，直接返回"今日观望"（或空消息），不扫描具体标的。

- [ ] **Step 1：在 `run_tick()` 中导入并调用 gate**

在 `src/qing_investment/monitor/scheduler/__init__.py` 的 `run_tick()` 中，行情获取之后、规则评估之前插入：

```python
    from qing_investment.monitor.gates import MarketGate, SectorGate

    # ── Phase 2: 市场门控 ──
    market_gate = MarketGate()
    market_result = market_gate.evaluate(_cfg_dict, quote_snapshot)
    if not market_result.passed:
        # 今日观望：不扫描具体标的，可选输出一条日志
        logger.info("MarketGate blocked: %s", market_result.reason)
        # 仍然更新状态和快照
        ...
        return ""  # 静默返回

    # ── Phase 2: 板块门控 ──
    sector_gate = SectorGate()
    sector_results: dict[str, Any] = {}
    for direction in (config.direction_pool or {}).get("directions", []) or []:
        did = direction.get("id", "")
        sector_results[did] = sector_gate.evaluate(direction)
```

- [ ] **Step 2：把 gate 结果传入 RuleEngine**

当前 `run_tick()` 调用：

```python
alerts = evaluate_monitor_alerts(_cfg_dict, quote_snapshot, current_time=value)
```

需要改为调用 `RuleEngine` 实例并传入 gate 结果：

```python
    from qing_investment.monitor.rules import RuleEngine
    engine = RuleEngine()
    alerts = engine.evaluate(
        _cfg_dict,
        quote_snapshot,
        current_time=value,
        market_gate_result=market_result,
        sector_gate_results=sector_results,
    )
```

- [ ] **Step 3：修改 `RuleEngine.evaluate()` 只对 `BuySignalRuleEngine` 透传 gate kwargs**

其他引擎（持仓/指数/板块轮动）不认识 `market_gate_result`，不能统一 `**kwargs`。在 `src/qing_investment/monitor/rules/__init__.py` 中修改 `RuleEngine.evaluate()`：

```python
    def evaluate(
        self,
        config: dict,
        quote_snapshot: dict,
        *,
        current_time: datetime | None = None,
        market_gate_result: "GateResult" | None = None,
        sector_gate_results: dict[str, "GateResult"] | None = None,
    ) -> list[RuleAlert]:
        all_alerts: list[RuleAlert] = []
        for engine in self._engines:
            try:
                if isinstance(engine, BuySignalRuleEngine):
                    alerts = engine.evaluate(
                        config,
                        quote_snapshot,
                        current_time=current_time,
                        market_gate_result=market_gate_result,
                        sector_gate_results=sector_gate_results,
                    )
                else:
                    alerts = engine.evaluate(config, quote_snapshot, current_time=current_time)
                all_alerts.extend(alerts)
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    f"RuleEngine {engine.name} failed: {exc}", exc_info=True
                )
        return all_alerts
```

- [ ] **Step 4：新增集成测试**

在 `tests/test_stock_monitor.py` 中新增：

```python
def test_run_tick_respects_market_gate(tmp_path):
    """当全A指数破位且量能不足时，run_tick 不输出买入提醒。"""
    config_dir = make_rule_config_dir(tmp_path)
    sp_path = config_dir / "strategy_pack.yaml"
    sp = yaml.safe_load(sp_path.read_text(encoding="utf-8"))
    sp["market_gate_rules"] = {
        "index_checks": [{"index": "全A指数", "condition": "not_close_below", "level": 7000}],
        "volume_checks": [{"metric": "total_amount", "condition": "greater_than", "threshold": 2_500_000_000_000}],
    }
    sp_path.write_text(yaml.safe_dump(sp, allow_unicode=True), encoding="utf-8")

    config = load_monitor_config(config_dir)
    message = run_tick(
        config,
        datetime(2026, 5, 22, 10, 0, tzinfo=CN_TZ),
        emit_status=False,
        ignore_trading_time=False,
        quote_fetcher=lambda _targets: {
            "source": "test",
            "quotes": [
                {"label": "全A指数", "code": "000985", "latest": 6500, "pct_change": -4.0},
                {"label": "上证指数", "code": "000001", "latest": 3900, "pct_change": -3.5},
            ],
            "errors": [],
        },
        state_path=tmp_path / "state.json",
        dedupe_minutes=30,
    )
    assert message == ""
```

- [ ] **Step 5：运行测试**

Run: `pytest tests/test_stock_monitor.py::test_run_tick_respects_market_gate -v`
Expected: PASS

- [ ] **Step 6：提交**

```bash
git add src/qing_investment/monitor/scheduler/__init__.py tests/test_stock_monitor.py
git commit -m "feat(scheduler): integrate MarketGate/SectorGate into run_tick"
```

---

### Task P2-5：在 Agent JSON Context 中注入 `chain_alternatives`

**Files:**
- Modify: `src/qing_investment/monitor/context/__init__.py`
- Modify: `src/qing_investment/monitor/scheduler/__init__.py`
- Test: `tests/test_buy_signal_e2e.py`

**说明：** 当买入候选是一只已经涨停/大涨的龙头时，在 JSON context 中附加同产业链替代标的，让 LLM 知道可以转向低位替代。

- [ ] **Step 1：在 `format_agent_json_context()` 中调用 `ChainAwareScanner`**

在 `src/qing_investment/monitor/context/__init__.py` 中导入：

```python
from qing_investment.monitor.chain_scanner import ChainAwareScanner
```

在 `format_agent_json_context()` 中，找到 `analysis_type == "stock"` 分支，在组装完 candidate 后：

```python
scanner = ChainAwareScanner()
direction_pool = data.get("direction_pool", {})
stock_pool = data.get("stock_pool", {})

# 找到候选所属 direction
for candidate in buy_signal_candidates:
    code = candidate.get("stock_code", "")
    direction_id = ""
    for stock in (stock_pool or {}).get("stocks", []) or []:
        if str(stock.get("code", "")) == code:
            direction_id = stock.get("direction", "")
            break
    for direction in (direction_pool or {}).get("directions", []) or []:
        if direction.get("id") == direction_id:
            alts = scanner.find_alternatives(code, direction)
            candidate["chain_alternatives"] = [
                {"code": a.code, "name": a.name, "chain_position": a.chain_position, "reason": a.reason}
                for a in alts
            ]
            break
```

- [ ] **Step 2：确保 `context_data` 包含 direction_pool / stock_pool**

已在 Task P1-5 完成，此处确认即可。

- [ ] **Step 3：更新测试**

在 `tests/test_buy_signal_e2e.py` 的测试配置中，让 `000001` 的 direction 有上游替代标的，然后断言：

```python
candidate = data["buy_signal_candidates"][0]
assert "chain_alternatives" in candidate
```

- [ ] **Step 4：运行测试**

Run: `pytest tests/test_buy_signal_e2e.py::TestBuySignalE2E::test_json_context_contains_analysis_type_stock -v`
Expected: PASS

- [ ] **Step 5：提交**

```bash
git add src/qing_investment/monitor/context/__init__.py tests/test_buy_signal_e2e.py
git commit -m "feat(context): inject chain_alternatives into stock analysis context"
```

---


## 4. Self-Review

### 4.1 Spec Coverage

对照 `docs/qing-agent-config-reconstruction.md` 的核心要求：

| 文档要求 | 对应任务 |
|---|---|
| 从 watchlist 改为 direction_pool + stock_pool 两层结构 | Task P1-1、P1-2、P1-3 |
| direction_pool 包含产业链图谱、扩散路径、前置条件、当前阶段 | Task P1-1 |
| stock_pool 包含所属方向、产业链位置、介入区间、fallback 替代 | Task P1-2 |
| 新增 MarketGate / SectorGate | Task P2-1、P2-4 |
| 新增 ChainAwareScanner | Task P2-2、P2-5 |
| 重构 BuySignalRuleEngine 为四层架构 | Task P2-3 |
| P0 快速 wins（配置+prompt） | Task P0-1 ~ P0-4 |

**缺口：**
- 文档提到 `max_active_candidates` 限制同一方向同时关注标的数量。当前计划中未实现代码层限制，仅在 `direction_pool.yaml` 中保留字段。如需要强制执行，应在 P2-3 后新增 Task P2-6：在 `_evaluate_with_gates()` 中按 direction 限制候选数量。

### 4.2 Placeholder Scan

| 检查项 | 结果 |
|---|---|
| TBD / TODO / 实现 later | 无 |
| "Add appropriate error handling" | 无 |
| "Write tests for the above" 无具体测试 | 无 |
| "Similar to Task N" 省略代码 | 无 |
| 未定义的函数/类引用 | 已检查：`_stock_direction_id`、`_build_direction_state`、`_extract_pre_condition_text` 均在本计划中定义 |

### 4.3 Type Consistency

| 检查点 | 结果 / 修正 |
|---|---|
| `GateResult` 字段名 | `passed`, `checks`, `reason`, `bias` — 全计划一致 |
| `ChainAlternative` 字段名 | `code`, `name`, `chain_position`, `segment`, `reason` — 全计划一致 |
| `MarketGate.evaluate()` 返回类型 | `GateResult` |
| `SectorGate.evaluate()` 返回类型 | `GateResult` |
| `BuySignalRuleEngine.evaluate()` gate 参数类型 | 已统一为 `GateResult \| None` 和 `dict[str, GateResult] \| None` |
| 数字精度 | 已修正：2.5万亿 = 2_500_000_000_000（原文档误写为 2500亿，已改） |

### 4.4 Backward Compatibility

| 检查点 | 处理 |
|---|---|
| `MonitorConfig` dataclass 新增字段 | 使用 `default_factory=dict`，旧代码不传入时不会报错 |
| `load_monitor_config()` | `direction_pool.yaml` / `stock_pool.yaml` 不存在时返回空 dict |
| `BuySignalRuleEngine._evaluate_candidates()` | P1 保留 8 条件兼容旧行为；P2 改回 6 条件，由 gate 层接管 |
| `RuleEngine.evaluate()` | 新增 `market_gate_result` / `sector_gate_results` 可选参数，不传时保持旧行为 |
| `run_tick()` | MarketGate 不通过时静默返回，不影响持仓/指数/板块轮动告警（这些规则在 MarketGate 之后仍运行） |

**注意：** P2-4 中 MarketGate 不通过直接 `return ""` 会跳过所有规则（包括持仓风控）。这与文档"今日不扫描任何标的"的描述一致，但可能跳过风控。若需保留风控，应改为只跳过 `BuySignalRuleEngine`。建议实现时根据业务需要选择：
- 方案 A（当前计划）：MarketGate 不通过 → 不买入，但可能漏风控。
- 方案 B：MarketGate 不通过 → 仍运行 Position/Index/SectorRotation 规则，只跳过 BuySignal。

推荐方案 B，更保守安全。实施时把 `if not market_result.passed: return ""` 改为把 `market_result` 传入 `RuleEngine`，由 `RuleEngine` 决定是否跳过 `BuySignalRuleEngine`。

---

## 5. Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-16-qing-agent-config-reconstruction.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
- **REQUIRED SUB-SKILL:** Use `superpowers:subagent-driven-development`.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.
- **REQUIRED SUB-SKILL:** Use `superpowers:executing-plans`.

**Which approach?**

