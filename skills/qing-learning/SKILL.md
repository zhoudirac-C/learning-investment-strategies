---
name: qing-learning
description: Use when the user asks to ingest, learn, digest, or update new blogger investment content, including ing, 学习今天内容, 消化早盘, 更新方法论, or processing Raw files.
---

# qing-learning

## 目标

持续学习博主新内容，更新 `sources`、`knowledge/claims`、`knowledge/wiki`、`methodology`、`framework` 和日志。

## 触发

用户表达以下意图时使用：

- `ing`
- 学习今天内容
- 消化这篇早盘/午盘/复盘
- 更新博主方法论
- 处理 Raw 中的新稿

## 必读参考

1. 先读 `framework/learning-update-protocol.md`。
2. 抽取 claim 前读 `skills/qing-learning/references/claim-schema.md`。
3. 遇到矛盾观点时读 `framework/contradiction-policy.md`。

## 工作流程

1. 运行 `scripts/find_unprocessed.py` 找未处理 raw。
2. 每次默认只处理一篇 raw，除非用户明确要求批量。
3. LLM 必须阅读全文后再写入任何结论。
4. 先抽取 claims，再更新 wiki、methodology、framework。
5. 只有满足 durable rule 的观点才进入 framework。
6. 更新 `knowledge/wiki/index.md`、`knowledge/claims/index.md` 和 `knowledge/wiki/log.md`。
7. 输出 Learning Update Report。

## 禁止事项

- 不用脚本替代 LLM 判断方法论变化。
- 不把单日语境直接提升为长期 framework。
- 不创建没有 source path 和 evidence quote 的 claim。
- 不删除旧观点；冲突观点使用 supersedes 或 contradicts 连接。
