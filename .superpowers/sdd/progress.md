# SDD Progress: chanlun-quant M1 calibration gate
Plan: docs/superpowers/plans/2026-07-18-chanlun-quant-m1-calibration-gate.md
Constraints: 禁止 git 提交类操作（只读 git 可用）；不碰 chan.py 源码；TDD；.venv (py3.11)；PYTHONPATH=src:third_party/chanpy
Note: 在 master 上工作、不建分支——计划全局约束禁止 git 操作，用户指令优先于 worktree skill。
Task 0: complete (vendor chanpy 429d6ed, czsc 0.10.12, import verified; 主控直接核验)
Task 1-3 (B1): complete (50 tests passed, review clean; Minor x3 记录终审)
  - Minor: builders dispatcher 数值列表报错误导; claim id 正则对引号/尾注释脆弱; 缓存无失效机制
Task 4 (chanpy adapter): complete (4 tests, review Approved; Minor x5 记录)
  - Minor: BSP 分支未被执行过; 空 bars 未处理; fx/bsp sure 为派生非独立信息; seg/zs 覆盖仅手动; 报告措辞过强
Task 5 (czsc adapter): complete (12 tests, fix 后 review Approved; Minor 余项记录)
  - Minor: env-restore 测试只覆盖一分支; zs filter/max_bi_num 无回归测试; 测试输入与 Task4 不同; max_bi_num env 边缘误报
Task 6+7 (B3): complete (146 tests, diff/report + 26 用例; 首评 Not approved: C-1/I-1/M-1/M-2 → 修复后复核 Approved, 见 task-6-7-rereview.md)
  - 关键结论(留 Task 9/ADR-001): "两口径一致不成笔"几何上不存在(口径B恒放行); BI-002 改造为向下笔判别样本; BI-003 左肩抬高合并高
  - 待仲裁(Task 9): BSP dir 语义; BSP-001..003 claim 双挂; BC 面积断言降级(meta 键 vs 注释)
Task 8 (B4 金标): complete (5 条金标 GOLD-001~005: 2 真实日线(baostock)+3 等比 synthetic; 162 tests passed(146+16); ADR-005 降级决策(2007 分钟级双路径证实不可得); 详见 task-8-report.md)
Task 9 (B5 对表+校准报告): complete (Step 1 全量运行 31 用例(chanpy 0 PASS/31 FAIL, czsc 7 PASS/24 FAIL, 0 ERROR); Step 2/3 评审填齐 93 处占位符+M2/M3 重估节; ADR-001~008 全部 resolved by 主控/待 UP 确认; 0 用例错误; P-B/P-C/P-I 等模式均经 /tmp 探针实证; 162 tests 复跑全绿; 详见 task-9-report.md)
  - 遗留: BI-002/003 expect 翻转待 UP 拍板(推荐翻转 bi:[(1,5)]); 全部 ADR 待 UP 确认; UP 评审门(Step 4)待过; GOLD-001/002 的 czsc PASS 系空断言产物需在 M2 重验
Note2: 2026-07-19 用户显式授权 git commit+push（覆盖计划"禁 git"全局约束，一次性指令），M1 全部产出已推 origin/master；.superpowers/sdd/ 原有自忽略约定（sdd/.gitignore=*），为使用户本地可拉取核对评审材料，主控以 git add -f 强制纳入跟踪——如 UP 不同意可 git rm --cached 回退。
M2 (plan: docs/superpowers/plans/2026-07-19-chanlun-quant-m2-calibration-fix.md): started 2026-07-19
  - M2-0: done (BI-002/003 expect 翻转 bi:[(1,5,down/up,False)], UP 拍板; ADR-001 状态 resolved; 162 tests 绿)
  - M2-1: done (adapter_chanpy.py 修复 _apply_positional_sure 缺失; chanpy 10/10 测试绿)
  - M2-2: done (czsc 安装+适配器改造: 首分型补偿+zs 重算+位置约定; czsc +12 PASS)
  - M2-3: done (bsp3_follow_1=False+bsp 过滤修 GOLD-003/005 +2; czsc zs 末位不延伸修 BC-001/BSP-001/GOLD-004 +3; czsc 九段升级修 ZS-003 +1; seg_conf/zs_conf 实验无解→降级)
  - M2-4: done (BI-002/003 expect fx sure 对齐位置约定 +4; sure/level 约定成文 附录 C)
  - M2-5: done (P-J/P-H/P-K/P-F 专项排查+PATCHES.md 登记; 14 降级项根因明确)
  - M2-6: done (重生成 chanlun-calibration-report.md M2 版; 48/62 PASS=77%; 168 tests 绿)
  - 最终: chanpy 23/31 PASS, czsc 25/31 PASS, 总计 48/62=77%; 14 降级项清单见报告+PATCHES.md
