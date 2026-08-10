# Spec：影子盲判数据包扩容 + 输出契约 v2

> 建稿：2026-08-10。依据：`evals/shadow/attributions/2026-08-10.json`（UP 对照人工归因：数据缺×2、步骤缺×1）及三份处置提案（`framework/proposals/2026-08-10-*.md`）。
> 用户裁决：复盘（shadow_daily）时间推后到 18:00 后，以覆盖龙虎榜等收盘后披露数据。

## 1. 目标

让每日盲判"看得见当天情绪结构、说得出可证伪的节奏判断"：

1. 数据包接入 KPL 情绪快照、当日资讯标题、龙虎榜席位摘要（三个新通道）；
2. 输出契约升 v2：情景分支、明日验证变量、失效条件、方向操作定性；
3. cron 时序调整：KPL 拉取提前、shadow_daily 推后至 18:00 后；
4. 版本分界记录，保毕业判决的度量一致性。

## 2. 现状（已核实）

- `build_daily_pack`（`src/investment_engine/blindtest/dataset.py:105`）：指数 K 线 + stock_pool 快照 + directions/chains/glossary/patterns 静态快照。**无情绪、无广度、无资讯、无席位**。
- `pack_to_prompt` 出厂带 `assert_no_leakage` 防泄漏断言——新增数据块必须过同一断言。
- KPL 通道已每日落盘（gitignored）：`infra/data/kpl/emotion/<date>.json`（六块原样）、`infra/data/kpl/news/<date>/`（index.json + 全文 md）。
- 龙虎榜接口已捕获实样（`docs/design/kpl-api-inventory.md` 第 5 节）：`c=UserBusiness&a=GetDay`（applhb），`TList` 分类 + `List` 当日明细；T 日收盘后披露，非披露日/披露未出时 List 为空。
- 输出契约：`replay.py` 的 `SYSTEM_PROMPT` + `parse_result`，仅 `market_stage/directions/used_patterns`。
- cron（本机）：15:35 pre_fetch → 15:40 shadow → 15:45 KPL。
- 结算口径：`maturity.py` 按 `directions[].stocks` 前向超额结算，`pending_maturity` 在途记录不受契约变更影响。

## 3. 设计

### D1 数据包新增三块（`build_daily_pack` 扩展）

全部**可选块**：当日文件缺失/字段缺失时整块省略，并在 pack 中记 `missing` 标注（如实，不编造）。均从本地 `infra/data/kpl/` 读，无网络调用。

- `emotion`：从 `kpl/emotion/<date>.json` 精选白名单字段——`daban`（涨停/跌停/封板率/上涨下跌家数/成交量能等计数类字段）+ `lianban`（梯队：高度/连板数/代表股及其板块归属——实样含"哈药股份,2连板,医药"，支持抱团结构识别）+ `fengkou`（风口名称列表）+ `bankuai`（板块榜：名称/涨幅——板块维度线索，UP 方向分析的粒度；注意只是 top 榜非全量）。控制 token，不落原始大字段。
- `news_titles`：从 `kpl/news/<date>/index.json` 取当日条目（标题/时间/关联股票代码），不含全文；条数封顶（如 60 条，超出如实截断标注）。
- `lhb`：从 `kpl/lhb/<date>.json` 取轻量摘要——当日上榜股票 + 席位类别（顶级/一线/知名/机构/庄股）；原始响应只落盘不进 prompt。

### D2 KPL 龙虎榜模块（`src/investment_engine/kpl/lhb.py` 新建）

- `fetch_lhb(client)`：调 `UserBusiness&a=GetDay`（applhb），原样落盘 + 返回结构化摘要；
- 容忍空：`List` 为空（非披露日/披露未出）时正常落盘并记 `note`，不报错；
- `save_lhb(data, out_root, date)` → `infra/data/kpl/lhb/<date>.json`。
- `scripts/kpl_daily_fetch.py`：加 `--skip-lhb` 开关，默认拉取；lhb 放在 emotion/news 之后执行（同一脚本顺序执行，使 lhb 拉取时刻最接近 18:00 披露窗口）。

### D3 输出契约 v2（`replay.py`）

`SYSTEM_PROMPT` v2 追加要求（原三条纪律不变）：

```json
{"market_stage": "...", "stage_reason": "...",
 "scenarios": [{"name": "A", "condition": "触发条件", "conclusion": "应对结论", "key": "区分关键变量"}],
 "watch_next": ["明日验证变量（可观察、可证伪）"],
 "invalidation": ["本判断失效条件"],
 "directions": [{"direction_id": "...", "reason": "...", "posture": "趋势|波段|右侧确认|回避", "stocks": ["..."]}],
 "used_patterns": ["..."]}
```

- `parse_result` 扩展解析新字段；**向后兼容**：缺新字段的老记录/输出解析为 `[]`，不报错；`posture` 非法值省略不拦截。
- 预测 JSON 新增 `prompt_version: "v2"`（老记录无此字段即 v1）。
- 结算口径不变：maturity 仍只按 stage/directions 结算，新字段不参与打分（属过程质量资产）。

### D4 cron 时序（本机 crontab）

| 时刻 | 任务 | 说明 |
|---|---|---|
| 15:35 | pre_fetch_klines | 不变 |
| 17:45 | kpl_daily_fetch | 提前（原 15:45）；脚本内 emotion → news → lhb 顺序，lhb 最接近披露窗口 |
| 18:05 | shadow_daily | 推后（原 15:40），给 KPL 留 20 分钟拉取窗口 |

- KPL 超窗未完成 → 数据包对应块缺失并标注，shadow 照常跑（降级原则）；需要当日重跑按既有手动补跑流程（删记录再跑，幂等）。
- 同步更新 `docs/tasks/kline-daily-fetch-ops.md` 时序表与排障指引。

