# 缠论口径校准报告（M1）

- 生成时间：2026-07-19T12:35:17
- 生成命令：`python -m chan_engine.harness.report --cases src/chan_engine/spec/cases --golden src/chan_engine/spec/golden --out docs/design/chanlun-calibration-report.md`
- 用例目录：`src/chan_engine/spec/cases`；金标目录：`src/chan_engine/spec/golden`
- float 容差：0.0（索引/方向/sure/level 永远严格）
- 状态口径：PASS=与 expect 逐字段一致；FAIL=存在口径偏差（M1 预期产出）；ERROR=实现运行崩溃。

## 校准矩阵

| 用例 | 来源 | chanpy | czsc |
| --- | --- | --- | --- |
| BC-001 | case | FAIL | FAIL |
| BC-002 | case | FAIL | FAIL |
| BI-001 | case | FAIL | FAIL |
| BI-002 | case | FAIL | FAIL |
| BI-003 | case | FAIL | FAIL |
| BI-004 | case | FAIL | FAIL |
| BI-005 | case | FAIL | FAIL |
| BSP-001 | case | FAIL | FAIL |
| BSP-002 | case | FAIL | FAIL |
| BSP-003 | case | FAIL | FAIL |
| BSP-004 | case | FAIL | FAIL |
| FX-001 | case | FAIL | FAIL |
| FX-002 | case | FAIL | PASS |
| FX-003 | case | FAIL | PASS |
| INCLUDE-001 | case | FAIL | PASS |
| INCLUDE-002 | case | FAIL | PASS |
| INCLUDE-003 | case | FAIL | PASS |
| SEG-001 | case | FAIL | FAIL |
| SEG-002 | case | FAIL | FAIL |
| SEG-003 | case | FAIL | FAIL |
| SEG-004 | case | FAIL | FAIL |
| SEG-005 | case | FAIL | FAIL |
| ZS-001 | case | FAIL | FAIL |
| ZS-002 | case | FAIL | FAIL |
| ZS-003 | case | FAIL | FAIL |
| ZS-004 | case | FAIL | FAIL |
| GOLD-001 | golden | FAIL | PASS |
| GOLD-002 | golden | FAIL | PASS |
| GOLD-003 | golden | FAIL | FAIL |
| GOLD-004 | golden | FAIL | FAIL |
| GOLD-005 | golden | FAIL | FAIL |

## 统计

| 实现 | PASS | FAIL | ERROR | 合计 |
| --- | --- | --- | --- | --- |
| chanpy | 0 | 31 | 0 | 31 |
| czsc | 7 | 24 | 0 | 31 |

## 偏差明细

### BC-001 × chanpy — FAIL

**fx 表**

- 主键 `(idx=51, type=up)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 主键 `(start_idx=46, end_idx=51, dir=up)` 字段 `sure`：期望 `False`，实际 `True`

**zs 表**

- 主键 `(start_idx=6, end_idx=21)` 字段 `sure`：期望 `True`，实际 `False`
- 主键 `(start_idx=26, end_idx=41)` 字段 `sure`：期望 `True`，实际 `False`

**bsp 表**

- 缺（expect 有，实现无）：`(idx=46, bstype=1, dir=up, level=1, sure=True)`
- 多（expect 无，实现有）：`(idx=46, bstype=1, dir=down, level=1, sure=True)`

### BC-001 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=up, sure=True)`

**zs 表**

- 缺（expect 有，实现无）：`(zd=26.3, zg=29.3, start_idx=6, end_idx=21, level=1, sure=True)`
- 缺（expect 有，实现无）：`(zd=22.7, zg=24.8, start_idx=26, end_idx=41, level=1, sure=True)`
- 多（expect 无，实现有）：`(zd=26.3, zg=29.6, start_idx=1, end_idx=26, level=1, sure=True)`
- 多（expect 无，实现有）：`(zd=22.7, zg=24.8, start_idx=26, end_idx=51, level=1, sure=True)`

### BC-002 × chanpy — FAIL

**fx 表**

- 主键 `(idx=51, type=up)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 主键 `(start_idx=46, end_idx=51, dir=up)` 字段 `sure`：期望 `False`，实际 `True`

**zs 表**

- 缺（expect 有，实现无）：`(zd=23.9, zg=26.2, start_idx=16, end_idx=31, level=2, sure=True)`
- 缺（expect 有，实现无）：`(zd=22.9, zg=24.4, start_idx=31, end_idx=46, level=1, sure=True)`
- 多（expect 无，实现有）：`(zd=25.3, zg=26.5, start_idx=6, end_idx=31, level=1, sure=False)`

**bsp 表**

- 缺（expect 有，实现无）：`(idx=46, bstype=1, dir=up, level=2, sure=True)`
- 缺（expect 有，实现无）：`(idx=46, bstype=1, dir=up, level=1, sure=True)`
- 多（expect 无，实现有）：`(idx=46, bstype=1, dir=down, level=1, sure=True)`

### BC-002 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=up, sure=True)`

**zs 表**

- 缺（expect 有，实现无）：`(zd=23.9, zg=26.2, start_idx=16, end_idx=31, level=2, sure=True)`
- 缺（expect 有，实现无）：`(zd=22.9, zg=24.4, start_idx=31, end_idx=46, level=1, sure=True)`
- 多（expect 无，实现有）：`(zd=25.3, zg=28.0, start_idx=1, end_idx=36, level=1, sure=True)`
- 多（expect 无，实现有）：`(zd=22.9, zg=24.0, start_idx=36, end_idx=51, level=1, sure=True)`

### BI-001 × chanpy — FAIL

**fx 表**

- 主键 `(idx=5, type=up)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 主键 `(start_idx=1, end_idx=5, dir=up)` 字段 `sure`：期望 `False`，实际 `True`

### BI-001 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=down, sure=True)`

### BI-002 × chanpy — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=up, sure=False)`
- 缺（expect 有，实现无）：`(idx=5, type=down, sure=False)`

### BI-002 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=up, sure=False)`

**bi 表**

- 多（expect 无，实现有）：`(start_idx=1, end_idx=5, dir=down, sure=False)`

### BI-003 × chanpy — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=down, sure=False)`
- 缺（expect 有，实现无）：`(idx=5, type=up, sure=False)`

### BI-003 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=down, sure=False)`

**bi 表**

- 多（expect 无，实现有）：`(start_idx=1, end_idx=5, dir=up, sure=False)`

### BI-004 × chanpy — FAIL

**fx 表**

- 主键 `(idx=9, type=up)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 主键 `(start_idx=1, end_idx=9, dir=up)` 字段 `sure`：期望 `False`，实际 `True`

### BI-004 × czsc — FAIL

**fx 表**

- 多（expect 无，实现有）：`(idx=5, type=up, sure=False)`
- 多（expect 无，实现有）：`(idx=6, type=down, sure=False)`
- 主键 `(idx=1, type=down)` 字段 `sure`：期望 `True`，实际 `False`

**bi 表**

- 缺（expect 有，实现无）：`(start_idx=1, end_idx=9, dir=up, sure=False)`

### BI-005 × chanpy — FAIL

**fx 表**

- 主键 `(idx=9, type=down)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 主键 `(start_idx=5, end_idx=9, dir=down)` 字段 `sure`：期望 `False`，实际 `True`

### BI-005 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=down, sure=True)`

### BSP-001 × chanpy — FAIL

**fx 表**

- 主键 `(idx=31, type=up)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 主键 `(start_idx=26, end_idx=31, dir=up)` 字段 `sure`：期望 `False`，实际 `True`

**zs 表**

- 主键 `(start_idx=6, end_idx=21)` 字段 `sure`：期望 `True`，实际 `False`

**bsp 表**

- 缺（expect 有，实现无）：`(idx=26, bstype=1, dir=up, level=1, sure=True)`
- 多（expect 无，实现有）：`(idx=26, bstype=1, dir=down, level=1, sure=True)`

### BSP-001 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=up, sure=True)`

**zs 表**

- 缺（expect 有，实现无）：`(zd=18.3, zg=20.2, start_idx=6, end_idx=21, level=1, sure=True)`
- 多（expect 无，实现有）：`(zd=18.3, zg=20.6, start_idx=1, end_idx=31, level=1, sure=True)`

### BSP-002 × chanpy — FAIL

**fx 表**

- 主键 `(idx=41, type=up)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 主键 `(start_idx=36, end_idx=41, dir=up)` 字段 `sure`：期望 `False`，实际 `True`

**bsp 表**

- 缺（expect 有，实现无）：`(idx=26, bstype=1, dir=up, level=1, sure=True)`
- 缺（expect 有，实现无）：`(idx=36, bstype=2, dir=up, level=1, sure=True)`
- 多（expect 无，实现有）：`(idx=26, bstype=1, dir=down, level=1, sure=True)`
- 多（expect 无，实现有）：`(idx=36, bstype=2, dir=down, level=1, sure=True)`

### BSP-002 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=up, sure=True)`

