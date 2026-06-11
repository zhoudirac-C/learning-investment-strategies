# Qdrant 本地模式 → 二进制服务端迁移计划

> 目标：消除 `portalocker.EXCLUSIVE` 单进程锁限制，允许 MCP Qdrant Server 和 Qing-Agent 同时访问
> 策略：方案① — 下载 Qdrant Rust 二进制，数据从 SQLite 本地模式迁移至 RocksDB 服务端
> 风险等级：低（每一步可独立回滚）
> 预计总耗时：15-20 分钟（含验证）

---

## 现状

```
┌─────────────────┐     ┌─────────────────┐
│  MCP Qdrant     │     │  Qing-Agent      │
│  (stdio)         │     │  (port 8000)     │
│       ↓          │     │       ↓          │
│  QdrantClient    │     │  QdrantClient    │
│  (path=本地)     │     │  (path=本地)     │
└───────┬─────────┘     └───────┬─────────┘
        │        ✗ 锁冲突        │
        └──────────┬────────────┘
                   ↓
          .qdrant_data/.lock
          (portalocker LOCK_EX)
```

## 目标

```
┌─────────────────┐     ┌─────────────────┐
│  MCP Qdrant     │     │  Qing-Agent      │
│  (stdio)         │     │  (port 8000)     │
│       ↓          │     │       ↓          │
│  QdrantClient    │     │  QdrantClient    │
│  (host:6333)     │     │  (host:6333)     │
└───────┬─────────┘     └───────┬─────────┘
        │          ✅ 并发        │
        └──────────┬────────────┘
                   ↓
         qdrant binary (:6333)
              ↓
         ./qdrant_storage/
         (RocksDB, 原生支持并发)
```

---

## 步骤拆解

### Phase 0：预检与备份

- [x] **0.1** 记录当前数据规模

```bash
$ du -sh .qdrant_data/
63M	.qdrant_data/
$ ls -lh .qdrant_data/collection/*/storage.sqlite
-rw-r--r-- 1 ubuntu ubuntu 3.8M Jun 11 00:29 .qdrant_data/collection/qing_claims/storage.sqlite
-rw-r--r-- 1 ubuntu ubuntu  60M Jun  8 08:51 .qdrant_data/collection/qing_knowledge/storage.sqlite
```

- [x] **0.2** 备份数据目录

```bash
$ cp -r .qdrant_data .qdrant_data.bak.$(date +%Y%m%d)
$ du -sh .qdrant_data.bak.*
63M	.qdrant_data.bak.20260611
```

- [x] **0.3** 确认 qdrant-client 版本（需 ≥1.12，当前 1.18.0）

```bash
$ .venv/bin/pip show qdrant-client | grep Version
Version: 1.18.0
```

- [x] **0.4** 记录当前 collection 配置（向量维度、距离度量）

```bash
$ PYTHONPATH=src .venv/bin/python3 -c "..."
qing_knowledge: dim=512, dist=Cosine
qing_claims: dim=512, dist=Cosine
```

---

### Phase 1：修复 QdrantClientWrapper 远程模式 bug

**文件**：`src/qing_investment/agent/tools/qdrant_client.py`

**问题**：`search()` 方法中远程分支调了不存在的 `self._client.search()`（qdrant-client 1.18.0 无此方法）。

**改动**：第 77-104 行，统一使用 `query_points()`，移除 `self._is_local` 分支。本地模式保留 `_search_manual()` fallback。

```diff
-    if self._is_local:
-        try:
-            resp = self._client.query_points(
-                collection_name=collection,
-                query=query_vec.tolist(),
-                limit=limit,
-                with_payload=True,
-            )
-            return [
-                {"id": r.id, "score": r.score, "payload": r.payload or {}}
-                for r in resp.points
-            ]
-        except Exception:
-            return self._search_manual(query_vec, collection, limit)
-    else:
-        results = self._client.search(
-            collection_name=collection,
-            query_vector=query_vec.tolist(),
-            limit=limit,
-            with_payload=True,
-        )
-        return [
-            {"id": r.id, "score": r.score, "payload": r.payload or {}}
-            for r in results
-        ]
+    try:
+        resp = self._client.query_points(
+            collection_name=collection,
+            query=query_vec.tolist(),
+            limit=limit,
+            with_payload=True,
+        )
+        return [
+            {"id": r.id, "score": r.score, "payload": r.payload or {}}
+            for r in resp.points
+        ]
+    except Exception:
+        if self._is_local:
+            return self._search_manual(query_vec, collection, limit)
+        raise
```