### D5 KNOWN_DATA_GAPS 更新（`shadow/attribute.py`）

移除已补项：`涨停池/炸板率`、`涨跌家数`；`公告/新闻流` 改为 `公告流`（资讯标题已补、全文与公告原文仍缺）；保留 `板块资金流`、`分时数据`。

### D6 版本分界

- `prompt_version` 字段即版本标记；
- `graduation` 报告（`shadow/graduation.py` 或其报告渲染）加一行版本窗口说明（各版本覆盖的日期段），**聚合逻辑不变**——分段由人读，不自动切开统计（样本太少时切分会误导）。

### D7 指数覆盖扩容（2026-08-11 查漏补充）

盲判数据包指数仅 `IDX000300/IDX000001`（沪深300+上证），UP 环境分析的基座是三指数对比 + 大小盘风格（黄白线分化近似）。扩容：`INDEX_CODES` 增加**创业板指、深成指、中证1000**（中小盘风格代理）；历史由既有指数自补机制（腾讯接口）回填，离线回放不受影响。中证2000/微盘股指数作为可选后续项，不在本期。

### D8 术语词典增补打板节奏概念（2026-08-11 查漏补充）

`framework/up-glossary.md` 缺 UP 复盘高频使用的节奏概念，补 3 条客观定义：**晋级率**（次日连板数 ÷ 前日首板数；UP 经验参考值 ~15% 标注"经验参数、待回测验证"，不写成定律）、**抱团**（若干高位连板股脱离各自板块共振上涨形成的资金集合；无产业锚、断板即失参照系）、**断板/换龙**（连板中断及其传导：外力扰动型 vs 内生换龙型）。契约 v2 给了载体，词典得给词汇。

## 4. 执行阶段（对应实施计划 Task）

| Task | 内容 | 测试 |
|---|---|---|
| T1 | `kpl/lhb.py` + client 通路 | fixture 测试：正常/空 List/鉴权失败三态 |
| T2 | `kpl_daily_fetch` 接 lhb | 幂等 + skip 开关测试 |
| T3 | `build_daily_pack` 三块扩展 | 有/无 KPL 数据两态 + 防泄漏断言过 + 截断标注 |
| T4 | 契约 v2（prompt/parse/prompt_version） | parse 新字段、老记录兼容、非法 posture 容忍 |
| T5 | crontab 调整 + ops 文档 + KNOWN_DATA_GAPS + graduation 版本行 | ops 文档核对；全量 `tests/investment_engine` 绿 |
| T6 | 指数扩容（INDEX_CODES + 自补回填） | 新指数进 pack 且历史窗口完整 |
| T7 | 术语词典增补 3 概念 | 词典进 pack 引用更新即生效（现有 glossary 通道） |

## 5. 文件改动清单

- 新建：`src/investment_engine/kpl/lhb.py`、`tests/investment_engine/test_kpl_lhb.py`
- 修改：`scripts/kpl_daily_fetch.py`、`src/investment_engine/blindtest/dataset.py`（含 INDEX_CODES）、`src/investment_engine/blindtest/replay.py`、`src/investment_engine/shadow/attribute.py`（KNOWN_DATA_GAPS）、`src/investment_engine/shadow/graduation.py`（版本行）、`framework/up-glossary.md`（3 概念）
- 文档：`docs/tasks/kline-daily-fetch-ops.md`（时序表）、`docs/current-system-guide.md`（架构图时刻与数据块说明）
- 本机 crontab（非 git）：17:45 KPL、18:05 shadow
- **不改** `src/qing_investment/`；`tests/` 子目录不放 `__init__.py`

## 6. 验收标准

1. `.venv/bin/pytest tests/investment_engine -q` 全绿；
2. 用 2026-08-10 数据本地回放 `build_daily_pack`：emotion/news_titles 两块在场且过防泄漏断言；lhb 块缺失时标注不报错；
3. `parse_result` 对 v1 老记录（`evals/shadow/predictions/2026-08-07.json` 的 raw）解析不报错、新字段为 `[]`；
4. crontab 实际调整到位且 ops 文档同步；
5. 当日 18:05 后 `log/shadow_daily.log` 首跑正常，预测 JSON 带 `prompt_version: "v2"`；
6. 数据包指数块含创业板指/深成指/中证1000 且当日数据在场；
7. `up-glossary.md` 新增晋级率/抱团/断板换龙 3 条，晋级率经验参数带"待回测验证"标注。

## 7. 风险与边界

- **龙虎榜披露时间未实测**：17:45 拉取可能拿到上一披露日（`Day` 字段可辨）。首周实盘观察后在 ops 文档记录实际披露边界，必要时把 lhb 再后移。
- **KPL token 过期**：lhb 与 emotion/news 同通道，鉴权失败按既有退出码 3 处理。
- **token 消耗**：news_titles 封顶 + emotion 白名单，控制数据包体积；实测一次 token 用量记录在执行记录。
- **bankuai 为 top 榜近似**：板块榜只有领涨前几名，全量板块行情（含领跌板块）仍缺——板块维度的"弱在哪"只能靠 stock_pool 个股与资讯标题近似，全量板块指数行情留作后续项。
- **指数回填依赖腾讯接口**：新增指数的历史回填与每日自补走腾讯行情，接口不可用时该指数块缺失并如实标注。
- **度量一致性**：v1/v2 混窗期间毕业判分报告标注版本分界；不自动切分统计。
- **信息差边界不变**：晚间信息（22:13 复盘含有的公告/票房/电话会）仍物理不可得，不承诺消除。
