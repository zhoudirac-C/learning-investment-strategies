from __future__ import annotations

from pydantic import BaseModel, Field


class TriggerRequest(BaseModel):
    trigger: dict = Field(default_factory=dict, description="Hermes传入的触发信息")
    alerts: list[dict] = Field(default_factory=list, description="规则信号列表")
    market_snapshot: dict = Field(default_factory=dict, description="行情快照")
    positions: list[dict] = Field(default_factory=list, description="当前持仓")
    watchlist: list[dict] = Field(default_factory=list, description="观察池关键标的")
    sector_strengths: list[dict] = Field(default_factory=list, description="板块强弱数据")
    session_id: str = Field(default="default", description="会话ID")
    query: str = Field(default="", description="用户原始问题")


class TriggerResponse(BaseModel):
    final_output: str = Field(description="UP风格化的最终分析文本")
    claims_cited: list[str] = Field(default_factory=list, description="引用的claim IDs")
    data_sources: list[str] = Field(default_factory=list, description="数据来源")
    confidence: str = Field(default="medium", description="置信度")
    review_passed: bool = Field(default=False, description="事实核查是否通过")
    reasoning_steps: list[str] = Field(default_factory=list, description="思考步骤")


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    reply: str
    memories_used: list[dict] = Field(default_factory=list)
