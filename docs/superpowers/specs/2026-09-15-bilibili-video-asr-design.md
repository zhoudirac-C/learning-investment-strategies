# B站视频动态语音转写接入 spec

日期：2026-09-15
状态：已实施（2026-09-15，端到端验证通过：BV1bEbD6PE8F 转写术语全对，单条 ¥0.0085）
前置调研：2026-09-15 实测完成（见文末「调研实测记录」）

## 背景

拉取 UP 动态时，视频类动态（`DYNAMIC_TYPE_AV`）当前在 raw 里只落 `## 原文` +
`## 视频封面`，**没有语音内容**。而实测表明视频语音往往承载比图文更完整的观点：

> 示例（卢本圆复盘 2026-08-16《周一计划，牛来！》，BV1bEbD6PE8F，05:33）：
> 「对机器人、对商业航天，我一直的看法就是，**有冲高就要减仓**，上一周的一个交割单减仓，
> 后面又接回来做T了」「下一个踢点我大概还是放在 **13.5 左右**这个区间」
> 「实盘号是没有补过仓，**9.94 的本**」

这类「操作纪律 + 具体价位」是图片 OCR 拿不到的一手信息，直接决定 claim 提取质量。

**现状**：卢本圆复盘 18 条视频动态已加入排除清单（`config/bilibili_exclude.yaml`），
原因即「视频内容无法提取」。本 spec 意在解除这个限制。

## 目标

拉取 UP 动态时，若动态类型为视频：
1. 从 raw 的 `major.archive` 提取 BV 号
2. 自动获取音频 → 语音转写
3. 转写文本写入 raw 的 `## 视频转写` 段
4. claim 提取管线可直接读取该段

**非目标（YAGNI）**：
- 不做视频画面 OCR（图片 OCR 已有独立流程）
- 不做说话人分离 / 时间戳对齐
- 不做视频下载留存（音频转写后即删临时文件）
- 不改动现有图片 OCR 流程

## 调研实测记录（2026-09-15）

### 一、视频拉取链路（已全通）

| 步骤 | API | 实测结果 |
|---|---|---|
| BV 号 | raw JSON `major.archive.bvid` | **18/18 全部存在** |
| cid | `x/player/pagelist` 或 `x/web-interface/view?bvid=` | code=0，cid=40962101101 |
| 音频流 | `x/player/playurl?bvid&cid&fnval=16` | code=0，3 条 dash 音频流，mp4a.40.2 @126kbps |
| 下载 | dash audio `baseUrl` | ✅ 5.1MB / 333 秒完整 |
| 转码 | ffmpeg | ✅ 16k 单声道 wav |

**注意**：BV 号在 raw JSON 中存在，但**当前 markdown 渲染未提取**（
`extract_video_info` 已解析 `archive.bvid`，但只在无正文时才写入 `- BV号：` 行，
有正文的视频动态会漏掉）。本 spec 需一并修正。

### 二、ASR 方案对比（同一段 333 秒真实音频实测）

| 方案 | 耗时 | 中文质量 | 成本（18条≈85分钟） | 结论 |
|---|---|---|---|---|
| 本地 whisper-tiny | 15.5s | ❌ 繁体乱码（"經流化工""A谷朝情緒"） | ¥0 | 不可用 |
| 本地 whisper-base | ~30s | ⚠️ 同音错字多（"踢点"≠"T点"） | ¥0 | 勉强 |
| 本地 whisper-small | 139s | ⚠️ 最准但仍有错（"童花顺"≠"同花顺"） | ¥0 | 可用但慢 |
| **OpenRouter xiaomi/mimo-v2.5** | 23.7s | ✅ **最佳**（"同花顺""劣币驱逐良币""金牛化工"全对） | **¥0.13** | **选定** |
| OpenRouter mistralai/voxtral-small | 3.4s | ✅ 很好 | ¥0.09 | 备选 |
| 小米国内直连 mimo-v2.5-asr | — | 未实测 | ¥0.71 | 需实名+新key |
| 智谱 GLM-ASR | — | 未实测 | ¥5.10 | 账户余额不足 |

**选型理由**：mimo-v2.5 中文金融术语准确率实测最高；OpenRouter key 已在 `.env`
（`CUSTOM_OPENROUTER_API_KEY`），零配置成本；单价 $0.14/M token，85 分钟音频约 ¥0.13。

**已排除的免费方案**（实测）：
- `thinkingmachines/inkling:free`、`inkling-small:free` → 403 仅限 agentic harness
- `nvidia/nemotron-3-nano-omni:free` → 收不到音频
- `openai/gpt-audio`、`google/gemini-2.5-flash` → 403 区域封锁

**已确认不支持**：`z-ai/glm-5.3-flash` 输入模态为 `['text','image','video']`，
**无 audio** —— GLM 系列在 OpenRouter 全线不支持音频输入
（`glm-asr` 仅存在于智谱官方 API，未上架 OpenRouter）。

### 三、OpenRouter 音频调用格式（实测通过）

```python
body = {
  "model": "xiaomi/mimo-v2.5",
  "messages": [{"role": "user", "content": [
      {"type": "text", "text": "把这段音频完整转写为简体中文..."},
      {"type": "input_audio", "input_audio": {"data": <base64>, "format": "mp3"}},
  ]}],
}
```

