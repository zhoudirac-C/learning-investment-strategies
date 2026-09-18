# 异动驱动产业链发现（引擎 B）设计

日期：2026-09-18
状态：待评审
关联：docs/tasks/m0-chain-industry-tracking.md（Phase 3 引擎 A）、`src/investment_engine/chain_tracker/`

## 1. 背景与问题

引擎 A（研报驱动发现）上线一个月，产出 5 条提案（油运、散热、财富管理、PVA、钒液流），
对照 9 月真实炒作主线（光通信/PCB/国产芯片/机器人/军工/液冷，见连板网题材矩阵），
**命中率为零**。根因诊断（有数据支撑）：

1. **信号层级错误**：券商深度报告是题材确认层（第 4 层）信号，不是发现层信号。
   5 条提案全部滞后于行情 3 天~1 年不等。
2. **资金行为数据被浪费**：板块异动触发器（`sector.py`）已在跑，但产出的是
   "存储芯片板块涨 3.4%（领涨 XX +20.0%）"这种裸文本行，喂给研报式
   prompt（`discovery.py` `_USER_TMPL` 要求 driver/thesis/传导路径），LLM
   无米下锅——discovery_items.db 实证：sector 来源条目 13 条 `no_proposal`、
   2 条 `matched_existing`，**提案产出为 0**。
3. **阶段判定靠报告语气**：散热材料在龙头 PE 330 倍时被标"阶段1-启动期"。

结论：产业链图谱本身是炒作确认后找补涨的正确工具，但发现触发器必须前移到
资金行为层（涨停/首板/板块资金流）。

## 2. 设计原则

- **顺序反转**：资金行为触发 → LLM 拆链。不再让 LLM 从新闻里"判断有没有
  产业链"，而是"这个已确认异动的题材，链怎么拆"。
- **阶段判定数据化**：首板/连板/炸板/涨停家数序列定阶段，LLM 只润色不拍脑袋。
- **复用不重建**：产出落同一个 `proposals_pending.json`，走同一套
  confirm/reject 人工确认流和跟踪引擎；新增代码收敛在 3 个文件。
- **规则层零 LLM**：信号聚合纯函数、可单测；LLM 只在触发后调用一次/题材。

## 3. 数据源（全部本地已有，零新增依赖）

| 数据 | 路径 | 内容 | 落盘时间 | 历史深度 |
|---|---|---|---|---|
| 涨停池 | `infra/data/limit_pool/{yyyymmdd}.json` | zt_count/zb_count/max_lbc、连板梯队 ladder、zt_items（code/name/pct/lbc 连板数/fbt 首封时间/fund 封单资金/zbc 炸板次数/hybk 行业板块） | 盘后 | 40 天（0727 起） |
| 板块资金流 | `infra/data/fund_flow/{yyyymmdd}.json` | 387 概念板块涨跌幅+领涨股（`sector.py` 已在用） | 15:40 | 25 天 |
| 题材情绪 | `infra/data/kpl/emotion/` | 情绪温度（可选输入） | 盘后 | 待核 |

龙虎榜席位（kpl/lhb）本账号拿不到明细（实测为空），不作为输入。

## 4. 链路设计

### 4.1 信号聚合（新模块 `chain_tracker/momentum.py`，纯函数）

每个发现 tick（15:40 后）读当日两个文件，产出**题材热度卡**列表：

```
{
  "theme": "通信设备",                # hybk 行业板块 / fund_flow 概念板块名
  "zt_count": 6,                     # 板块内涨停家数
  "first_board_count": 4,            # 首板家数（lbc=1）
  "max_lbc": 3,                      # 板块内最高连板
  "seal_fund": 8.2e8,                # 封单资金合计
  "earliest_seal": "09:35",          # 最早首封（资金攻击迫切度）
  "leaders": ["剑桥科技", ...],      # 高度板/领涨股
  "sector_pct": 4.3,                 # fund_flow 概念涨幅（交叉验证，可空）
  "streak_days": 2,                  # 连续上榜天数（需读昨日文件）
}
```

