# qing-hermes-synced — Hermes 层 qing skills 权威副本

本目录是 `~/.hermes/skills/qing/`（Hermes Agent 运行层 skill）的**版本管理副本**，
落库原因：Hermes 层不在任何 git 仓库内，踩坑经验（影子双轨运维、claim 提取排障、
数据源降级链等）只存在单机目录，无备份无历史（2026-08-27 决定落库，方案 A）。

## 同步机制（手动）

**Hermes 层 → repo（存档）**：Hermes 层 skill 更新后，手动同步过来：

```bash
rm -rf skills/qing-hermes-synced && cp -r ~/.hermes/skills/qing skills/qing-hermes-synced
```

同步后必须过一遍敏感信息扫描（凭证只允许 `$(cat ...)` 引用或 `xxx` 占位，
不允许真实值），再提交：

```bash
grep -rniE 'sk-[a-zA-Z0-9]{15,}|SESSDATA=[^$(x]|buvid3=[^$x.]|api[_-]?key.{0,4}[:=].{10,}' skills/qing-hermes-synced/
```

**repo → Hermes 层（恢复）**：新机器/目录损坏时反向恢复：

```bash
mkdir -p ~/.hermes/skills && cp -r skills/qing-hermes-synced/* ~/.hermes/skills/qing/
```

## 注意

- 本目录内容**不被 Hermes 直接加载**（Hermes 只读 `~/.hermes/skills/`），仅作存档。
- 运行时修改发生在 Hermes 层；repo 侧是快照，两侧可能短暂不一致，属预期。
- 2026-08-27 首次落库快照，含 qing-shadow-dual-track / qing-shadow-contract-ops /
  qing-cron-analysis-fallback 等 14 个 skill；已脱敏 buvid3/_uuid 两处设备指纹。
