# M4 降级项补丁评估报告

> 计划：docs/superpowers/plans/2026-08-02-chanlun-quant-m4-patch-assessment.md
> 范围：M3 保持降级 8 项（chanpy PATCHES 4 + czsc 局限 4），只读评估，不改源码。
> 每项结论三选一：A=改 chanpy 源码（登记 PATCHES.md）/ B=适配器层补偿 / C=永久降级（登记附录 C.5）。

## 1. SEG-004/005 × chanpy（EigenFX seg 拆段口径，P-F）
- **根因复核**：（M2-5 结论）chanpy 特征序列分型在 SEG-004/005 拆段与 expect 口径不一致；`left_seg_method=all` 修 SEG-004 但净 -2（破坏 BC-001/BSP-001/GOLD-004）；`seg_algo=break` 无效。
- **探针实证**：（M4-1，探针 `/tmp/m4_probe_seg.py` + 追踪探针 `/tmp/m4_probe_seg_trace.py`，运行时 monkeypatch 未改源码）
  - 输出对照（bi 表两用例均与 expect 一致，差异纯在 seg 层）：
    - SEG-004：expect 1 段 `bi0..bi4 up sure=false`；chanpy 拆 2 段 `bi0..bi0 up` + `bi1..bi3 down`。
    - SEG-005：expect 2 段 `bi0..bi8 down sure=true` + `bi9..bi11 up sure=false`；chanpy 拆 4 段 `bi0..bi0 down / bi1..bi3 up / bi4..bi8 down / bi9..bi11 up`。
  - 分叉点定位（函数+行号，追踪实证）：
    - **SEG-004**：EigenFX 主流程与 expect 口径一致——`treat_second_ele`（EigenFX.py:33-35）正确判定 X2=bi3[11,15] 高点 < X1=bi1[12,16] 高点 → reset，无顶分型；`can_be_end`(:82)/`find_revert_fx`(:159)/`actual_break`(:117) 全程零调用。真正分叉点在 EigenFX **之外**的尾部兜底：`SegListComm.collect_first_seg` PEAK 分支（SegListComm.py:55-66，reason=`0seg_find_high`）把首段钉在峰值 bi0，`collect_left_as_seg`（SegListComm.py:121-129，reason=`collect_left_0/1`）把余下 bi1..bi3 硬补成向下段——兜底路径不检查"线段必须被线段破坏"（claim-20070702-002-a）。
    - **SEG-005**：EigenFX 本体最终在 bi11 确认底分型（`treat_third_ele`:38 → `actual_break`:117=True → `can_be_end`:82 gap=False → True），段终结于 bi8 sure=true，**与 expect 一致**；真正分叉点在 `try_add_new_seg` 的 `split_first_seg` 分支（SegListComm.py:132-138，reason=`split_first_1st/2nd`）：首段内部峰值 bi3（21）超过起点 bi0（20）即把首段劈成 `bi0..bi0 + bi1..bi3`，而 expect 按课78"古怪线段标准化"保留单段 bi0..bi8（区间 [12,21]，不拆）。`find_revert_fx`(:159) 缺口分支在两用例均未触发（无缺口语料）。
  - 结论：M2-5 归因"EigenFX 拆段口径"需细化——两个真正分叉点都在 **SegListComm.py 的首段/兜底启发式**，不在 EigenFX 的 can_be_end/find_revert_fx/actual_break。
- **爆炸半径**：
  - 直接：expect 含 seg 表的用例共 5 个（`grep -l 'seg:' src/chan_engine/spec/cases/*.yaml` → seg-001..005；brief 给定的 `grep -l '"seg"'` 因 YAML 键不带引号返回空，已用等价命令佐证），其中 chanpy PASS 3 个（seg-001/002/003）。
  - 间接：seg 是 zs/bsp 上游（chanpy 同一 KLU 产出 seg_list/zs_list/bs_point_lst，adapter_chanpy.py:235-275 同源读取），且 trace 显示兜底路径（`0seg_find_*`/`collect_left_*`/`split_first_*`）在常规增量运行中高频触发 → 粗粒度口径：**全部 23 个 chanpy PASS 都在半径内**，任一兜底/首段行为修改需 23 个逐一复跑。
  - 半径实证：M2-5 已实测 `left_seg_method=all`（全局切兜底）修 SEG-004 但净 -2（BC-001/BSP-001/GOLD-004 翻转）。
