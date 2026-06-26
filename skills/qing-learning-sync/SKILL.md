---
name: qing-learning-sync
description: |
  知识库同步管线：discover → Neo4j migrate → Qdrant → restart Agent。
  触发词：同步知识库、sync、重建索引、discover、migrate、Qdrant
---

# qing-learning-sync

## 四步强制流水线

```
① discover_claim_relations.py   →   ② migrate_claims_to_neo4j.py   →   ③ index_claims_to_qdrant.py   →   ④ 重启
    (ONNX+LLM 发现关系)                (MERGE 原子写入 Neo4j)               (向量重建，需独占锁)              (Agent+MCP)
```

**前置：Qdrant 重建前必须停 Qing-Agent + Hermes gateway + MCP server**。Neo4j 迁移不需要停。

推荐直接跑封装好的脚本：

```bash
cd ~/learning-investment-strategies
./bin/run_sync_pipeline.sh
```

脚本会依次完成：停进程 → discover → Neo4j → Qdrant → 重启 Qing-Agent → 重启 Hermes gateway → 验证 MCP 连接。

如需手动执行，参考 `bin/run_sync_pipeline.sh` 内容。

## ~~Claims→Entry 桥接（2026-06-10 已废弃）~~

`sync_claims_to_config.py` 功能设计未落地，`entry_suggestions/` 始终为空。此步骤已从管线移除。

## 关键坑

1. **Qdrant 重建需要独占锁 —— 必须同时停 Qing-Agent + Hermes gateway + MCP server（2026-06-26 修正）**
   - Qdrant 本地模式通过 `.qdrant_data/.lock` 文件实现独占访问
   - **三个进程可能同时持有该锁**：Qing-Agent（uvicorn）、MCP Qdrant server（Hermes gateway 子进程）、Hermes gateway 本身
   - `delete_collection()` 需要独占写锁，任一进程持有锁都会导致失败
   - 脚本内置 30 秒等待 + 强制删除兜底，但强制删除活跃进程的锁可能损坏数据
   - 正确做法：先 `pkill -f "hermes_cli.main gateway"` 关 gateway（顺带关 MCP 子进程），再 `pkill -f "uvicorn.*qing_investment"` / `pkill -f "gunicorn.*qing_investment"` 关 Agent
   - **避免在后台命令行里直接用 `pgrep -f "mcp_qdrant_server" | xargs kill`**：命令行文本本身会匹配 pgrep 模式，导致 bash 自杀。应把命令写到脚本文件里执行，或用 `pkill -f`
   - **Neo4j 迁移不需要停 Qing-Agent**：MERGE 是原子的，Neo4j 原生支持 MVCC 并发读写
2. `PYTHONUNBUFFERED=1` — 否则 cron 捕获不到 stdout
3. **仅改元数据字段**（timeframe/related_stocks/tags）→ discover 输出 0 relations 是预期的，可跳过 discover 直接 migrate
4. **改 supersedes/contradicts** → 必须跑 discover --all-missing，否则空列表覆盖 Neo4j 已有关系
5. **新 claim 无 supersedes/contradicts → 可跳过 discover，但必须确定无关系（2026-06-12 修正）**：
   - discover 调 ONNX+LLM 可能超时 120s+，可以节省时间
   - **但只适用于你确信新 claim 与存量 claim 没有潜在关系的情况**（如纯技术知识类 claim、纯操作纪律类 claim）
   - **判断标准**：
     - ✅ 可以跳过：纯技术知识（如"什么是球形硅微粉"）、纯操作纪律（如"止损纪律，跌X%清仓"）、纯事实描述（如"全A触及年线"）
     - ❌ **不能跳过**：方向判断（如"科技内部跷跷板"）、周期判断（如"调整期1-2个月"）、个股/板块观点（如"商业航天IPO双面效应"）——这些几乎必然会与存量claim产生supersedes/contradicts/supplements关系
   - 如果不确定，跑 discover 更安全。跳过的代价是关系缺失，存量 claim 的 superseded_by 无法更新，Neo4j 图不完整
6. **mtime 竞争条件**（2026-06-11）：git commit/push 更新已有 claim 文件的 mtime。若 mtime > last_sync 但 hash 未变，脚本仍会尝试重新 migrate。`migrate_claims_to_neo4j.py` 已修复 `CREATE`→`MERGE+SET`，重复 migrate 安全不报错。但首次 migrate 前删除旧节点的逻辑仍会执行（无害）。
7. **同步后必须验证 Agent 在线**：`curl http://localhost:8000/health`

