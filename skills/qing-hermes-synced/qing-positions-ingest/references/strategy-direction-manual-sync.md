# strategy_pack.yaml / direction_pool.yaml 手动同步工作流

> 会话来源：2026-08-11（用户问"strategy_pack.yaml 和 direction_pool.yaml 怎么更新？"→ 完整执行 8/9-8/11 同步）。
> 与 `post-review-config-sync.md`（17:05 cron 自动同步）互补：本文件是**手动**同步（早盘/盘中基于 UP 最新观点）。
> 归属说明：qing-stock-monitor-update 与 qing-fupan-morning-usage 均为只读（external/手动作者），此参考暂存于本 skill（同为 config 更新领域）。

## 两个文件的角色

| 文件 | 角色 | 消费方 | 典型更新频率 |
|---|---|---|---|
| `strategy_pack.yaml` | 全局策略包：市场框架/门禁/方向优先级/板块轮动/指数/仓位/时段 | 🔴 poll（index_rules/intraday_schedule/sector_rotation）+ Agent prompt | 每次复盘/早盘 |
| `direction_pool.yaml` | 方向池：每个方向的产业链结构/扩散路径/介入前提 | Agent（MCP 检索 + context 注入） | 有新方向/方向阶段变化时 |

**铁律**：只改系统消费的字段（见 qing-stock-monitor-update 的 `references/config-field-consumer-map.md`）。加字段前 `grep -rn 字段名 src/ scripts/` 确认有代码读它。

## strategy_pack.yaml 更新模式（8/11 实测）

| 字段 | 动作 | 细节 |
|---|---|---|
| `market_framework.current_stage` | **顶部追加**最新定调段落 | 保留全部历史段落（追加不覆盖）；每段以"8月11日早盘（今晨）定调："开头 |
| `market_framework.up_quote` | **全量替换**为最新 UP 原话 | 简短引述+带日期 |
| `market_framework.core_question` | 全量替换为当日验证清单 | ①量能②科技③情形AB④新题材⑤国产链信号...编号列出 |
| `market_framework.key_assumptions` | 顶部追加 `【框架升级 8/11 早盘】` 条目 | 压缩当天 claims 核心，日期为锚 |
| `direction_priority` | **顶部插入**最新方向（不删旧的） | 每条含 direction/intensity/trigger/source_claim/entry_range/chain_note |
| `market_gate_rules.volume_checks` | 阈值变化才改 | 8/11 升级量能三档：2.5万亿确认线 + 3万亿压力位(less_than) + 3.5万亿风险区 |
| `updated_at` + `source_claims` | 更新日期 + 顶部插入新 claim 文件 | source_claims 顶部加最新 yaml |

## direction_pool.yaml 更新模式（8/11 实测）

| 动作 | 细节 |
|---|---|
| **头部时间线** | 追加 `# ⚠️ 日期 类型：内容` 注释行，**最新在最上方**（updated_at 下方第一条），保留旧行 |
| **新增方向** | 文件尾部追加完整条目：id/name/current_stage/industry_chain(上中下游各带 stocks[]+pumped+note)/diffusion_path/pre_condition(market+sector+timing)/note |
| **已有方向** | 只改 `pre_condition.market`（最新市场定调）+ note 追加日期段落；不动 industry_chain 除非标的增减 |
| **股票代码** | 新增标的必须用东财 searchapi 核实，**绝不凭记忆写**（见坑位2） |

## ⚠️ 坑位（本次真实踩过）

### 坑 1：patch 改错方向（最危险）
**症状**：`direction_pool.yaml` 多个方向（ccL_resin_upstream / pcb_ai_chain / electronic_gas_wf6）的 `pre_condition.market` 都是同一句旧文本"7/14 A股缩量深V企稳..."。用该文本做 old_string patch → 匹配到了**第一个**出现的位置（ccL_resin_upstream），而非目标 pcb_ai_chain。
**修复**：patch 前先 `awk '/- id: pcb_ai_chain/,/^  note:/'` 定位目标方向的精确行号；patch 的 old_string 必须包含方向独有的上下文（如 id 行或该方向特有的 diffusion_path）；**改完必须回读验证**（python yaml 加载 + 打印目标方向的 pre_condition.market 确认改动落在正确位置）。出错时先把误改的方向恢复原样再改目标。

### 坑 2：凭记忆写错股票代码
**症状**：新增 switch_800g_domestic 方向时写 `600732.SH 爱旭股份` 作为交换机标的——600732 实际是光伏电池（爱旭股份），与交换机无关。
**教训**：**任何新增/修改的标的代码必须用东财 searchapi 核实全名与代码一致**（`curl searchapi.eastmoney.com/api/suggest/get?input=<名称>&type=14`），核实名称含义（光伏/交换机/半导体...）是否匹配该 segment。修复：`600732` → `000938 紫光股份`/`603118 共进股份`。

### 坑 3：两个 config 的 updated_at 格式不同
- `strategy_pack.yaml`：`'2026-08-11T09:30'`（ISO 带时间）
- `direction_pool.yaml`：`'2026-08-11'`（纯日期）
- 别统一格式，各自保持原风格。

## 验证链（改完必跑）

```bash
python3 -c "import yaml; yaml.safe_load(open('config/stock_monitor/strategy_pack.yaml')); yaml.safe_load(open('config/stock_monitor/direction_pool.yaml'))"
python3 scripts/validate_config.py   # 注意：today_snapshot 缺失是预存 warning（17:05 cron 自动写），非本次引入
git diff --stat config/stock_monitor/   # 确认改动范围仅两个 config + cron 自动产物
```

**预存 warning 区分**：`watchlist 20 主题未在 sector_groups` 和 `缺少 today_snapshot` 均为历史遗留，不要试图在手动同步时"顺手修复"——today_snapshot 由 sync_config_from_review.py 自动维护，sector_groups 是独立架构决策。

## 提交惯例

- 单 commit：`config: strategy_pack + direction_pool 同步 8/9-8/11 最新 UP 观点`
- 若 `daily_review_summary.json` 等 cron 产物同时变动，一并 add（历史惯例已入库）
- push 前 `git pull --rebase origin master`（远程常领先）
