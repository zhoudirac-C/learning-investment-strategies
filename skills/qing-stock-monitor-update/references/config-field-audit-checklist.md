# Config 字段补全核对清单

当用户要求"核对改动是否与文档一致"或"补全Config层字段"时，使用此清单逐项核对。

## 核对范围

必须覆盖三个层面：
1. **Prompt/Agent 层** — system prompt、cron prompt、trader_mindset
2. **代码/工具层** — daily_state、context_builder、hot_score、claims_to_entry、stock_monitor
3. **Config/YAML 层** — watchlist.yaml、strategy_pack.yaml、positions.yaml

## 文档设计 vs 实现核对表

### Prompt 层

| 设计项 | 检查方法 | 文件 |
|--------|---------|------|
| trader_mindset 8条人格 | `grep -E "赔率\|产业逻辑\|阶段\|优先级\|不追高\|做T\|点位\|认错"` | `src/.../prompts/system/trader_mindset.txt` |
| 推理模式激活 | `grep -E "mainline\|upstream\|赔率\|复盘"` | `src/.../prompts/system/market_analyst.txt` |
| 表达风格5条 | `grep -E "先给结论\|敢于预判\|可执行"` | `src/.../prompts/system/market_analyst.txt` |
| 9个差异化cron | `ls src/.../prompts/system/cron_*.txt` | 应输出9个文件 |

### 代码层

| 设计项 | 检查方法 | 文件 |
|--------|---------|------|
| daily_state 5字段 | `grep -E "market_stage\|direction_priority\|position_stance\|active_opportunities\|intraday_narrative"` | `src/.../tools/daily_state.py` |
| hot_score 8维度 | `grep -E "claim_freshness\|up_mention\|priority\|technical\|sector_momentum\|linked_claims\|entry_zone\|position_status"` | `src/.../tools/hot_score.py` |
| claims_to_entry 回写 | `grep -E "update_watchlist_linked_claims\|save_watchlist"` | `src/.../tools/claims_to_entry.py` |
| stock_monitor add_zone | `grep "add_zone"` | `src/.../stock_monitor.py` |

### Config 层（最关键，最易遗漏）

| 设计项 | 检查方法 | 文件 |
|--------|---------|------|
| watchlist: lifecycle | `grep "lifecycle"` | `config/stock_monitor/watchlist.yaml` |
| watchlist: hot_score | `grep "hot_score"` | `config/stock_monitor/watchlist.yaml` |
| watchlist: linked_claims | `grep "linked_claims"` | `config/stock_monitor/watchlist.yaml` |
| watchlist: opportunity_patterns | `grep "opportunity_patterns"` | `config/stock_monitor/watchlist.yaml` |
| strategy_pack: linked_daily_state | `grep "linked_daily_state"` | `config/stock_monitor/strategy_pack.yaml` |
| strategy_pack: strategy_meta | `grep "strategy_meta"` | `config/stock_monitor/strategy_pack.yaml` |
| strategy_pack: entry_points_schema | `grep "entry_points_schema"` | `config/stock_monitor/strategy_pack.yaml` |
| positions: entry_decision | `grep "entry_decision"` | `config/stock_monitor/positions.yaml` |
| positions: add_zone | `grep "add_zone"` | `config/stock_monitor/positions.yaml` |
| positions: trade_log | `grep "trade_log"` | `config/stock_monitor/positions.yaml` |
| positions: portfolio_stats | `grep "portfolio_stats"` | `config/stock_monitor/positions.yaml` |

## 自动化核对脚本

**专用校验脚本**（推荐使用）：
```bash
python scripts/validate_watchlist.py
# 输出分级报告：❌ 致命 / ⚠️ 警告 / ✅ 通过
```

**旧版手动核对脚本**（供参考）：

```python
# 保存为 scripts/verify_config_fields.py
import yaml
import sys

def check_watchlist(path="config/stock_monitor/watchlist.yaml"):
    with open(path) as f:
        data = yaml.safe_load(f)
    
    fields = ["lifecycle", "hot_score", "linked_claims", "opportunity_patterns"]
    total = sum(len(t.get("stocks", [])) for t in data.get("themes", []))
    
    # 抽样检查前10只
    checked = 0
    for theme in data.get("themes", [])[:3]:
        for stock in theme.get("stocks", [])[:5]:
            missing = [f for f in fields if f not in stock]
            if missing:
                print(f"❌ {stock['code']} 缺失: {missing}")
            checked += 1
    
    print(f"检查 {checked}/{total} 只stock，字段: {fields}")

def check_strategy_pack(path="config/stock_monitor/strategy_pack.yaml"):
    with open(path) as f:
        data = yaml.safe_load(f)
    
    fields = ["linked_daily_state", "strategy_meta", "entry_points_schema"]
    for f in fields:
        status = "✅" if f in data else "❌"
        print(f"{status} strategy_pack.{f}")

def check_positions(path="config/stock_monitor/positions.yaml"):
    with open(path) as f:
        data = yaml.safe_load(f)
    
    fields = ["entry_decision", "add_zone", "trade_log", "portfolio_stats"]
    
    # 检查 portfolio_stats
    if "portfolio_stats" in data:
        print("✅ positions.portfolio_stats")
    else:
        print("❌ positions.portfolio_stats")
    
    # 检查每只持仓
    for acc in data.get("accounts", []):
        for pos in acc.get("positions", []):
            missing = [f for f in fields if f not in pos]
            if missing:
                print(f"❌ {pos['code']} 缺失: {missing}")

if __name__ == "__main__":
    check_watchlist()
    check_strategy_pack()
    check_positions()
```