- [x] **1.1** 应用上述改动到 `qdrant_client.py`
- [x] **1.2** 验证改动未破坏现有本地模式

```bash
$ PYTHONPATH=src .venv/bin/python3 -c "..."
本地搜索 OK: 3 条结果
第一条: id=0052589b-356d-1b5b-5471-6bb772cb53ec, score=nan
# (score=nan 是因为用了全零向量测试，非 bug)
```

- [x] **1.3** 提交改动的 commit（方便独立回滚）

```
[master aecc654] fix: QdrantClientWrapper.search() remote mode bug
```

---

### Phase 2：下载 Qdrant 二进制

- [x] **2.1** 下载 v1.18.2（与 qdrant-client 1.18.0 兼容）

> 网络下载中断，用户手动上传完整文件替代

```bash
$ cp /home/ubuntu/.hermes/cache/documents/.../qdrant-x86_64-unknown-linux-gnu.tar.gz bin/qdrant.tar.gz
$ ls -lh bin/qdrant.tar.gz
-rw-rw-r-- 1 ubuntu ubuntu 30M Jun 11 08:39 bin/qdrant.tar.gz
$ tar xzf bin/qdrant.tar.gz -C bin/
$ chmod +x bin/qdrant
```

- [x] **2.2** 验证二进制可用

```bash
$ ./bin/qdrant --version
qdrant 1.18.2
```

- [x] **2.3** 创建 Qdrant 数据目录和配置

```bash
$ mkdir -p ./qdrant_storage
```

---

### Phase 3：启动 Qdrant 服务端并创建 Collection

- [x] **3.1** 启动 Qdrant 二进制（后台运行）

```bash
cd ~/learning-investment-strategies
nohup ./bin/qdrant --storage-snapshots-path ./qdrant_storage/snapshots \
  > /tmp/qdrant-server.log 2>&1 &
echo "PID: $!"
```

实际执行：使用 Hermes background 模式启动，PID 2285375

- [x] **3.2** 等待就绪（健康检查）

```bash
sleep 2
curl -s http://localhost:6333/health
```

预期：`{"title":"healthz","version":"1.18.2"}`

实际：Qdrant 1.18.2 使用 `/readyz` 端点，返回 `all shards are ready`

- [x] **3.3** 创建两个 collection（用 Phase 0.4 记录的维度/距离）

```bash
cd ~/learning-investment-strategies
.venv/bin/python3 -c "..."
```

结果：qing_claims, qing_knowledge 创建成功

- [x] **3.4** 验证 collection 为空

```bash
.venv/bin/python3 -c "..."
```

结果：qing_claims: 0 points, qing_knowledge: 0 points ✓

---

### Phase 4：数据迁移

- [x] **4.1** 执行迁移脚本

```bash
cd ~/learning-investment-strategies
PYTHONPATH=src .venv/bin/python3 scripts/migrate_qdrant_local_to_remote.py
```

结果：
- qing_claims: 699/699 points migrated ✓
- qing_knowledge: 10880/10880 points migrated ✓

注意：迁移脚本修复了本地 SQLite 模式的嵌套 list 向量格式问题（`[[v1,v2,...]]` → `[v1,v2,...]`）。

- [x] **4.2** 验证数据完整性（条数）

结果：qing_claims: local=699, remote=699 ✓；qing_knowledge: local=10880, remote=10880 ✓

- [x] **4.3** 验证数据完整性（随机抽样向量）

结果：两个集合各 10 条 spot-check 全部通过（向量 + payload 匹配）✓

---

### Phase 5：切换配置

- [x] **5.1** 确认 Qdrant 二进制进程存活

```bash
ps aux | grep './bin/qdrant' | grep -v grep
curl -s http://localhost:6333/readyz
```

结果：PID 2285375 运行中，`all shards are ready`

- [x] **5.2** 修改 `config.py`，清空 `QDRANT_LOCAL_PATH`

文件：`src/qing_investment/agent/config.py`

```diff
-    qdrant_local_path: str = "/home/ubuntu/learning-investment-strategies/.qdrant_data"
+    qdrant_local_path: str = ""  # 空字符串启用远程模式（Qdrant 二进制服务端）
```

- [x] **5.3** 验证 QdrantClientWrapper 自动切换到远程模式

结果：
```
qdrant_local_path: ""
qdrant_host: localhost
qdrant_port: 6333
is_local: False
远程搜索 OK: 3 条
```

---

### Phase 6：重启服务并端到端验证

- [ ] **6.1** 停止 MCP Qdrant Server

```bash
ps aux | grep mcp_qdrant_server | grep -v grep | awk '{print $2}' | xargs kill 2>/dev/null
```