聚合键：limit_pool 的 `hybk` 为主，与 fund_flow 概念名做模糊互认
（名称包含/别名表，首期只做精确+包含匹配，不为难自己）。

### 4.2 触发规则（打分制，阈值可配）

满足任一即成为候选题材：

- 板块涨停 ≥ 3 家（新题材启动的典型形态，对照 9/07 机器人 17 家、9/16 通信 6 家）
- 出现 ≥ 2 板的连板梯队且板块涨停 ≥ 2 家（持续性确认）
- fund_flow 涨幅 ≥ 3% 且对应板块涨停 ≥ 2 家（两源共振）

过滤（复用现有机制）：

- `matching.build_chain_index` 匹配到已有 chain.yaml → 转证据通道（现状逻辑不变）
- 匹配到 pending 提议 → 证据累积（现状逻辑不变）
- 纯情绪题材（次新股/ST/外贸受益等无可拆链条的）打 `sentiment_only` 标记，
  交 LLM 裁决但预期驳回（见 4.3 纪律）

### 4.3 阶段初判（规则，替代 LLM 拍脑袋）

| 阶段 | 规则 |
|---|---|
| 阶段1-启动期 | 首板占比 > 70% 且 streak_days ≤ 2 |
| 阶段2-加速期 | max_lbc ≥ 3 或涨停家数环比增 ≥ 50% |
| 阶段3-分歧期 | 涨停家数环比降 + zb_count（炸板）占比 > 30% |
| 阶段4-见顶期 | 高度板断板 + 板块涨停 ≤ 1 家 |

初判结果写入 proposal 的 `current_stage`，并附 `stage_evidence`（命中的规则值），
人工 confirm 时可核验。LLM 不再自由发挥阶段标签。

### 4.4 LLM 拆链（新 prompt 模板，触发后每题材一次调用）

输入不再是裸板块行，而是：

1. 题材热度卡（4.1 的结构化 JSON）
2. 板块内涨停个股明细（code/name/lbc/封单资金/首封时间）
3. 当日 `collect_items` 已拉取的研报/公告标题中，按题材关键词预筛的 ≤10 条
   （研报从"触发源"降级为"拆链素材"，位置归位）

任务：拆上中下游图谱 + 标注各环节受益层级（核心/间接/联动，对应炒作
传导顺序）+ 各环节 A 股标的（优先从涨停明细里取，保证是资金认的票）。

输出 schema 复用现有 proposal 结构，新增字段 `source_type: "momentum"`
（与研报驱动的 `"report"` 区分，便于事后分层统计命中率）。

纪律沿用：无可拆链条/纯单票事件 → 输出空；单来源 confidence ≤ 中。

### 4.5 编排（`discovery_core.py` 新分支）

```
run_discovery() 现有流程不变
  └─ 新增：sector_items 不再混入研报批次走 _USER_TMPL
     └─ 改走 run_momentum_branch():
          momentum.py 聚合 → 触发规则 → 已有链/pending 过滤
          → 幸存题材各调一次 LLM 拆链 → filter_duplicate_proposals
          → upsert_pending + append_daily_audit（同一 pending 池）
```

三条硬规则继承：info_id 去重（`sector:{date}:momentum:{theme}`）、空批次静默、
LLM 失败不落账。

## 5. qing agent 流程接入

- **cron 零改动**：引擎 B 作为 `chain_discovery.py` 内部分支，复用现有
  `~/.hermes/scripts/qing_chain_discovery.py` 30 分钟 tick。fund_flow 15:40
  落盘后首个 tick 生效（日级触发，与现状一致）。
- **LLM 配置零改动**：`default_llm_call` 已走 `resolve_runtime_provider()`。
- **人工确认零改动**：`list/confirm/reject` 子命令、跟踪引擎自动纳入，全部复用。
  `list` 输出加一列来源标记（momentum/report）。
- **新增 CLI**：`--source momentum|report|all`（默认 all），便于分层调试与回放。

