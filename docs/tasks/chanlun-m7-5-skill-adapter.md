# M7-5 Skill 接入层实施计划

> 设计依据：`docs/design/chanlun-m7-multitimeframe-skill.md` §八（M7-5 设计）+ §2.1。
> 验收（§十一）：CLI 兼容测试；512400 端到端输出含防守线/入场点/背驰类型且级别标注正确；
> 切换后首两周人工加密复核（流程纪律，非代码）。

## 预检结论（依赖面实证）

- `chan_plot.py`（154 行）import 旧算法函数（merge_inclusion/find_fractals/find_bi/
  calc_macd/identify_zhongshu/detect_backtension/classify_buy_points）——薄壳替换必须同步移植，
  否则绘图断链。
- `boll7.py`（bollinger-7track）import `fetch_sina/fetch_tencent_daily/_parse_cli`
  ——数据函数与 CLI 解析器须在 chan_analysis.py 保留原签名。
- skill 输出惯例（SKILL.md §输出惯例）：防守线=最近底背驰低点；反转确认位=前高突破回踩；
  仓位性质=反弹仓/反转仓（仅日线可定）；失效条件=破防守线/破更大级别前低；
  背驰类型必须标注（盘整背驰≠一买）；价格给具体数值；报告标数据基准日。

## 范围

1. `src/chan_engine/report/skill_adapter.py`（新）：MultiTimeframeChart → skill 输出惯例
2. `skills/finance/chanlun-course/scripts/chan_analysis.py`：薄壳 CLI
   （算法管线替换为 chan_engine 多周期管线；数据源函数保留原签名供 boll7）
3. `chan_plot.py`：移植到引擎输出（笔/中枢/买卖点从 NormalizedChart 读，MACD 用 core.macd）
4. `SKILL.md`：管线描述、数据源段更新（新口径=chan_engine 数据层）
5. 测试：`test_skill_adapter.py`（synthetic）+ `test_skill_adapter_golden.py`（512400 e2e）
   + `test_chan_analysis_cli.py`（CLI 兼容，mock 数据层，不触网）

## 输出翻译规则（设计 §8.2 锁定 + 落地细化）

| 输出 | 规则 |
|---|---|
| 防守线 | 日线最近 bstype=1 dir=up 低点（图=日线）；与 60m 最近买入点（bstype 1/2/3 dir=up）低点（图=60m）；两者带级别标签并列，缺一不可时给存在的 |
| 反转确认位 | 日线最近顶分型高（前高，图=日线）+ 60m 有三买时附注"突破回踩结构已现" |
| 仓位性质 | **仅日线**（硬规则：60m 信号永不改变日线仓位性质）：日线最近一买 backchi_type=trend_div→反转仓；consolidation_div→反弹仓；无日线一买→观察（附 TrendState 依据） |
| 失效条件 | 破各防守线（注明图）→ 买点失败停止买入；破日线最近底分型低（前低）→ 反弹终结 |
| 入场点 | 60m/30m 最近次级别买卖点（价位+时刻+类型+图），30m 辅助精细入场 |
| 背驰类型 | 相关一买/一卖的 backchi_type 强制标注 |
| 级别三问 | 每项输出强制 level 标签；report 含 level_check 汇总（信号图/防守图/目标图） |
| 数据基准 | asof 三周期各自的最后 bar 日期/dt（skill 纪律：必须标基准日） |

## CLI 路由（§8.1，无 legacy）

```
chan_analysis.py sh512400 ...        → multi_tf 管线（日线+60m+30m）
                  --60m / --30m      → 次级别子集选择（只跑该 tf）
                  --day              → 仅日线
                  --scale N          → N∉{30,60} 明确报错（30m 已是最细，§2.2 非目标）
                  --fresh            → 兼容保留（chan_bars.db 每次运行即刷新，实为 no-op）
                  --decomp           → G8 同级别分解视角（级别由 --60m/--30m 选，默认 60m）
```

数据路径：chan_engine.data（fetch_daily 全量 qfq + fetch_minute 260 窗口 → chan_bars.db
→ load）→ RecursionEngine → analyze_nested → skill_adapter → /tmp/chan_results.json
（list 形态保持）+ 控制台摘要。双源皆挂 → 该标的 [FAIL] 行（旧 CLI 行为保持）。

## G8/G9（§8.3）

- --decomp：选定级别输出 当前中枢（zd/zg/区间）+ 上一段/当前段（dir+sure）+ 位置
  （中枢内/上方/下方）——机械化"只做上涨+盘整段"视角。
- 分类状态→预案（G9，含在默认报告 state_plan 字段）：{中枢位置, 状态（延伸/新生候选/
  破坏确认）, 预案}——状态由 last zs + 最新 close + bstype=3 bsp 判定（L18 定理三）。

## 任务拆分（TDD）

1. skill_adapter.build_report 七项输出 + level_check（synthetic stub 测试）
2. build_decomp + classify_state_plan（synthetic）
3. golden e2e：fixture mt512400_20260828.json → 防守线/入场点/背驰类型/级别标注断言
   （数值以管线实际输出为准，人工核对合理性后锚定）
4. chan_analysis.py 薄壳 + CLI 兼容测试（mock fetch，断言 /tmp/chan_results.json 结构）
5. chan_plot.py 移植（引擎输出口径）+ SKILL.md 更新
6. 验收：全量零回归 + e2e 真实跑通 512400（触网手动验证一次）+ 文档收尾

## 验收记录（2026-08-29，全部通过）

| 验收项（§十一 M7-5） | 结果 |
|---|---|
| CLI 兼容测试 | ✅ `test_chan_analysis_cli.py` 10 例（mock 数据层不触网）：_parse_cli 三元组契约（boll7 兼容）、默认多周期、--60m 子集、--day 仅日线、--scale 15 明确报错、--decomp、双源失败 → [FAIL] 行不编造 |
| 512400 端到端 | ✅ 真实触网跑通（sina 源）：防守线 60m 三买低点 1.86 / 30m 二买 1.87；反转确认位 日线前高 2.029@8/11；仓位性质=观察（仅日线）；入场点=60m 三买@8/19 1.864 + 30m 一买@8/19 + 二买@8/25；背驰类型逐级别标注（60m 一卖=盘整背驰）；级别三问齐备；分类状态→预案三级输出（60m=破坏确认/三买成立） |
| 级别标注正确 | ✅ golden 11 例锚定（fixture 复跑）：每项输出带 level 标签，仓位性质恒为日线 |
| adapter/decomp 单测 | ✅ build_report 21 例 + decomp/state_plan 10 例（synthetic，stub/直接构造） |
| chan_plot 移植 | ✅ 引擎口径（NormalizedChart + core.macd），smoke 2 例 + 512400 60m 图人工核对（笔/中枢/一卖二卖三买标注正确） |
| 零回归 | ✅ 420 passed（=366 + 54 新增）；校准矩阵 chanpy 25 / czsc 25 / recursion 19 逐 cell 不变 |
| SKILL.md | ✅ 管线段（M7-5 切换说明）、脚本位置段更新；数据源经验段保留（boll7 未迁移依赖） |

**仲裁⑥切换纪律执行**：chan_analysis.py 算法管线已直接替换（旧 merge_inclusion→…管线删除，
无 --legacy）；新旧口径差异点将在首两周人工加密复核中显式记录（流程待办，非代码）。

**跟进项（不阻塞）**：boll7 仍走旧 fetcher（fetch_tencent_daily/fetch_sina 保留原签名，
功能未动）；其迁移 chan_engine.data 属另一个 skill 的独立改动，不在 M7-5 范围。
