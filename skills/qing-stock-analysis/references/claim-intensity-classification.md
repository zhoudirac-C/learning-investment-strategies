# Claim Intensity 分级体系

> 方案C实现：区分 UP "认真分析" vs "随口一提"，在检索阶段过滤低强度 claims。
> 创建：2026-06-07 | 状态：Schema+数据已完成，Neo4j/Qdrant/检索代码待迁移（任务4-10）

## 三个等级

| 等级 | 标签 | 定义 | 典型场景 | 检索行为 |
|------|------|------|---------|---------|
| 🔴 high | 认真分析 | UP 深入研究、确定性高 | 视频专题推荐、专栏深度分析、明确"必买/确定性很高/类比" | 正常进入 prompt，可引用但必须配实时数据 |
| 🟡 medium | 一般提及 | UP 复盘/方向判断 | 复盘提及某方向、一般性看好、默认分类 | 正常进入，时效标注 |
| ⚪ low | 随口一提 | 非核心观点 | 盘中转发、一句话动态、评论回复 | 个股查询时排到末尾或过滤 |

## 8 条自动分类规则（优先级递减）

```
Rule 1: claim_type = methodology | operation | technical-knowledge
  → intensity = "high"
  理由：方法论/操作框架是 UP 核心体系

Rule 2: confidence = "high" AND 包含强语言关键词
  关键词："确定性","一定要","必买","核心","主线","类比","格局","机构都要买","确定性很高","可以格局","类比锂电池"
  → intensity = "high"
  理由：高置信度 + 强语言 = 认真分析

Rule 3: source_type 属于深度来源
  匹配：bilibili_video, bilibili_column, 视频, 复盘, 复盘专栏, 专栏, 深度, 早盘, video, column
  或 source_type 包含 "视频","复盘","专栏","深度"
  → intensity = "high"
  理由：视频/专栏是精心准备的深度内容

Rule 4: source_type 包含 "repost" 或 "转发"
  → intensity = "low"
  理由：转发/转载 = 随口

Rule 5: subject 含6位股票代码 + statement < 50字
  → intensity = "low"
  理由：盘中随口提某只票

Rule 6: claim_type = "stock-view" AND confidence = "low"
  → intensity = "low"
  理由：低置信度个股观点

Rule 7: evidence_quote < 30字 AND interpretation < 50字
  → intensity = "low"
  理由：原文引用短 + 解释短 = 真正一句话

Rule 8: 默认
  → intensity = "medium"
  理由：需要人工 review，默认中等
```

## 当前分布（561条 claims，2026-06-07）

| 等级 | 数量 | 占比 |
|------|------|------|
| high | 444 | 79.1% |
| medium | 115 | 20.5% |
| low | 2 | 0.4% |

2条 low 为真正随口：`"要谨慎"` 和 `"大概率能反复，短期没法直接看空"`

## 修改的 Schema 字段

`src/qing_investment/claim_schema.py`:
- 新增 `VALID_INTENSITY = {"high", "medium", "low"}`
- `REQUIRED_FIELDS` 新增 `"intensity"`
- `Claim` dataclass 新增 `intensity: str`
- `validate_claim_dict` 新增 `_require_enum("intensity", ...)`

## 回填脚本

`scripts/backfill_claim_intensity.py` — 自动按 8 条规则分类所有 YAML claims。
重新运行：`PYTHONPATH=src .venv/bin/python scripts/backfill_claim_intensity.py`

## 待完成（任务4-10）

- Neo4j 迁移：`migrate_claims_to_neo4j.py` 增加 `intensity` 属性 + 索引
- Qdrant 索引：`index_claims_to_qdrant.py` payload 增加 `intensity`
- Neo4j 客户端：`neo4j_client.py` 查询增加 `min_intensity` 过滤参数
- 检索节点：`nodes.py` `retrieve_knowledge` 增加 intensity boost/penalty
- Chat 端点：`main.py` prompt 按 intensity 分级标注
- 时效模块：`claim_freshness.py` 附加 intensity 信息
- 全量重建：Neo4j + Qdrant 重新索引

详见 `docs/superpowers/plans/2026-06-07-claim-intensity-field.md`
