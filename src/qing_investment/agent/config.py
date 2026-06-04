from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """qing-agent 全局配置，支持多厂商 LLM 切换。"""

    # === LLM 通用配置 ===
    llm_provider: str = "kimi"
    llm_model: str | None = None
    llm_base_url: str | None = None

    # 各厂商 API Key（按需填写）
    openai_api_key: str | None = None
    azure_openai_api_key: str | None = None
    kimi_api_key: str | None = None
    deepseek_api_key: str | None = None
    zhipu_api_key: str | None = None
    qwen_api_key: str | None = None
    baichuan_api_key: str | None = None
    siliconflow_api_key: str | None = None
    groq_api_key: str | None = None
    together_api_key: str | None = None

    # === 存储层配置 ===
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "qingneo4j"

    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

    mem0_api_key: str | None = None
    mem0_base_url: str = "http://localhost:8001"

    # === 项目路径 ===
    repo_path: str = "/home/ubuntu/learning-investment-strategies"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