**zs 表**

- 缺（expect 有，实现无）：`(zd=18.3, zg=20.2, start_idx=6, end_idx=21, level=1, sure=True)`
- 多（expect 无，实现有）：`(zd=18.3, zg=20.6, start_idx=1, end_idx=41, level=1, sure=True)`

### BSP-003 × chanpy — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=21, type=up, sure=True)`
- 缺（expect 有，实现无）：`(idx=26, type=down, sure=True)`
- 主键 `(idx=31, type=up)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 缺（expect 有，实现无）：`(start_idx=16, end_idx=21, dir=up, sure=True)`
- 缺（expect 有，实现无）：`(start_idx=21, end_idx=26, dir=down, sure=True)`
- 缺（expect 有，实现无）：`(start_idx=26, end_idx=31, dir=up, sure=False)`
- 多（expect 无，实现有）：`(start_idx=16, end_idx=31, dir=up, sure=True)`

**zs 表**

- 缺（expect 有，实现无）：`(zd=11.4, zg=14.0, start_idx=1, end_idx=16, level=1, sure=True)`

**bsp 表**

- 缺（expect 有，实现无）：`(idx=26, bstype=3, dir=up, level=1, sure=True)`

### BSP-003 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=up, sure=True)`

**zs 表**

- 缺（expect 有，实现无）：`(zd=11.4, zg=14.0, start_idx=1, end_idx=16, level=1, sure=True)`
- 多（expect 无，实现有）：`(zd=11.4, zg=14.0, start_idx=1, end_idx=21, level=1, sure=True)`

### BSP-004 × chanpy — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=31, type=up, sure=True)`
- 缺（expect 有，实现无）：`(idx=36, type=down, sure=True)`
- 主键 `(idx=41, type=up)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 缺（expect 有，实现无）：`(start_idx=26, end_idx=31, dir=up, sure=True)`
- 缺（expect 有，实现无）：`(start_idx=31, end_idx=36, dir=down, sure=True)`
- 缺（expect 有，实现无）：`(start_idx=36, end_idx=41, dir=up, sure=False)`
- 多（expect 无，实现有）：`(start_idx=26, end_idx=41, dir=up, sure=True)`

**zs 表**

- 主键 `(start_idx=6, end_idx=21)` 字段 `sure`：期望 `True`，实际 `False`

**bsp 表**

- 缺（expect 有，实现无）：`(idx=26, bstype=1, dir=up, level=1, sure=True)`
- 缺（expect 有，实现无）：`(idx=36, bstype=2, dir=up, level=1, sure=True)`
- 缺（expect 有，实现无）：`(idx=36, bstype=3, dir=up, level=1, sure=True)`
- 多（expect 无，实现有）：`(idx=26, bstype=1, dir=down, level=1, sure=True)`

### BSP-004 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=up, sure=True)`

**zs 表**

- 缺（expect 有，实现无）：`(zd=18.3, zg=20.2, start_idx=6, end_idx=21, level=1, sure=True)`
- 多（expect 无，实现有）：`(zd=18.3, zg=20.6, start_idx=1, end_idx=41, level=1, sure=True)`

### FX-001 × chanpy — FAIL

**fx 表**

- 主键 `(idx=5, type=down)` 字段 `sure`：期望 `False`，实际 `True`

### FX-001 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=up, sure=True)`

### FX-002 × chanpy — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=up, sure=False)`

### FX-003 × chanpy — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=2, type=up, sure=False)`

### INCLUDE-001 × chanpy — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=up, sure=False)`

### INCLUDE-002 × chanpy — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=down, sure=False)`

### INCLUDE-003 × chanpy — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=up, sure=False)`

### SEG-001 × chanpy — FAIL

**fx 表**

- 主键 `(idx=25, type=down)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 主键 `(start_idx=21, end_idx=25, dir=down)` 字段 `sure`：期望 `False`，实际 `True`

### SEG-001 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=down, sure=True)`

### SEG-002 × chanpy — FAIL

**fx 表**

- 主键 `(idx=25, type=up)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 主键 `(start_idx=21, end_idx=25, dir=up)` 字段 `sure`：期望 `False`，实际 `True`

### SEG-002 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=up, sure=True)`

### SEG-003 × chanpy — FAIL

**fx 表**

- 主键 `(idx=25, type=down)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 主键 `(start_idx=21, end_idx=25, dir=down)` 字段 `sure`：期望 `False`，实际 `True`

**seg 表**

- 主键 `(start_bi=0, end_bi=2, dir=up)` 字段 `sure`：期望 `True`，实际 `False`

### SEG-003 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=down, sure=True)`

### SEG-004 × chanpy — FAIL

**fx 表**

- 主键 `(idx=21, type=up)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 主键 `(start_idx=17, end_idx=21, dir=up)` 字段 `sure`：期望 `False`，实际 `True`

**seg 表**

- 缺（expect 有，实现无）：`(start_bi=0, end_bi=4, dir=up, sure=False)`
- 多（expect 无，实现有）：`(start_bi=0, end_bi=0, dir=up, sure=False)`
- 多（expect 无，实现有）：`(start_bi=1, end_bi=3, dir=down, sure=False)`

### SEG-004 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=down, sure=True)`

### SEG-005 × chanpy — FAIL

**fx 表**

- 主键 `(idx=49, type=up)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 主键 `(start_idx=45, end_idx=49, dir=up)` 字段 `sure`：期望 `False`，实际 `True`

**seg 表**

- 缺（expect 有，实现无）：`(start_bi=0, end_bi=8, dir=down, sure=True)`
- 多（expect 无，实现有）：`(start_bi=0, end_bi=0, dir=down, sure=False)`
- 多（expect 无，实现有）：`(start_bi=1, end_bi=3, dir=up, sure=False)`
- 多（expect 无，实现有）：`(start_bi=4, end_bi=8, dir=down, sure=False)`

### SEG-005 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=up, sure=True)`

### ZS-001 × chanpy — FAIL

**fx 表**

- 主键 `(idx=21, type=up)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 主键 `(start_idx=17, end_idx=21, dir=up)` 字段 `sure`：期望 `False`，实际 `True`

**zs 表**

- 主键 `(start_idx=5, end_idx=17)` 字段 `sure`：期望 `True`，实际 `False`

### ZS-001 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=down, sure=True)`

**zs 表**

- 缺（expect 有，实现无）：`(zd=18.0, zg=19.0, start_idx=5, end_idx=17, level=1, sure=True)`
- 多（expect 无，实现有）：`(zd=17.0, zg=19.0, start_idx=1, end_idx=21, level=1, sure=True)`

### ZS-002 × chanpy — FAIL

**fx 表**

- 主键 `(idx=29, type=up)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 主键 `(start_idx=25, end_idx=29, dir=up)` 字段 `sure`：期望 `False`，实际 `True`

**zs 表**

- 主键 `(start_idx=5, end_idx=25)` 字段 `sure`：期望 `True`，实际 `False`

### ZS-002 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=down, sure=True)`

**zs 表**

- 缺（expect 有，实现无）：`(zd=17.0, zg=18.0, start_idx=5, end_idx=25, level=1, sure=True)`
- 多（expect 无，实现有）：`(zd=16.0, zg=18.0, start_idx=1, end_idx=29, level=1, sure=True)`

### ZS-003 × chanpy — FAIL

**fx 表**

- 主键 `(idx=45, type=up)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 主键 `(start_idx=41, end_idx=45, dir=up)` 字段 `sure`：期望 `False`，实际 `True`

**zs 表**

- 缺（expect 有，实现无）：`(zd=16.5, zg=17.0, start_idx=5, end_idx=41, level=2, sure=True)`
- 多（expect 无，实现有）：`(zd=16.0, zg=17.0, start_idx=5, end_idx=17, level=1, sure=True)`

### ZS-003 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=down, sure=True)`

**zs 表**

- 缺（expect 有，实现无）：`(zd=16.5, zg=17.0, start_idx=5, end_idx=41, level=2, sure=True)`
- 多（expect 无，实现有）：`(zd=15.0, zg=17.0, start_idx=1, end_idx=45, level=1, sure=True)`

### ZS-004 × chanpy — FAIL

**fx 表**

- 主键 `(idx=37, type=up)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 主键 `(start_idx=33, end_idx=37, dir=up)` 字段 `sure`：期望 `False`，实际 `True`

**zs 表**

- 主键 `(start_idx=5, end_idx=17)` 字段 `sure`：期望 `True`，实际 `False`
- 主键 `(start_idx=21, end_idx=33)` 字段 `sure`：期望 `True`，实际 `False`

### ZS-004 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=down, sure=True)`

