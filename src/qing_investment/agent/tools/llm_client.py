from __future__ import annotations

import contextvars
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

from langchain_openai import ChatOpenAI

from qing_investment.agent.config import settings

# 本地 Kimi Code CLI 调用（通过子进程 `kimi -p`）
_KIMI_CODE_CLI_PROVIDER = "kimi-code-cli"

# 本地 Kimi Code ACP 调用（通过 `kimi acp` 子进程 JSON-RPC）
_KIMI_CODE_ACP_PROVIDER = "kimi-code-acp"

# Provider 使用轨迹跟踪（按请求隔离，contextvars 保证 async 任务间不串号）
_provider_usage_ctx: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "provider_usage", default=None
)


def reset_provider_usage() -> list[dict]:
    """开始新的请求前重置 tracker，返回当前请求的 tracker 列表。"""
    tracker: list[dict] = []
    _provider_usage_ctx.set(tracker)
    return tracker


def record_provider_usage(provider: str, status: str, note: str = "") -> None:
    """记录一次 provider 调用事件（attempt / success / failed / fallback）。"""
    tracker = _provider_usage_ctx.get()
    if tracker is None:
        # 未显式 reset 时自动初始化，保证单元测试 / 脚本直接调用也能记录
        tracker = reset_provider_usage()
    tracker.append(
        {
            "provider": provider,
            "status": status,
            "note": note,
        }
    )


def get_provider_usage_records() -> list[dict]:
    """返回当前请求的所有 provider 调用记录。"""
    tracker = _provider_usage_ctx.get()
    return list(tracker) if tracker else []


def format_provider_usage_summary(records: list[dict] | None = None) -> str:
    """把 provider 调用记录格式化为人类可读的文案。"""
    records = records if records is not None else get_provider_usage_records()
    if not records:
        return "模型路由：未记录"

    # 按 provider 聚合成简洁描述
    seen: set[str] = set()
    parts: list[str] = []
    for r in records:
        provider = r.get("provider", "unknown")
        status = r.get("status", "")
        note = r.get("note", "")
        key = f"{provider}:{status}"
        if key in seen:
            continue
        seen.add(key)
        if provider == _KIMI_CODE_CLI_PROVIDER:
            label = "本地 Kimi Code CLI"
        else:
            label = f"远端 {provider}"
        if status == "success":
            parts.append(f"{label} ✓")
        elif status == "failed":
            parts.append(f"{label} ✗{f'（{note}）' if note else ''}")
        elif status == "fallback":
            parts.append(f"{label}（fallback）")
        elif status == "attempt":
            parts.append(f"{label} …")

    # 如果存在 fallback 成功，优先展示最终成功的 provider
    success_providers = [r["provider"] for r in records if r.get("status") == "success"]
    if success_providers:
        final = success_providers[-1]
        final_label = "本地 Kimi Code CLI" if final == _KIMI_CODE_CLI_PROVIDER else f"远端 {final}"
        summary = f"模型路由：最终走 {final_label}"
        if len(parts) > 1:
            summary += " | 尝试: " + " → ".join(parts)
        return summary

    return "模型路由：" + " → ".join(parts)


# 预置常见大模型厂商配置（写死，用户只需配置 provider + api_key）
LLM_PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "api_key_env": "OPENAI_API_KEY",
    },
    "azure": {
        "base_url": None,
        "default_model": "gpt-4o",
        "api_key_env": "AZURE_OPENAI_API_KEY",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-128k",
        "api_key_env": "KIMI_API_KEY",
    },
    "kimi-coding": {
        "base_url": "https://api.kimi.com",
        "default_model": "kimi-k2-turbo-preview",
        "api_key_env": "KIMI_API_KEY",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-v4-flash",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4.7-flash",
        "api_key_env": "ZHIPU_API_KEY",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-max",
        "api_key_env": "QWEN_API_KEY",
    },
    "baichuan": {
        "base_url": "https://api.baichuan-ai.com/v1",
        "default_model": "Baichuan4",
        "api_key_env": "BAICHUAN_API_KEY",
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "api_key_env": "SILICONFLOW_API_KEY",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "api_key_env": "GROQ_API_KEY",
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "api_key_env": "TOGETHER_API_KEY",
    },
}