8. **MCP / Hermes gateway 重启必须用 `gateway run --replace`，`hermes restart` 已不可用（2026-06-26 修正）**：
   - 当前 `hermes` CLI 没有 `restart` 子命令；MCP server 由 Hermes gateway 进程统管
   - **正确做法**：同步时 Step 0 先杀掉 Qing-Agent **和** Hermes gateway（连带关闭其管理的 qdrant/neo4j MCP 子进程），Qdrant 重建完后再重启 Qing-Agent，最后用 `nohup <hermes-venv-python> -m hermes_cli.main gateway run --replace &` 拉起 gateway
   - 这同时重启了 **Kimi Code CLI 侧**和 **Hermes Agent 侧**的 MCP 连接，因为二者共享同一个 gateway
   - 重启后务必 `hermes mcp test qdrant` / `hermes mcp test neo4j` 验证工具已 discover
   - 如果 Qing-Agent 被 systemd/supervisor 管理（auto-restart），kill 后它会自动重启。可通过 `sleep 3 && pgrep -f 'gunicorn.*qing_investment'` 确认。这种情况下不需要显式 `uvicorn &` 命令，但需验证自动重启是否成功加载了新 Qdrant 数据。

9. **000636 类歧义警告排查**：`migrate_claims_to_neo4j.py` 的代码→名称映射从 `positions.yaml` + `watchlist.yaml` 动态构建，不会出错。歧义通常来自**其他脚本的独立映射表**（如 `backfill_claim_related_stocks.py` 的 supplemental 硬编码字典）。排查路径：
   - 先确认 YAML 源文件正确：`grep '000636' config/stock_monitor/watchlist.yaml`
   - 再查所有脚本的独立映射表：`grep -rn '000636' scripts/ --include='*.py'`
   - 修复后重新 migrate + Qdrant rebuild（--force-recreate），旧进程的警告来自遗留进程

10. **Claim 节点必须用 MERGE 而非 CREATE（2026-06-11 修复）**：`_migrate_single_claim()` 中 Claim 节点必须用 `MERGE ... SET`，而非 `CREATE`。否则重复迁移（文件 hash/mtime 变化导致判断为"需要处理"）时会因 `UNIQUE CONSTRAINT` 报错：
    ```
    Node(771) already exists with label `Claim` and property `id` = 'claim-20260611-001-a'
    ```
    **修复写法**：
    ```python
    MERGE (c:Claim {id: $id})
    SET c.statement = $statement, ...
    ```
    这与 Stock/SourceDocument 等节点用 MERGE（见 migrate 脚本其他部分）保持一致。

11. **Neo4j migrate 被 SIGTERM 终止是安全的**：exit 143（128+15）表示超时或手动 kill。Neo4j MERGE 是原子写入，已提交的条目不回滚。重新运行 migrate 会显示 "All N files up to date"——不需要 panic，校验即可：
   ```bash
   # 校验 Neo4j 实际节点数
   PYTHONPATH=src .venv/bin/python -c "
   from neo4j import GraphDatabase
   from qing_investment.agent.config import settings
   d = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
   with d.session() as s:
       r = s.run('MATCH (c:Claim) RETURN count(c) as cnt'); print(f'Claims: {r.single()[\"cnt\"]}')
       r = s.run('MATCH (s:Stock) RETURN count(s) as cnt'); print(f'Stocks: {r.single()[\"cnt\"]}')
       r = s.run('MATCH ()-[r:ABOUT]->() RETURN count(r) as cnt'); print(f'ABOUT: {r.single()[\"cnt\"]}')
   d.close()
   "
   ```
12. **Qdrant 重建时 Vector dimension mismatch**：`ValueError: could not broadcast input array from shape (512,) into shape (1,)` 表示旧 collection 的 schema 与新模型不匹配。**必须用 `--force-recreate`** 删除旧 collection 重建。不要手动删 `.qdrant_data/` 目录——Qdrant local 模式有内部状态，直接用脚本的 `delete_collection()` 接口。

## 详细文档

详见 `docs/neo4j-relation-pipeline.md`
