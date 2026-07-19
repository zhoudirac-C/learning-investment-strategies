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
