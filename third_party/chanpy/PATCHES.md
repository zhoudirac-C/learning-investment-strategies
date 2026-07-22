# chan.py vendor 补丁登记

> M2 状态：chan.py 源码零改动（vendored fork，配置/适配器层解决）。
> 已知偏差结论登记在 `docs/design/chanlun-quant-engine.md` 附录 C.5。
> 以下补丁条目在 M2-3~M2-5 排查后如需改源码时补充。

| 文件 | 函数 | 原行为 | 改后行为 | claim id | 用例 id |
|------|------|--------|----------|----------|---------|

## M2-5 专项排查结论（不改源码，登记根因）

### P-J：BI-004 czsc 不成笔（czsc 库行为差异）
- **根因**：czsc 0.10.12 默认 `min_bi_len=6`（rust 后端内置，忽略环境变量），
  BI-004 笔跨度不足（1→5 仅 4 根、5→6 仅 1 根、6→9 仅 3 根）→ bi_list 空。
  切换 python 后端 `min_bi_len=4` 可成笔，但画出 3 笔 `(1,5,u)/(5,6,d)/(6,9,u)`，
  因 czsc 不实现课77 步骤二"同性质相邻分型保留更极值者"消解，与 expect 1 笔
  `(1,9,u)` 不一致。
- **结论**：czsc 库固有行为差异，适配器层不补偿。BI-004 czsc FAIL 为已知偏差。

### P-H：GOLD-001/002 chanpy 笔太少（真实日线数据根因）
- **根因**：GOLD-001（41 根日线）chanpy 仅画 3 笔、GOLD-002 仅 1 笔，
  笔数不足无 zs 无 bsp。expect 期望三买（基于更细笔划分）。
- **结论**：chanpy 笔划分口径在真实数据上偏粗，需 M3 级别递归或 PATCHES 改笔算法。
  当前登记为降级项。

### P-H：GOLD-003/005 chanpy 误一买不报三买（M2-3 已修复 ✅）
- **根因**：chanpy 默认 `bsp3_follow_1=True`，要求三买前必须先有一买。
  GOLD-003/005 课文实例中三买出现前无一买，导致漏报。
  同时 chanpy 报基于末位笔（sure=False）的一卖，与 expect"只列确认 bsp"不一致。
- **修复**：`bsp3_follow_1=False`（三买独立检出）+ 适配器过滤基于末位笔的 bsp
  （`adapter_chanpy.py` bsp 处理：`bi_table[bsp.bi.idx].sure=False` 时跳过）。
- **结果**：GOLD-003/005 chanpy 修复（+2 PASS），无回归。

### P-K：ZS-003 九段升级（czsc 已修复 ✅，chanpy 降级）
- **czsc 修复**：`adapter_czsc.py` 新增 `_apply_nine_bi_upgrade()` 后处理函数——
  中枢范围内笔数 ≥9 时，分 3 组子中枢（每组 3 笔），计算重合区间
  `max(sub_zd)/min(sub_zg)`，升级为 level=2。ZS-003 czsc 修复（+1 PASS），无回归。
- **chanpy 降级**：chanpy zs 受 seg 切分限制（ZS-003 zs end=17，不够 9 段）。
  `one_bi_zs=T` 可构造 3 个子中枢但回归 BSP-002/GOLD-003/005（-3）。
  `combine()` 拒绝合并 one_bi_zs（ZS.py 第 116 行）和跨 seg（第 118 行）。
  需改 chanpy ZSList/ZS 源码实现跨 seg 九段升级，风险高，暂不实施。

### P-K：BC-002 level=2 双中枢（降级）
- **根因**：BC-002 expect level=2 是"笔按线段分组"的大级别中枢，需要线段层支持。
  chanpy/czsc 都不在适配器层产出线段层 level=2（BC-002 的 level=2 不是九段升级，
  而是区间套的大级别中枢）。
- **结论**：需要 M3 级别递归层。当前登记为降级项。

### P-F：SEG-004/005 chanpy seg 拆段过细
- **根因**：chanpy seg 算法（特征序列分型）在 SEG-004/005 拆段过细。
  `left_seg_method=all` 修 SEG-004 但破坏 BC-001/BSP-001/GOLD-004（净 -2，
  SegListComm 注释明示"left=all 容易找不到二类买卖点"）。
  `seg_algo=break`（简化算法）回归 BC-001/GOLD-004 且不修 SEG-004/005。
- **结论**：seg 算法口径差异，单一配置无法解决，需 PATCHES 改 seg 算法或逐用例配置。
  当前登记为降级项。

### P-K：BSP-003/004/GOLD-005 中枢构造口径差异（M2-3 深入排查）
- **根因**：expect 的中枢构造规则不是统一的"反向笔配对"（chanpy normal 模式），
  而是根据走势结构判定中枢起始笔：
  - ZS-001：中枢从 bi1 开始（跳过引导笔 bi0）
  - BSP-003：中枢从 bi0 开始（包含引导笔）
  - GOLD-005：中枢从 bi2 开始（跳过 bi0 引导笔 + bi1 A 段离开笔）
  - BC-001：中枢从 bi1 开始（跳过引导笔 bi0）
  expect 的"离开笔"数量不固定（1~2 笔），判定涉及走势类型（上升/下降/盘整）。
- **结论**：czsc 适配器 `_recompute_zs` 的"反向笔配对"规则无法复现所有 expect
  中枢构造，需深入走势类型判定算法。归 P-K 专项，M2-5 降级项。

### P-K：BSP-004 三买@36 缺失（二三类重合）
- **根因**：BSP-004 expect 三买@36 与二买@36 重合（课21"二三类重合"）。
  chanpy 报一买@26 + 二买@36，但不报三买@36。实验 `strict_bsp3`/`bsp3_peak`/
  `bsp3a_max_zs_cnt` 均无效。chanpy 三买判定逻辑不覆盖"二三类重合"场景。
- **结论**：需 PATCHES 改 chanpy BSPointList 三买判定，或适配器层补偿。
  当前登记为降级项。

