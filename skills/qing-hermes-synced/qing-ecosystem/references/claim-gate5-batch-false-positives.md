# Gate 5 假阳性批量处理流程

## 触发场景

当 raw 文件是大段分析性文本（复盘专栏、深度分析），Gate 2 的 `gate5_stock_codes` 会产生大量假阳性：
- `科技`（板块通用词）→ "判断科技见底" "聚焦科技板块"
- `有限`（程度副词）→ "空间有限" "帮助有限" "涨幅有限"
- `智能`（通用名词）→ "人工智能" "商业智能"
- `电子`（行业通用词）→ "消费电子" "半导体电子"

症状：`continue` 输出 20+ 个"在文本中出现但未标注 6 位代码"错误。

## 处理步骤

```bash
# 1. 排查：找出所有假阳性，区分真公司名与通用词汇
python3 -c "
import json, re
with open('temp/claims/<session>/step2_enriched.json') as f:
    claims = json.load(f)
for c in claims:
    text = c.get('statement','') + ' ' + c.get('interpretation','') + ' ' + c.get('evidence_quote','')
    names = re.findall(r'([\u4e00-\u9fff]{2,5}(?:股份|科技|电子|智能|医疗|有限))', text)
    for name in set(names):
        if not re.search(re.escape(name) + r'[（(]\d{6}[）)]', text):
            print(f'{c[\"id\"]}: \"{name}\"')
"

# 2. 区分真假
#    真公司名 → 需要在 statement/interpretation 字段补充 (6位代码)
#    假阳性 → 追加到 gate_validate_claims.py 的 NON_COMPANY 集合

# 3. 修改 gate_validate_claims.py
#    NON_COMPANY set 位置: ~/learning-investment-strategies/scripts/gate_validate_claims.py

# 4. 清理缓存后重跑（关键！不删缓存 pipeline 不会重新校验）
rm -f temp/claims/<session>/gate*_result.json
python scripts/extract_claims_pipeline.py continue
```

## NON_COMPANY 维护原则

- 通用词汇（科技作板块、有限表程度、智能表通用概念）→ 放入 NON_COMPANY
- 非上市标的（如 宇树科技、沐曦股份、阶跃星辰）→ 放入 NON_COMPANY
- 真实公司名必须在 statement/interpretation 中出现时带 `(6位代码)`，仅 evidence_quote 带不够
- 追加后按日期和 raw 类型注释分组（便于回溯: `# 2026-07-20 22:01 复盘动态假阳性`）
- Gate 5 的 regex 模式: `[\u4e00-\u9fff]{2,5}(?:股份|科技|电子|智能|医疗|有限)`

## 实战案例：2026-07-20 22:01 复盘

**原始错误**（Gate 2 输出）：
```
- '不意味着科技' 在文本中出现但未标注 6 位代码
- '是下行空间有限' 在文本中出现但未标注 6 位代码
- '数下行空间有限' 在文本中出现但未标注 6 位代码
- '否从权重向科技' 在文本中出现但未标注 6 位代码
- '件能否带动科技' 在文本中出现但未标注 6 位代码
- '也叠加了科技' 在文本中出现但未标注 6 位代码
- '料涨价线在科技' 在文本中出现但未标注 6 位代码
```

**根因**：此 raw 是 2000+ 字长文复盘（非短观点摘要），`科技` 全为板块通用词，`有限` 为"指数下行空间有限"的程度副词。正则 `[\u4e00-\u9fff]{2,5}(?:科技|有限)` 匹配了这些文本片段但找不到附近括号代码。

**批量添加步骤**：

```bash
# 1. 打开 gate_validate_claims.py，定位花括号闭合前的位置
#    最后一条 NON_COMPANY 条目在当前日期注释之前

# 2. 直接追加新模式：
    # 2026-07-20 22:01 复盘动态假阳性（科技/有限 板块通用词+文本片段）
    "不意味着科技", "是下行空间有限", "数下行空间有限",
    "否从权重向科技", "件能否带动科技", "也叠加了科技",
    "料涨价线在科技",

# 3. 必须清理缓存！Gate 2 结果缓存在 temp/claims/<session>/gate2_result.json
rm -f temp/claims/<session>/gate*_result.json

# 4. 重跑
python scripts/extract_claims_pipeline.py continue
```

**关键教训**：长文复盘类 raw（2000+ 字）的 interpretation/evidence_quote 包含大量带 `科技`/`有限` 的文本片段。建议在 Step 1 撰写时就预判这些假阳性，在 Step 2 补代码时一并标记给 NON_COMPANY。

## 参考

- `scripts/gate_validate_claims.py` 第 260-366 行（NON_COMPANY 集合），文件末尾还持续新增
- `skills/qing-learning-claim/references/gate5-false-positive-patterns.md`（按 raw 类型分组的模式记录）
