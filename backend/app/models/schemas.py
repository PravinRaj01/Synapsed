"""Pydantic models mirroring schema.sql. Constraints match the SQL checks."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Tier = Literal["enterprise", "mid_market", "free", "other"]
SourceType = Literal[
    "transcript", "ticket", "survey", "audio", "video", "ocr", "pdf", "web_scrape"
]
ResourceStatus = Literal["staged", "approved", "rejected"]
Sentiment = Literal["positive", "neutral", "negative"]
InsightKind = Literal["pain_point", "feature_request"]
Horizon = Literal["now", "next", "later"]
RunStatus = Literal["running", "done", "error"]

Score10 = Annotated[int, Field(ge=1, le=10)]
Embedding = Annotated[list[float], Field(min_length=768, max_length=768)]


class Row(BaseModel):
    """Base for models read from the database."""

    model_config = ConfigDict(from_attributes=True)


class Workspace(Row):
    id: UUID
    name: str
    company: str
    industry: str
    created_at: datetime


class WorkspaceMember(Row):
    workspace_id: UUID
    user_id: UUID
    role: str = "owner"


class Campaign(Row):
    id: UUID
    workspace_id: UUID
    name: str
    goal: str | None = None
    created_at: datetime


class Segment(Row):
    id: UUID
    campaign_id: UUID
    name: str
    tier: Tier
    weight: Annotated[float, Field(gt=0, le=99.9)] = 1.0
    description: str | None = None


class Persona(Row):
    id: UUID
    campaign_id: UUID
    segment_id: UUID | None = None
    name: str
    description: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class Resource(Row):
    id: UUID
    campaign_id: UUID
    title: str
    source_type: SourceType
    source_url: str | None = None
    storage_path: str | None = None
    content: str
    language: str | None = None
    segment_id: UUID | None = None
    content_hash: str
    pii_redacted: bool = False
    status: ResourceStatus = "staged"
    created_at: datetime


class ResourceChunk(Row):
    id: UUID
    resource_id: UUID
    chunk_index: int
    content: str
    start_offset: int
    end_offset: int
    embedding: Embedding | None = None


class Theme(Row):
    id: UUID
    campaign_id: UUID
    label: str
    color_code: str
    description: str | None = None
    frequency: int = 0
    business_impact: Annotated[float, Field(ge=0, le=100)] = 0
    created_at: datetime


class Insight(Row):
    id: UUID
    campaign_id: UUID
    theme_id: UUID | None = None
    segment_id: UUID | None = None
    use_case: str | None = None
    summary_text: str
    severity: Annotated[int, Field(ge=1, le=5)] = 3
    sentiment: Sentiment = "neutral"
    kind: InsightKind = "pain_point"
    confidence_score: Annotated[float, Field(ge=0, le=1)] | None = None
    embedding: Embedding | None = None
    created_at: datetime


class Citation(Row):
    id: UUID
    insight_id: UUID
    resource_id: UUID
    chunk_id: UUID | None = None
    text_snippet: str
    start_offset: int
    end_offset: int


class RoadmapItem(Row):
    id: UUID
    campaign_id: UUID
    theme_id: UUID | None = None
    insight_id: UUID | None = None
    title: str
    description: str
    horizon: Horizon
    impact_score: Score10
    confidence_score: Score10
    ease_score: Score10
    ice_score: int  # generated column: impact * confidence * ease
    created_at: datetime


class Prd(Row):
    id: UUID
    roadmap_item_id: UUID
    content: dict[str, Any]
    markdown: str
    jira_issue_key: str | None = None
    created_at: datetime


class AgentRun(Row):
    id: UUID
    campaign_id: UUID
    run_id: UUID
    node: str
    status: RunStatus
    model_used: str | None = None
    prompt: str | None = None
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    tokens: int = 0
    latency_ms: int | None = None
    created_at: datetime


class TelemetryLog(Row):
    id: UUID
    campaign_id: UUID
    model_used: str
    tokens_processed: int
    latency_ms: int | None = None
    action_type: str
    fallback_from: str | None = None
    created_at: datetime


class AuditLog(Row):
    id: UUID
    workspace_id: UUID
    actor: str
    action: str
    target_resource: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