- **建议**：**C（永久降级，登记附录 C.5）**。判据对照：
  - 两个分叉点（`collect_first_seg`:55-66 / `collect_left_as_seg`:121-129 / `try_add_new_seg` split_first:132-138）均为全库共享的默认行为路径，非可旁路的边角分支；
  - 唯一已知配置通道 `left_seg_method`（枚举仅 ALL/PEAK，SegConfig.py:6-13）全局切换已实测净 -2 → 满足判据"需改动默认行为且任一 PASS 翻转"；
  - 形式上可走 A（新增配置项默认关）——评审指正：harness 侧**已有** per-case 配置通道 `ChanPyAdapter.__init__(config_overrides)`（adapter_chanpy.py:162-173），A 的实际门槛低于原论证字面所述；维持 C 的真正依据是收益/成本与门控脆弱性：①新增"默认关"配置仍需改 vendor 源码（新 LEFT_SEG_METHOD 成员 + split_first 开关，SEG-005 另需源码补丁），违反最小 diff 原则，且 M2-5 已实证该路径相关参数组合（`left_seg_method=all`）净 -2；②收益仅 chanpy +2 PASS（2 个单级别 seg cell，expect 仅比 fx/bi/seg 三表、无 zs/bsp 牵连），而配置项触碰 seg 上游共享路径、影响全量 23 个 PASS 用例，门控脆弱需逐一复跑；③演进方向由 ADR-009 recursion L0 承担；
  - B（适配器补偿）亦否：改写 seg 表会与 chanpy 内部 zs/bsp 口径脱节，且 reason 模式门控脆弱（seg-001..003 同样走兜底路径，易误伤 PASS）；
  - 替代路径由 ADR-009 recursion L0 演进承担（当前 recursion 列对此二用例同源 FAIL，属已知待演进项）。
- **UP 决策**：C 采纳——永久降级（2026-08-02 UP 确认），已登记附录 C.5

## 2. BSP-004 × chanpy（三买"二三类重合"缺失，P-K）
- **根因复核**：（M2-3 结论）BSP-004 expect 三买@36 与二买@36 重合（课21）；chanpy `cal_seg_bs3point` 不覆盖该场景；`strict_bsp3`/`bsp3_peak`/`bsp3a_max_zs_cnt` 实验均无效。
- **探针实证**：（M4-2，探针 `/tmp/m4_probe_bsp3.py` + 追踪探针 `/tmp/m4_probe_bsp3_trace.py`，运行时 monkeypatch 未改源码）
  - 输出对照：expect bsp = 一买@26 + 二买@36 + 三买@36（同 idx 两条记录表达二三类重合，课21 / claim-20070109-001-b）；chanpy 归一表仅一买@26 + 二买@36，缺三买@36。zs 表一致（zd=18.3 zg=20.2 start=6 end=21），bar36 回试低点 20.30 > ZG 20.20，"回抽不触及中枢"成立。
  - 漏报机制定位（追踪实证，结论：既非"三买须晚于二买"时序约束，也非 chanpy 侧信息丢失——三买判定路径**完整命中**，丢失发生在适配器提取层）：
    - chanpy 内部 `bs_point_lst` 实际含 `bsp @klu36 bi6 types=['BSP_TYPE.T2', 'BSP_TYPE.T3B']`——三买**已算出**，与二买合并于同一 `CBS_Point`。
    - 命中路径：`treat_bsp3_before`（BSPointList.py:368-399）——seg0（bi0..bi4 down，sure=True）的 `cmp_zs=(18.3, 20.2)`（`get_final_multi_bi_zs`，:379），候选笔 bi6（31→36 down）`low=20.30`；`bsp3_back2zs`（:419-420）判 `20.30 < zs.high=20.2` 为 False（未回中枢）→ `add_bs(T3B)`（:399）。
    - 合并而非去重：`cal()` 顺序为一买→二买→三买（:103-105），二买先入 store；三买 `add_bs` 走 `exist_bsp` 分支（:133-138）`add_another_bsp_prop` 把 T3B 并入 bi6 既有 T2 记录——**信息保留在 `bsp.type` 列表中**。
    - 真正丢失点：**适配器** `adapter_chanpy.py:272` `bstype=int(bsp.type[0].main_type())` 只取首类型，T3B 被丢弃。
  - 补偿可行性：判定信息**不在**归一表之外——chanpy 内存对象 `bsp.type` 适配器可直接枚举，无需 seg 内部状态、无需重算 → B 类（适配器层补偿）成立。先例：M2-3 末位笔 bsp 过滤（adapter_chanpy.py:261-268）同为 B 类。补偿形态：提取循环（:264-278）按 `bsp.type` 每个 distinct `main_type()` 出一条 `BSPoint`（保持 idx/dir/level/sure 口径不变）。
