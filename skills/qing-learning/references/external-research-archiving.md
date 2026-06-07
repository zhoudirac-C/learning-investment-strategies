# 外部研究报告归档规则

> 适用场景：UP 复盘/视频中引用的投行/机构研究报告，UP 明确说了延迟再看。

## 与 UP 原创内容的区别

| 维度 | UP 原创内容 | 外部研究报告 |
|------|-----------|------------|
| 目录 | `sources/raw/财经/` | `sources/research/` |
| 处理方式 | 完整 qing-learning（raw→claims→wiki→framework） | **暂不处理**，到期评估 |
| 时效 | 按 source_date 管理 | 按 UP 指定的延迟窗口 |
| Claims | 必须提取 | **不提取** |
| 索引 | claims/index.md | `sources/research/index.md` |

## 目录结构

```
sources/research/
├── index.md                          ← 索引 + 使用规则 + 到期提醒
├── <机构>_<日期>_<标题>.md           ← 要点摘录（不提取 claims）
└── pdfs/
    └── <机构>_<标题>_<日期>.pdf      ← 原始 PDF
```

## 处理流程

1. **保存 PDF** 到 `sources/research/pdfs/`
2. **提取要点** 写入 markdown（非 claim 格式，保留关键数据和结论即可）
3. **标注 UP 时效判断**：延迟多久、预计什么时候再看
4. **在相关 UP raw/wiki 中添加引用链接**
5. **不进入 qing-learning 流程**：不提取 claims、不更新 wiki/framework
6. **到期提醒**：到达 UP 指定时间窗口后评估是否需要提取观点

## 案例：高盛 2026-06-03 两份报告

UP 在 6/7 周复盘中说：
- "全盘的这篇报告现在不太好说，因为时间不太对"
- "他给的时间节点差不多也是七八月份"
- "往后移就行了，不用提前去关注"
- "后面我们肯定还是要再把它拿出来看的"

处理：
- 存入 `sources/research/高盛_2026-06-03_*.md` + PDF
- 在周复盘 raw 中标注引用链接 + UP 延迟提示
- 在每日复盘 wiki 中标注外部研究引用
- `index.md` 记录到期时间：2026-07~08

## index.md 模板

```markdown
# 外部研究资料索引

> ⚠️ 使用规则：每份报告标注 UP 的时效判断，到期前不提取 claims。

## <年份>

| 报告 | UP 判断 | 预计再看 |
|------|---------|---------|
| [报告名](文件名.md) | 延迟 X 个月 | YYYY-MM |

## 处理规则

1. **不进入 qing-learning**：不提取 claims，不更新 wiki/framework
2. **到期提醒**：到达时间窗口后重新评估
3. **引用关系**：相关 UP raw 中标注链接即可
```