**zs 表**

- 缺（expect 有，实现无）：`(zd=13.0, zg=14.0, start_idx=5, end_idx=17, level=1, sure=True)`
- 缺（expect 有，实现无）：`(zd=17.0, zg=18.0, start_idx=21, end_idx=33, level=1, sure=True)`
- 多（expect 无，实现有）：`(zd=12.0, zg=14.0, start_idx=1, end_idx=21, level=1, sure=True)`
- 多（expect 无，实现有）：`(zd=17.0, zg=18.0, start_idx=21, end_idx=37, level=1, sure=True)`

### GOLD-001 × chanpy — FAIL

**bsp 表**

- 缺（expect 有，实现无）：`(idx=34, bstype=3, dir=up, level=1, sure=True)`

### GOLD-002 × chanpy — FAIL

**bsp 表**

- 缺（expect 有，实现无）：`(idx=21, bstype=3, dir=up, level=1, sure=True)`

### GOLD-003 × chanpy — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=21, type=up, sure=True)`
- 缺（expect 有，实现无）：`(idx=25, type=down, sure=True)`
- 主键 `(idx=29, type=up)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 缺（expect 有，实现无）：`(start_idx=17, end_idx=21, dir=up, sure=True)`
- 缺（expect 有，实现无）：`(start_idx=21, end_idx=25, dir=down, sure=True)`
- 缺（expect 有，实现无）：`(start_idx=25, end_idx=29, dir=up, sure=False)`
- 多（expect 无，实现有）：`(start_idx=17, end_idx=29, dir=up, sure=True)`

**zs 表**

- 主键 `(start_idx=5, end_idx=17)` 字段 `sure`：期望 `True`，实际 `False`

**bsp 表**

- 缺（expect 有，实现无）：`(idx=25, bstype=3, dir=up, level=1, sure=True)`
- 多（expect 无，实现有）：`(idx=29, bstype=1, dir=up, level=1, sure=True)`

### GOLD-003 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=down, sure=True)`

**zs 表**

- 缺（expect 有，实现无）：`(zd=2760.0, zg=2858.0, start_idx=5, end_idx=17, level=1, sure=True)`
- 多（expect 无，实现有）：`(zd=2760.0, zg=2858.0, start_idx=1, end_idx=21, level=1, sure=True)`

### GOLD-004 × chanpy — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=13, type=up, sure=True)`
- 缺（expect 有，实现无）：`(idx=17, type=down, sure=True)`
- 缺（expect 有，实现无）：`(idx=21, type=up, sure=True)`
- 缺（expect 有，实现无）：`(idx=25, type=down, sure=True)`
- 缺（expect 有，实现无）：`(idx=29, type=up, sure=True)`
- 缺（expect 有，实现无）：`(idx=33, type=down, sure=True)`
- 主键 `(idx=41, type=down)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 缺（expect 有，实现无）：`(start_idx=9, end_idx=13, dir=up, sure=True)`
- 缺（expect 有，实现无）：`(start_idx=13, end_idx=17, dir=down, sure=True)`
- 缺（expect 有，实现无）：`(start_idx=17, end_idx=21, dir=up, sure=True)`
- 缺（expect 有，实现无）：`(start_idx=21, end_idx=25, dir=down, sure=True)`
- 缺（expect 有，实现无）：`(start_idx=25, end_idx=29, dir=up, sure=True)`
- 缺（expect 有，实现无）：`(start_idx=29, end_idx=33, dir=down, sure=True)`
- 缺（expect 有，实现无）：`(start_idx=33, end_idx=37, dir=up, sure=True)`
- 多（expect 无，实现有）：`(start_idx=9, end_idx=37, dir=up, sure=True)`
- 主键 `(start_idx=37, end_idx=41, dir=down)` 字段 `sure`：期望 `False`，实际 `True`

**zs 表**

- 缺（expect 有，实现无）：`(zd=38.6, zg=39.5, start_idx=5, end_idx=17, level=1, sure=True)`
- 缺（expect 有，实现无）：`(zd=40.7, zg=41.3, start_idx=21, end_idx=33, level=1, sure=True)`

**bsp 表**

- 缺（expect 有，实现无）：`(idx=37, bstype=1, dir=down, level=1, sure=True)`

### GOLD-004 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=down, sure=True)`

**zs 表**

- 缺（expect 有，实现无）：`(zd=38.6, zg=39.5, start_idx=5, end_idx=17, level=1, sure=True)`
- 缺（expect 有，实现无）：`(zd=40.7, zg=41.3, start_idx=21, end_idx=33, level=1, sure=True)`
- 多（expect 无，实现有）：`(zd=38.5, zg=39.5, start_idx=1, end_idx=21, level=1, sure=True)`
- 多（expect 无，实现有）：`(zd=40.7, zg=41.3, start_idx=21, end_idx=41, level=1, sure=True)`

### GOLD-005 × chanpy — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=25, type=up, sure=True)`
- 缺（expect 有，实现无）：`(idx=29, type=down, sure=True)`
- 主键 `(idx=33, type=up)` 字段 `sure`：期望 `False`，实际 `True`

**bi 表**

- 缺（expect 有，实现无）：`(start_idx=21, end_idx=25, dir=up, sure=True)`
- 缺（expect 有，实现无）：`(start_idx=25, end_idx=29, dir=down, sure=True)`
- 缺（expect 有，实现无）：`(start_idx=29, end_idx=33, dir=up, sure=False)`
- 多（expect 无，实现有）：`(start_idx=21, end_idx=33, dir=up, sure=True)`

**zs 表**

- 主键 `(start_idx=9, end_idx=21)` 字段 `sure`：期望 `True`，实际 `False`

**bsp 表**

- 缺（expect 有，实现无）：`(idx=29, bstype=3, dir=up, level=1, sure=True)`
- 多（expect 无，实现有）：`(idx=33, bstype=1, dir=up, level=1, sure=True)`

### GOLD-005 × czsc — FAIL

**fx 表**

- 缺（expect 有，实现无）：`(idx=1, type=up, sure=True)`

**zs 表**

- 缺（expect 有，实现无）：`(zd=7.55, zg=7.85, start_idx=9, end_idx=21, level=1, sure=True)`
- 多（expect 无，实现有）：`(zd=7.5, zg=7.6, start_idx=1, end_idx=25, level=1, sure=True)`

## 口径偏差清单

> 每条偏差的【原文依据 / 仲裁结论 / M2 改造点】已由 Task 9 Step 2/3 评审填写。
> 仲裁依据 docs/design/chanlun-quant-adr.md（ADR-001~008，均 resolved by 主控 / 待 UP 确认）；
> P-B/P-C/P-I 等偏差模式经 /tmp 探针实证（证据与归类统计见 .superpowers/sdd/task-9-report.md）。

### 偏差 1：BC-001

- 规则源 claim：claim-20070118-001-a, claim-20070118-001-b
- chan.py 行为：FAIL — fx 表：字段不一致 1 处；bi 表：字段不一致 1 处；zs 表：字段不一致 2 处；bsp 表：缺 1 条、多 1 条
- czsc 行为：FAIL — fx 表：缺 1 条；zs 表：缺 2 条、多 2 条
- 原文依据：claim-20070118-001-a（课24）："C 段的走势类型完成时对应的 MACD 柱子面积（向上的看红柱子，向下看绿柱子）比 A 段对应的面积要小，这时候就构成标准的背弛"；claim-20070118-001-b（课24）："任一背驰都必然制造某级别的买卖点，任一级别的买卖点都必然源自某级别走势的背驰"。
- 仲裁结论：chanpy=【实现偏差】：末位 fx/bi sure（P-A 语义差）+ 两处 zs sure（P-G 语义差，探针实证其原生 zs 的 zd/zg/端点与 expect 完全一致）+ bsp dir 反（P-E，ADR-006 已仲裁=操作方向）；czsc=【实现偏差】：缺首分型 fx@1（P-C 语义差，探针实证该分型在 czsc 原始输出中存在、被 fx_list 构造丢弃）+ zs 窗口偏移（P-D）。用例无误；MACD 面积断言按 ADR-008 降级 expect.meta 键，M1 不参与 diff。
- M2 改造点：chanpy 适配器归一层：统一 sure 约定（末位未确认 fx/bi→sure=False；zs 形成即 sure=True）+ bsp dir 映射翻转（is_buy→up）；czsc 适配器层：补偿首分型（bi_list[0].fx_a，sure=True）+ zs 弃 get_zs_seq 窗口按引擎约定从归一 bi 表重算；引擎约定：ADR-008 面积断言（expect.meta）接入 diff 比对。

### 偏差 2：BC-002