- **爆炸半径**：
  - expect 含 bsp 的 chanpy PASS 用例共 **6 个**（逐一列示，括号内为 chanpy 内部 bsp type 全列表，均单类型）：BC-001（@46 T1）、BSP-001（@26 T1）、BSP-002（@26 T1 + @36 T2）、GOLD-003（@25 T3A）、GOLD-004（@37 T1）、GOLD-005（@29 T3A）。校正 brief 口径：BSP-003 的 chanpy 列为 FAIL（属另一降级项、已由 recursion 列覆盖，见 `chanlun-calibration-report.md:22,84`），不计入 PASS 半径。
  - 半径实证：全语料 31 用例（26 spec + 5 golden）扫描，多类型合并 bsp **仅 1 个实例**（BSP-004 bi6 = T2+T3B）；6 个 PASS 用例的内部 bsp 全部单类型 → "每个 distinct main_type 出一条"的补偿对全部 PASS 用例输出逐字节不变，**实证半径 = 0**。
  - 理论半径：仅"同一笔多类型"形态受影响，该形态此前适配器只出首类型记录，补偿为纯增量（追加记录），不删改既有记录。
- **建议**：**B（适配器层补偿）**。判据对照：
  - 漏报点不在 vendor 源码：chanpy 三买判定路径（`treat_bsp3_before`）完整命中且多类型信息保留于 `bsp.type`，改源码（A）无收益、违反最小 diff；
  - 补偿点明确且与先例同类：改 `adapter_chanpy.py:264-278` 提取循环，按 `bsp.type` 逐 distinct main_type 出记录，同 M2-3 末位笔过滤属 B 类，不动 `third_party/chanpy/`；
  - 半径实证 = 0（全语料仅 BSP-004 一例多类型；6 个 bsp-PASS 用例输出不变），实施验收门：198 全绿 + BSP-004 chanpy 列 FAIL→PASS；
  - C（永久降级）否：非不可修复项，且"二三类重合"是课21 明确形态（claim-20070109-001-b），成本一行提取口径、收益 chanpy +1 PASS，无挂账理由。
- **UP 决策**：B 采纳——批准实施（2026-08-02 UP 确认），另立 M5 实施里程碑

