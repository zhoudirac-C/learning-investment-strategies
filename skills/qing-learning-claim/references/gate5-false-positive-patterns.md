# Gate 5 假阳性模式库

`gate_validate_claims.py` 的 Gate 5 使用正则检测 statement/evidence_quote/interpretation 中是否遗漏股票代码。由于正则基于"2-5个汉字 + 公司后缀"模式，在处理非个股类 claim 时会产生假阳性。

## 假阳性模式列表

### 通用模式（多场景出现）

| 模式 | 正则命中片段 | 实际含义 | 出现场景 | 修复状态 |
|------|------------|---------|---------|---------|
| "资金从高位科技" | "高位科技" | 描述资金从高位科技股流出 | market-cycle / 资金流向 | ✅ |
| "导市场的是科技" | "科技" | 描述市场主导行业 | market-cycle | ✅ |
| "主导行业为科技" | "科技" | 同上 | market-cycle | ✅ |
| "今日对智能" | "智能" | 描述今日对智能体的带动 | sector-theme / AI应用 | ✅ |
| "今日智能" | "智能" | 同上 | sector-theme | ✅ |
| "机会但弹性有限" | "弹性有限" | 描述反弹空间判断 | stock-view / 判断描述 | ✅ |
| "空间但弹性有限" | "弹性有限" | 同上 | stock-view | ✅ |

### 历史模式（已积累）

| 模式 | 出现场景 | 修复状态 |
|------|---------|---------|
| "高位科技", "低位科技" | 市场方向描述 | ✅ |
| "专业智能", "转向了智能" | AI/智能体描述 | ✅ |
| "智能体", "具身智能" | 概念名称 | ✅ |
| "物理AI" | 概念名称 | ✅ |
| "今日科技", "美股科技" | 市场/板块描述 | ✅ |
| "上游电子", "缺货的电子" | 产业链描述 | ✅ |
| "硬科技" | 概念名称 | ✅ |
| "新增供给有限" | 供给侧描述 | ✅ |

## 假阳性判断标准

一个词组被判定为假阳性需满足：
1. **上下文明确不是公司名**：该词组在原文中作为通用概念使用（如"科技股"指整个板块）
2. **无法对应到具体上市公司**：在东方财富搜索 API 中查询该词组，返回的不是单一公司
3. **属于描述性/修饰性词汇**：如"高位"、"空间"、"弹性"等修饰词 + 行业词的组合

## 修复流程（标准操作）

```bash
# 1. 确认假阳性：查看具体 claim 的文本上下文
python -c "
import json
with open('temp/claims/<session_id>/step2_enriched.json') as f:
    claims = json.load(f)
for c in claims:
    if c['id'] == '<claim-id>':
        print('Statement:', c['statement'])
        print('Evidence:', c['evidence_quote'])
"

# 2. 编辑 gate_validate_claims.py，在 NON_COMPANY 集合中追加新模式
# ⚠️ 直接编辑 Python 文件，追加到集合中。不要尝试 sed 全局替换或其他自动化方式。

# 3. 清除 Gate 2 缓存，重跑 continue
rm temp/claims/<session_id>/gate2_result.json
python scripts/extract_claims_pipeline.py continue
```

## 按 raw 类型的假阳性预判

| raw 类型 | 常见假阳性模式 | 预防动作 |
|----------|--------------|---------|
| 早盘 | "科技股", "概念股", "高位", "低位" | 预判加入 NON_COMPANY |
| 复盘专栏 | "资金从高位科技", "主导行业", "弹性有限" | 同上 |
| 板块分析 | "上游材料", "下游应用", "国产替代" | 同上 |
| 方法论 | "交易纪律", "仓位管理", "风险控制" | 通常不触发 Gate 5 |
| 个股深度 | 无（真阳性为主） | 确保代码标注正确 |

## 相关代码位置

```
scripts/gate_validate_claims.py
  → gate5_stock_codes()
  → NON_COMPANY: set[str]
```
