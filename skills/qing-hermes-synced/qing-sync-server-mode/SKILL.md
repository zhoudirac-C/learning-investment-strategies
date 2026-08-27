---
name: qing-sync-server-mode
description: |
  知识库同步管线的服务端模式更正（2026-08-16 起）。qing-learning-sync（repo 只读 skill）
  中"Qdrant 重建前必须停 Agent/gateway/MCP"的流程已过时。本 skill 记录当前正确的
  在线重建流程与验证方法。触发词：Qdrant 重建、Neo4j migrate、在线同步、sync。
---

# qing-sync-server-mode — Qdrant/Neo4j 在线同步（服务端模式）

## 核心结论

自 Qdrant 迁移到**二进制服务端模式**（`./bin/qdrant`, port 6333, RocksDB, 数据在 `./storage/`）后，
`qing-learning-sync`（repo `skills/` 目录，`skills.external_dirs` 只读）中
"必须停 Qing-Agent + Hermes gateway + MCP server 才能重建"的流程**已过时，不再需要**。

## 同步前预检（2026-08-25 实战补充）

跑管线前先确认三件事，避免中途才发现基础服务缺失：

```bash
# ① Qdrant 服务端是否在线（同步时可能未启动——上次实测就是 curl 空响应）
curl -s localhost:6333/collections   # 空/超时 → 需要先恢复
# 恢复：Hermes terminal 前台命令禁止 shell 级 nohup/& 包装（会 exit -1 被拒），
# 必须 terminal(background=true) 跑 `cd ~/learning-investment-strategies && ./bin/qdrant`，
# 然后 sleep 3 再 curl localhost:6333/collections 验证
# ② 确认同步缺口：Neo4j 里按日期查 claim 是否已进库
#    MATCH (c:Claim) WHERE c.id STARTS WITH 'claim-YYYYMMDD' RETURN c.id
#    若为空 → 该日 claims 已 ingest 但未 migrate/index，正是本次要补的
# ③ Agent 状态：curl localhost:8000/health（在线同步全程不应中断）
```

**discover 日志位置**：repo 下 `logs/discover_relations_<timestamp>.log`（不是 /tmp），
进度行格式 `[N/M] claim-XXXX...`，脚本每 10 分钟输出一次进度摘要。

**⚠️ 已知非错误日志（2026-08-25 更正：并非无害）**：discover 启动时可能打印
`ONNX embedding model failed to load (huggingface-hub ... <1.0 is required but found ...)，
falling back to hash embedding`——discover 会照常跑完不报错，但这是**静默降级**：
hash bigram 只认字面重叠，语义近义但表述不同的关系（"回踩"vs"回调"）全部漏召回，
导致观点演进链断裂。**不要当作无害忽略**——看到此日志应先按下方
「环境坑：ONNX embedding 静默 fallback 到 hash」章节修复（降级 hub 到 <1.0）
再跑或重跑 discover。若时间紧迫可先跑完（LLM 判定仍有效，只是候选召回不全），
但需标记待重跑。

## 当前正确流程（在线，无需停任何进程）

```bash
cd ~/learning-investment-strategies

# 1. Neo4j 迁移（MERGE 原子写入，在线安全）
#    注意：可能超过 execute_code 5 分钟沙箱超时——后台启动 + 轮询，不要前台等待
PYTHONPATH=src setsid nohup .venv/bin/python scripts/migrate_claims_to_neo4j.py \
  > /tmp/migrate.log 2>&1 < /dev/null &
# 轮询：pgrep -f migrate_claims + tail /tmp/migrate.log

# 2. Qdrant 全量重建（服务端支持多 Client 并发）
PYTHONPATH=src setsid nohup .venv/bin/python scripts/index_claims_to_qdrant.py \
  --force-recreate --skip-agent-kill > /tmp/qdrant_rebuild.log 2>&1 < /dev/null &
# ~3938 claims 约 1 分钟；日志出现 "✅ Integrity check passed" 即完成

# 3. 验证
curl -s localhost:6333/collections/qing_claims   # points_count 应等于 Neo4j Claims 数
PYTHONPATH=src .venv/bin/python -c "
from neo4j import GraphDatabase
from qing_investment.agent.config import settings
d = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
with d.session() as s:
    print('Claims:', s.run('MATCH (c:Claim) RETURN count(c) as cnt').single()['cnt'])
d.close()"
curl -s localhost:8000/health   # Agent 全程未中断
```

## 实测记录（2026-08-24）

- Neo4j Claims: 2903 → 3938（新增 1035），ABOUT 关系 9349
- Qdrant force-recreate 后 points_count = 3938，512 维完整性检查 10/10 通过
- Qing-Agent / gateway / MCP **全程未中断**，Agent 未重启即加载新数据

## 环境坑：ONNX embedding 静默 fallback 到 hash（2026-08-25 修复）

**症状**：discover/索引日志出现
`ONNX embedding model failed to load (huggingface-hub>=0.34.0,<1.0 is required...) falling back to hash embedding`，
但管线照常跑完——**无报错、难察觉**。

**根因**：项目 `.venv` 的 `transformers 4.57.6` 硬要求 `huggingface-hub<1.0`，
若 hub 被升到 ≥1.0（如 1.16.4），`AutoTokenizer.from_pretrained()` 直接抛错。

**影响**：discover 候选召回 / Qdrant 索引用 hash bigram（字面重叠才有相似度），
语义近义但字面不同（如"回踩"vs"回调"）的关系全部漏召回 → 关系链断裂。

**修复**：
```bash
.venv/bin/pip install "huggingface-hub>=0.34.0,<1.0"   # 落到 0.36.2
.venv/bin/pip check  # 确认无 broken requirements
# 验证 ONNX 可用（应输出 OnnxEmbeddingModel）：
PYTHONPATH=src .venv/bin/python -c "from qing_investment.agent.tools.llm_client import get_embedding_model; print(type(get_embedding_model()).__name__)"
```