## 3. ZS-003 × chanpy（跨 seg 九段升级，P-K）
- **根因复核**：（M2-5 结论）ZS-003 的 chanpy zs 受 seg 切分限制（end=17，不够 9 段）；`ZS.combine` 拒绝 one_bi_zs（ZS.py:116）和跨 seg（ZS.py:118）；`one_bi_zs=T` 实验回归 BSP-002/GOLD-003/005（-3）。czsc 适配器已有参照实现 `_apply_nine_bi_upgrade()`。
- **探针实证**：（M4-3，探针 `/tmp/m4_probe_zs9.py` + 延伸演算探针 `/tmp/m4_probe_zs9_ext.py`，只读未改源码）
  - 输出对照：expect zs = `{zd:16.5 zg:17.0 start:5 end:41 level:2 sure:true}`；chanpy 归一 zs 仅 1 个 `{zd:16.0 zg:17.0 start:5 end:17 level:1}`；seg 3 段（bi0..4 up / bi5..7 down / bi8..10 up），bi 共 11 笔。chanpy zs end=17 止步于 seg1（bi5..7 down）内，跨 seg 到 seg2（bi8..10 up）的合并被 `ZS.combine`:118 seg 一致性检查（`begin_bi.seg_idx != zs2.begin_bi.seg_idx → False`）拒绝。
  - 关键发现 1（纯移植不可行）：chanpy 中枢内笔数仅 **3**（bi1..bi3），远低于 9 → 直接移植 czsc `_apply_nine_bi_upgrade()`（只做"范围内笔数≥9 → 升级"，不含延伸）在 chanpy 上**零触发**，修不了 ZS-003。B 必须是复合形式：**跨 seg 延伸试探 + 九段升级**（延伸作为升级判定的内部步骤，不单独落改）。
  - 关键发现 2（复合 B 可行，信息充分）：模拟跨 seg 延伸（自 zs.end 起逐笔与 [zd,zg]=[16.0,17.0] 判重叠，末位 sure=False 笔 bi10 不延伸，对齐 M2-3 czsc 口径）：end 17→41，中枢内笔数 3→9（bi1..bi9）。9 笔分 3 组子中枢演算：组1（bi1..3）→ [16.0,17.0]；组2（bi4..6）→ [16.5,18.0]；组3（bi7..9）→ [16.2,17.8]；重合区间 zd=max(16.0,16.5,16.2)=16.5、zg=min(17.0,18.0,17.8)=17.0 → **与 expect 逐字段一致**（zd=16.5 zg=17.0 end=41 level=2）。延伸与升级所需全部信息（归一 bi 表 start/end/dir/sure + bars 极值）适配器齐备，无需 chanpy seg 内部状态 → 不触发 brief 的"A 兜底条件"。
  - A 路径评估（对照）：`combine` 被 `ZSList.try_combine`（ZSList.py:157-161）while 循环全库共享调用；:118 seg 检查无配置旁路（CZSConfig 仅 `need_combine/zs_combine_mode/one_bi_zs/zs_algo` 四项，无跨 seg 开关）；`do_combine` 还会把 zd/zg 改为子中枢并集（min/max），直接破坏 bsp-002/004 expect zs `zd:18.3 zg:20.2` 口径；且归一化 zs `level=1` 恒写死（adapter_chanpy.py:255），即便 combine 合并成功也无 level=2 输出通道，A 需叠加 vendor 侧级别推导新逻辑。M2-5 已实测同区域实验 `one_bi_zs=T` 净 -3（BSP-002/GOLD-003/005 翻转）。
- **爆炸半径**：
  - 全量用例扫描"chanpy zs 内笔数≥9"（统计命令：逐用例 `ChanPyAdapter().run` 后数 `bi.start_idx>=z.start_idx and bi.end_idx<=z.end_idx` 的笔数）：结果 **0 个**——chanpy zs 全部受 seg 限制，无一达 9 笔（含 ZS-003 本身仅 3 笔）。与 brief 预期"仅 ZS-003"的偏差本身即证据：偏差在 chanpy 不延伸中枢，而非用例语料。
  - 复合 B 的延伸试探触发集合（跨 seg 可延伸 ≥1 笔的用例，末位 sure=False 不延伸）：**4 个**——bsp-002（end 21→36，6 笔）、bsp-004（21→31，5 笔）、seg-005（33→45，6 笔）、zs-003（17→41，9 笔）。
  - 门控必要性实证：bsp-002/bsp-004 expect zs 均为 `{zd:18.3 zg:20.2 start:6 end:21 level:1}`——若裸跨 seg 延伸落改 end_idx，bsp-002（chanpy PASS）zs cell 立即翻转。因此延伸必须只作升级判定的内部试探，**唯一落改门控 = 延伸后笔数≥9 且 3 子中枢重合区间成立**；该门控下触发集合 = **仅 ZS-003**（其余 3 用例延伸后 6/5/6 笔均 <9），半径实证 = 1，对其余 23 个 chanpy PASS 输出逐字节不变。
- **建议**：**B（适配器层补偿，复合形式）**。判据对照：
  - 纯移植 `_apply_nine_bi_upgrade()` 零触发不可行，但复合 B（同一后处理函数内完成"跨 seg 延伸试探 → ≥9 笔门控 → 3 子中枢重合 → 落改 zd/zg/end_idx/level=2"）信息充分、不动 vendor，与 czsc ZS-003 +1 PASS 零回归先例（M2-3）同类；
  - A（改 vendor）否：:118 为全库共享默认路径且无配置旁路，`do_combine` 并集口径破坏既有 expect zs，另需新增级别推导通道（归一化 level 恒 1 无 level=2 输出口径），违反最小 diff，同区域实验已实证净回归（`one_bi_zs=T` -3）；
  - C（永久降级）否：非不可修复项，九段升级为课33 明确形态，补偿收益 chanpy +1 PASS、半径实证 = 1，无挂账理由；
  - 实施验收门（供后续里程碑）：198 全绿 + ZS-003 chanpy 列 FAIL→PASS + bsp-002/bsp-004/seg-005 三用例输出逐字节不变。