## 6. 验证计划（先回放，再上线）

1. 回放 2026-09-01 ~ 09-18（limit_pool 数据齐）：
   - 对照连板网题材矩阵，引擎 B 是否能在 09-07 当晚提出"机器人产业链"、
     09-15/16 提出"PCB/国产芯片/存储"、09-02 提出"军工"。
   - 统计：主线命中率、相对引擎 A 的提前天数。
2. 引擎 A 已产出的 5 条提案做反向核验：油运（09-09 涨停潮先于 09-13 提案）、
   散热材料若由异动层触发可提前多久。
3. 成功标准：9 月 ≥ 4 条主线当晚出提案；单题材 LLM 调用 ≤ 1 次；误报
   （纯情绪题材出提案）≤ 20%。
4. 回放通过前不改 cron 行为（可用 `--dry-run --source momentum` 并行影子跑）。

### 实际回放结果（2026-09-18 执行）

规则层（14 个交易日，`--no-llm`）：光通信/PCB（元件）/芯片（半导体）/机器人
（汽车零部件口径）/农业/军工全部当日触发，与连板网题材矩阵一致。

LLM 层（dry-run 实盘模型）：

| 日期 | 触发 | LLM 调用 | 提案 | 关键结果 |
|---|---|---|---|---|
| 09-07 | 15 | 11 | 6 | ✅ 汽车零部件（机器人协同）当晚出提案（机器人主线）；元件/通信设备正确去重到已有链（ai-pcb-ccl/ai-optical），未重复提议；种植业匹配已有 agriculture 链 |
| 09-16 | 16 | ~15 | 9 | ✅ 半导体硅片产业链当晚出提案（芯片主线）；通信设备去重到 ai-optical；误报偏高（黄酒/家居/包装印刷等轮动题材也出提案） |

结论：主线当晚覆盖成立，去重纪律成立，阶段判定由规则给出（09-07 元件/通信
判启动期，与首板潮一致）。已知不足：情绪高潮日提案量偏大（6-9 条），靠
pending 池+人工确认吸收，后续可对"streak=1 且 sector_pct 缺交叉验证"的题材
提高门槛；概念/行业口径差异（机器人落在汽车零部件）依赖 LLM 拆链时归并。

## 7. 改动清单

| 文件 | 改动 | 量级 |
|---|---|---|
| `src/investment_engine/chain_tracker/momentum.py` | 新增：聚合+触发+阶段规则 | ~180 行 |
| `src/investment_engine/chain_tracker/discovery.py` | 新增 momentum prompt 模板 + `source_type` 字段 | ~70 行 |
| `src/investment_engine/chain_tracker/discovery_core.py` | sector 分支改道 + 编排 | ~50 行 |
| `scripts/chain_discovery.py` | `--source` 参数 + list 输出来源列 | ~15 行 |
| `tests/`（跟随现有测试布局） | momentum 规则层单测（纯函数） | ~120 行 |

不动：跟踪引擎（`core.py`/`chain_tracker.py`）、`proposals.py`、
`industry_chain/schema.py`（`source_type` 走 proposal 自由字段，不进 schema）、
cron 包装脚本。

## 8. 风险与边界

- **时滞**：盘后快照，T 日收盘后触发——比盘中选手慢半天，比研报层快 1~3 天。
  定位是"次日开盘前的补涨地图"，不是打板工具。
- **题材≠产业链**：纯情绪题材无链可拆，靠 LLM 纪律驳回；误报率回放验证。
- **概念股名互认**：fund_flow 概念名（"PCB概念"）与 limit_pool 行业名（"元件"）
  粒度不同，首期只做宽松匹配，宁可各出一张卡交触发规则兜底。
- **历史深度**：limit_pool 仅 40 天，回放窗口受限；上线后数据自然累积。
- **阈值过拟合**：3 家涨停/2 板梯队等阈值来自 9 月样本，写入 config 可配，
  回放时做敏感性检查（±1 家对命中率的影响）。
