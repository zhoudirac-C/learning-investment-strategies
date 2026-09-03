from __future__ import annotations

import contextvars
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

from langchain_openai import ChatOpenAI

from qing_investment.agent.config import settings

# [DEPRECATED] 本地 Kimi Code CLI 调用（通过子进程 `kimi -p`）已废弃，保留代码仅作历史参考。
# _KIMI_CODE_CLI_PROVIDER = "kimi-code-cli"

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
        if provider == "kimi-code-cli":
            label = "本地 Kimi Code CLI（已废弃）"
        elif provider == _KIMI_CODE_ACP_PROVIDER:
            label = "本地 Kimi Code ACP"
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
        if final == "kimi-code-cli":
            final_label = "本地 Kimi Code CLI（已废弃）"
        elif final == _KIMI_CODE_ACP_PROVIDER:
            final_label = "本地 Kimi Code ACP"
        else:
            final_label = f"远端 {final}"
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
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "stealth/ox-alpha",
        "api_key_env": "OPENROUTER_API_KEY",
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-5.3-flash",
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
    "sensenova": {
        "base_url": "https://token.sensenova.cn/v1",
        "default_model": "glm-5.2",
        "api_key_env": "SENSENOVA_API_KEY",
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "api_key_env": "TOGETHER_API_KEY",
    },
    # 2026-09-03：discover 改用 Hermes 全局模型（跟随 ~/.hermes/config.yaml 的
    # model.default，与 cron 调度器、chain_tracker 走同一个 resolve_runtime_provider）。
    # base_url/api_key/default_model 留空——运行时由 _resolve_hermes_global() 注入；
    # 解析失败（非 Hermes 环境/Hermes 配置缺失）→ 降级到 .env 主通道。
    "hermes_global": {
        "base_url": None,
        "default_model": None,
        "api_key_env": None,
        "_dynamic": True,
    },
}


# Hermes 全局解析缓存（进程内只解析一次，配置漂移由下次 tick 感知——与 chain_tracker 同语义）
_HERMES_GLOBAL_CACHE: dict | None = None
_HERMES_GLOBAL_TRIED: bool = False


def _resolve_hermes_global() -> dict | None:
    """解析 Hermes 全局模型配置，返回 {api_key, base_url, model, source}。

    实现移植自 src/investment_engine/chain_tracker/analysis._hermes_global()，
    与 cron 调度器、chain_tracker 走同一个 resolve_runtime_provider()。
    非 Hermes 环境或解析失败 → 返回 None（调用方降级到 .env 主通道）。

    Returns:
        {"api_key": str, "base_url": str, "model": str, "source": str} 或 None
    """
    global _HERMES_GLOBAL_CACHE, _HERMES_GLOBAL_TRIED
    if _HERMES_GLOBAL_TRIED:
        return _HERMES_GLOBAL_CACHE
    _HERMES_GLOBAL_TRIED = True

    import sys
    from pathlib import Path

    agent_pkg = Path.home() / ".hermes" / "hermes-agent"
    if not agent_pkg.is_dir():
        logger.info("[hermes_global] agent package not found at %s — skipping", agent_pkg)
        return None
    # 末尾 append 而非 insert(0)：避免与任何已加载的 hermes_cli 同名包冲突
    if str(agent_pkg) not in sys.path:
        sys.path.append(str(agent_pkg))
    try:
        from hermes_cli.config import load_config
        from hermes_cli.runtime_provider import resolve_runtime_provider

        runtime = resolve_runtime_provider()
        model = (load_config().get("model") or {}).get("default")
    except Exception as e:  # noqa: BLE001 - Hermes 不可用不算错误
        logger.info("[hermes_global] resolve failed (%s) — will fallback to .env", e)
        return None
    if not runtime.get("api_key") or not runtime.get("base_url") or not model:
        logger.info("[hermes_global] incomplete config (api_key=%s, base_url=%s, model=%s) — fallback",
                    bool(runtime.get("api_key")), bool(runtime.get("base_url")), bool(model))
        return None
    _HERMES_GLOBAL_CACHE = {
        "api_key": runtime["api_key"],
        "base_url": runtime["base_url"],
        "model": str(model),
        "source": runtime.get("source"),
    }
    logger.info("[hermes_global] resolved model=%s source=%s base_url=%s",
                _HERMES_GLOBAL_CACHE["model"], _HERMES_GLOBAL_CACHE["source"], _HERMES_GLOBAL_CACHE["base_url"])
    return _HERMES_GLOBAL_CACHE