- **UP 决策**：B 采纳——批准实施（2026-08-02 UP 确认），另立 M5 实施里程碑

## 4. BI-004 × czsc（min_bi_len + 课77步骤二，P-J）
- **根因复核**：（M2-5 结论）czsc 0.10.12 rust 后端内置 min_bi_len=6（忽略环境变量）→ BI-004 bi_list 空；切 python 后端 min_bi_len=4 出 3 笔，但因无课77步骤二"同性质相邻分型保留更极值者"消解，与 expect 1 笔 (1,9,u) 不一致。
- **探针实证**：（M4-4，探针 `/tmp/m4_probe_czsc.py` + 后端对照探针，只读未改源码）
  - 输出对照：expect bi = 1 笔 `(1,9,up)`；czsc 默认 rust 后端 **bi 表为空**，fx 表 4 条孤立分型 `(1,D)(5,U)(6,D)(9,U)`——fx 多 idx=5/6 两条（无笔时 czsc 候选分型搬运分支 adapter_czsc.py:363-373）、bi 缺 1 条，与校准报告 FAIL 明细（`chanlun-calibration-report.md:152-161`）逐项一致。
  - 后端对照实证：适配器既有通道 `CzscAdapter(min_bi_len=4)` 切 python 后端 → 出 3 笔 `(1,5)up/(5,6)down/(6,9)up`，fx 同为 4 条；课77步骤二"同性质相邻分型保留更极值者"应消解 idx=5 顶/idx=6 底、合并为 1 笔 `(1,9)up`——czsc rust/python 两后端均不实现该消解，实证根因复核 P-J 归因（min_bi_len 之外另有步骤二缺失，单改 min_bi_len 修不好）。
  - 补偿可行性：偏差位于**分型/笔构造层**（czsc 成笔内核）。rust 后端为编译扩展（rs_czsc 内置 min_bi_len=6、忽略环境变量，0.10.12 实证，adapter_czsc.py:64-68），不可改；python 后端 fork 可改，但补步骤二消解=重写 czsc 核心成笔逻辑。适配器层自建成笔=在适配器内重写分型消解+成笔算法，与 recursion 层职责重叠（ADR-010：recursion 列 BI-004 已 PASS，fx/bi 复用 chanpy 适配器）。czsc 列该项边际价值=单级别库对表完整性（chanpy/recursion 两列已 PASS 该形态）。
- **爆炸半径**：czsc 全部 25 个 PASS 用例的 fx/bi 表均出自 czsc 成笔内核；任何形式的成笔层补偿（fork 改内核 / 适配器自建成笔替换输出）半径 = **25 全量**，需逐一复跑。
- **建议**：**C（永久降级，登记附录 C.5）**。判据对照：
  - 补偿点在 vendor 成笔内核，B（适配器补偿）不成立——适配器自建=重写 czsc 核心成笔且与 recursion 层（ADR-010）职责重叠；
  - 半径 = 25 全量，远非零；
  - 收益仅 czsc +1 PASS（bi 单 cell），课77步骤二形态已由 chanpy/recursion 两列覆盖；
  - D（pin 版本+fork）评估：fork czsc python 后端补步骤二消解技术上可行（python `check_bi` 每次调用读 `envs.get_min_bi_len()`，有注入通道），但成本=长期维护整库 fork，收益 +1 cell，不成比例——**不推荐**；若 UP 另有考虑需单独拍板。
- **UP 决策**：C 采纳——永久降级（2026-08-02 UP 确认），已登记附录 C.5

