# Code Review: 充电专属视频 ASR 链路加固（2026-10-22）

范围：`scripts/bilibili_video_asr.py`、`tests/test_bilibili_video_asr.py`
设计：`docs/superpowers/specs/2026-10-22-bilibili-charge-asr-hardening.md`

## 结论

无 Critical/Major 问题。42 个单测（本文件 32 + test_fetch_bilibili_asr 10）
+ test_bilibili_notify_gator_hook 9 全部通过；真实 API 冒烟验证
`fetch_video_meta + fetch_audio_url`（含试看校验）对鳄鱼派充电视频
BV161nN6zERa 返回完整 dash 音频，未误触发 preview 判定。

## Minor

1. `b_nut` 按首次生成时间持久化、不刷新——与真实浏览器一致（b_nut 为
   一次性首次访问时间戳），无需改。
2. `_ensure_device_cookies` 在进程内按路径缓存，测试间用
   `BILIBILI_DEVICE_STATE` 隔离，无状态泄漏。
3. 412 维持 fail-fast（`_is_retryable` 对非 429/5xx 不重试），由 cron 下一
   tick 自然重试，避免快速重试加剧风控评分——预期行为，已在设计中记录。

## 遗留（不在本次范围）

- 412 高发时段的有效转录需等待风控冷却；cron 轮询频率优化为后续建议。
- WBI 签名端点切换：实测旧端点对已授权账号可用，暂不引入复杂度。
