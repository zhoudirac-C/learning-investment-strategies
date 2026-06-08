# Claim 执行时自检清单

> 用途：写完 claims 后，执行前逐条对照 skill 规范自检
> 更新日期：2026-06-08
> 核心原则：自检不是"可选优化"，是硬性步骤。跳过自检 = 违反 skill 规范。

## 自检五步法

写完 claims YAML 后，提交前必须完成以下五步检查：

### Step 1: 字段完整性（18个必需字段）

运行验证脚本：
```bash
cd ~/learning-investment-strategies
python3 -c "
import yaml; data=yaml.safe_load(open('新claim文件.yaml'))
claims=data.get('claims',data) if isinstance(data,dict) else data
claims=claims if isinstance(claims,list) else [claims]
R=['id','statement','claim_type','subject','source_path','source_date',
   'source_type','extracted_at','confidence','status','intensity',
   'evidence_quote','interpretation','timeframe','supersedes',
   'contradicts','links','topic']
for c in claims:
    m=[k for k in R if k not in c or c[k] in (None,'')]
    assert not m, f'{c.get(\"id\")} 缺: {m}'
print(f'✅ {len(claims)} claims 字段完整')
"
```

**不通过 = 不能提交。**

### Step 2: 股票代码（所有公司名称带6位代码）

逐条检查 `statement` 中所有公司名称：
- ✅ 正确：`乔锋智能(301061)`、`宣安科技(300725)`
- ❌ 错误：`乔锋智能`、`宣安科技`（无代码）

**查询方法**：
```python
import urllib.request, urllib.parse, json

def get_stock_code(name):
    encoded = urllib.parse.quote(name)
    url = f"https://searchapi.eastmoney.com/api/suggest/get?input={encoded}&type=14&count=1"
    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read().decode())
    items = data.get("QuotationCodeTable", {}).get("Data", [])
    if items:
        return items[0]["Code"]
    return None
```

**常见遗漏**：
- 公司名在 `statement` 中出现但未标注代码
- `interpretation` 中提到公司但未标注代码

### Step 3: related_stocks（涉及个股的 claim 必须填）

检查规则：
- 如果 `statement` 或 `interpretation` 中提到任何个股 -> `related_stocks` 必须非空
- 格式：`related_stocks: ["301061", "300725"]`

**反面案例**：004-h 和 004-i 最初 `related_stocks: []` -> 用户纠正

### Step 4: Claim 原子性（单主题/单标的）

检查规则：
- 一条 claim 只能包含 **一个主题**、**一个方向**、或 **一只标的**
- `subject` 中不能出现 `、` `/` `+` 等多实体标记

### Step 5: claim_type 正确性

检查规则：
- `market-cycle`：市场周期判断
- `sector-theme`：板块/主题判断
- `operation`：具体操作
- `methodology`：方法论/框架
- `risk`：风险提示
- `technical-knowledge`：技术工具知识

## 自检执行纪律

1. **写完 claims 后立即自检**，不要等用户提醒
2. **自检不通过不提交**，补全后再提交
3. **自检通过后简要汇报**："✅ 自检通过：字段完整/代码齐全/related_stocks已填/原子性合规/type正确"

## 反面案例（2026-06-08）

**004-h 和 004-i 最初版本的问题**：
| 检查项 | 最初状态 | 问题 |
|--------|---------|------|
| 字段完整性 | ✅ 通过 | 无问题 |
| 股票代码 | ❌ 缺失 | 乔锋智能、宣安科技、风语筑、软通动力均无代码 |
| related_stocks | ❌ 空列表 | `related_stocks: []` |
| 原子性 | ✅ 通过 | 无问题 |
| claim_type | ✅ 通过 | 无问题 |

**根因**：执行时跳过了 Step 2 和 Step 3 的自检。

**用户纠正**："qing-learning skill不是改了吗？为什么还是没有代码"

**教训**：skill 规范写得再好，执行时跳过自检 = 规范失效。