M3 递归层 (plan: docs/superpowers/plans/2026-07-29-chanlun-quant-m3-level-recursion.md): started 2026-07-29
  - 架构结论: 递归层**不能依赖适配器 seg 表**(侦察发现 chanpy 对 BC-002 把 9 笔并成 1 段 seg=[[0,8,down]]、czsc 无 seg), 须自建 L0 走势类型; 复用附录 C.4 中枢构造口径(ZD=max(三笔低点)/ZG=min(三笔高点))
  - M3-0: done (写实施计划, 覆盖设计文档第六节全部要点 + 6 降级项)
  - M3-1: done (core/segments.py + core/model.py — L0 走势类型分组: 贪婪最小 3 笔段 + 沿段方向扩展(创极值则吸收); BC-002→A2/B2/C2 三段, SEG-001→两段; 7/7 测试通过)
  - M3-2: done (core/levels.py — LevelTree 递归合成 level-2 中枢 + 通用 3×L_N→L_{N+1}; BC-002 level-2 zs(23.9/26.2,16→31)+level-1 zs(22.9/24.4,31→46); TDD 纠出 bar36 低点手算误读(实际 22.9 非 23.06), expect 正确无需改; 11/11 通过)
  - M3-3: done (core/backchi.py — 面积代理 Σ|Δc| 背驰 + 多级买卖点; BC-002 level-2 进入A2(10.84)vs离开C2(6.04)背驰, 一买 idx=46 level=1+2 双条; 4/4 通过)
  - 测试结果: 全量 183 passed (168+15), 无回归
  - M3-4: done 2026-08-01 (core/engine.py RecursionEngine 第三实现接入校准矩阵; levels.py 抽 find_trend_patterns+synthesize_standalone_zs; backchi.py 加 detect_third_type_bsp 笔级三类买卖点; fxlevel.py 日线箱体三买代理)
  - 验收: BC-002/BSP-003/GOLD-001/GOLD-002 recursion 列全部 PASS（M2 降级 6 项清零）; chanpy 23/czsc 25 不变零回归; recursion 18/31（13 FAIL=中枢构造哲学差异, ADR-010 归因）
  - GOLD-001/002 根因新解: 课文日线三买的次级别是 30 分钟结构, 日线笔/分型均不可达 → 箱体代理(横盘≥15bar+收盘破箱顶+首次回试不破→三买落回试最低低点bar), 仅笔级双空时兜底（ADR-011）
  - M3-5: done 2026-08-01 (ChanPySession/RecursionSession 增量会话; 6 用例批量 vs 逐bar增量终态五表全等硬门; is_sure 透传+增量生长测试)
  - M3-6: done 2026-08-01 (重生成 chanlun-calibration-report.md M3 版 --version M3; ADR-009 L0分组/ADR-010 双哲学/ADR-011 箱体代理; 附录 C.2 level≥2 语义+C.5 刷新; task-m3-report.md)
  - 最终: chanpy 23 + czsc 25 + recursion 18（93 cell）; M2 降级 14 项: 6 项 recursion 覆盖✅, 8 项保持⏸(PATCHES 4 + czsc 局限 4); 198 测试全绿
  - 推送: 3 笔提交已推 origin/master（72b68c5 M3-4 / 737a31d M3-5 / dee39ca M3-6），工作区干净
  - UP 已决 2026-08-02: ADR-009~011 三条全部采纳（adr.md 状态已改 resolved）; M3 评审门通过; 8 项保持降级另立 M4 专项评估（PATCHES 4 需改 chanpy 源码，评估爆炸半径与 vendor 策略）