## 5. BSP-002/004 × czsc（无 seg 限制 zs 延伸）
- **根因复核**：czsc 不产出线段，中枢延伸缺 seg 约束口径，BSP-002/004 的 expect bsp 依赖延伸后中枢。
- **探针实证**：（M4-4，探针 `/tmp/m4_probe_czsc.py`，只读未改源码）
  - 输出对照（两用例 bi 表均与 expect 逐字段一致，差异纯在 zs 层）：expect zs = `{zd:18.3 zg:20.2 start:6 end:21 level:1}`；czsc zs = `{18.3, 20.2, 6, 31}`——中枢确立正确（反向笔 bi1(6,11)/bi3(16,21) 配对），但已确认反向笔 bi5(26,31) in_range 被 `_recompute_zs` 延伸分支（adapter_czsc.py:164-172）延展 end 21→31；expect 的 end=21 依赖 chanpy seg 切分限制（zs 只在已确认 seg0 内延伸）。czsc 无 seg，`_recompute_zs` 已知局限注释（adapter_czsc.py:145-147）已登记该偏差；末位笔 bi7(36,41) sure=False 不延伸（M2-3 修正）已生效，缺口恰在"已确认但跨 seg"的 bi5。
  - bsp 维度：czsc bsp 置空属 `na_fields` 契约（不产出买卖点），校准门跳过 bsp 比较，两用例 FAIL 仅 zs cell——修好延伸即两项转 PASS。
  - 补偿可行性：对齐 expect 需在延伸门控引入 seg 约束（"仅已确认 seg 内的反向笔延伸"），即适配器**自建线段**（特征序列分型）——与 recursion 层 L0 走势类型职责重叠（ADR-009，`core/segments.py` 已自建一份），等于在第三处实现线段算法；绕开 seg 的启发式（"延伸最多 N 笔/幅度阈值"）均属语料拟合，违反校准门公平性，不可接受。
- **爆炸半径**：`_recompute_zs` 是 czsc zs 输出的唯一通道。czsc 25 个 PASS 中 expect 含 zs 表（走 `_recompute_zs` 且被校准门检验）共 **8 个**：BC-001 / BSP-001 / ZS-001 / ZS-002 / ZS-003 / ZS-004 / GOLD-003 / GOLD-004（探针 `/tmp/m4_probe_czsc_radius.py` 实证；其余 17 个 PASS 无 zs expect）。其中 ZS-003 PASS 直接依赖当前延伸口径（延伸至 ≥9 笔才触发 `_apply_nine_bi_upgrade` 九段升级），任何延伸门控修改半径 = 8，非零。
- **建议**：**C（永久降级，登记附录 C.5）**。判据对照：
  - B（适配器补偿）否：补偿=适配器自建 seg，与 recursion 层（ADR-009）职责重叠，成本≈第三份线段实现，违反最小 diff；无 seg 的启发式门控=语料拟合作弊；
  - 半径 = 8 非零（ZS-003 直接依赖当前延伸口径），不满足"补偿可严格限定形态且半径=0"的例外条件；
  - chanpy 列 BSP-002 已 PASS、BSP-004 已由 M4-2 建议 B 补偿；"seg 限制延伸"属 seg 上游知识，czsc 架构性无 seg；
  - D（pin 版本+fork）否：无 seg 是 czsc 架构性缺失，fork 补 seg=重写库核心，不成立。
- **UP 决策**：C 采纳——永久降级（2026-08-02 UP 确认），已登记附录 C.5

## 6. GOLD-005 × czsc（zs 构造口径，P-K）
- **根因复核**：（M2-3 结论）GOLD-005 expect 中枢从 bi2 开始（跳过 bi0 引导笔+bi1 离开笔）；czsc 适配器 `_recompute_zs`"反向笔配对"无法复现，涉及走势类型判定。
- **探针实证**：（M4-4，探针 `/tmp/m4_probe_czsc.py`，只读未改源码）
  - 输出对照（bi 表与 expect 逐字段一致，差异纯在 zs 构造口径）：expect zs = `{zd:7.55 zg:7.85 start:9 end:21 level:1}`（课文口径：bi0 引导笔+bi1 离开笔跳过，中枢由 bi2(9,13) 起的反向笔构成，P-K）；czsc zs = `{7.5, 7.85, 5, 25}`——`_recompute_zs` 以 bi0(1,5) 为引导笔、bi1(5,9) 作为首个反向笔参与配对（adapter_czsc.py:155-194），start=5、zd 取 bi1 低点 7.5（vs expect 7.55），bi5(21,25) in_range 延伸 end 至 25（vs expect 21）。
  - 补偿可行性：修正要求"判定 bi1 为离开段笔并跳过"=**走势类型判定**（课文例依赖走势类型的段结构先验），`_recompute_zs` 的"引导笔+反向笔配对"单级别口径无表达通道；"按用例配置起始笔"=语料专属 if，违反校准门公平性（作弊），不可接受；一般化的"跳过离开笔"规则需 seg/走势类型上游信息，回到与 BSP-002/004 同一堵墙（自建 seg 与 recursion 层职责重叠）。