# Embedding 客户端（本地 BGE，单例，lazy import）
_embedding_model = None



# Fallback 链：主 provider 失败时自动切换（2026-08-27 新增）
# 2026-09-01：支持 "provider:model" 跨 provider 条目（sensenova 平台配额耗尽，
# 主通道切 zhipu 直连 glm-5.3-flash，sensenova 模型降为末位兜底）
SENSENOVA_FALLBACK_MODELS = [
    "sensenova:glm-5.2",
    "sensenova:deepseek-v4-flash",
    "sensenova:sensenova-6.8-flash-lite",
    "sensenova:sensenova-u1-fast",
]


def get_llm_client_with_fallback(
    provider: str | None = None,
    max_tokens: int | None = None,
    fallback_models: list[str] | None = None,
) -> Any:
    """带 fallback 的 LLM 客户端：主模型失败时按链切换。

    触发条件：ChatOpenAI invoke 时若主模型连续失败（429/5xx/超时），
    自动尝试 fallback_models 中的下一个模型。
    2026-09-01：fallback 链支持跨 provider——链条目形如 "provider:model"，
    无前缀则沿用主 provider（向后兼容旧的纯模型名条目）。
    """
    base_client = get_llm_client(provider=provider, max_tokens=max_tokens)
    chain = fallback_models or SENSENOVA_FALLBACK_MODELS
    primary_model = getattr(base_client, "model_name", None) or "unknown"

    # 构建 fallback client 列表（支持跨 provider："provider:model"，无前缀沿用主 provider）
    clients = [base_client]
    for m in chain:
        if ":" in m and not m.startswith("http"):
            fb_provider, fb_model = m.split(":", 1)
        else:
            fb_provider, fb_model = (provider or settings.llm_provider or "sensenova").lower(), m
        if fb_provider == (provider or settings.llm_provider or "").lower() and fb_model == primary_model:
            continue
        fb_cfg = LLM_PROVIDERS[fb_provider]
        fb_api_key = (
            getattr(settings, fb_cfg["api_key_env"].lower(), None)
            or os.environ.get(fb_cfg["api_key_env"])
        )
        clients.append(ChatOpenAI(
            model=fb_model,
            api_key=fb_api_key,
            base_url=fb_cfg["base_url"],
            temperature=0.3,
            max_tokens=max_tokens or 4096,
            request_timeout=120,
        ))
    return FallbackChatOpenAI(clients)


class FallbackChatOpenAI:
    """包装多个 ChatOpenAI，invoke 失败时自动切换到下一个。"""

    def __init__(self, clients: list):
        self.clients = clients
        self.model_name = getattr(clients[0], "model_name", "unknown")

    def invoke(self, prompt: str, **kwargs) -> Any:
        last_error = None
        for idx, client in enumerate(self.clients):
            model = getattr(client, "model_name", f"client_{idx}")
            try:
                resp = client.invoke(prompt, **kwargs)
                if idx > 0:
                    logger.info("[FallbackChatOpenAI] fallback to model=%s succeeded", model)
                return resp
            except Exception as e:
                last_error = e
                logger.warning("[FallbackChatOpenAI] model=%s failed: %s", model, e)
        raise RuntimeError(f"All fallback models failed. Last error: {last_error}")


