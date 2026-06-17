# Hermes Cron Job 输出文件访问指南

> 当用户引用一个 cron job ID（如 "fc7d8a270d84今天的复盘结论"）时，如何找到并读取对应的输出文件。

---

## 输出文件位置

Hermes cron job 的输出保存在：

```
~/.hermes/cron/output/<job_id>/
```

每个 job 目录下包含该任务历史运行的输出文件，命名格式：

```
YYYY-MM-DD_HH-MM-SS.md
```

## 查找步骤

### 1. 确认 job ID 存在

```bash
ls -la ~/.hermes/cron/output/ | grep <job_id>
```

### 2. 列出该 job 的所有历史输出

```bash
ls -la ~/.hermes/cron/output/<job_id>/
```

### 3. 读取最新的输出文件

```bash
cat ~/.hermes/cron/output/<job_id>/$(ls -t ~/.hermes/cron/output/<job_id>/ | head -1)
```

或读取特定日期的输出：

```bash
cat ~/.hermes/cron/output/<job_id>/2026-06-03_15-24-58.md
```

## 输出文件结构

典型的 cron job 输出包含：

1. **Job 元数据**：job ID、运行时间、schedule
2. **Prompt**：cron 任务使用的完整 prompt
3. **Script Output**：前置脚本收集的数据（如股票监控上下文）
4. **Response**：LLM 生成的分析报告

## 常见 job ID 模式

| Job 类型 | 典型 ID 示例 | 输出内容 |
|---------|------------|---------|
| A股监控收盘复盘 | fc7d8a270d84 | 收盘监控复盘报告 |
| B站动态抓取 | 3a1c39a7e543 | 新动态通知 |
| 盘中监控 | 5b6113aa0d21 | 盘中提醒 |

## 注意事项

- 输出文件可能包含 `[SILENT]` 标记，表示该次运行无新内容
- 文件权限通常为 `rw-------`，需确保当前用户有读取权限
- 历史输出文件不会被自动清理，可能积累较多旧文件
