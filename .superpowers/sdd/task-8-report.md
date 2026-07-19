# Task 8 报告：金标样本（5 条）

执行：B4 批次 subagent。产出 5 条金标于 `src/chan_engine/spec/golden/`（GOLD-001~005），
全部通过 `load_case`（schema + claim_refs 存在性）与 `expect_to_chart` 校验；
唯一代码改动为按任务授权扩展 `tests/chan_engine/test_cases_schema.py` 参数化 golden 目录；
未动 cases 26 条既有用例、未动 harness/model/case_io、未动 third_party/chanpy、零 git 操作。
降级决策已记入 `docs/design/chanlun-quant-adr.md` ADR-005（状态：resolved by 主控代理 / 待 UP 确认）。

## 1. 实例定位表

| golden | 品种 | 时段 | 周期 | 课文结论（原文摘） | 对应 claim id | 数据 |
|---|---|---|---|---|---|---|
| GOLD-001 | 工商银行 sh.601398 | 2006-10-27~12-22 | 日线 | 课20："工商银行在12月14日构成典型的日线级别第三类买点" | claim-20070105-001-b | 真实（baostock 日线，不复权） |
| GOLD-002 | 北辰实业 sh.601588 | 2006-10-16~11-23 | 日线 | 课20："北辰实业在11月14日构成典型的日线级别第三类买点" | claim-20070105-001-b | 真实（baostock 日线，不复权） |
| GOLD-003 | 上证指数 | 2007-03（0305~0309 语境） | 30 分钟（课文语境） | 课36："2760到2858这30分钟中枢，03081000的5分钟回抽确认了一个第三类买点"；"回抽低点2871点比上一中枢的最高点2888点要低" | claim-20070105-001-b、claim-20070313-001-f（实例出处课） | 等比 synthetic（课文点位原值保留） |
| GOLD-004 | 中国人寿 601628 | 2007-01-11~01-17 语境 | 5 分钟（课文语境） | 课24："11日11点30分到15日10点35分构成一个中枢……16日10点25分到17日10点10分，一个标准的三段构成新的中枢，也相应构成B段……其后就是C段的上涨，其对应的MACD红柱子面积明显小于A段的，这样的背驰简直太标准了"；"回跌一定至少重新回到B段的中枢里" | claim-20070118-001-a、claim-20070118-001-b | 等比 synthetic |
| GOLD-005 | 万科 000002 | 2006-12-15~12-18 语境 | 15 分钟（课文语境） | 课24："000002万科的15分钟图，12月15日10点45分，构成一个盘整背驰，所以要出来，其后的次级别回跌并不重新回到前面的中枢里，就在18日9点45分构成了标准的第三类买点" | claim-20070118-001-c（原文案例所在）、claim-20070105-001-b | 等比 synthetic |

候选池补充（未采用，备查）：课33 全是 a+A+b+B+c 字母推演、无具体品种点位；课35 开头
"该中枢从7日13点多的2911算起……2915是不能有效跌破的"（上证 5 分钟）与课36 同源同时段，
被 GOLD-003 覆盖；课14 茅台 2004-06-18 日线一买属均线系统吻+MACD 口径（非中枢背驰口径），
与 M1 五表 BSP 语义不同源，弃用；课17 驰宏锌锗/580991 日线趋势vs盘整，课文未给中枢区间
数值且 580991 为已退市权证（数据不可得），弃用。

## 2. 取数尝试与降级决策

环境：仓内 `.venv` 已有 akshare 1.18.64、baostock 0.9.3。取数脚本放 /tmp 不入仓
（`/tmp/golden_data_probe.py`、`/tmp/golden_dump_daily.py`、`/tmp/gen_golden.py`）。

证据（完整输出 `/tmp/probe_out.txt`）：
- **2007 分钟级不可得（两条独立路径均证实）**：
  1. baostock 分钟线查询 `sh.000001` 5min 2007-03-05~03-13、`sh.601628` 5min
     2007-01-11~01-18、`sz.000002` 15min 2006-12-14~12-19：接口 `err=0 success`
     但 **rows=0**（baostock 分钟线仅覆盖 2015 年起）；
  2. akshare `stock_zh_a_hist_min_em`/`index_zh_a_hist_min_em`（东财分钟线）无起止
     日期参数、只回近期；且本环境对 eastmoney 接口连接被拒（ConnectionError:
     RemoteDisconnected），2007 分钟级确认不可得。