# Embedding 客户端（本地 BGE，单例，lazy import）
_embedding_model = None


def get_llm_client(provider: str | None = None) -> Any:
    """根据配置的 provider 返回对应的 LLM 客户端。

    Args:
        provider: 目标 provider，如 'kimi', 'deepseek', 'kimi-code-cli'。
            None 则使用 settings.llm_provider。

    Returns:
        ChatOpenAI — 标准 OpenAI 协议 provider
        KimiCodingClient — Kimi Coding Plan（Anthropic 协议）
        KimiCodeCLIClient — 本地 Kimi Code CLI（子进程）
        KimiCodeAcpClient — 本地 Kimi Code ACP（JSON-RPC 子进程）
    """
    target = (provider or settings.llm_provider).lower()
    logger.info("[get_llm_client] target=%s (requested=%s, default=%s)", target, provider, settings.llm_provider)

    # 本地 Kimi Code CLI：不走 LLM_PROVIDERS，不需要 api_key/base_url
    if target == _KIMI_CODE_CLI_PROVIDER:
        from .kimi_code_cli_client import KimiCodeCLIClient

        logger.info("[get_llm_client] using local Kimi Code CLI")
        return KimiCodeCLIClient(
            cli_path=None,  # 使用默认 /home/ubuntu/.kimi-code/bin/kimi
            cwd=None,       # 使用默认 /home/ubuntu/learning-investment-strategies
            timeout=int(os.environ.get("KIMI_CODE_CLI_TIMEOUT", "300")),
        )

    if target == _KIMI_CODE_ACP_PROVIDER:
        from .kimi_code_acp_client import KimiCodeAcpClient

        logger.info("[get_llm_client] using local Kimi Code ACP")
        return KimiCodeAcpClient()

    if target not in LLM_PROVIDERS:
        raise ValueError(
            f"Unknown LLM provider: {target}. "
            f"Supported: {', '.join(LLM_PROVIDERS.keys())}, {_KIMI_CODE_CLI_PROVIDER}, {_KIMI_CODE_ACP_PROVIDER}"
        )

    config = LLM_PROVIDERS[target]
    api_key = (
        getattr(settings, config["api_key_env"].lower(), None)
        or os.environ.get(config["api_key_env"])
    )
    base_url = settings.llm_base_url or config["base_url"]
    model = settings.llm_model or config["default_model"]
    logger.info("[get_llm_client] target=%s model=%s base_url=%s has_key=%s", target, model, base_url, bool(api_key))

    if not api_key:
        raise ValueError(
            f"Provider '{target}' requires {config['api_key_env']}. "
            f"Set it in .env or environment variable."
        )

    # Kimi Coding Plan 走 Anthropic 协议 → 返回专用客户端
    if target == "kimi-coding":
        from .kimi_coding_client import KimiCodingClient

        return KimiCodingClient(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )

    # 标准 OpenAI 协议 provider
    if not base_url:
        raise ValueError(
            f"Provider '{target}' requires llm_base_url to be set."
        )

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.3,
        max_tokens=4096,
        request_timeout=120,  # 防止 API hang 死
    )


def get_embedding_model():
    """返回本地 Embedding 模型（单例）。优先使用 ONNX，回退到 hash fallback。"""
    global _embedding_model
    if _embedding_model is None:
        try:
            from .embedding_utils import OnnxEmbeddingModel

            _embedding_model = OnnxEmbeddingModel()
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(
                "ONNX embedding model failed to load (%s), falling back to hash embedding", e
            )
            from .embedding_utils import FallbackEmbeddingModel

            _embedding_model = FallbackEmbeddingModel()
    return _embedding_model