- 规则源 claim：claim-20070202-001-c
- chan.py 行为：FAIL — fx 表：字段不一致 1 处；bi 表：字段不一致 1 处；zs 表：缺 2 条、多 1 条；bsp 表：缺 2 条、多 1 条
- czsc 行为：FAIL — fx 表：缺 1 条；zs 表：缺 2 条、多 2 条
- 原文依据：claim-20070202-001-c（课27）："某大级别的转折点，可以通过不同级别背驰段的逐级收缩范围而确定……直到最低级别，相应的转折点就在该级别背驰段确定的范围内"。
- 仲裁结论：chanpy=【实现偏差】：末位 sure（P-A）+ bsp dir 反（P-E）+ zs 数值/窗口/级别差（P-K：探针实证同 bi 序列下 chanpy 原生 zs 仅 (25.3,26.5,6,31) 一条 5 笔合并中枢，与 expect 两个中枢均不同，且无 level=2 表达）；czsc=【实现偏差】：缺首分型（P-C）+ zs 窗口偏移（P-D）。用例无误；level=2 断言是引擎模型对区间套两层的合法表达，两实现归一层 level 恒 1 属实现能力缺口；面积断言同 ADR-008 降级。
- M2 改造点：chanpy 适配器归一层：sure 统一 + bsp dir 翻转；chanpy 配置层：排查 zs_conf（zs_combine/zs_algo）对该合并行为的解释，配置不能解决则登记 M2 补丁项；czsc 适配器层：首分型补偿 + zs 重算；引擎约定：level 归一规则定义（九段升级/嵌套推导，依赖 M3 递归层的部分登记 M3）+ ADR-008 meta 面积断言启用。

### 偏差 3：BI-001

- 规则源 claim：claim-20070905-001-b
- chan.py 行为：FAIL — fx 表：字段不一致 1 处；bi 表：字段不一致 1 处
- czsc 行为：FAIL — fx 表：缺 1 条
- 原文依据：claim-20070905-001-b（课77）："笔，必须是一顶一底，而且顶和底之间至少有一个 K 线不属于顶分型与底分型……顶分型中最高那 K 线的区间至少要有一部分高于底分型中最低那 K 线的区间"。
- 仲裁结论：chanpy=【实现偏差】：仅末位 fx/bi sure（P-A 语义差；笔结构 1→5 与 expect 一致）；czsc=【实现偏差】：仅缺首分型 fx@1（P-C 语义差，探针实证 bi_list[0].fx_a=(1,底分型) 存在于 czsc 原始输出、被 fx_list=Σbi.fxs[1:] 构造丢弃）。用例无误。
- M2 改造点：chanpy 适配器归一层：末位未确认 fx/bi 归一为 sure=False（P-A 项）；czsc 适配器层：补偿首分型（P-C 项）。

### 偏差 4：BI-002

- 规则源 claim：claim-20070905-001-b
- chan.py 行为：FAIL — fx 表：缺 2 条
- czsc 行为：FAIL — fx 表：缺 1 条；bi 表：多 1 条
- 原文依据：claim-20070905-001-b（课77）："在同一笔中，顶分型中最高那 K 线的区间至少要有一部分高于底分型中最低那 K 线的区间，如果这条都不满足，也就是顶都在低的范围内或顶比底还低，这显然是不可接受的"——"最高那 K 线的区间"存在"该 K 线自身区间"与"分型合并区间"两种读法（ADR-001）。
- 仲裁结论：【原文歧义】→ ADR-001 已仲裁=B（分型中间 K 线自身区间）；chanpy=口径 A 实现（探针实证 strict 区间检查拒掉唯一候选笔、bi_list=[] 致 fx 表空；loss 下出 (1,5,down) 笔），czsc=口径 B 实现（画出 (1,5,down)），各代表一种读法，均非实现缺陷；expect(bi:[]) 系口径 A 判决，相对 B 属用例口径不一致，M2 按 B 配 chanpy 后用例 expect 待 UP 拍板翻转，M1 不动用例。另：czsc 缺 fx@1 属 P-C 语义差（独立问题）。
- M2 改造点：chanpy 配置层：bi_fx_check strict→loss（ADR-001 连带）；用例层：expect 翻转——(a) 翻转为 bi:[(1,5,down,False)] 保持全库单一口径（推荐）/(b) 保留 A/B 对照样本并 meta 标注不参与 PASS 统计，待 UP 评审门拍板；czsc 适配器层：补偿首分型。

### 偏差 5：BI-003

- 规则源 claim：claim-20070905-001-b
- chan.py 行为：FAIL — fx 表：缺 2 条
- czsc 行为：FAIL — fx 表：缺 1 条；bi 表：多 1 条
- 原文依据：同偏差 4——claim-20070905-001-b（课77）区间句（本例为向上笔判别样本，左肩大区间 K 线抬高合并高：口径 A 下顶在底范围内不成笔，口径 B 下成笔）。
- 仲裁结论：【原文歧义】→ ADR-001 已仲裁=B；chanpy=口径 A 实现（探针实证 strict 拒笔 bi_list=[]、loss 出 (1,5,up)），czsc=口径 B 实现（画出 (1,5,up)），各代表一种读法，非实现缺陷；expect(bi:[]) 系口径 A 判决，待 UP 拍板翻转。另：czsc 缺 fx@1 属 P-C；chanpy 缺 fx@1/@5 为 strict 拒笔下游（loss 下随笔恢复，sure 口径仍需 P-A 项处理）。
- M2 改造点：同偏差 4——chanpy 配置层 bi_fx_check→loss；用例 expect 翻转待 UP 拍板；czsc 适配器层补偿首分型。

### 偏差 6：BI-004

- 规则源 claim：claim-20070716-001-b, claim-20070905-001-b
- chan.py 行为：FAIL — fx 表：字段不一致 1 处；bi 表：字段不一致 1 处
- czsc 行为：FAIL — fx 表：多 2 条、字段不一致 1 处；bi 表：缺 1 条
- 原文依据：claim-20070905-001-b（课77）步骤二："如果前后两分型是同一性质的，对于顶，前面的低于后面的，只保留后面的，前面那个可以 X 掉"；claim-20070716-001-b（课65）："线段被破坏，当且仅当至少被有重叠部分的连续三笔的其中一笔破坏"（反向结构出现前旧结构不完成的确认思想——旧顶@5 未被反向笔确认，故可被更高顶@9 取代）。
- 仲裁结论：chanpy=【实现偏差】：仅末位 fx@9/bi(1,9) sure（P-A；其 fx/bi 结构与 expect 完全一致，实证 chanpy 已正确执行课77 步骤二）；czsc=【实现偏差】（P-J）：探针实证 czsc 多出 fx@5(顶)/fx@6(底)（课62 双条件下确为合法分型，但 5→6 仅距 1 根 K 线且共用 K 线，按课77 不可能成笔、应被消解），且 bi_list 全空——未执行同性质分型保留规则、笔构造停滞。用例无误（expect 与课77 步骤二/三一致；用例注释"bar6/bar7 间无底分型"表述不严谨——bar6 按课62 双条件实为底分型——不影响 expect 正确性，记录备查）。
- M2 改造点：chanpy 适配器归一层：末位 sure 归一（P-A 项）；czsc 层：登记 M2 专项核对笔构造对"间距过近不成笔 fx 对"的消解逻辑（czsc 库行为差致笔全丢，适配器层无法低成本补偿）。

### 偏差 7：BI-005

- 规则源 claim：claim-20071217-001-a, claim-20070905-001-b
- chan.py 行为：FAIL — fx 表：字段不一致 1 处；bi 表：字段不一致 1 处
- czsc 行为：FAIL — fx 表：缺 1 条
- 原文依据：claim-20071217-001-a（课91）："任何的当下，在任何时间周期的 K 线图中，走势必然落在一确定的具有明确方向的笔当中……任何的当下，都只有这四种状态，这四种状态描述了所有的当下走势。更关键的是，这四种状态是不能随便连接的"；claim-20070905-001-b（课77）笔定义。
- 仲裁结论：chanpy=【实现偏差】：末位 fx@9/bi(5,9) sure（P-A）；czsc=【实现偏差】：缺首分型 fx@1（P-C）。用例无误（四状态迁移链结构两实现均吻合）。
- M2 改造点：chanpy 适配器归一层 sure 统一（P-A 项）；czsc 适配器层首分型补偿（P-C 项）。

### 偏差 8：BSP-001