- **日线可得**：baostock 日线 `sh.601398` 2006-10-27 起 51 行、`sh.601588`
  2006-10-16 起 45 行、`sh.000001` 2007-02-26~03-16 15 行，均成功。

决策（ADR-005）：方案①+②组合——课 20 两个日线三买实例走①真实日线（不复权
adjustflag=3，该时段无除权）；课 24/36 三个分钟级实例走②等比 synthetic
（课文点位/段结构原样保留，段=笔口径同 cases）。

## 3. 每条 golden 的设计要点

统一约定（与 cases 一致）：段=笔；fx type up=顶/down=底；bsp dir 买点=up/卖点=down；
末位 fx/bi sure=false；synthetic 用 pivot 间距 4（两分型间 1 根独立 K 线，新旧笔口径
均满足，与 ZS-001 族同），腿内单调零包含（生成器 `/tmp/gen_golden.py` 程序化断言：
pivot 极值落位、无包含、中枢 max/min 公式复核全过）。

- **GOLD-001（真实）**：41 根工行日线。人工读图核对：idx0~30（10-27~12-08）长期
  3.25~4.01 震荡为中枢区域，idx31~33（12-11~13）放量上行离开，idx34=2006-12-14
  l=4.20 为干净底分型（两侧无包含），回试未跌回中枢区域 → 与课文一致。
  **只断言 bsp{34,3,up,lv1,sure=true}**：课文未给中枢精确区间，zs 不断言（不过度
  断言课文没说的细节）；课文思考题二（12-22 是否三买）无答案，不断言。
- **GOLD-002（真实）**：29 根北辰日线。idx0~17（上市~11-08）3.12~4.05 震荡
  （ZG≈4.05 首日高点），idx18（11-09）收 4.15 跳空向上突破，课文指认 11-14
  （idx21，l=4.20>4.05）为三买。**只断言 bsp{21,3,up,lv1,sure=true}**。
  已知摩擦点写入头注：idx20 [4.17,4.43] 包含 idx21 [4.20,4.39]，严格包含处理后
  底分型落合并 K 线（低点 4.17@11-13）——课文指认日 vs 严格包含口径的偏差留
  Task 9 归类（见疑虑 1）。
- **GOLD-003（synthetic）**：课文点位原值保留。中枢三笔 [2760,2858]/[2760,2880]/
  [2755,2880] → ZD=2760、ZG=2858（max/min 公式复核）；离开笔顶 2888=课文"上一中枢
  最高点"；回抽低点 2871>ZG 2858 且 <2888（课文大小关系成立）→ bsp{25,3,up}。
  fx/bi/zs/bsp 四表全断言。
- **GOLD-004（synthetic）**：上涨趋势两中枢 + C 段衰竭 → 一卖。中枢1 [38.6,39.5]
  @5-17，A 段 idx17→21 幅度 2.9，中枢2=B 段 [40.7,41.3] @21-33（高于中枢1 无重叠
  =趋势），C 段 idx33→37 幅度 1.3≪2.9（面积代理 Σ|Δc| C<A 成立）→ bsp{37,1,down}；
  回跌 idx37→41 至 41.0 重回 B 中枢 [40.7,41.3]（课文"回跌至少回到 B 段中枢"✓）。
  双 zs + 完整 fx/bi 全断言。与 BC-001（通则版一买）互补：本条是课文实例原文的
  卖点镜像，带 source_ref。
- **GOLD-005（synthetic）**：盘整背驰→三买全流程。A 段 idx5→9 幅度 0.7，中枢
  [7.55,7.85] @9-21，C 段 idx21→25 至 8.0 上破 ZG 但幅度 0.45<0.7（盘整背驰，
  课文 12-15 10:45），回跌 idx25→29 低点 7.9>ZG 7.85 不返中枢 → bsp{29,3,up}
  （课文 12-18 9:45）。盘整背驰是操作信号非五表结构元素，不单列断言。

## 4. 验证结果

- **schema**：扩展后 `tests/chan_engine/test_cases_schema.py` 对 cases+golden 两目录
  参数化（新增 golden 的 schema/命名/source_ref 非空三项校验 + golden_dir_not_empty）。
  `PYTHONPATH=src:third_party/chanpy .venv/bin/python -m pytest tests/chan_engine/ -q`
  → **162 passed**（基线 146 + 新增 16）。