## 常见遗漏模式

1. **代码实现了但YAML没写**：hot_score.py 有计算逻辑，但 watchlist.yaml 中没有 `hot_score` 字段 → 计算结果无处存放
2. **stock_monitor 能读但YAML没配**：add_zone 解析逻辑在代码里，但 positions.yaml 中没有 `add_zone` 字段 → 永远不会触发
3. **prompt 写了但表达风格缺失**：market_analyst.txt 有推理框架，但缺少「先给结论」「敢于预判」等风格约束 → LLM 输出仍然保守模糊
4. **claims_to_entry 提取了但没回写**：提取了 entry 建议，但没有 `update_watchlist_linked_claims` → watchlist 的 `linked_claims` 永远为空

## 跨字段一致性检查（2026-06-11 更新）

以上 1-4 是「字段是否存在」的问题，但还有两种更隐蔽的。

### 类型 A：读者和写着用不同字段表达同一含义（已修复）

**反面案例**：poll 读 `buy_setup` 提取价格区间，但 watchlist 写入者写的是 `entry_zone.price_range`。

**修复（2026-06-11）**：`stock_monitor.py:407-409` 从 `stock.get("buy_setup")` 改为 `stock.get("entry_zone", {}).get("price_range")`。

### 类型 B：P3-观察标的的语义 price_range（已清理）

**反面案例**：和远气体(002971) P3-观察，`price_range: "48.0 ~ 50.0（仅供参考，不建议主动介入）"`。注释说「不建议介入」，但 parse_price_zone 只认数字，提取出 (48.0, 50.0)，poll 会把它当作有价格区间的候选——注释和代码逻辑矛盾。

**规则**：P3-观察标的的 `price_range` 必须为 `null`。禁止写数字区间（哪怕带说明文字），因为 poll 只认数字。

**验证命令**：
```bash
python scripts/validate_watchlist.py
# P3 标的带数字 price_range 会显示 ⚠️ 警告
```

### 检查清单（2026-06-11 更新后）

| 检查项 | 读者用的字段 | 写着用的字段 | 验证方法 |
|--------|-------------|-------------|---------|
| poll watchlist 回退路径 | `stock["entry_zone"]["price_range"]` | `stock["entry_zone"]["price_range"]` | ✅ 已修复一致 |
| poll entry_points 路径 | `entry["entry_zone"]` | `strategy_pack.entry_points[].entry_zone` | ✅ 一致 |
| poll positions 路径 | `pos["add_zone"]` | `positions.positions[].add_zone` | ✅ 一致 |
| hot_score 读取路径 | `stock["priority"]` | `watchlist.stocks[].priority` | ✅ 一致 |

### 判定规则

- 当字段同时存在于两个位置时，**以代码中代码的读取路径为准**，不以后续人工约定为准
- 修复方案：**改读者不改写着**（改读者影响 1 个函数的几行，改写着需修改全部已有数据）
- 新增字段时必须同时确定读者和写者的使用路径
- **P3-观察标的的 price_range 必须为 null**——任何数字区间都会被 poll 误判为候选

## 修复优先级

当发现不匹配时，按以下优先级修复：

1. **P0 — YAML字段缺失**：直接影响 stock_monitor 和 Agent 运行
2. **P1 — Prompt风格缺失**：影响 LLM 输出质量
3. **P2 — 代码功能缺失**：如 hot_score 维度不完整

## 历史案例

**2026-06-08 核对结果**：
- Prompt/Agent 层: ~85% ✅
- 代码/工具层: ~90% ✅  
- Config/YAML 层: ~10% ❌（几乎全部字段缺失）

**根因**：开发时 focus 在代码和 prompt，忽略了 Config 文件的实际结构更新。文档 v2.0 设计了字段，但 YAML 文件仍保持旧结构。

**修复方案**：
- Python 脚本批量为 164 只 stock 添加 `lifecycle`/`hot_score`/`linked_claims`/`opportunity_patterns`
- 为 positions.yaml 的持仓添加 `entry_decision`/`add_zone`/`trade_log`
- 为 strategy_pack.yaml 添加 `linked_daily_state`/`strategy_meta`/`entry_points_schema`
- 补充 market_analyst.txt 的 UP 表达风格约束
- 补充 hot_score.py 的 `entry_zone_proximity` + `position_status` 维度
- 补充 claims_to_entry.py 的 `update_watchlist_linked_claims` + `save_watchlist`
