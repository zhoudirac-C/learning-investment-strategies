# 全方向性能扫描方法论（模式 C）

> 当用户问"UP 提到的方向哪些在调整""全面梳理历史方向"时使用。

---

## 触发信号

- "过去提到的方向哪些在调整"
- "全面梳理 UP 历史上提过的所有方向"
- "帮我看看所有方向的涨跌情况"
- "哪些调整充分可以关注"

## 数据来源

### 方向清单（三层递进）

| 层级 | 来源 | 覆盖度 | 时效性 |
|:---|:---|:---|:---|
| **L1 — 方向级** | `watchlist.yaml` → `themes[].name` | 最全（UP 全部历史方向） | 人工维护 |
| **L2 — 标的级** | `watchlist.yaml` → `themes[].stocks[]` | 所有 UP 点名过的票 | 人工维护 |
| **L3 — 观点级** | `knowledge/claims/claim-*.yaml` → `tags` + `related_stocks` | 最新的 UP 方向定性 | Claims 日期 |

### 行情数据

优先腾讯 API 批量获取（`references/data-source-fallback-chain.md`）：

```python
# 批量获取所有主板票的收盘价
api_codes = [f"sh{c}" if c[0]=='6' else f"sz{c}" for c in num_codes]
url = f"http://qt.gtimg.cn/q={','.join(api_codes)}"
```

**⚠️ 关键陷阱**：API 返回的 key 是纯数字（`002055`），不带 `sh`/`sz` 前缀。匹配时用 `parts[2]` 作 key。

## 执行流程

### Step 1: 提取所有方向 × 所有主板票

```python
import yaml

with open('config/stock_monitor/watchlist.yaml') as f:
    w = yaml.safe_load(f)

all_stocks = {}
for t in w['themes']:
    for s in t.get('stocks', []):
        code = s.get('code', '')
        clean = code.replace('.SH','').replace('.SZ','').replace('.sh','').replace('.sz','')
        if len(clean) == 6 and clean[0] in '60':  # 主板 only
            all_stocks[clean] = {
                'orig_code': code,
                'name': s.get('name', ''),
                'themes': [t.get('name', '')]
            }
```

### Step 2: 批量获取行情并分组

```python
# 按 50 只一批请求
for i in range(0, len(api_list), 50):
    batch = api_list[i:i+50]
    url = f"http://qt.gtimg.cn/q={','.join(batch)}"
    ...

# 按 theme 分组计算平均涨跌幅
from collections import defaultdict
theme_data = defaultdict(lambda: {'stocks': [], 'sum': 0.0, 'n': 0})
for num_code, info in all_stocks.items():
    q = quotes[num_code]
    pct = (q['latest'] - q['prev']) / q['prev'] * 100
    for theme in info['themes']:
        theme_data[theme]['stocks'].append((info['orig_code'], info['name'], pct, q['latest']))
        theme_data[theme]['sum'] += pct
        theme_data[theme]['n'] += 1
```

### Step 3: 排名输出

```python
sorted_themes = sorted(theme_data.items(), 
    key=lambda x: x[1]['sum'] / max(x[1]['n'], 1))

for theme, d in sorted_themes:
    avg = d['sum'] / max(d['n'], 1)
    marker = "🔴" if avg < -2 else ("🟡" if avg < 0 else "🟢")
    print(f"{marker} {theme} | avg {avg:+.1f}% | {d['n']}只")
```

## 输出格式

| 标记 | 含义 | 操作含义 |
|:---:|:---|:---|
| 🔴 | 平均跌超 -2% | 调整中，等企稳 |
| 🟡 | 平均 -2% ~ 0% | 震荡方向 |
| 🟢 | 平均为正 | 强势方向，但需判断是否主升末期 |

## 与 UP 视频/复盘的交叉验证

扫描结果出来后，必须结合 UP 最新观点做二次判断：

1. 🟢 方向如果是"主升末期"（如 6/4 的 CPO/光互连）→ 不追
2. 🔴 方向如果 UP 明确规避（如城市更新非核心方向）→ 不抄底
3. 🔴 方向如果 UP 说"中线逻辑未坏"+ 调整充分 → **这才是"星辰大海"的候选方向**

## 缺口检测

扫描过程中可能发现 claims 中提到的方向在 watchlist 中缺失。例如：

- Claim-20260604-003-b：燃气轮机（机构看好，回调上车）
- 但 watchlist 中无 `gas_turbine` theme

处理：在分析中明确标注缺口，询问用户是否补充。

## 已知限制

- 只用日跌幅判断"调整"，单日数据不能等同于中期趋势
- 无历史 K 线，无法判断"调整是否充分"——需要补充多日数据或 scan_all_stocks.py
- claims 数据库重建于 2026-05，更早的方向在 wiki/raw 中