注意：`{"type": "audio_url", ...}` 与 `{"type": "image_url", ...}` 两种结构均失败，
**只有 `input_audio` + base64 有效**。

## 设计

### 新模块 `scripts/bilibili_video_asr.py`

职责单一化，每个函数可独立测试：

| 函数 | 职责 | 输入 → 输出 |
|---|---|---|
| `extract_bvid(item)` | 从动态 item 提取 BV 号 | `dict` → `str`（无则 `""`） |
| `fetch_cid(bvid, sessdata)` | BV → cid | `str` → `str` |
| `fetch_audio_url(bvid, cid, sessdata)` | 取最高码率 dash 音频 URL | → `str` |
| `download_audio(url, sessdata, dest)` | 下载 m4s | → `Path` |
| `to_wav(src, dest)` | ffmpeg 转 16k 单声道 | → `Path` |
| `transcribe(wav, cfg)` | 调 OpenRouter ASR（含切段+重试） | → `str` |
| `asr_video(item, cfg, sessdata)` | **对外主入口**，编排上述 | → `str`（失败返回 `""`） |

依赖收敛：所有 HTTP 走单个 `_get_json` / `_post_json`（便于测试 monkeypatch）。

### 改动 `scripts/fetch_bilibili_up_v2.py`

1. `save_dynamic_to_file()` 新增参数 `asr_text: str = ""`，
   在 `## 原文` 之后插入：

   ```markdown
   ## 视频转写

   > 模型：xiaomi/mimo-v2.5 | 时长：05:33 | 转写时间：2026-09-15T11:30

   <转写正文>
   ```

2. 修正 `extract_video_info` 的 BV 号写入逻辑：视频类型**总是**写 `- BV号：`
   （当前只在无正文时才写）

3. `run()` 新增 `enable_asr: bool = True` 参数；视频类型时调用 `asr_video()`

### 配置文件 `config/bilibili_asr.yaml`

```yaml
enabled: true
provider: openrouter
model: xiaomi/mimo-v2.5
api_key_env: CUSTOM_OPENROUTER_API_KEY
api_base: https://openrouter.ai/api/v1

audio:
  format: wav
  sample_rate: 16000
  channels: 1
  encode: mp3          # 上传前转 mp3 降体积
  bitrate: 32k
  max_base64_mb: 10    # 超限切段
  segment_seconds: 240 # 保守分块（每条 5 分钟视频约 2 段）

timeout:
  download: 60
  transcribe: 180

retry:
  max_attempts: 3
  backoff_seconds: [5, 15, 45]

cost_guard:
  daily_limit_cny: 5.0
  log_file: logs/bilibili_asr.jsonl
```

## 错误处理

**核心原则：ASR 是增强不是必需，任何 ASR 失败都不能导致动态丢失。**

| 场景 | 行为 |
|---|---|
| BV 号缺失 | 跳过，raw 记 `[ASR跳过: 无BV号]` |
| cid / playurl 失败 | 重试 3 次（指数退避）→ 记 `[ASR失败: <原因>]` |
| 音频下载失败 | 同上 |
| ffmpeg 缺失 | 启动时预检，缺失则 ASR 整体禁用并告警 |
| ASR API 429 | 指数退避重试（实测 OpenRouter 有速率限制） |
| Cookie 失效 | 报错但**不中断**后续动态处理 |
| 超出日成本上限 | 停止 ASR，记警告，raw 正常落盘 |

**raw 落盘优先级最高** —— ASR 在其内部的 try/except 中，异常只降级为文本标注。

## 成本与性能

| 项 | 预计 |
|---|---|
| 单条 5 分钟视频 | ≈ ¥0.007 |
| 18 条全量 | ≈ ¥0.13 |
| 单条处理耗时 | 下载 3s + 转码 1s + ASR 25s ≈ **30 秒** |

## 验收标准

1. 跑 1 条真实视频端到端，转写文本人工核对，**金融术语准确**（同花顺/T点/板块名）
2. raw 中 `## 视频转写` 段格式正确，含模型/时长/时间元信息
3. ASR 失败时 raw 正常落盘，仅记 `[ASR失败: ...]`
4. 成本日志 `logs/bilibili_asr.jsonl` 正确记录每条用量
5. 现有图片 OCR / 转发动态流程**零回归**

## 待确认项

1. **回填**：现有 18 条视频 raw 是否补跑（`--asr-backfill`）
2. **触发时机**：拉取时同步 vs 拉完统一跑
   （建议统一跑 —— cron 拉取有时限，且统一跑便于成本控制）
3. **排除清单处理**：18 条视频已入 `bilibili_exclude.yaml`，
   ASR 落地后是否移出该清单

## 未决风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| OpenRouter 音频长度上限未实测 | 长视频可能失败 | 已设计切段（240s） |
| OpenRouter 余额耗尽 | ASR 静默失效 | 失败降级为标注，不影响 raw；加成本日志 |
| 音频 base64 体积上限 | 长音频超限 | 转 mp3 32kbps（5分钟≈1.2MB） |
| IP 区域限制变化 | 模型不可用 | 备选 voxtral-small；失败降级 |
