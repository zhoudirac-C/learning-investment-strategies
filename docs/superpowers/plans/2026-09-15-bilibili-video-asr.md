# B站视频动态语音转写接入 实施计划

对应 spec：`docs/superpowers/specs/2026-09-15-bilibili-video-asr-design.md`
创建：2026-09-15
状态：**未实施**（本文档仅为计划，不含代码改动）

## 前置条件

- [ ] spec 经用户确认
- [ ] 确认「待确认项」三条（回填 / 触发时机 / 排除清单处理）
- [ ] 确认 OpenRouter 账户余额充足（≥ $5）

## 任务

### T1 — ASR 核心模块 `scripts/bilibili_video_asr.py`

- [ ] `_get_json(url, sessdata)` / `_post_json(url, body, api_key)`：
      统一 HTTP 出口，便于测试 monkeypatch
- [ ] `extract_bvid(item) -> str`：从 `modules.module_dynamic.major.archive.bvid` 提取，
      缺失返回 `""`
- [ ] `fetch_cid(bvid, sessdata) -> str`：`x/web-interface/view?bvid=`
- [ ] `fetch_audio_url(bvid, cid, sessdata) -> str`：
      `x/player/playurl?fnval=16`，取 dash.audio 中 bandwidth 最高一条
- [ ] `download_audio(url, sessdata, dest) -> Path`：带 Referer + Cookie
- [ ] `to_wav(src, dest, cfg) -> Path`：ffmpeg 转 16k 单声道；缺 ffmpeg 抛明确异常
- [ ] `to_mp3(wav, dest, cfg) -> Path`：32kbps 压缩（降 base64 体积）
- [ ] `_segment(wav, seconds) -> list[Path]`：ffmpeg segment 切段
- [ ] `transcribe(audio_path, cfg) -> str`：base64 → OpenRouter
      `input_audio` 结构；含重试（指数退避）+ 切段合并
- [ ] `asr_video(item, cfg, sessdata) -> str`：**主入口**，编排全链路，
      任何异常返回 `""` 并记日志（不抛出）
- [ ] `_log_cost(entry, cfg)`：追加 `logs/bilibili_asr.jsonl`
- [ ] `_check_daily_budget(cfg) -> bool`：读日志汇总当日成本，超限返回 False
- [ ] 测试 `tests/test_bilibili_video_asr.py`：
      - BV 提取（有/无 archive）
      - cid / playurl 解析（fake HTTP）
      - 下载失败重试
      - ASR 响应解析（正常 / 429 / 超时）
      - 切段合并
      - 成本日志写入 + 预算拦截
      - **关键**：全链路异常时返回 `""` 而不抛出

### T2 — 主流程接入 `scripts/fetch_bilibili_up_v2.py`

- [ ] `save_dynamic_to_file()` 加 `asr_text: str = ""` 参数
- [ ] 在 `## 原文` 段后插入 `## 视频转写` 段（含模型/时长/时间元信息）
- [ ] 修正 `extract_video_info` 的 BV 号写入：视频类型**总是**输出 `- BV号：` 行
      （当前仅无正文时输出，导致有正文的视频动态漏 BV 号）
- [ ] `run()` 加 `enable_asr: bool = True`；`dyn_type == "视频"` 时：
  ```python
  asr_text = ""
  if enable_asr and video_info.get("bvid"):
      try:
          asr_text = asr_video(item, asr_cfg, sessdata)
      except Exception as exc:
          print(f"WARN: ASR 失败 {dynamic_id}: {exc}", file=sys.stderr)
  ```
  **注意**：ASR 调用位置在 `save_dynamic_to_file` 之前，但异常必须吞掉
- [ ] `main()` 加 CLI 参数：`--no-asr`、`--asr-backfill`、`--asr-model`
- [ ] 测试增补：视频动态走 ASR / ASR 失败仍落盘 / `--no-asr` 跳过

### T3 — 配置文件 `config/bilibili_asr.yaml`

- [ ] 按 spec 定义写完整配置（provider / audio / timeout / retry / cost_guard）
- [ ] `bilibili_notify.py` 启动时读取该配置；文件缺失则用内置默认值（不硬失败）

### T4 — 验证与收尾

- [ ] **端到端单条验证**：取 BV1bEbD6PE8F（05:33）跑完整链路，
      人工核对转写质量（重点：同花顺 / T点 / 板块名 / 价位）
- [ ] `git log` 预检确认无并发改动
- [ ] 全量 pytest（注意：**分文件跑**，全量会挂真网络）
- [ ] 成本日志核对：单条成本与预估（¥0.007）同量级
- [ ] 回归确认：图片 OCR / 转发动态 / 充电专属 三条路径不受影响
- [ ] 更新 skill `qing-bilibili-manual-fetch`（记录 ASR 链路 + 踩坑）
- [ ] commit + push

## 执行顺序

```
T3（配置，无依赖）
  ↓
T1（核心模块）+ 测试
  ↓
T2（主流程接入）+ 测试
  ↓
T4（端到端验证 + 回归）
```

T1 与 T3 可并行；T2 依赖 T1 的接口签名。

## 待确认项（实施前必须拍板）

1. **回填**：现有 18 条视频 raw 是否补跑？
   - 补跑 → T4 增加 `--asr-backfill` 全量任务（约 18×30s = 9 分钟，¥0.13）
   - 不补 → 仅新动态走 ASR
2. **触发时机**：拉取时同步 vs 拉完统一跑？
   - 同步：实现简单，但每条 +30s，cron 拉取任务可能超时
   - 统一跑：需额外脚本/参数，但可控性好（**建议**）
3. **排除清单**：`config/bilibili_exclude.yaml` 中 18 条视频是否移出？
   - ASR 生效后视频内容可提取 → 理应移出
   - 但需先确认转写质量达标

## 风险与回滚

| 风险 | 回滚方式 |
|---|---|
| ASR 拖慢 cron 拉取 | `--no-asr` 或 `enabled: false` 一键关闭 |
| 成本超预期 | `cost_guard.daily_limit_cny` 自动拦截 |
| OpenRouter 不可用 | 降级为只记 BV 号，raw 不受影响 |
| 引入回归 | 改动集中在 `save_dynamic_to_file` 尾部，可单独 revert |

**回滚成本低**：ASR 是纯增量，关闭开关即回到当前行为。