- **爆炸半径**：与第 5 节同通道——`_recompute_zs` 唯一通道，**8 个** zs-PASS 用例（BC-001 / BSP-001 / ZS-001..004 / GOLD-003/004）全部走同一"引导笔+反向笔配对"起点逻辑；尤其 ZS-001/002/004 的 expect zs `start=5`（引导笔后第一反向笔起点）正是当前口径产物，改起点判定直接翻转，半径 = 8 非零。
- **建议**：**C（永久降级，登记附录 C.5）**。判据对照：
  - B（适配器补偿）否：补偿依赖走势类型判定上游信息，`_recompute_zs` 无法表达；语料专属配置=作弊，排除；
  - 半径 = 8 非零，不满足例外条件；
  - GOLD-005 chanpy 列已 PASS，recursion 列 FAIL 属 ADR-010 语料双哲学并存已知项，czsc 列边际价值=对表完整性；
  - D（pin 版本+fork）否：同第 5 节，fork 无法解决"无走势类型判定"的架构性缺失。
- **UP 决策**：C 采纳——永久降级（2026-08-02 UP 确认），已登记附录 C.5

## 7. 汇总与 UP 决策门

### 7.1 八项建议汇总表

| 降级项 | 建议 | 爆炸半径 | 预期收益 | UP 决策 |
|--------|------|----------|----------|---------|
| SEG-004/005 × chanpy | C | 全量 23 PASS（seg 上游） | chanpy +2 PASS | C 采纳（永久降级） |
| BSP-004 × chanpy | B（adapter_chanpy.py:264-278 按 distinct main_type 逐条出记录） | 实证 0（全语料多类型 bsp 仅 1 例） | chanpy +1 PASS | B 采纳（批准实施，另立 M5） |
| ZS-003 × chanpy | B（复合：跨 seg 延伸试探+九段升级，门控=延伸后≥9 笔且 3 子中枢重合） | 触发集 {bsp-002,bsp-004,seg-005,zs-003}，门控下仅 zs-003 落改 | chanpy +1 PASS | B 采纳（批准实施，另立 M5） |
| BI-004 × czsc | C | 25 全量（成笔内核） | czsc +1 PASS | C 采纳（永久降级） |
| BSP-002/004 × czsc | C | 8（_recompute_zs 路径）[^radius8] | czsc +2 PASS | C 采纳（永久降级） |
| GOLD-005 × czsc | C | 8（同上）[^radius8] | czsc +1 PASS | C 采纳（永久降级） |

[^radius8]: 半径=8 为校准门可见口径——SEG-001..005 五个 czsc PASS 用例 czsc zs 实际非空但无 zs expect，改 `_recompute_zs` 可能静默改变其输出。

总账：**B × 2 / C × 6 / D × 0**。8 项全部落地的理论收益：chanpy +4 PASS（SEG-004/005 + BSP-004 + ZS-003，FAIL 8 中其余 4 个为 BSP-003 等其他已知项）、czsc +4 PASS（BI-004 + BSP-002/004 + GOLD-005，FAIL 6 中其余 2 个为其他已知项）。

### 7.2 基线复跑（2026-08-02）

- 全量校准矩阵：`chanpy: PASS 23 / FAIL 8 / ERROR 0`；`czsc: PASS 25 / FAIL 6 / ERROR 0`；`recursion: PASS 18 / FAIL 13 / ERROR 0`（与 M3 基线一致，评估全程只读未破基线）。
- 单测：`198 passed`。

### 7.3 UP 决策（2026-08-02 已决）

- UP 对汇总表逐项拍板：**8 项全部按建议采纳**（B×2 批准实施 / C×6 确认永久降级），无推翻重议。
- B 项（BSP-004 × chanpy、ZS-003 × chanpy）：另立 M5 补丁实施里程碑（新 plan），验收门分别见第 2、3 节"实施验收门"；M4-2 评审提示一并带入——补偿实现时注意同 main_type 去重（T1/T1P 理论可同挂一笔）。
- C 项（6 项）：已登记附录 C.5（2026-08-02 登记块 + 原表状态行统一为"永久降级（M4）"），无任何代码改动，M4 就此收官。