**⚠️ 进程内单例不随 pip 更新**：已运行的 discover 进程仍用 hash，必须 kill 重启。
**⚠️ --all-missing 跳过已标记 claim**：重启 discover 前，若上次跑已逐条写回
`last_discovered` 标记（`write_results_to_yaml` 逐条写），须先清除标记——
`grep -rl "last_discovered: 2026-08-25" knowledge/claims/ | 判重后删除对应行`。
重跑是**覆盖式写回** supersedes/contradicts/supplements，安全。

**排查顺序**：先看 discover 日志前 5 行有无 fallback 警告；再 `.venv/bin/pip check`。

## discover 429 限流与定点重判（2026-08-25 实测）

**症状**：discover 日志出现
`LLM error after 3 retries: Error code: 429 - stealth/ox-alpha is temporarily rate-limited...`，
该条候选关系直接落为 `none`。

**识别特征**：候选 sim 很高（>0.8）却判定 none、且 reason 含 "LLM error" = **限流漏判**，
不是真的语义无关。8/25 实测 claim-20260825-032-a（AI调整结构完成）3 条 supersedes 候选
（sim 0.907-0.911）全部因 429 落空，重判后全部找回——漏掉它们会断掉
"AI 调整阶段判断 6月→8月 演进链"。

**同模式变体（2026-08-27 实测）：模型下线 404**。`LLM error after 5 retries: 404 -
testing period ended, Use it now: <新模型>` 也是漏判，不是限流——重试无效。
8/27 实测 discover 跑完"Found 0 relations"，但定点重判 claim-20260826-025-a 显示
3 条 sim 0.898-0.900 候选全部因 404 落空。处理：先切换模型（qing-agent-model-switch），
清除 `last_discovered` 标记，重跑。

**修复流程**：
1. `judge_relation` 重试已从 3 提升到 **5 次**（`src/qing_investment/agent/tools/discover_claim_relations.py:146`
   `for attempt in range(5)`，backoff `2**attempt` = 1s/2s/4s/8s）。
   日后日志出现 "LLM error after **5** retries" 是正常兜底（5 次全失败），非 bug。
2. **定点重判单条**（`--claim-id` 模式**不检查** last_discovered——无需清标记、
   不影响其他 claim，与 `--all-missing` 不同）：
   ```bash
   PYTHONPATH=src .venv/bin/python src/qing_investment/agent/tools/discover_claim_relations.py \
     --claim-id claim-YYYYMMDD-NNN-x
   ```
3. 重判写回后必须重跑 `migrate_claims_to_neo4j.py` 同步 Neo4j 关系边
   （Qdrant 只存文本向量、不含关系，关系变化不触发向量重建）。
4. 重试逻辑有回归测试：`tests/test_discover_judge_relation_retry.py`
   （mock LLM 持续抛错，断言 invoke 恰好 5 次 + 返回 none 兜底不抛异常）。
   修改重试次数/backoff 时先跑此测试（TDD 流程，改动前先写失败测试）。

## discover LLM fallback 机制（2026-08-27 实施）

针对"主模型 404 下线/429 限流导致整批关系漏判"问题，代码已改两层：

1. **`llm_client.get_llm_client_with_fallback()`**：返回 FallbackChatOpenAI，invoke 失败自动按链切换（deepseek-v4-flash → sensenova-6.8-flash-lite → sensenova-u1-fast → glm-5.2，全 sensenova 生态内，避免跨 provider 的 base_url/api_key 问题）。discover_claim_relations.py 已接入。
2. **judge_relation 错误分类**：LLM 全失败返回 `{"relation": "error"}` 而非 `none`；process_claim 遇 `error` **跳过不计入结果、不写 last_discovered**——下次 `--all-missing` 自动重试，无需手动清标记。

**行为变化**：修复后 discover 日志不再出现"LLM error 落 none"；若全部 fallback 模型都挂，judge 抛 RuntimeError 直接中断（fail-fast，不再静默吞错）。

## discover 关系发现（仍然需要）

- 新 claim 有潜在观点关系（方向判断/周期判断/个股板块观点）→ 必须跑
  `bash scripts/run_discover_with_progress.sh`（内部 `--all-missing`，自动只处理新 claim）
- 纯技术知识/纯操作纪律类可跳过
- discover 每条 claim 需 LLM 判定 1~2 分钟，35 条约 40 分钟——后台跑 + 轮询日志
- 启动方式：`terminal(background=true, notify_on_complete=true)` 跑
  `bash scripts/run_discover_with_progress.sh`，完成时自动通知，不必手动轮询

## qing-learning-sync 过时章节对照

| repo skill 章节 | 服务端模式下状态 |
|---|---|
| 坑 1（.lock 独占锁、停四进程） | ❌ 不再适用（local_mode 遗留） |
| 坑 8（MCP 重启分两边） | ⚠️ 仅在杀 MCP server 进程时相关，日常重建不需要 |
| 坑 12（force-recreate） | ✅ 仍适用，但无需停进程 |
| 坑 13（run_sync_pipeline.sh Step 0 误杀 qdrant 服务端） | ⚠️ 若跑封装脚本仍需注意；手动分步跑可完全避开 |

## 为什么 repo skill 不直接改

`~/learning-investment-strategies/skills/` 位于 Hermes 配置的 `skills.external_dirs`，
对 autonomous curation 只读（patch 被拒绝）。本 skill 是执行层补充；
下次人工维护 repo skills 时，应把本文件内容合并进 `qing-learning-sync/SKILL.md`
并删除本 skill。
