# YAML Stock Code 前导零丢失修复记录

## 问题

`_auto_format_yaml()` 使用 `yaml.dump()` 将 enriched JSON 格式化为 YAML 时，
6 位字符串 `"002971"` 被写成裸数字 `code: 002971`。

YAML 1.1 解析器将前导零的数字视为八进制整数，读回时变成 `2971`。

## 影响

所有以 `0` 开头的 6 位股票代码受影响（002xxx / 001xxx / 000xxx / 300xxx 等）。
存量扫描发现 **10+ 处**整数代码。

## 修复

### 1. `extract_claims_pipeline.py:_auto_format_yaml()`

`yaml.dump()` 后追加后处理：

```python
import re
raw = yaml_path.read_text(encoding="utf-8")
# 修复前导零代码
fixed = re.sub(
    r'(?m)^(  - code: )0(\d{5})\s*$',
    r"\1'0\2'",
    raw,
)
# 修复非零开头代码
fixed = re.sub(
    r'(?m)^(  - code: )([1-9]\d{5})\s*$',
    lambda m: f"  - code: '{m.group(2)}'",
    fixed,
)
if fixed != raw:
    yaml_path.write_text(fixed, encoding="utf-8")
```

### 2. `gate_validate_claims.py:gate3_related_stocks()`

新增 code 类型校验：

```python
code_val = item.get("code")
if isinstance(code_val, int):
    errors.append(
        f"related_stocks code={code_val} 是整数类型，应改为字符串 '{code_val}'"
    )
elif isinstance(code_val, str) and not code_val.isdigit():
    errors.append(
        f"related_stocks code='{code_val}' 不是纯数字字符串"
    )
```

## 存量扫描

```bash
cd ~/learning-investment-strategies
python scripts/gate_validate_claims.py --all --step 2 | grep "是整数类型"
```

## 手动修复示例

```yaml
# ❌ 错误
  - code: 002971
    name: 和远气体

# ✅ 正确
  - code: '002971'
    name: 和远气体
```

## 第一次发现

2026-06-12: `claim-20260612-001.yaml` 中 `002971` 在 step1-2 JSON 中为字符串，
step3 YAML 生成后变为数字。