- [ ] **6.2** 停止 Qing-Agent（如果在运行）

```bash
ps aux | grep "gunicorn.*qing" | grep -v grep | awk '{print $2}' | xargs kill 2>/dev/null
```

- [ ] **6.3** 启动 MCP Qdrant Server

```bash
cd ~/learning-investment-strategies
nohup ~/.hermes/hermes-agent/venv/bin/python3 scripts/mcp_qdrant_server.py \
  > /tmp/mcp-qdrant.log 2>&1 &
```

- [ ] **6.4** 启动 Qing-Agent

```bash
cd ~/learning-investment-strategies
nohup .venv/bin/gunicorn qing_investment.agent.main:app \
  -w 1 -k uvicorn.workers.UvicornWorker \
  --bind 127.0.0.1:8000 \
  --timeout 120 --keep-alive 5 \
  > /tmp/qing-agent.log 2>&1 &
```

- [ ] **6.5** 验证两个服务都存活且**无锁冲突**

```bash
sleep 3
ps aux | grep -E "(mcp_qdrant|gunicorn.*qing)" | grep -v grep
curl -s http://localhost:8000/health
# 检查 Qdrant 二进制日志无报错
tail -5 /tmp/qdrant-server.log
```

- [ ] **6.6** 端到端验证：通过 Hermes MCP 工具搜索

在 Hermes 会话中调用 `mcp_qdrant_search_claims`（查询 "涨价逻辑"），确认返回非空结果。

- [ ] **6.7** 端到端验证：通过 Qing-Agent 分析

调用 Qing-Agent 的 `/analyze` 接口，确认 knowledge retrieval 正常返回 claims。

---

### Phase 7：清理与 Git 提交

- [ ] **7.1** 提交所有改动

```bash
cd ~/learning-investment-strategies
git add src/qing_investment/agent/tools/qdrant_client.py
git add src/qing_investment/agent/config.py         # 如果改了
git add scripts/migrate_qdrant_local_to_remote.py   # 迁移脚本
git add .env                                         # 如果改了
git commit -m "feat: Qdrant 本地模式 → 二进制服务端

- 修复 QdrantClientWrapper.search() 远程模式 bug (search()→query_points())
- 新增 migrate_qdrant_local_to_remote.py 迁移脚本
- 切换 qdrant_local_path 为空，启用远程模式
- MCP 和 Qing-Agent 并发访问，消除 portalocker 锁冲突"
```

- [ ] **7.2** 标记旧数据目录（保留 7 天作为保险）

```bash
mv .qdrant_data .qdrant_data.old.$(date +%Y%m%d)
# 备份保留在 .qdrant_data.bak.20260610
```

- [ ] **7.3** 推送

```bash
git push
```

---

## 回滚计划

如需回滚到本地模式，执行以下步骤（反向操作）：

```bash
# 1. 停止服务
ps aux | grep -E "(mcp_qdrant|gunicorn.*qing|./bin/qdrant)" | grep -v grep | awk '{print $2}' | xargs kill

# 2. 恢复配置（.env 或 config.py）
# QDRANT_LOCAL_PATH=/home/ubuntu/learning-investment-strategies/.qdrant_data.bak.20260610

# 3. 恢复数据目录
mv .qdrant_data.bak.20260610 .qdrant_data

# 4. 重启服务（MCP Qdrant → Qing-Agent 串行启动，不并发）
```

---

## 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 迁移脚本中断 | 低 | 部分数据未迁 | 脚本幂等（upsert），重跑即可 |
| 向量精度损失 | 极低 | 搜索结果略异 | float64→float32 存储，Qdrant 两边一致 |
| 二进制崩溃 | 低 | 服务不可用 | 本地模式备份可秒切回 |
| 内存不足 | 极低 | 二进制 OOM | 66MB 数据 < 100MB 内存 |
| Qdrant 版本不兼容 | 低 | API 差异 | client 1.18.0 ↔ binary 1.18.2，大版本一致 |

---

## 关键前提确认清单

在执行前逐项确认：

- [ ] 确认 qdrant-client 版本 1.18.0 与 Qdrant 二进制 v1.18.2 大版本兼容
- [ ] 确认 `query_points()` 在远程模式返回结构与本地模式一致（已验证：均返回 `QueryResponse.points → List[ScoredPoint]`，ScoredPoint 含 id/score/payload）
- [ ] 确认 `.qdrant_data` 备份完整可用
- [ ] 确认 6333 端口未被占用
- [ ] 确认磁盘空间充足（至少预留 200MB：66MB 数据 + 二进制 ~30MB + RocksDB 开销）
