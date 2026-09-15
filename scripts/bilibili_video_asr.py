#!/usr/bin/env python3
"""B站视频动态语音转写（ASR）核心模块。

链路：BV 号 → cid → dash 音频 URL → 下载 m4s → ffmpeg 转 16k 单声道 wav
→ （按需切段）→ 转 mp3 32kbps → OpenRouter input_audio base64 转写 → 合并文本。

设计文档：docs/superpowers/specs/2026-09-15-bilibili-video-asr-design.md

核心原则：ASR 是增强不是必需。`asr_video()` 任何异常都吞掉返回 ""，
绝不因转写失败导致动态丢失。

所有 HTTP 走 `_get_json` / `_post_json` 两个出口，便于测试 monkeypatch。
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
BILIBILI_REFERER = "https://www.bilibili.com/"

CONFIG_PATH = "config/bilibili_asr.yaml"

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "provider": "openrouter",
    "model": "xiaomi/mimo-v2.5",
    "api_key_env": "CUSTOM_OPENROUTER_API_KEY",
    "api_base": "https://openrouter.ai/api/v1",
    "audio": {
        "format": "wav",
        "sample_rate": 16000,
        "channels": 1,
        "encode": "mp3",
        "bitrate": "32k",
        "max_base64_mb": 10,
        "segment_seconds": 240,
    },
    "timeout": {"download": 60, "transcribe": 180},
    "retry": {"max_attempts": 3, "backoff_seconds": [5, 15, 45]},
    "cost_guard": {
        "daily_limit_cny": 5.0,
        "cny_per_second": 0.0000255,
        "log_file": "logs/bilibili_asr.jsonl",
    },
}

TRANSCRIBE_PROMPT = (
    "把这段音频完整转写为简体中文。这是财经投资类口播，包含股票名称、"
    "板块术语、操作纪律和价格数字，请准确转写专有名词与数字。"
    "只输出转写正文，不要输出任何解释。"
)

# 模型偶发返回「拒答」而非转写（实测出现过），按失败处理以便重试
_REFUSAL_PATTERNS = (
    "我无法直接接收或处理音频",
    "我是文本AI",
    "无法处理该音频",
    "无法转写这段音频",
    "语音转文字工具",
)


# ── 配置 ──────────────────────────────────────────────────────────

def repo_root() -> Path:
    configured = os.environ.get("HERMES_REPO_ROOT")
    if configured:
        return Path(configured)
    cwd = Path.cwd()
    if (cwd / "scripts" / "stock_monitor.py").exists():
        return cwd
    return Path(__file__).resolve().parents[1]


def load_config(path: Path | None = None) -> dict:
    """读取 ASR 配置；文件缺失或解析失败时用内置默认值（不硬失败）。"""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deepcopy
    cfg_path = path or (repo_root() / CONFIG_PATH)
    if not cfg_path.exists():
        return cfg
    try:
        import yaml

        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        print(f"WARN: ASR 配置解析失败 {cfg_path}: {exc}，使用默认值", file=sys.stderr)
        return cfg
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(value)
        else:
            cfg[key] = value
    return cfg


def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


# ── HTTP 出口（测试 monkeypatch 点） ───────────────────────────────

def _build_cookie(sessdata: str) -> str:
    return f"SESSDATA={sessdata}" if sessdata else ""


def _get_json(url: str, sessdata: str = "", timeout: int = 15) -> dict:
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": BILIBILI_REFERER,
        "Accept": "application/json, text/plain, */*",
    }
    cookie = _build_cookie(sessdata)
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(url: str, body: dict, api_key: str, timeout: int = 180) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── 重试 ──────────────────────────────────────────────────────────

def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or exc.code >= 500
    return True  # 网络错误 / 超时均可重试


def _retry(fn: Callable[[], Any], cfg: dict, what: str = "") -> Any:
    retry_cfg = cfg.get("retry", {})
    max_attempts = int(retry_cfg.get("max_attempts", 3))
    backoff = list(retry_cfg.get("backoff_seconds", [5, 15, 45]))
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - 统一重试入口
            last_exc = exc
            if attempt >= max_attempts - 1 or not _is_retryable(exc):
                raise
            wait = backoff[min(attempt, len(backoff) - 1)]
            print(f"WARN: {what} 第 {attempt + 1} 次失败（{exc}），{wait}s 后重试", file=sys.stderr)
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]


# ── B站链路 ───────────────────────────────────────────────────────

def extract_bvid(item: dict) -> str:
    """从动态 item 提取 BV 号，缺失返回 ""。"""
    archive = (
        (item.get("modules", {}).get("module_dynamic", {}).get("major") or {})
        .get("archive")
    )
    if isinstance(archive, dict):
        return str(archive.get("bvid", "") or "")
    return ""


def fetch_cid(bvid: str, sessdata: str, cfg: dict | None = None) -> str:
    """BV → cid（x/web-interface/view）。"""
    cfg = cfg or DEFAULT_CONFIG

    def _call() -> str:
        data = _get_json(
            f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
            sessdata,
        )
        if data.get("code") != 0:
            raise RuntimeError(f"view API 返回 code={data.get('code')}: {data.get('message', '')}")
        cid = data.get("data", {}).get("cid")
        if not cid:
            raise RuntimeError("view API 未返回 cid")
        return str(cid)

    return _retry(_call, cfg, what=f"fetch_cid({bvid})")


def fetch_audio_url(bvid: str, cid: str, sessdata: str, cfg: dict | None = None) -> str:
    """取 dash 音频中 bandwidth 最高一条的 baseUrl。"""
    cfg = cfg or DEFAULT_CONFIG

    def _call() -> str:
        data = _get_json(
            "https://api.bilibili.com/x/player/playurl"
            f"?bvid={bvid}&cid={cid}&fnval=16",
            sessdata,
        )
        if data.get("code") != 0:
            raise RuntimeError(f"playurl API 返回 code={data.get('code')}: {data.get('message', '')}")
        audios = (
            data.get("data", {}).get("dash", {}).get("audio") or []
        )
        if not audios:
            raise RuntimeError("playurl 未返回 dash 音频流")
        best = max(audios, key=lambda a: a.get("bandwidth", 0))
        url = best.get("baseUrl") or best.get("base_url")
        if not url:
            raise RuntimeError("音频流缺少 baseUrl")
        return url

    return _retry(_call, cfg, what=f"fetch_audio_url({bvid})")


def download_audio(url: str, sessdata: str, dest: Path, cfg: dict | None = None) -> Path:
    """下载 m4s 音频（带 Referer + Cookie）。"""
    cfg = cfg or DEFAULT_CONFIG
    timeout = int(cfg.get("timeout", {}).get("download", 60))

    def _call() -> Path:
        headers = {"User-Agent": USER_AGENT, "Referer": BILIBILI_REFERER}
        cookie = _build_cookie(sessdata)
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dest.write_bytes(resp.read())
        if dest.stat().st_size == 0:
            raise RuntimeError("下载得到空文件")
        return dest

    return _retry(_call, cfg, what="download_audio")


# ── ffmpeg ────────────────────────────────────────────────────────

def _run_ffmpeg(args: list[str]) -> None:
    if not check_ffmpeg():
        raise RuntimeError("ffmpeg 未安装，ASR 不可用")
    proc = subprocess.run(
        ["ffmpeg", "-y", *args],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {proc.stderr[-300:]}")


def to_wav(src: Path, dest: Path, cfg: dict | None = None) -> Path:
    """转 16k 单声道 wav。"""
    cfg = cfg or DEFAULT_CONFIG
    audio = cfg.get("audio", {})
    _run_ffmpeg([
        "-i", str(src),
        "-ar", str(audio.get("sample_rate", 16000)),
        "-ac", str(audio.get("channels", 1)),
        "-f", "wav",
        str(dest),
    ])
    return dest


def to_mp3(wav: Path, dest: Path, cfg: dict | None = None) -> Path:
    """32kbps mp3 压缩（降 base64 体积）。"""
    cfg = cfg or DEFAULT_CONFIG
    bitrate = cfg.get("audio", {}).get("bitrate", "32k")
    _run_ffmpeg([
        "-i", str(wav),
        "-codec:a", "libmp3lame",
        "-b:a", str(bitrate),
        str(dest),
    ])
    return dest


def _probe_duration(path: Path) -> float:
    """ffprobe 取时长（秒）；失败返回 0。"""
    if not shutil.which("ffprobe"):
        return 0.0
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(proc.stdout.strip())
    except (ValueError, subprocess.SubprocessError):
        return 0.0


def _segment(wav: Path, seconds: int, out_dir: Path) -> list[Path]:
    """ffmpeg segment 切段，返回分段文件列表（按序）。"""
    pattern = str(out_dir / "seg_%03d.wav")
    _run_ffmpeg([
        "-i", str(wav),
        "-f", "segment",
        "-segment_time", str(seconds),
        "-c", "copy",
        pattern,
    ])
    parts = sorted(out_dir.glob("seg_*.wav"))
    if not parts:
        raise RuntimeError("ffmpeg 切段未产出分段文件")
    return parts


# ── 成本日志与预算 ─────────────────────────────────────────────────

def _log_path(cfg: dict) -> Path:
    log_file = cfg.get("cost_guard", {}).get("log_file", "logs/bilibili_asr.jsonl")
    path = Path(log_file)
    return path if path.is_absolute() else repo_root() / path


def _log_cost(entry: dict, cfg: dict) -> None:
    path = _log_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _daily_cost_cny(cfg: dict) -> float:
    path = _log_path(cfg)
    if not path.exists():
        return 0.0
    today = datetime.now().strftime("%Y-%m-%d")
    total = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(entry.get("ts", "")).startswith(today):
            total += float(entry.get("cost_cny", 0) or 0)
    return total


def _check_daily_budget(cfg: dict) -> bool:
    limit = float(cfg.get("cost_guard", {}).get("daily_limit_cny", 5.0))
    return _daily_cost_cny(cfg) < limit


# ── OpenRouter ASR ─────────────────────────────────────────────────

def _read_key_from_env_file(path: Path, key: str) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def resolve_api_key(cfg: dict) -> str:
    """按 api_key_env 解析 key：进程环境 → ~/.hermes/.env → 仓库 .env，
    最后兜底 OPENROUTER_API_KEY。"""
    key_name = cfg.get("api_key_env", "CUSTOM_OPENROUTER_API_KEY")
    candidates = [key_name]
    if key_name != "OPENROUTER_API_KEY":
        candidates.append("OPENROUTER_API_KEY")
    for name in candidates:
        value = os.environ.get(name, "")
        if value:
            return value
    for env_file in [Path.home() / ".hermes" / ".env", repo_root() / ".env"]:
        for name in candidates:
            value = _read_key_from_env_file(env_file, name)
            if value:
                return value
    return ""


def _transcribe_single(mp3_path: Path, cfg: dict, api_key: str) -> str:
    audio_b64 = base64.b64encode(mp3_path.read_bytes()).decode("ascii")
    max_mb = float(cfg.get("audio", {}).get("max_base64_mb", 10))
    if len(audio_b64) > max_mb * 1024 * 1024:
        raise RuntimeError(f"音频 base64 超限（{len(audio_b64) / 1024 / 1024:.1f}MB > {max_mb}MB）")
    body = {
        "model": cfg.get("model", "xiaomi/mimo-v2.5"),
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": TRANSCRIBE_PROMPT},
            {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "mp3"}},
        ]}],
    }
    url = f"{cfg.get('api_base', 'https://openrouter.ai/api/v1').rstrip('/')}/chat/completions"
    timeout = int(cfg.get("timeout", {}).get("transcribe", 180))

    def _call() -> str:
        data = _post_json(url, body, api_key, timeout=timeout)
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if isinstance(content, list):  # 部分模型返回分段结构
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        if not content.strip():
            raise RuntimeError(f"ASR 返回空内容: {json.dumps(data, ensure_ascii=False)[:200]}")
        text = content.strip()
        if any(p in text for p in _REFUSAL_PATTERNS) and len(text) < 500:
            raise RuntimeError(f"ASR 返回拒答而非转写: {text[:80]}")
        return text

    return _retry(_call, cfg, what=f"transcribe({mp3_path.name})")


def transcribe(audio_path: Path, cfg: dict | None = None) -> str:
    """wav → （按需切段）→ mp3 → OpenRouter ASR，返回合并转写文本。"""
    cfg = cfg or DEFAULT_CONFIG
    api_key = resolve_api_key(cfg)
    if not api_key:
        raise RuntimeError("未找到 OpenRouter API key（api_key_env 配置无效）")

    audio_cfg = cfg.get("audio", {})
    segment_seconds = int(audio_cfg.get("segment_seconds", 240))
    duration = _probe_duration(audio_path)

    if segment_seconds > 0 and duration > segment_seconds:
        seg_dir = audio_path.parent / "segments"
        seg_dir.mkdir(exist_ok=True)
        parts: list[Path] = _segment(audio_path, segment_seconds, seg_dir)
    else:
        parts = [audio_path]

    texts = []
    for i, part in enumerate(parts):
        mp3_path = part.with_suffix(".mp3")
        to_mp3(part, mp3_path, cfg)
        texts.append(_transcribe_single(mp3_path, cfg, api_key))
        if len(parts) > 1:
            print(f"INFO: ASR 分段 {i + 1}/{len(parts)} 完成", file=sys.stderr)
    return "\n".join(texts)


# ── 主入口 ────────────────────────────────────────────────────────

def asr_video(item: dict, cfg: dict | None = None, sessdata: str = "") -> str:
    """对外主入口：编排全链路，任何异常返回 "" 并记日志（不抛出）。"""
    cfg = cfg or load_config()
    if not cfg.get("enabled", True):
        return ""

    bvid = extract_bvid(item)
    if not bvid:
        print("INFO: ASR 跳过：无 BV 号", file=sys.stderr)
        return ""

    if not check_ffmpeg():
        print("WARN: ffmpeg 未安装，ASR 整体禁用", file=sys.stderr)
        return ""

    if not _check_daily_budget(cfg):
        print(f"WARN: ASR 超出日成本上限，跳过 {bvid}", file=sys.stderr)
        _log_cost({
            "ts": datetime.now().isoformat(), "bvid": bvid,
            "model": cfg.get("model"), "status": "budget_exceeded", "cost_cny": 0,
        }, cfg)
        return ""

    duration_s = 0.0
    try:
        with tempfile.TemporaryDirectory(prefix="bili_asr_") as tmp:
            tmp_dir = Path(tmp)
            cid = fetch_cid(bvid, sessdata, cfg)
            audio_url = fetch_audio_url(bvid, cid, sessdata, cfg)
            m4s_path = download_audio(audio_url, sessdata, tmp_dir / "audio.m4s", cfg)
            wav_path = to_wav(m4s_path, tmp_dir / "audio.wav", cfg)
            duration_s = _probe_duration(wav_path)
            text = transcribe(wav_path, cfg)
        _log_cost({
            "ts": datetime.now().isoformat(), "bvid": bvid,
            "model": cfg.get("model"), "duration_s": round(duration_s, 1),
            "cost_cny": round(duration_s * float(cfg.get("cost_guard", {}).get("cny_per_second", 0)), 6),
            "status": "ok",
        }, cfg)
        return text
    except Exception as exc:  # noqa: BLE001 - ASR 失败绝不中断主流程
        print(f"WARN: ASR 失败 {bvid}: {exc}", file=sys.stderr)
        _log_cost({
            "ts": datetime.now().isoformat(), "bvid": bvid,
            "model": cfg.get("model"), "duration_s": round(duration_s, 1),
            "cost_cny": 0, "status": "failed", "error": str(exc)[:200],
        }, cfg)
        return ""