- **逐条 load_case**：5 条全过（claim_refs 存在性、expect 白名单、
  `expect_to_chart` 字段校验）。
- **真实适配器对照**：`python -m chan_engine.harness.report --cases ... --golden
  src/chan_engine/spec/golden --out /tmp/golden_smoke.md` → **退出码 0**，31 条用例
  （26 case + 5 golden），golden 行**无 ERROR**（FAIL 为预期产出）。

golden 部分矩阵/明细摘要（详见 `/tmp/golden_smoke.md`）：

| golden | chanpy | czsc | 明细要点 |
|---|---|---|---|
| GOLD-001 | FAIL | PASS* | chanpy：bsp 缺 {34,3,up}（未在 12-14 报出三买）；其余表 no-expect skipped |
| GOLD-002 | FAIL | PASS* | chanpy：bsp 缺 {21,3,up}；同上 |
| GOLD-003 | FAIL | FAIL | chanpy：fx/bi 把 17→21/21→25/25→29 并成一笔 17→29，三买未报出（报 1 买@29）；zs 区间一致但 sure 异。czsc：zs 区间值 2760/2858 与课文**完全一致**，端点 1-21 vs 断言 5-17 |
| GOLD-004 | FAIL | FAIL | chanpy：bi 大合并（9→37 一笔），双中枢未拆出，一卖缺；czsc：两个中枢 zd/zg 与断言**完全一致**（38.6/39.5、40.7/41.3），端点/数量异 |
| GOLD-005 | FAIL | FAIL | chanpy：同 GOLD-003 合并模式，bsp 错位为 1 买@33；czsc：zs 区间异（[7.5,7.6] vs [7.55,7.85]） |

*czsc 对 GOLD-001/002 的 PASS 是空断言产物：bsp 表对 czsc 为 N/A（skip），唯一被断言的
表不可比 → 无 diff → PASS，并非真正命中课文结论，评审矩阵时需注意（见疑虑 4）。

## 5. 疑虑点（留主控/Task 9 仲裁）

1. **GOLD-002 课文指认日 vs 严格包含处理**：11-14 与 11-13 存在包含关系，合并 K 线后
   底分型低点在 11-13（idx20）；expect 忠实课文断言 idx21。实现若按合并口径落在
   idx20，应归类"课文歧义"还是"实现偏差"？涉及 golden 的 idx 对齐口径，建议 Task 9
   评审时统一裁定（GOLD-001 无此问题，12-14 为干净底分型）。
2. **GOLD-001/002 只断言 bsp 单点**：课文未给中枢区间，zs 表 skipped。chanpy 未报出
   三买的根因（其日线笔/中枢划分与课文分析口径的关系）需 Task 9 结合 fx/bi 实际输出
   深挖——本任务只保证 golden 无 ERROR 跑通。
3. **GOLD-003 级别压平**：课文"5 分钟回抽确认对 30 分钟中枢的三买"严格说是两级结构，
   M1 五表单层表达下按段=笔压平为 level 1（与 cases 口径一致）。是否需要在 golden 用
   level 2 表达"30 分钟中枢 + 5 分钟回抽"，留主控裁定。
4. **czsc 空断言 PASS 的解读**：见上表 * 注。是否应在报告渲染层把"全表 skipped 的 PASS"
   单独标记（如 SKIP），属 report.py 行为变更，超出 Task 8 授权，仅提议。
5. **等比 synthetic 的保真度**：段=笔 + pivot 间距 4 的压缩比例是工程约定（1 课文段≈
   1 笔），课文时间比例（如人寿中枢 2.7 天 vs A 段 1 天）未逐 bar 等比，仅保留结构
   比例与全部课文数值断言。若 M2 需要更细的等比粒度，需另立约定。

## 附：文件清单

- 新增：`src/chan_engine/spec/golden/gold-001.yaml` ~ `gold-005.yaml`（5 条）
- 修改：`tests/chan_engine/test_cases_schema.py`（参数化 golden 目录，授权内唯一代码改动）
- 修改：`docs/design/chanlun-quant-adr.md`（追加 ADR-005）
- 取数/生成脚本（/tmp 不入仓）：`golden_data_probe.py`、`golden_dump_daily.py`、`gen_golden.py`
- 冒烟产出：`/tmp/golden_smoke.md`（31 条用例校准矩阵）