- 规则源 claim：claim-20070105-001-b, claim-20070109-001-a, claim-20070118-001-b
- chan.py 行为：FAIL — fx 表：字段不一致 1 处；bi 表：字段不一致 1 处；zs 表：字段不一致 1 处；bsp 表：缺 1 条、多 1 条
- czsc 行为：FAIL — fx 表：缺 1 条；zs 表：缺 1 条、多 1 条
- 原文依据：claim-20070109-001-a（课21）："这三类买卖点，都是被理论所保证的，100% 安全的买卖点"；claim-20070118-001-b（课24）："任一背驰都必然制造某级别的买卖点"（一买源自背驰）；claim-20070105-001-b（课20，计划挂接）第三类买卖点定理。
- 仲裁结论：chanpy=【实现偏差】：末位 sure（P-A）+ zs sure（P-G，探针实证原生 zs (18.3,20.2,6,21) 数值全对、仅 is_sure 语义不同）+ bsp dir 反（P-E，ADR-006）；czsc=【实现偏差】：缺 fx@1（P-C）+ zs 窗口偏移（P-D：缺 (18.3,20.2,6,21) 多 (18.3,20.6,1,31)，zd 对、zg/端点随窗口变）。用例无误（claim 多挂按 ADR-007 允许）。
- M2 改造点：chanpy 适配器归一层：sure 统一 + bsp dir 翻转；czsc 适配器层：首分型补偿 + zs 按引擎约定从归一 bi 表重算。

### 偏差 9：BSP-002

- 规则源 claim：claim-20071024-001-b, claim-20071024-001-c, claim-20070109-001-b
- chan.py 行为：FAIL — fx 表：字段不一致 1 处；bi 表：字段不一致 1 处；bsp 表：缺 2 条、多 2 条
- czsc 行为：FAIL — fx 表：缺 1 条；zs 表：缺 1 条、多 1 条
- 原文依据：claim-20071024-001-c（课86）："第一类买点次级别上去后，次级别回跌，只要不破第一类买点的位置，就介入"；claim-20070109-001-b（课21）："第二类买点与第一类买点前后相连，是第一类买点出现后第二段次级别走势的低点"。
- 仲裁结论：chanpy=【实现偏差】：末位 sure（P-A）+ bsp dir 反×2（P-E：一买@26/二买@36 的 dir 均反）；czsc=【实现偏差】：缺 fx@1（P-C）+ zs 窗口偏移（P-D）。用例无误。
- M2 改造点：chanpy 适配器归一层：sure 统一 + bsp dir 翻转；czsc 适配器层：首分型补偿 + zs 重算。

### 偏差 10：BSP-003

- 规则源 claim：claim-20070109-001-b, claim-20070105-001-b
- chan.py 行为：FAIL — fx 表：缺 2 条、字段不一致 1 处；bi 表：缺 3 条、多 1 条；zs 表：缺 1 条；bsp 表：缺 1 条
- czsc 行为：FAIL — fx 表：缺 1 条；zs 表：缺 1 条、多 1 条
- 原文依据：claim-20070105-001-b（课20）："一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破 ZG，则构成第三类买点……必须要注意，并不是任何回调回抽都是第三类买卖点，必须是第一次"；claim-20070109-001-b（课21，计划挂接）。
- 仲裁结论：chanpy=【原文歧义】（P-I）：strict 区间检查吞掉中间笔 16→21/21→26（3 笔并 1 笔 16→31），探针实证 loss 下三笔全部恢复且与 expect 一致——归 ADR-001=B，chanpy 为口径 A 实现、非算法缺陷；叠加【实现偏差】：末位 sure（P-A）+ zs 未检出（P-K：探针实证 loss 下 bi 已与 expect 一致而 chanpy 原生 zs_list 仍为空，6 笔重叠未出中枢，非 P-I 下游，三买缺系其前提未检出）。czsc=【实现偏差】：缺 fx@1（P-C）+ zs end 延展（P-D：(11.4,14.0,1,21) vs expect (11.4,14.0,1,16)）。用例无误。
- M2 改造点：chanpy 配置层：bi_fx_check→loss（P-I 项）+ 排查 zs_conf（6 笔重叠不出中枢，配置不能解决则登记补丁项）+ zs 修复后复验 bsp 检出；chanpy 适配器归一层：sure 统一；czsc 适配器层：首分型补偿 + zs 重算。

### 偏差 11：BSP-004

- 规则源 claim：claim-20070109-001-b
- chan.py 行为：FAIL — fx 表：缺 2 条、字段不一致 1 处；bi 表：缺 3 条、多 1 条；zs 表：字段不一致 1 处；bsp 表：缺 3 条、多 1 条
- czsc 行为：FAIL — fx 表：缺 1 条；zs 表：缺 1 条、多 1 条
- 原文依据：claim-20070109-001-b（课21）："只有第二类买点与第三类买点是可能产生重合的……当第一类买点出现后，一个次级别走势凌厉地直接上破前面下跌的最后一个中枢，然后在其上次级别回抽不触及该中枢……一个大级别的上涨往往就会出现"。
- 仲裁结论：chanpy=【原文歧义】（P-I）：strict 吞中间笔 26→31/31→36（并成 26→41），探针实证 loss 下 8 笔全部恢复与 expect 一致；叠加【实现偏差】：末位 sure（P-A）+ zs sure（P-G）+ bsp dir 反（P-E：loss 下 (26,1)/(36,2) 检出但 dir=down vs expect up）+ 三买@36 未检出（P-H 家族：bi/zs 修复后仍缺，bsp 检出条件差）。czsc=【实现偏差】：缺 fx@1（P-C）+ zs 窗口偏移（P-D）。用例无误（同 idx 两条 bsp 表达二三类重合，schema 合法）。
- M2 改造点：chanpy 配置层：bi_fx_check→loss + 排查 bsp_conf（三买检出条件）；chanpy 适配器归一层：sure 统一 + bsp dir 翻转；czsc 适配器层：首分型补偿 + zs 重算。

### 偏差 12：FX-001

- 规则源 claim：claim-20070630-001-a
- chan.py 行为：FAIL — fx 表：字段不一致 1 处
- czsc 行为：FAIL — fx 表：缺 1 条
- 原文依据：claim-20070630-001-a（课62）："第二 K 线高点是相邻三 K 线高点中最高的，而低点也是相邻三 K 线低点中最高的，本 ID 给一个定义叫顶分型；图 2 这种叫底分型，第二 K 线低点是相邻三 K 线低点中最低的，而高点也是相邻三 K 线高点中最低的"。
- 仲裁结论：chanpy=【实现偏差】：末位 fx@5 sure（P-A：chanpy 分型无独立 is_sure、归一取所在笔 is_sure=笔已成立，与引擎"右侧确认"约定不同——语义差）；czsc=【实现偏差】：缺首分型 fx@1（P-C）。用例无误。
- M2 改造点：chanpy 适配器归一层：末位未确认 fx/bi→sure=False（P-A 项）；czsc 适配器层：首分型补偿（P-C 项）。

### 偏差 13：FX-002

- 规则源 claim：claim-20070924-001-c, claim-20070630-001-a
- chan.py 行为：FAIL — fx 表：缺 1 条
- czsc 行为：PASS（与 expect 一致）
- 原文依据：claim-20070924-001-c（课82）："如果该 5 分钟中枢或 1 分钟中枢出现第三类卖点，并该卖点不形成中枢扩张的情形，那么几乎 100% 可以肯定，一定在日线上要出现笔了"（分型是否延伸成笔需右侧确认，确认前分型只是候选→sure=False）；claim-20070630-001-a（课62）分型双条件定义。
- 仲裁结论：chanpy=【实现偏差】（P-B1）：探针实证 chan.py 已在合并 K 线上标出分型（klu[1] fx=TOP），但全图仅单分型、strict/loss 下 bi_list 均空（根本不构成候选笔，非区间拒笔）——适配器"fx 从笔端点推导"归一规则丢失孤立分型，根因在归一层；czsc=PASS（与 expect 一致）。用例无误。
- M2 改造点：chanpy 适配器归一层：fx 归一改从 CKLine.fx 标记直接取——孤立分型入表 sure=False，被笔使用者仍取笔 is_sure。

### 偏差 14：FX-003

- 规则源 claim：claim-20070630-001-b, claim-20070630-001-a
- chan.py 行为：FAIL — fx 表：缺 1 条
- czsc 行为：PASS（与 expect 一致）
- 原文依据：claim-20070630-001-b（课62）："经过这样的处理，所有 K 线图都可以处理成没有包含关系的图形"（分型等后续识别都在包含处理后的图形上进行）；claim-20070630-001-a（课62）分型定义。
- 仲裁结论：chanpy=【实现偏差】（P-B1）：探针实证 chan.py 已在合并 K 线（klu[1,2]）上标出 TOP（极值来自原始 bar2=expect idx），单分型无笔、适配器推导丢失（strict/loss 同）；czsc=PASS。用例无误。
- M2 改造点：chanpy 适配器归一层：fx 从 CKLine.fx 标记直取；合并 K 线分型 idx 取极值所在原始 klu（本例=2），孤立分型 sure=False。

