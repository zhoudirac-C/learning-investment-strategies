---
name: qing-learning
description: |
  投资知识管理系统总入口。根据触发词路由到子 skill。
  - `ing` / 提取 claim → 加载 qing-learning-claim（C2 编排管线）
  - 学习/消化/处理 raw → 加载 qing-learning-ingestion
  - qing review / 复盘 → 加载 qing-learning-review
  - 同步知识库 / sync → 加载 qing-learning-sync
---

# qing-investment-knowledge — 总入口

## 触发路由

| 触发词 | 加载子 skill |
|--------|-------------|
| `ing`、提取 claim、写 claim、学这篇、消化 | **qing-learning-claim**（C2 编排管线） |
| 处理 raw、学习、整理文档 | **qing-learning-ingestion**（完整管线） |
| qing review、方法论复盘、review claims、检查一致性 | **qing-learning-review** |
| 同步知识库、sync、discover、migrate、重建索引 | **qing-learning-sync** |

## 跨 Skill 兼容性

qing-learning 采用**双轨制**架构（市场认知层 vs 操作工具层），这对下游 skill 有明确影响：

| 下游 Skill | 影响 | 处理方式 |
|-----------|------|---------|
| `qing-stock-analysis` | 检索 claims 时需区分市场认知 vs 技术工具 | 技术 claims 只作为工具引用，不用于判断当前市场方向 |
| `qing-learning-review` | 技术 claims 不参与 drift/contradiction 分析 | 跳过 `claim_type: technical-knowledge` 且 `timeframe: permanent` 的 claims |
| `stock-research-engine` | 无直接影响 | 通用个股研究工具，不依赖 qing-learning claims |
| `valuation-analysis` | 无直接影响 | 基于《股市真规则》方法论，独立于博主内容体系 |

> **注意**：下游 skill 不应重复定义本兼容性说明，应引用本总入口 skill。历史上曾因 skill 合并导致内容错放——详见 `qing-learning-review/references/skill-scope-boundary.md`。

## 用户偏好（核心）

1. **文档驱动执行**：有文档时直接读文档执行，无需逐步确认
2. **内容验证优先**：检查文件时读原文内容，不只比较文件名
3. **先处理文档，后改脚本**：硬性优先级
4. **远程版本优先**：配置文件接受远程版本，再写入本地数据
5. **持仓更新完整 pipeline**：positions → 行情 → claims → 更新 → 建议
6. **操作建议必须关联 claims**：引用具体 claim ID
7. **修改前先提交+拉取**：`git stash → pull → stash pop`

## 禁止事项

- 不删除旧观点；冲突用 supersedes/contradicts 连接
- 不把单日语境直接提升为长期 framework
- 不创建没有 source path 和 evidence quote 的 claim
- 不跳过 knowledge base sync（discover → Neo4j → Qdrant → restart）
- 不跳过 claim 字段完整性自检

## 参考

完整文档和 35+ 参考文件：`skills/qing-learning/references/`

### Skill Name Collision

当 Hermes global skills 与 project repo skills 同名时，使用 `-hermes-copy` 后缀解决。详见 `references/skill-name-collision-hermes-copy-pattern.md`。
