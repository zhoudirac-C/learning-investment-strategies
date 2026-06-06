# Claim Schema 验证指南

> 生成 claims 后必须用 `src/qing_investment/claim_schema.py` 验证，避免字段缺失或枚举值错误导致后续流程中断。

---

## 必需字段

```python
REQUIRED_FIELDS = {
    "id", "source_path", "source_date", "source_type",
    "extracted_at", "claim_type", "subject", "timeframe",
    "statement", "evidence_quote", "interpretation",
    "confidence", "status", "supersedes", "contradicts", "links",
}
```

**注意**：旧写法中的 `predicate`, `object`, `context`, `tags` 已不被支持，必须替换为：
- `predicate` + `object` → `statement`（完整陈述句）
- `context` → `interpretation`（解读说明）
- `tags` → 删除，用 `links` 中的页面关联代替
- 新增 `supersedes: []` 和 `contradicts: []`（空列表即可）

## 枚举值

| 字段 | 允许值 |
|------|--------|
| `claim_type` | `market-cycle`, `sector-theme`, `stock-view`, `methodology`, `risk`, `technical-signal`, `technical-knowledge`, `macro`, `operation`, `catalyst`, `general` |
| `timeframe` | `intraday`, `short-term`, `trend`, `industry`, `permanent` |
| `confidence` | `high`, `medium`, `low` |
| `status` | `active`, `superseded`, `contradicted`, `expired`, `case-only` |

## 快速验证命令

```bash
cd ~/learning-investment-strategies && python3 -c "
from src.qing_investment.claim_schema import validate_claim_dict
import yaml
with open('knowledge/claims/claim-YYYYMMDD-NNN.yaml') as f:
    claims = yaml.safe_load(f)
for claim in claims:
    validated = validate_claim_dict(claim)
    print(f'✓ {validated.id} validated')
print('All claims valid')
"
```

## 常见错误

1. **使用 `short_term` 而非 `short-term`** → `ValueError: Invalid timeframe`
2. **缺少 `statement` 字段** → `ValueError: Missing required claim fields: statement`
3. **使用旧字段 `predicate`/`object`** → `ValueError: Missing required claim fields: statement`
4. **`supersedes` 不是列表** → `ValueError: supersedes must be a list`