### 偏差 15：INCLUDE-001

- 规则源 claim：claim-20070630-001-b
- chan.py 行为：FAIL — fx 表：缺 1 条
- czsc 行为：PASS（与 expect 一致）
- 原文依据：claim-20070630-001-b（课62）："在向上时，把两 K 线的最高点当高点，而两 K 线低点中的较高者当成低点，这样就把两 K 线合并成一新的 K 线"。
- 仲裁结论：chanpy=【实现偏差】（P-B1）：探针实证 chan.py 合并 K 线（klu[1,2]）上 TOP 标记存在（合并正确、极值来自原始 bar1=expect idx），单分型无笔、适配器推导丢失；czsc=PASS。用例无误。
- M2 改造点：chanpy 适配器归一层：fx 从 CKLine.fx 标记直取（idx 取极值所在原始 klu=1，孤立分型 sure=False）。

### 偏差 16：INCLUDE-002

- 规则源 claim：claim-20070630-001-b
- chan.py 行为：FAIL — fx 表：缺 1 条
- czsc 行为：PASS（与 expect 一致）
- 原文依据：claim-20070630-001-b（课62）："当向下时，把两 K 线的最低点当低点，而两 K 线高点中的较低者当成高点，这样就把两 K 线合并成一新的 K 线"。
- 仲裁结论：chanpy=【实现偏差】（P-B1）：探针实证 chan.py 合并 K 线（klu[1,2]）上 BOTTOM 标记存在，单分型无笔、适配器推导丢失；czsc=PASS。用例无误。
- M2 改造点：同偏差 15——chanpy 适配器归一层 fx 从 CKLine.fx 标记直取（idx 取极值所在原始 klu=1）。

### 偏差 17：INCLUDE-003

- 规则源 claim：claim-20070716-001-a, claim-20070630-001-b
- chan.py 行为：FAIL — fx 表：缺 1 条
- czsc 行为：PASS（与 expect 一致）
- 原文依据：claim-20070716-001-a（课65）："在 K 线包含关系的分析中，还要遵守顺序原则，就是先用第 1、2 根 K 线的包含关系确认新的 K 线，然后用新的 K 线去和第三根比，如果有包含关系，继续用包含关系的法则结合成新的 K 线"；claim-20070630-001-b（课62）合并规则。
- 仲裁结论：chanpy=【实现偏差】（P-B1）：探针实证 chan.py 顺序合并正确（klu[1,2,3] 上 TOP 标记存在），单分型无笔、适配器推导丢失——包含处理本身两实现均正确，差在归一层；czsc=PASS。用例无误。
- M2 改造点：chanpy 适配器归一层：fx 从 CKLine.fx 标记直取（idx 取极值所在原始 klu=1）。

### 偏差 18：SEG-001

- 规则源 claim：claim-20070905-001-c
- chan.py 行为：FAIL — fx 表：字段不一致 1 处；bi 表：字段不一致 1 处
- czsc 行为：FAIL — fx 表：缺 1 条
- 原文依据：claim-20070905-001-c（课77）："线段必须至少有三笔……线段开始的那三笔，必须有重合，开始三笔没有重合的，是构不成线段的……线段必须被线段所破坏才能确定其完成"。
- 仲裁结论：chanpy=【实现偏差】：仅末位 fx@25/bi(21,25) sure（P-A；seg 表与 expect 完全一致）；czsc=【实现偏差】：缺首分型 fx@1（P-C；seg 表对 czsc 为 N/A skip）。用例无误。
- M2 改造点：chanpy 适配器归一层 sure 统一（P-A 项）；czsc 适配器层首分型补偿（P-C 项）。

### 偏差 19：SEG-002

- 规则源 claim：claim-20070801-001-a
- chan.py 行为：FAIL — fx 表：字段不一致 1 处；bi 表：字段不一致 1 处
- czsc 行为：FAIL — fx 表：缺 1 条
- 原文依据：claim-20070801-001-a（课67）："特征序列两相邻元素间没有重合区间，称为该序列的一个缺口……以向上笔开始的线段的特征序列，只考察顶分型；以向下笔开始的线段，只考察底分型"。
- 仲裁结论：chanpy=【实现偏差】：末位 fx@25/bi(21,25) sure（P-A；seg 结构一致）；czsc=【实现偏差】：缺首分型 fx@1（P-C）。用例无误（ADR-003 已仲裁=A：缺口判断基于经包含处理后的特征序列元素）。
- M2 改造点：chanpy 适配器归一层 sure 统一（P-A 项）；czsc 适配器层首分型补偿（P-C 项）。

### 偏差 20：SEG-003

- 规则源 claim：claim-20070816-001-b
- chan.py 行为：FAIL — fx 表：字段不一致 1 处；bi 表：字段不一致 1 处；seg 表：字段不一致 1 处
- czsc 行为：FAIL — fx 表：缺 1 条
- 原文依据：claim-20070816-001-b（课71）："从转折点开始，如果第一笔就破坏了前线段，进而该笔延伸出三笔来，其中第三笔破点第一笔的结束位置，那么，新的线段一定形成，前线段一定结束"。
- 仲裁结论：chanpy=【实现偏差】：末位 fx/bi sure（P-A）+ seg0 sure（P-G 家族：探针实证 chanpy 原生 seg (0,2,up)/(3,5,down) 起止方向与 expect 完全一致，仅 is_sure=False——其 sure 语义与引擎"被破坏确认即 sure"约定不同，语义差）；czsc=【实现偏差】：缺首分型 fx@1（P-C）。用例无误。
- M2 改造点：chanpy 适配器归一层：sure 约定统一并扩展至 seg 表（已被反向线段破坏确认的 seg→sure=True 的映射规则）；czsc 适配器层：首分型补偿。

### 偏差 21：SEG-004

- 规则源 claim：claim-20070702-002-a
- chan.py 行为：FAIL — fx 表：字段不一致 1 处；bi 表：字段不一致 1 处；seg 表：缺 1 条、多 2 条
- czsc 行为：FAIL — fx 表：缺 1 条
- 原文依据：claim-20070702-002-a（课66）："线段必须要被线段破坏才算是真破坏，单纯的一笔是不能破坏线段的，这就避免了一些特偶然因素对走势的干扰"。
- 仲裁结论：chanpy=【实现偏差】（P-F）：把 bi3 单笔急挫当破坏处理——seg 拆为 (0,0)/(1,3)、缺 expect 单段 (0,4,up)，与"单纯一笔不能破坏线段"课文口径直接冲突（ADR-003 连带）；另有末位 sure（P-A）。czsc=【实现偏差】：缺首分型 fx@1（P-C；seg N/A skip）。用例无误。
- M2 改造点：chanpy 配置层：排查 seg_conf（seg_algo/left_seg_method）与线段破坏确认逻辑对"单笔破坏未发展成线段破坏"形态的处理，配置层不能解决则登记 M2 补丁项（PATCHES.md，chan.py 源码只读）；chanpy 适配器归一层 sure 统一；czsc 适配器层首分型补偿。

### 偏差 22：SEG-005

- 规则源 claim：claim-20070906-001-c
- chan.py 行为：FAIL — fx 表：字段不一致 1 处；bi 表：字段不一致 1 处；seg 表：缺 1 条、多 3 条
- czsc 行为：FAIL — fx 表：缺 1 条
- 原文依据：claim-20070906-001-c（课78）："如果线段中，最高或最低点不是线段的端点，那么，在任何以线段为基础的分析中，例如把线段为基础构成最小级别的中枢等，都可以把该线段标准化为最高低点都在端点"。
- 仲裁结论：chanpy=【实现偏差】（P-F）：古怪线段被拆为 (0,0)/(1,3)/(4,8) 三段、缺 expect 单段 (0,8,down)——该行为更接近 ADR-004 已否决的解释 B（重新起算线段候选），与课78"第一种情况笔破坏后未发展出线段破坏则原线段延续"口径冲突；另有末位 sure（P-A）。czsc=【实现偏差】：缺首分型 fx@1（P-C）。用例无误。
- M2 改造点：chanpy 配置层：seg_conf 排查（同偏差 21，本例古怪线段形态为重点样本），不能配置解决则登记补丁项；chanpy 适配器归一层 sure 统一；czsc 适配器层首分型补偿。

### 偏差 23：ZS-001