M4 补丁评估 (plan: docs/superpowers/plans/2026-08-02-chanlun-quant-m4-patch-assessment.md): started 2026-08-02
  - M4-0: complete (commit e842d32, review clean; Minor x2: 政策段插入位置空行后/报告未注 push 授权来源)
  - M4-1: complete (commits 6a3784c..4b6ac6e, review Approved; I-1 修复闭环; 结论: 建议 C 永久降级, 分叉点实为 SegListComm:55-66/:121-129/:132-138 非 EigenFX; Minor x3 记录)
  - M4-2: complete (commit 978160a, review Approved; 结论: 建议 B 适配器补偿——漏报点在 adapter_chanpy.py:272 只取 bsp.type[0], chanpy 内部已算出 T2+T3B; 半径实证=0; Minor x2: 语料计数 32→31 待 M4-5 更正 / push 授权已确认)
  - M4-3: complete (commit 50feebc, review Approved; 结论: 建议 B 复合形态——跨seg延伸试探+九段升级单函数, 门控=延伸后≥9笔且3子中枢重合; brief "仅ZS-003≥9笔"被证伪(实测0); Minor x2: /tmp探针工件脱节(不修) / "22个PASS"→23笔误待 M4-5 更正)
  - M4-4: complete (commit 6c9d9df, review Approved; 结论: BI-004→C(半径25全量) / BSP-002/004→C(自建seg与ADR-009重叠,半径8) / GOLD-005→C(语料专属if=作弊,半径8); D 三项不推荐但登记; Minor x3: SEG-001..005 静默输出口径待汇总节注明 / D 论证详略不均 / 探针逐字不可验证)
  - M4-5: done 2026-08-02 (第 7 节汇总表 Bx2/Cx6/Dx0 + 基线复跑 + 附录 C.5 登记 6 项永久降级 + 笔误修正 32→31 / 22→23)
M4 补丁评估 (plan: docs/superpowers/plans/2026-08-02-chanlun-quant-m4-patch-assessment.md): done 2026-08-02
  - 8 项评估结论见 docs/design/chanlun-m4-patch-assessment.md 第 7 节汇总表
  - 基线复跑: 198 测试全绿; chanpy 23 / czsc 25 / recursion 18 不变
  - UP 已决 2026-08-02: 汇总表 8 项全部按建议采纳——B×2（BSP-004/ZS-003 × chanpy）批准实施另立 M5；C×6 确认永久降级（附录 C.5 状态行已统一 ⛔，报告 UP 决策列全部落账）
  - M4-5: complete (commit 91484fd, review Approved; 汇总表 B×2/C×6/D×0; 附录C.5 登记 6 项 C; 2 处笔误修正)
  - M4 终审: ready for UP 决策门 (review-m4-full.diff 7 commits; Minor 14 条 triage: 5 已关闭/7 不修/2 留后续[T1/T1P去重提示入B实施brief; C.5双轨待UP拍板后统一])

M5 适配器补偿 (plan: docs/superpowers/plans/2026-08-26-chanlun-quant-m5-adapter-compensation.md): done 2026-08-26
  - M5-1: BSP-004 同笔多类型 bsp 按 distinct main_type 逐条出记录 → chanpy 列 FAIL→PASS（三买@36 二三类重合，课21）(commit 3e7cfb0)
  - M5-2: ZS-003 跨 seg 延伸试探+九段升级（门控=延伸后≥9笔且3子中枢重合）→ chanpy 列 FAIL→PASS（level=2 [16.5,17.0]）(commit a112c55)
  - 收官矩阵: chanpy 25 / czsc 25 / recursion 18（chanpy 剩余 6 FAIL 全部有归属：BC-002/BSP-003 recursion 覆盖、SEG-004/005 永久降级、GOLD-001/002 recursion 箱体代理）；单测 202 passed
  - 验收门: bsp-002/bsp-004/seg-005 及其余 chanpy PASS 用例快照逐字节不变（diff 仅 BSP-004/ZS-003 两处预期差异）
  - 正式校准报告未重生成（report.py --version 仅 M1/M2/M3，M5 版本段扩展另立项待 UP 拍板）