def get_llm_client(provider: str | None = None, max_tokens: int | None = None) -> Any:
    """根据配置的 provider 返回对应的 LLM 客户端。

    Args:
        provider: 目标 provider，如 'kimi', 'deepseek', 'kimi-code-cli', 'kimi-code-acp'。
            None 则使用 settings.llm_provider。
        max_tokens: 覆盖默认的 4096 输出上限（长输出任务如批量提取建议 16384）；
            仅对标准 OpenAI 协议 provider 生效。

    Returns:
        ChatOpenAI — 标准 OpenAI 协议 provider
        KimiCodingClient — Kimi Coding Plan（Anthropic 协议）
        KimiCodeCLIClient — 本地 Kimi Code CLI（子进程）
        KimiCodeAcpClient — 本地 Kimi Code ACP（JSON-RPC 子进程）
    """
    target = (provider or settings.llm_provider).lower()
    logger.info("[get_llm_client] target=%s (requested=%s, default=%s)", target, provider, settings.llm_provider)

    # [DEPRECATED] 本地 Kimi Code CLI（kimi -p）已废弃，不再支持直接调用。
    # if target == _KIMI_CODE_CLI_PROVIDER:
    #     from .kimi_code_cli_client import KimiCodeCLIClient
    #
    #     logger.info("[get_llm_client] using local Kimi Code CLI")
    #     return KimiCodeCLIClient(
    #         cli_path=None,  # 使用默认 /home/ubuntu/.kimi-code/bin/kimi
    #         cwd=None,       # 使用默认 /home/ubuntu/learning-investment-strategies
    #         timeout=int(os.environ.get("KIMI_CODE_CLI_TIMEOUT", "300")),
    #     )

    if target == _KIMI_CODE_ACP_PROVIDER:
        from .kimi_code_acp_client import KimiCodeAcpClient

        logger.info("[get_llm_client] using local Kimi Code ACP")
        return KimiCodeAcpClient()

    if target not in LLM_PROVIDERS:
        raise ValueError(
            f"Unknown LLM provider: {target}. "
            f"Supported: {', '.join(LLM_PROVIDERS.keys())}, {_KIMI_CODE_ACP_PROVIDER}"
        )

    # 2026-09-03：hermes_global provider——优先解析 Hermes 全局模型配置，
    # 解析失败（非 Hermes 环境/配置不完整）→ 透明降级到 .env 主通道。
    if target == "hermes_global":
        g = _resolve_hermes_global()
        if g:
            logger.info("[get_llm_client] using hermes_global model=%s base_url=%s",
                        g["model"], g["base_url"])
            return ChatOpenAI(
                model=g["model"],
                api_key=g["api_key"],
                base_url=g["base_url"],
                temperature=0.3,
                max_tokens=max_tokens or 4096,
                request_timeout=120,
            )
        # 降级到 .env 主通道
        fallback_target = (settings.llm_provider or "").lower()
        if fallback_target and fallback_target != "hermes_global" and fallback_target in LLM_PROVIDERS:
            logger.warning("[get_llm_client] hermes_global unavailable, falling back to .env provider=%s",
                           fallback_target)
            target = fallback_target
        else:
            raise RuntimeError(
                "hermes_global: 无法解析 ~/.hermes/config.yaml 的全局模型配置，"
                "且 .env 中未配置可降级的 provider。"
                "请检查 ~/.hermes/hermes-agent 是否存在、或在 .env 设置 LLM_PROVIDER=zhipu 等。"
            )

    config = LLM_PROVIDERS[target]
    api_key = (
        getattr(settings, config["api_key_env"].lower(), None)
        or os.environ.get(config["api_key_env"])
    )
    base_url = settings.llm_base_url or config["base_url"]
    # 2026-08-24 修复：LLM_MODEL 是主 provider 的模型名（如 stealth/ox-alpha），
    # 不能透传给 fallback provider——deepseek 收到会报 400 invalid model name。
    # 仅当目标就是主 provider 时才用 settings.llm_model，否则用该 provider 默认模型。
    if target == (settings.llm_provider or "").lower():
        model = settings.llm_model or config["default_model"]
    else:
        model = config["default_model"]
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
        max_tokens=max_tokens or 4096,
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