- 规则源 claim：claim-20061218-001-b, claim-20061226-001-a
- chan.py 行为：FAIL — fx 表：字段不一致 1 处；bi 表：字段不一致 1 处；zs 表：字段不一致 1 处
- czsc 行为：FAIL — fx 表：缺 1 条；zs 表：缺 1 条、多 1 条
- 原文依据：claim-20061218-001-b（课17）："某级别走势类型中，被至少三个连续次级别走势类型所重叠的部分，称为缠中说禅走势中枢"；claim-20061226-001-a（课18）："中枢的区间就是（max（a2,b2,c2），min（a1,b1,c1））"。
- 仲裁结论：chanpy=【实现偏差】：末位 sure（P-A）+ zs sure（P-G：探针实证原生 zs (18,19,5,17) 数值与 expect 完全一致、仅 is_sure=False）；czsc=【实现偏差】：缺 fx@1（P-C）+ zs 窗口偏移（P-D：实证 czsc bi 表与 expect 完全一致仍出 (17,19,1,21)——get_zs_seq 窗口含引导笔、端点延展至最后触及笔，非 P-C 下游，为独立 zs 口径差）。用例无误。
- M2 改造点：chanpy 适配器归一层 sure 统一；czsc 适配器层：首分型补偿 + zs 弃 get_zs_seq 窗口、按引擎约定从归一 bi 表重算（前三段重叠确立：start=首段起点、end=第三段终点、区间=max(低)/min(高)、延伸触及即延展 end）。

### 偏差 24：ZS-002

- 规则源 claim：claim-20061226-001-b
- chan.py 行为：FAIL — fx 表：字段不一致 1 处；bi 表：字段不一致 1 处；zs 表：字段不一致 1 处
- czsc 行为：FAIL — fx 表：缺 1 条；zs 表：缺 1 条、多 1 条
- 原文依据：claim-20061226-001-b（课18）："对于盘整来说，其'延伸'就在于不能产生新的'缠中说禅走势中枢'……'走势类型延伸'是否结束的判断关键就在于是否产生新的'缠中说禅走势中枢'"。
- 仲裁结论：chanpy=【实现偏差】：末位 sure（P-A）+ zs sure（P-G）；czsc=【实现偏差】：缺 fx@1（P-C）+ zs 窗口偏移（P-D：缺 (17,18,5,25) 多 (16,18,1,29)，延伸端点口径不同）。用例无误。
- M2 改造点：chanpy 适配器归一层 sure 统一；czsc 适配器层：首分型补偿 + zs 重算（含延伸规则：延伸段与中枢区间有重叠即延展 end、不产生新中枢不升级）。

### 偏差 25：ZS-003

- 规则源 claim：claim-20070302-001-b
- chan.py 行为：FAIL — fx 表：字段不一致 1 处；bi 表：字段不一致 1 处；zs 表：缺 1 条、多 1 条
- czsc 行为：FAIL — fx 表：缺 1 条；zs 表：缺 1 条、多 1 条
- 原文依据：claim-20070302-001-b（课33）："中枢的延伸不能超过 5 段，也就是一旦出现 6 段的延伸，加上形成中枢本身那三段，就构成更大级别的中枢了"。
- 仲裁结论：chanpy=【实现偏差】（P-K）：探针实证原生 zs 仅 (16,17,5,17) 一条 level=1 中枢，无九段升级出 level=2 中枢；叠加末位 sure（P-A）。czsc=【实现偏差】：缺 fx@1（P-C）+ zs 窗口全偏且无升级（P-D：(15,17,1,45,lv1) vs expect (16.5,17,5,41,lv2)，get_zs_seq 无级别概念）。用例无误（expect 只列升级后 lv2 中枢，与"9 段即构成更大级别、归属唯一"口径一致）；level=2 为引擎合法模型字段，两实现归一 level 恒 1 属实现缺口。
- M2 改造点：chanpy 配置层：排查 zs_conf 对九段升级的支持（无则登记补丁项）；czsc 适配器层：首分型补偿 + zs 重算（含九段升级→level=2 推导）；引擎约定：level 归一规则定义（九段升级/中枢嵌套推导，依赖 M3 递归层的部分登记 M3）。

### 偏差 26：ZS-004

- 规则源 claim：claim-20061226-001-c
- chan.py 行为：FAIL — fx 表：字段不一致 1 处；bi 表：字段不一致 1 处；zs 表：字段不一致 2 处
- czsc 行为：FAIL — fx 表：缺 1 条；zs 表：缺 2 条、多 2 条
- 原文依据：claim-20061226-001-c（课18）："在趋势中，连接两个同级别'缠中说禅走势中枢'的必然是次级别以下级别的走势类型"（同课 claim-20061226-001-a："趋势中的缠中说禅走势中枢之间必须绝对不存在重叠"）。
- 仲裁结论：chanpy=【实现偏差】：末位 sure（P-A）+ 两处 zs sure（P-G：两中枢数值全对、仅 is_sure 语义差）；czsc=【实现偏差】：缺 fx@1（P-C）+ zs 窗口偏移×2（P-D）。用例无误。
- M2 改造点：chanpy 适配器归一层 sure 统一；czsc 适配器层：首分型补偿 + zs 重算。

### 偏差 27：GOLD-001

- 规则源 claim：claim-20070105-001-b
- chan.py 行为：FAIL — bsp 表：缺 1 条
- czsc 行为：PASS（与 expect 一致）
- 原文依据：claim-20070105-001-b（课20）："一个次级别走势类型向上离开缠中说禅走势中枢，然后以一个次级别走势类型回试，其低点不跌破 ZG，则构成第三类买点"；课文原话（source_ref）："工商银行在 12 月 14 日构成典型的日线级别第三类买点"。
- 仲裁结论：chanpy=【实现偏差】（P-H）：探针实证 41 根真实日线 chanpy 仅出 3 笔、zs_list 全空（strict/loss 同）——中枢区域被并为单笔、无中枢即无三买检出前提，根因在上游笔/zs 划分而非 bsp_conf；czsc=PASS 但系空断言产物（bsp 表对 czsc 为 N/A skip，唯一被断言表不可比→无 diff，非真正命中课文结论，task-8 报告已注明）。用例无误（真实数据+课文指认，金标）。
- M2 改造点：chanpy 专项：排查真实数据笔划分（GOLD-001/002 为样本，41 根日线仅 3 笔、zs 空），从 bi/zs 层逐级核对——登记 M2 专项（可能涉配置与算法两层）；引擎约定：czsc 空断言 PASS 的解读规则（报告渲染层是否单列 SKIP，留 M2 决定）。

### 偏差 28：GOLD-002

- 规则源 claim：claim-20070105-001-b
- chan.py 行为：FAIL — bsp 表：缺 1 条
- czsc 行为：PASS（与 expect 一致）
- 原文依据：claim-20070105-001-b（课20）三买定理；课文原话（source_ref）："北辰实业在 11 月 14 日构成典型的日线级别第三类买点"。
- 仲裁结论：chanpy=【实现偏差】（P-H）：探针实证 29 根真实日线 chanpy 仅出 1 笔（strict 5→27 / loss 2→27）、zs 空——上游笔层已崩塌，三买无检出前提；czsc=PASS 系空断言产物（同 GOLD-001）。用例无误；已知摩擦点（task-8 疑虑 1）：课文指认日 idx21 与严格包含处理（idx20 包含 idx21）的 idx 对齐口径——当前实证 chanpy 笔层已崩、尚未走到该摩擦点，留 UP 评审门一并裁定。
- M2 改造点：chanpy 专项（同偏差 27，P-H 项）；GOLD-002 idx 对齐口径（课文日 vs 合并 K 线口径）留 UP 裁定后进入 M2 用例层处理。

### 偏差 29：GOLD-003

- 规则源 claim：claim-20070105-001-b, claim-20070313-001-f
- chan.py 行为：FAIL — fx 表：缺 2 条、字段不一致 1 处；bi 表：缺 3 条、多 1 条；zs 表：字段不一致 1 处；bsp 表：缺 1 条、多 1 条
- czsc 行为：FAIL — fx 表：缺 1 条；zs 表：缺 1 条、多 1 条
- 原文依据：claim-20070105-001-b（课20）三买定理；课文原话（课36，source_ref/claim-20070313-001-f）："2760 到 2858 这 30 分钟中枢，03081000 的 5 分钟回抽确认了一个第三类买点""回抽低点 2871 点比上一中枢的最高点 2888 点要低"。
- 仲裁结论：chanpy=【原文歧义】（P-I）：strict 吞中间笔 17→21/21→25（并成 17→29）——探针实证 loss 下 7 笔全部恢复且与 expect 一致（含 fx@21/@25），归 ADR-001=B、chanpy 为口径 A 实现、非算法缺陷；叠加【实现偏差】：末位 sure（P-A）+ zs sure（P-G：数值 2760/2858/5/17 全对）+ 三买未报、误报一买@29（P-H 家族：loss 下 bi/zs 已正确仍报 (29,1,up) 而非 (25,3,up)，bsp 检出条件差）。czsc=【实现偏差】：缺 fx@1（P-C）+ zs 端点偏移（P-D：数值 2760/2858 与课文完全一致，端点 1-21 vs 5-17）。用例无误（金标：缠师图上分解实例）。
- M2 改造点：chanpy 配置层：bi_fx_check→loss + 排查 bsp_conf（三买检出条件）；chanpy 适配器归一层：sure 统一；czsc 适配器层：首分型补偿 + zs 重算。

