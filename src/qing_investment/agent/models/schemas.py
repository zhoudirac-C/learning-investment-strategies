from __future__ import annotations

from pydantic import BaseModel, Field


class TriggerRequest(BaseModel):
    trigger: dict = Field(default_factory=dict, description="Hermes传入的触发信息")
    alerts: list[dict] = Field(default_factory=list, description="规则信号列表")
    market_snapshot: dict = Field(
        default_factory=dict,
        description="行情快照，可包含 sentiment 字段（涨跌家数、涨停/跌停、连板高度等）",
    )
    positions: list[dict] = Field(default_factory=list, description="当前持仓")
    watchlist: list[dict] = Field(default_factory=list, description="观察池关键标的")
    sector_strengths: list[dict] = Field(default_factory=list, description="板块强弱数据")
    external_sector_boards: dict = Field(default_factory=dict, description="外部行情源板块数据（概念+行业）")
    buy_signal_candidates: list[dict] = Field(default_factory=list, description="买入信号候选列表（trigger.kind=buy_signal_candidate时填充）")
    watchlist_shard: dict | None = Field(default=None, description="当前批次分析的 watchlist 子集（分片请求时使用）")
    session_id: str = Field(default="default", description="会话ID")
    query: str = Field(default="", description="用户原始问题")
    analysis_type: str = Field(default="market", description="分析类型：market/stock/portfolio")


class TriggerResponse(BaseModel):
    final_output: str = Field(description="UP风格化的最终分析文本")
    claims_cited: list[str] = Field(default_factory=list, description="引用的claim IDs")
    data_sources: list[str] = Field(default_factory=list, description="数据来源")
    confidence: str = Field(default="medium", description="置信度")
    review_passed: bool = Field(default=False, description="事实核查是否通过")
    citation_report: dict | None = Field(default=None, description="引用校验报告")
    reasoning_steps: list[str] = Field(default_factory=list, description="思考步骤")
    cost_info: dict = Field(default_factory=dict, description="LLM 调用成本信息")


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    reply: str
    memories_used: list[dict] = Field(default_factory=list)
