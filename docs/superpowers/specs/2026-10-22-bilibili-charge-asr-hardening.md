# B 站充电专属视频 ASR 链路加固（2026-10-22）

## 背景

账号（狄拉克Dirac）对 UP 主（如鳄鱼派）已有生效充电订阅，实测 `x/player/playurl`
可返回完整 dash 音频（4470s 全片）。但线上 ASR 对充电专属视频仍间歇失败，日志三种形态：

1. `playurl 未返回 dash 音频流` / `ok_preview_only`（仅 durl 试看 1299s/4470s）
   —— 风控对会话降级：请求外观不像真实浏览器（无设备 cookie、请求头稀疏，
   本机 IP 因 5 分钟轮询被盯上）时，对充电视频按未授权处理，静默返回试看流。
2. `HTTP 412` —— 风控硬阻断。
3. 模型返回 null —— 与充电无关，已有换模型重跑先例，不在本次范围。

设计验证（2026-10-22 实测）：旧端点 + 稀疏请求头 + URL 编码 SESSDATA 四种组合
均能拿到全片，说明端点与编码不是根因；**失败是间歇性风控降级**，加固目标是
让请求行为与真实浏览器播放器一致，并在降级发生时显式识别、不再静默转录试看内容。

## 改动设计（scripts/bilibili_video_asr.py）

### Chunk 1：设备 cookie + 完整请求头

- 新增 `_ensure_device_cookies()`：生成并持久化 `buvid3`（uuid+`infoc`）与
  `b_nut`（首次生成时间戳）到 `~/.hermes/bilibili_device.json`（环境变量
  `BILIBILI_DEVICE_STATE` 可覆盖，供测试）。跨运行复用，模拟真实浏览器设备指纹；
  进程内缓存避免每次 I/O。
- `_build_cookie(sessdata)`：SESSDATA 经 `urllib.parse.unquote` 解码
  （当前文件存的是 `%2C` 编码值），cookie 串带上 `buvid3`/`b_nut`。
- `_get_json` 与 `download_audio` 共用新增 `_browser_headers()`：
  在原有 UA/Referer 基础上补 `Accept`/`Accept-Language`/`Origin`。

### Chunk 2：试看识别（核心）

- 新增 `ChargePreviewError(RuntimeError)`。
- 新增 `fetch_video_meta(bvid, sessdata, cfg)`：一次 view API 返回
  `{"cid", "duration_ms"}`；`fetch_cid` 改为委托它（对外签名不变，旧测试兼容）。
- `fetch_audio_url(..., expected_duration_ms=None)`：playurl 返回后校验
  `timelength`，若小于预期的 95% 判定为试看流，抛 `ChargePreviewError`。
- `_is_retryable` 对 `ChargePreviewError` 返回 False（重试无意义，立即失败）。
- `asr_video` 捕获 `ChargePreviewError`：日志落 `status="preview_only"`，
  返回 ""（沿用"ASR 失败绝不中断主流程"原则）。残缺试看内容不再进 raw。

### Chunk 3：412 保持 fail-fast

`_is_retryable` 现状对 412 已不重试（5/15/45s 快速重试会加剧风控评分），
本次不改，仅在设计中确认为预期行为；由 cron 下一 tick 自然重试。

## 不做（YAGNI）

- 不换 WBI 签名端点（实测旧端点可用，鉴权正常时返回全片）。
- 不改 cron 轮询频率（超出本次最小改动范围，作为后续建议）。
- 不处理模型 null（已有手动重跑路径）。

## 测试（tests/test_bilibili_video_asr.py，全部 fake HTTP）

新增：
- `test_build_cookie_decodes_urlencoded` / `test_build_cookie_plain`
- `test_device_cookies_persisted`（env 覆盖到 tmp_path）
- `test_get_json_browser_headers`（捕获请求头断言）
- `test_fetch_audio_url_preview_mismatch_nonretryable`
- `test_fetch_audio_url_timelength_close_enough_passes`
- `test_fetch_video_meta`（cid + duration_ms）
- `test_asr_video_preview_only_logs_and_returns_empty`

调整：`fetch_cid` 委托后，`asr_video` 内部改调 `fetch_video_meta`，
3 个既有测试（full_chain_exception / budget_exceeded / happy_path）的
monkeypatch 目标从 `fetch_cid` 改为 `fetch_video_meta`。

## 验证

`uv run pytest tests/test_bilibili_video_asr.py tests/test_fetch_bilibili_asr.py -q`
全部通过。
