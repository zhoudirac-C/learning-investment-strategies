# Config Health Check — 观察池/持仓池配置完整性检查清单

> 此文件记录 2026-06-06 全链路架构 Review 中发现的缺陷模式和检查方法。
> 每次更新 watchlist / strategy_pack / positions 后，或定期做 config review 时使用。

---

## 检查清单

### 1. Code 格式标准化

**规则**：所有 watchlist / strategy_pack / positions 中的 `code` 字段必须为 `XXXXXX.SZ` 或 `XXXXXX.SH` 格式。

**检查方法**：
```python
import re, yaml
with open('config/stock_monitor/watchlist.yaml') as f:
    wl = yaml.safe_load(f)
for theme in wl.get('themes', []):
    for stock in theme.get('stocks', []):
        code = stock.get('code', '')
        if code and not re.match(r'^\d{6}\.(SZ|SH)$', str(code)):
            print(f"BAD: {code} in {theme['name']}")
```

**非标准格式 → 标准格式**：
| 错误 | 正确 |
|------|------|
| `sh688381` | `688381.SH` |
| `sz002897` | `002897.SZ` |
| `sh600487` | `600487.SH` |

**根因**：`stock_monitor.py` 的 `stock_code_to_secid()` 正则只匹配 `(\d{6})\.(SZ|SH)`，非标准格式返回 `None`，导致行情拉取静默跳过。

---

### 2. Entry Points 去重

**规则**：`strategy_pack.yaml` 的 `entry_points` 中，同一 `code + name` 只能出现一次。

**检查方法**：
```python
import yaml
with open('config/stock_monitor/strategy_pack.yaml') as f:
    sp = yaml.safe_load(f)
eps = sp.get('quant_entry_strategy', {}).get('entry_points', [])
seen = {}
for i, ep in enumerate(eps):
    key = f"{ep.get('code')}_{ep.get('name')}"
    if key in seen:
        print(f"DUP: {key} at indices {seen[key]} and {i}")
    seen[key] = i
```

---

### 3. today_snapshot 唯一位置

**规则**：`today_snapshot` 仅存在于 `strategy_pack.yaml` 中，`watchlist.yaml` 不应有此字段。

**检查方法**：
```python
import yaml
for fname in ['watchlist.yaml', 'strategy_pack.yaml']:
    with open(f'config/stock_monitor/{fname}') as f:
        data = yaml.safe_load(f)
    ts = data.get('today_snapshot')
    if fname == 'watchlist.yaml' and ts:
        print(f"BAD: watchlist.yaml has today_snapshot (should only be in strategy_pack.yaml)")
    if fname == 'strategy_pack.yaml' and not ts:
        print(f"BAD: strategy_pack.yaml missing today_snapshot")
```

---

### 4. Sector Groups 覆盖

**规则**：所有包含可交易标的的 watchlist theme，其 ID 必须出现在 `sector_groups` 中（或至少有一个等价的 sector_group 覆盖其标的）。

**检查方法**：
```python
import yaml
with open('config/stock_monitor/watchlist.yaml') as f:
    wl = yaml.safe_load(f)
with open('config/stock_monitor/strategy_pack.yaml') as f:
    sp = yaml.safe_load(f)

wl_ids = {t['id'] for t in wl.get('themes', [])}
sg_ids = {g['id'] for g in sp.get('sector_groups', [])}

for tid in sorted(wl_ids - sg_ids):
    t = next(t for t in wl['themes'] if t['id'] == tid)
    has_active = any(s.get('tradable', True) for s in t.get('stocks', []))
    if has_active:
        print(f"GAP: theme '{tid}' ({t['name']}) has {len(t['stocks'])} stocks, not in sector_groups")
```

**注意**：sector_groups 中有一些 ID 与 watchlist theme ID 不同但覆盖同方向（如 sector_groups 的 `liquid_cooling` 对应 watchlist 的 `liquid_cooling_heat_dissipation`）。这是可接受的别名，只要 `sector_groups.members` 包含了正确的标的即可。

---

### 5. 持仓价格区间防失真

**规则**（已集成到 `stock_monitor.py` 的 `validate_position_price_zones()`）：
- `reduce_zone` 下限距现价不应 > 12%
- `risk_zone` 下限不应 > 现价（已被跌破 → 风险线已失效）
- 每个持仓必须至少配置 `reduce_zone` 或 `risk_zone`/`risk_line`，否则跌停无提醒

**手动检查**（补充自动化检查未覆盖的）：
```python
# 基于最新行情手动校验
# 若 risk_zone 下限 > 现价 → 必须下调
# 若 reduce_zone 下限 vs 现价 > 12% → 必须下调
```

---

### 6. 非主板标的标记

**规则**：非主板标的（688/300/301）在 watchlist 中标记 `tradable: false`，在 entry_points 中不配介入区间或标注"不可交易（非主板）"。

**检查方法**：
```python
import re
for theme in wl.get('themes', []):
    for stock in theme.get('stocks', []):
        code = stock.get('code', '')
        m = re.match(r'(\d{6})\.(SZ|SH)', str(code))
        if m:
            num, mkt = m.groups()
            if mkt == 'SZ' and num.startswith('3'):
                if stock.get('tradable', True):
                    print(f"WARN: {code} ({stock.get('name')}) is 创业板 but tradable not set to false")
            if mkt == 'SH' and num.startswith('688'):
                if stock.get('tradable', True):
                    print(f"WARN: {code} ({stock.get('name')}) is 科创板 but tradable not set to false")
```

---

## 快速全量检查

```bash
cd ~/learning-investment-strategies
python3 -m qing_investment.stock_monitor --status
python3 -m qing_investment.stock_monitor --analysis-context --ignore-trading-time
```

若 `--status` 或 `--analysis-context` 失败，先检查 YAML 可解析性：
```python
import yaml
for f in ['watchlist.yaml', 'strategy_pack.yaml', 'positions.yaml']:
    try:
        with open(f'config/stock_monitor/{f}') as fh:
            yaml.safe_load(fh)
        print(f"✅ {f}")
    except Exception as e:
        print(f"❌ {f}: {e}")
```
