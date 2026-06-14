from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

from langchain_openai import ChatOpenAI

from qing_investment.agent.config import settings

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
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-v4-flash",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4",
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


def get_llm_client(provider: str | None = None) -> ChatOpenAI:
    """根据配置的 provider 返回对应的 LLM 客户端。

    Args:
        provider: 目标 provider，如 'kimi', 'deepseek'。None 则使用 settings.llm_provider。
    """
    target = (provider or settings.llm_provider).lower()
    logger.info("[get_llm_client] target=%s (requested=%s, default=%s)", target, provider, settings.llm_provider)
    if target not in LLM_PROVIDERS:
        raise ValueError(
            f"Unknown LLM provider: {target}. "
            f"Supported: {', '.join(LLM_PROVIDERS.keys())}"
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
