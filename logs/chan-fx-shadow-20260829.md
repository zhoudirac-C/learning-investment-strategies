# B-3 影子证据：递归层内部单元 → 特征序列段（全量语料）

- 用例数：31（cases 26 + golden 5）
- 基线（greedy 内部单元）：21 PASS / 10 FAIL（官方矩阵口径 21/10）
- 影子（fx 内部单元）：19 PASS / 12 FAIL
- 判定变化：2 例

| 用例 | 基线 | 影子 | 判定 |
|---|---|---|---|
| BC-001 | FAIL | FAIL | 不变 |
| BC-002 | PASS | FAIL | 回归 |
| BI-001 | PASS | PASS | 不变 |
| BI-002 | PASS | PASS | 不变 |
| BI-003 | PASS | PASS | 不变 |
| BI-004 | PASS | PASS | 不变 |
| BI-005 | PASS | PASS | 不变 |
| BSP-001 | FAIL | FAIL | 不变 |
| BSP-002 | FAIL | FAIL | 不变 |
| BSP-003 | PASS | FAIL | 回归 |
| BSP-004 | FAIL | FAIL | 不变 |
| FX-001 | PASS | PASS | 不变 |
| FX-002 | PASS | PASS | 不变 |
| FX-003 | PASS | PASS | 不变 |
| INCLUDE-001 | PASS | PASS | 不变 |
| INCLUDE-002 | PASS | PASS | 不变 |
| INCLUDE-003 | PASS | PASS | 不变 |
| SEG-001 | PASS | PASS | 不变 |
| SEG-002 | PASS | PASS | 不变 |
| SEG-003 | PASS | PASS | 不变 |
| SEG-004 | PASS | PASS | 不变 |
| SEG-005 | PASS | PASS | 不变 |
| ZS-001 | FAIL | FAIL | 不变 |
| ZS-002 | FAIL | FAIL | 不变 |
| ZS-003 | PASS | PASS | 不变 |
| ZS-004 | FAIL | FAIL | 不变 |
| GOLD-001 | PASS | PASS | 不变 |
| GOLD-002 | PASS | PASS | 不变 |
| GOLD-003 | FAIL | FAIL | 不变 |
| GOLD-004 | FAIL | FAIL | 不变 |
| GOLD-005 | FAIL | FAIL | 不变 |

## 判定变化明细（影子列 zs/bsp 对 expect 的差异）

### BC-002：PASS → FAIL（回归）

- 表 `zs`：
  - 缺（expect 有影子无）: zs(zd=23.9, zg=26.2, 16→31, L2, sure=True)
  - 缺（expect 有影子无）: zs(zd=22.9, zg=24.4, 31→46, L1, sure=True)
- 表 `bsp`：
  - 缺（expect 有影子无）: bsp(@46, 1买, L2, sure=True)
  - 缺（expect 有影子无）: bsp(@46, 1买, L1, sure=True)

### BSP-003：PASS → FAIL（回归）

- 表 `zs`：
  - 缺（expect 有影子无）: zs(zd=11.4, zg=14.0, 1→16, L1, sure=True)

## 补充查证（手工，2026-08-29）

- **BSP-003 的 bsp 表仍 PASS 是虚通过**：fx 链路下 zs 为空、段合成 bsp 也为空，
  触发 GOLD 日线箱体兜底（`core/fxlevel.detect_box_third_buy`），三买@26 由兜底
  机制碰巧重建，而非"离开中枢+回试不破"的课 20/21 路径。机制变了，结论碰巧一致，
  与 czsc SEG-004/005 的 na_fields 虚通过同类，不应计入"fx 链路保有能力"。
- **BC-002 影子列零产出**：fx 下 zs/bsp 全无（缺 4 条、无多余），区间套结构
  整体消失而非错位——不存在"换个位置还在"的解读空间。
- 既有 10 例 FAIL（ZS-001/002/004、BSP-001/002/004、BC-001、GOLD-003/004/005）
  全部为中枢构造哲学差异（ADR-010），与段分组口径正交，fx 切换不修复也不恶化。

