# 多动态合并提取（一次 C2 session 处理多条 B站动态）

**适用**：一天内有多条未处理的 B站动态（如 0953/1147 盘中图片动态 + 2300 晚间复盘），
内容互补、单条颗粒度小。2026-08-04（4 个 source → 27 条）和 2026-08-05（3 条动态 → 21 条，
claim-20260805-040~060）两次实战验证。

## 做法

1. **只对内容最丰富的一条执行 `start`**（拿到 session id），其余动态并入同一 session
2. step1_raw.json 中每条 claim 的 `source_path` **各自指向其真实来源文件**——不必与 session 的 raw 一致
3. Gate 1/2/3 只校验字段完整性和 source_path 文件存在性，**不校验与 session raw 的一致性**
4. Step 2 补代码时一次性查询所有动态涉及的公司（东方财富 suggest API 批量循环）

## 预检查去重

合并提取前先 grep 现有 claims 的 subject/statement，判断动态内容是否已被同日早盘 claims 覆盖：

```bash
grep -l "关键词" knowledge/claims/claim-YYYYMMDD-*.yaml
```

典型场景（2026-08-05 实测）：1147 动态的 ADP/ISM 部分与早盘专栏 claim 重复——
只提取增量信息（T出纪律、科技仓位5成上限、B浪后C浪），重复部分不建 claim。

## 编号规则

- 同一天多个 yaml 文件用 `claim-YYYYMMDD-001`、`-002` 区分
- 同文件内 `id` 连续递增；提取前查现有最大编号避免冲突：
  `grep "^- id:" knowledge/claims/claim-YYYYMMDD-*.yaml | tail -1`

## 同步管线

提取完跑标准四步：discover（`PYTHONPATH=src .venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py --all-missing`）→
Neo4j migrate → Qdrant index（增量用 `index_claims_to_qdrant_monitored.py`，全量才 `--force-recreate`）→ 重启 Agent。
Qdrant 服务端（port 6333）被误杀时需 `exec ./bin/qdrant` 重启（见 qing-cron-analysis-fallback 陷阱）。