### 偏差 30：GOLD-004

- 规则源 claim：claim-20070118-001-a, claim-20070118-001-b
- chan.py 行为：FAIL — fx 表：缺 6 条、字段不一致 1 处；bi 表：缺 7 条、多 1 条、字段不一致 1 处；zs 表：缺 2 条；bsp 表：缺 1 条
- czsc 行为：FAIL — fx 表：缺 1 条；zs 表：缺 2 条、多 2 条
- 原文依据：claim-20070118-001-a（课24）："C 段的走势类型完成时对应的 MACD 柱子面积（向上的看红柱子，向下看绿柱子）比 A 段对应的面积要小，这时候就构成标准的背弛"；claim-20070118-001-b（课24）："任一背驰都必然制造某级别的买卖点"（课文："背驰后其回跌一定至少重新回到 B 段的中枢里"）。
- 仲裁结论：chanpy=【原文歧义】（P-I 大规模）：strict 吞中段 6 笔（9→37 并一笔），双中枢未拆出——探针实证 loss 下 10 笔全部恢复与 expect 一致、双中枢 (38.6,39.5,5,17)/(40.7,41.3,21,33) 出现且数值全对；叠加【实现偏差】：末位 sure（P-A）+ zs sure（P-G）+ 一卖@37 dir 反（P-E：loss 下检出 (37,1,up) vs expect (37,1,down)，ADR-006 翻转后吻合）。czsc=【实现偏差】：缺 fx@1（P-C）+ zs 窗口偏移×2（P-D：中枢2 数值全对，中枢1 zd 38.5 vs 38.6 随窗口微变，端点 1-21/21-41 vs 5-17/21-33）。用例无误（金标）。
- M2 改造点：chanpy 配置层：bi_fx_check→loss；chanpy 适配器归一层：sure 统一 + bsp dir 翻转；czsc 适配器层：首分型补偿 + zs 重算。

### 偏差 31：GOLD-005

- 规则源 claim：claim-20070118-001-c, claim-20070105-001-b
- chan.py 行为：FAIL — fx 表：缺 2 条、字段不一致 1 处；bi 表：缺 3 条、多 1 条；zs 表：字段不一致 1 处；bsp 表：缺 1 条、多 1 条
- czsc 行为：FAIL — fx 表：缺 1 条；zs 表：缺 1 条、多 1 条
- 原文依据：claim-20070118-001-c（课24）："如果回跌不重新跌回，就在次级别的第一类买点回补，刚好这反而构成该级别的第三类买点"；claim-20070105-001-b（课20）三买定理。
- 仲裁结论：chanpy=【原文歧义】（P-I）：strict 吞 21→25/25→29（并成 21→33）——探针实证 loss 下 8 笔全部恢复与 expect 一致；叠加【实现偏差】：末位 sure（P-A）+ zs sure（P-G：数值 7.55/7.85/9/21 全对）+ 三买未报、误报一买@33（P-H 家族：loss 下仍报 (33,1,up) 而非 (29,3,up)，bsp 检出条件差）。czsc=【实现偏差】：缺 fx@1（P-C）+ zs 窗口偏移（P-D：(7.5,7.6,1,25) vs (7.55,7.85,9,21)，数值与端点均随窗口偏）。用例无误（金标）。
- M2 改造点：chanpy 配置层：bi_fx_check→loss + 排查 bsp_conf（三买检出条件）；chanpy 适配器归一层：sure 统一；czsc 适配器层：首分型补偿 + zs 重算。

## M2/M3 重新估算

> 基于 31 用例 × 2 实现的偏差归类（明细见上方口径偏差清单；归类统计与探针实证记录见 .superpowers/sdd/task-9-report.md）。
> M1 结论：**0 条用例错误**；全部偏差归因为实现侧（实现偏差/语义差）与原文歧义（均已经 ADR-001~008 仲裁，待 UP 确认）。

### M2 改造项清单（按层分组）

**chanpy 配置层（CChanConfig 键，不改源码）——3 项**

1. `bi_fx_check` strict→loss（ADR-001 连带）——覆盖 P-B2（BI-002/003）与 P-I（BSP-003/004、GOLD-003/004/005）全部"中间笔被吞"；探针实证 loss 下 GOLD-003/004/005、BSP-003/004 的 bi 表与 expect 完全一致。
2. `seg_conf` 排查（P-F：SEG-004/005 拆段）——seg_algo/left_seg_method 配置先试，不能解决则登记 PATCHES.md 补丁项。
3. `zs_conf` + `bsp_conf` 排查（P-K：BC-002 合并、ZS-003 无升级、BSP-003 未检出；P-H 家族：GOLD-003/005 在 bi/zs 已正确下仍误报一买不报三买）——配置先试，不能解决则登记补丁项。

**chanpy 适配器归一层（adapter_chanpy.py）——3 项**

4. sure 约定统一（P-A/P-G，覆盖 22 例末位 fx/bi sure + 9 例 zs/seg sure）：末位未被反向笔确认的 fx/bi 归一为 sure=False；zs/seg 按引擎"形成即 sure / 被破坏确认即 sure"约定映射。
5. fx 归一改从 CKLine.fx 标记直取（P-B1，5 例）：孤立分型入表 sure=False；合并 K 线分型 idx 取极值所在原始 klu。
6. bsp dir 映射翻转（P-E，ADR-006，5 例 + GOLD-004 修复后显现）：is_buy→up / 非 buy→down（操作方向）。

**czsc 适配器层（adapter_czsc.py）——2 项 + 1 专项**

7. 首分型补偿（P-C，23 例）：bi_list[0].fx_a 补一条 FX（sure=True——其已被首笔延伸确认；bi_list 空则不补）。
8. zs 归一弃用 get_zs_seq 窗口（P-D，13 例）：按引擎约定从归一 bi 表重算——前三段重叠确立：start=首段起点、end=第三段终点、区间=max(低)/min(高)、延伸触及即延展 end、九段升级推导 level=2。
9. 专项：BI-004 型"间距过近不成笔 fx 对"消解（P-J，1 例）——czsc 库行为差（bi_list 全空），适配器无法低成本补偿，登记 M2 专项核对 czsc 笔构造。

**引擎约定/用例层——4 项**

10. sure 约定成文（写入归一契约文档）：末位未确认=False、形成即 sure。
11. level 归一规则定义（BC-002/ZS-003 的 level=2）：九段升级/中枢嵌套推导；依赖 M3 递归层的部分登记 M3。
12. ADR-008 面积断言启用：expect.meta 键接入 diff 比对。
13. BI-002/003 expect 翻转（待 UP 拍板）：(a) 翻转 bi:[(1,5)]（推荐）/ (b) 保留 A/B 对照样本且 meta 标注不参与 PASS 统计。

**chanpy 源码补丁项（PATCHES.md 登记，源码只读前提）——视排查结果，至多 2 项**

14. P-F/P-K 配置层解决不掉的部分（线段破坏/缺口确认、zs 构造口径）。
15. P-H 真实数据笔/zs 划分专项（GOLD-001/002：chanpy 日线 41 根仅 3 笔、zs 空；根因在 bi/zs 层，可能触及算法补丁）。

### M2 校准门目标

- **M2 完成后 31 用例 × 2 实现 100% PASS**（26 case + 5 golden，与 M1 plan 验收口径一致）。
- 前提依赖：BI-002/003 expect 翻转待 UP 评审门拍板（不拍板则按对照样本处理、不计入 PASS 统计）；GOLD-001/002 的 czsc PASS 为空断言产物，M2 启用 bsp 断言后需重验；P-H（真实数据）若根因深入 chanpy 笔算法，允许降级为"登记已知偏差 + 补丁项"，由 UP 评审门决定是否阻塞 M2 关门。

### 工作量定性重估

- 适配器归一层（项 4-8）：小——归一逻辑集中、harness 测试已齐备，每项约半天量级。
- 配置层排查（项 1-3）：中——逐项配置实验即可；项 1 路径已被探针验证。
- 补丁/专项（项 9、14、15）：大且不确定——P-H（真实数据笔划分）是最大不确定项；P-F/P-K 取决于配置排查结果。
- 定性总量：**中（约 2~3 倍 M1 适配器层工作量）**，关键路径 = P-H 根因深度 + UP 对 BI-002/003 的拍板。
- **M3 占位说明不变**：`src/chan_engine/core/levels/` 递归层（f1/f2），批量正确性→增量一致性；M2 校准报告出来后再单独立 plan 估算。
