---
name: qing-stock-monitor-update
description: |
  配置一致性驱动的看盘系统更新。基于 UP 最新观点 + config 交叉检查，输出差异报告后执行修改。
  Use when: "更新观察池"、"更新持仓"、"更新策略"、"检查配置"
---

# qing-stock-monitor-update

## 设计原则

**每次更新必须交叉检查全部 config**。不按文件分步，而是一个 checklist 覆盖 watchlist + strategy_pack + positions + cron 的一致性。

## 触发条件

- "更新观察池" / "更新方向" / "更新策略"
- "更新持仓" / "清仓" / "减仓"
- "检查配置" / "config review"
- "加标的" / "新增方向"

## 必读参考

| 场景 | 文件 |
|------|------|
| MCP 驱动方向更新 | `references/mcp-powered-directional-update.md` |
| 数据源降级 | `references/data-source-fallback-chain.md` |
| Claims 一致性校验 | `references/claims-consistency-check.md` |
| Entry points 生成 | `references/entry-points-generation.md` |
| 配置健康检查 | `references/config-health-check.md` |
| Agent-UP 矛盾处理 | 本 SKILL §陷阱 |
| Cron pipeline 架构 | `references/cron-pipeline-architecture.md` |

---

## 工作流程（4 步）

### Step 1: 门禁检查

```bash
cd ~/learning-investment-strategies
python3 scripts/check_config_consistency.py
```

输出 **8 维差异报告**（P0/P1/P2 分级）：
1. strategy_pack 过期（日期、点位、方向词）
2. watchlist 缺口（claims 提到的标的未在 watchlist）
3. watchlist ↔ strategy_pack 对齐
4. positions 缺失（无 risk_zone 等）
5. invalidation 点位过期
6. cron focus 过期
7. claims 引用完整性
8. watchlist 字段校验（code 格式/priority/lifecycle/linked_claims/sentiment）

```bash
# JSON 输出供 LLM 消费
python3 scripts/check_config_consistency.py --json
```

### Step 2: 收集变化源

**变化源检测——找到「什么变了」：**

| 来源 | 方法 | 产出 |
|------|------|------|
| UP 最新 claims | `mcp_neo4j_get_recent_claims(days=2)` | 新观点列表 |
| B站动态 | `sources/original/bilibili/` → unprocessed 时转录 raw | raw 文件 |
| 用户操作 | 用户明确说的清仓/建仓/减仓 | 持仓变动 |
| 市场行情 | 腾讯 API 拉全A + 关键标的（仅 full update） | 实时价格 |

### Step 3: 差异报告 → 用户确认

合并 Step 1 门禁输出 + Step 2 变化源 → **一份统一差异报告**：

```
## Config 一致性报告

### 🔴 P0（必须修复）
- strategy_pack focus 含过期方向"燃气轮机" → 更新为当前主线
- positions 万泽 missing risk_zone → 补配

### 🟡 P1（建议修复）
- watchlist 缺 立昂微(605358)：claim-005-b 提及硅片方向
- invalidation 含数字点位 4000，已过期

### 🟢 P2（可选）
- sector_groups 有 12 个组不在 watchlist
```

**用户确认后执行修改。** 不要直接改 config——先展示报告。

### Step 4: 执行修改 + 验证

用户确认后：
1. 逐项修改（优先 P0 → P1 → P2）
2. 运行 `python3 scripts/validate_config.py` 验证
3. 运行 `python3 scripts/check_config_consistency.py --json` 确认 P0 清零
4. 更新 strategy_pack.updated_at
5. Git 提交

---

## 陷阱

### 陷阱 1: 只更新一个文件忘记交叉检查

**反面案例（2026-06-10）**：加了硅片标的到 watchlist，但没检查 strategy_pack.sector_groups 是否覆盖 → 板块轮动计算遗漏硅片方向。

**正确做法**：Step 3 的差异报告自动检测这个。

### 陷阱 2: Qing-Agent 离线导致分析退化

**反面案例（2026-06-10）**：Agent 挂了整整一个上午，全部 cron 走 LLM fallback，输出过期方向词。

**正确做法**：Step 1 前置健康检查：
```bash
curl -s http://127.0.0.1:8000/health || echo "需要重启 Qing-Agent"
```

### 陷阱 3: Agent vs UP 矛盾

**反面案例（2026-06-10）**：万泽跌停，Qing-Agent 建议清仓，UP 10:04 说"直接砍不合适"。

**处理流程**：
1. 时序判断：UP 观点在 Agent 分析之后 → 以 UP 为准
2. 归类：信息不对称（Agent 缺 claim-007）→ 补 claims → 重新分析
3. 写入 strategy_pack 时标注来源 claim ID

### 陷阱 4: invalidation 点位过期

数字点位（如"收盘跌破4000"）和当前指数偏离 >3% 时自动检测。Step 1 门禁覆盖。

### 陷阱 5: Cron prompt 空改

改了 cron prompt 但没验证 → 下次 cron 执行才发现不生效。

**正确做法**：Step 4 验证时 dry-run：
```bash
python3 scripts/hermes_stock_monitor_agent.py
# 检查输出是否含新框架关键词
```

---

## 关键纪律

- **先报告后修改**：差异报告必须经用户确认
- **全链路检查**：不能只看 watchlist 不看 strategy_pack
- **claims 优先**：UP 直接点名的方向/标的必须补入 watchlist
- **Agent 健康优先**：Qing-Agent 离线时先重启再分析
- **验证必须跑**：`validate_config.py` + `check_config_consistency.py --json`
- **主板-only**：用户只能交易 sh6xxxxx / sz0xxxxx。非主板标的标记 `tradable: false`
- **不删旧数据**：旧 theme 降级为 monitor_only，不删除
- **不编造价格**：数据源降级时诚实说明

---

## 验证清单

- [ ] `check_config_consistency.py` P0 清零
- [ ] `validate_config.py` 退出码 ≤1
- [ ] Qing-Agent health check 200
- [ ] strategy_pack.updated_at 已更新
- [ ] cron prompt 已验证（dry-run）
- [ ] Git 已提交
