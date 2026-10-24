"""Scenario View: a weekly trend forecast and a what-if on segment weights or added insights.

The numbers come from plain code (ai_pipeline/forecast.py). The model only writes a short narrative, and
it is dropped if it mentions a figure that is not in the data. Everything here is labelled an estimate.
"""

import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from ai_pipeline import forecast, narrative
from ai_pipeline.providers import Completion, chain_for, complete
from ai_pipeline.telemetry import record_completion
from app.api.common import require_campaign
from app.core.auth import AuthUser
from app.core.database import user_tx
from app.core.rate_limit import limited

logger = logging.getLogger("synapsed.scenario")

router = APIRouter(prefix="/api/v1", tags=["scenario"])

MAX_WEIGHT = 20.0


class WeekPointOut(BaseModel):
    week: str  # the Monday of the week, ISO date
    value: float
    partial: bool  # the current week, still filling up


class ForecastPointOut(BaseModel):
    week: str
    value: float
    lower: float
    upper: float


class ForecastOut(BaseModel):
    metric: Literal["insights", "impact"]
    scope: dict[str, str]  # {"theme": ..., "segment": ...}, empty for the whole campaign
    estimate: Literal[True]
    series: list[WeekPointOut]
    forecast: list[ForecastPointOut] | None  # null until there are enough complete weeks
    trend: Literal["rising", "falling", "flat"] | None
    weekly_change: float | None = None
    method: str
    weeks_used: int
    interval: str | None = None
    note: str
    narrative: str | None


class ImpactAtOut(BaseModel):
    business_impact: float
    rank: int
    frequency: int


class ScenarioThemeOut(BaseModel):
    theme_id: str
    label: str
    before: ImpactAtOut
    after: ImpactAtOut
    impact_change: float
    rank_change: int  # positive = moved up


class WeightChangeOut(BaseModel):
    segment: str
    from_: float = Field(alias="from")
    to: float

    model_config = {"populate_by_name": True}


class ExtraAssumptionOut(BaseModel):
    theme: str
    segment: str | None
    count: int


class AssumptionsOut(BaseModel):
    segment_weights: list[WeightChangeOut]
    extra_insights: list[ExtraAssumptionOut]


class ScenarioOut(BaseModel):
    estimate: Literal[True]
    assumptions: AssumptionsOut
    themes: list[ScenarioThemeOut]
    top_before: str | None
    top_after: str | None
    narrative: str | None
    note: str


class ForecastRequest(BaseModel):
    metric: Literal["insights", "impact"] = "insights"
    theme_id: UUID | None = None
    segment_id: UUID | None = None
    horizon_weeks: int = Field(4, ge=1, le=forecast.MAX_HORIZON)
    narrative: bool = True


class ExtraInsights(BaseModel):
    theme_id: UUID
    segment_id: UUID | None = None
    count: int = Field(ge=1, le=1000)
    severity: int | None = Field(None, ge=1, le=5)  # default: the theme's average


class ScenarioRequest(BaseModel):
    segment_weights: dict[UUID, float] = Field(default_factory=dict, max_length=20)
    extra_insights: list[ExtraInsights] = Field(default_factory=list, max_length=20)
    narrative: bool = True

    @field_validator("segment_weights")
    @classmethod
    def sane_weights(cls, weights: dict[UUID, float]) -> dict[UUID, float]:
        for weight in weights.values():
            if not 0.1 <= weight <= MAX_WEIGHT:
                raise ValueError(f"weights must be between 0.1 and {MAX_WEIGHT:g}")
        return {k: round(v, 1) for k, v in weights.items()}


def call_llm(messages: list[dict]) -> Completion:
    """The model call for a narrative; tests replace this."""
    return complete(messages, chain_for("en"), max_tokens=400)


def today() -> datetime:
    return datetime.now(timezone.utc)


def _narrate(user_id, campaign_id, data: dict) -> str | None:
    def record(completion: Completion) -> None:
        try:
            with user_tx(user_id) as conn:
                record_completion(conn, campaign_id, "forecast_narrative", completion)
        except Exception:
            logger.warning("Could not record telemetry", exc_info=True)

    return narrative.narrate(data, call_llm, record)


@router.post("/campaigns/{campaign_id}/forecast", response_model=ForecastOut)
def forecast_trend(campaign_id: UUID, body: ForecastRequest, user: AuthUser = Depends(limited("forecast"))):
    """Weekly history of insights (or Business Impact) for the campaign, a theme or a segment, and a short forecast."""
    require_campaign(user.id, campaign_id)
    with user_tx(user.id) as conn:
        names = {}
        if body.theme_id:
            row = conn.execute("select label from themes where id = %s and campaign_id = %s", (body.theme_id, campaign_id)).fetchone()
            if row is None:
                raise HTTPException(422, "That theme is not part of this campaign")
            names["theme"] = row["label"]
        if body.segment_id:
            row = conn.execute("select name from segments where id = %s and campaign_id = %s", (body.segment_id, campaign_id)).fetchone()
            if row is None:
                raise HTTPException(422, "That segment is not part of this campaign")
            names["segment"] = row["name"]
        rows = conn.execute(
            """select (i.created_at at time zone 'utc')::date as day,
                      case when %s::text = 'impact' then coalesce(s.weight, 1) * i.severity else 1 end as value
               from insights i left join segments s on s.id = i.segment_id
               where i.campaign_id = %s and (%s::uuid is null or i.theme_id = %s) and (%s::uuid is null or i.segment_id = %s)""",
            (body.metric, campaign_id, body.theme_id, body.theme_id, body.segment_id, body.segment_id),
        ).fetchall()
    series = forecast.weekly_series([(r["day"], float(r["value"])) for r in rows], today().date())
    result = {"metric": body.metric, "scope": names, "estimate": True, "series": series,
              **forecast.forecast_series(series, body.horizon_weeks)}
    result["narrative"] = None
    if body.narrative and result["forecast"]:
        facts = {"metric": "Business Impact points" if body.metric == "impact" else "new pain points and requests per week",
                 "scope": names or "whole campaign", "recent_weeks": [p["value"] for p in series if not p["partial"]][-8:],
                 "trend": result["trend"], "weekly_change": result["weekly_change"], "method": result["method"],
                 "interval": result["interval"], "forecast": [{"week": p["week"], "value": p["value"], "range": [p["lower"], p["upper"]]} for p in result["forecast"]]}
        result["narrative"] = _narrate(user.id, campaign_id, facts)
    return result


@router.post("/campaigns/{campaign_id}/scenario", response_model=ScenarioOut, response_model_by_alias=True)
def scenario(campaign_id: UUID, body: ScenarioRequest, user: AuthUser = Depends(limited("forecast"))):
    """What if the customer segments counted differently, or we heard more about a theme? Impact and rank before and after."""
    require_campaign(user.id, campaign_id)
    if not body.segment_weights and not body.extra_insights:
        raise HTTPException(422, "Change at least one segment weight or add some insights")
    with user_tx(user.id) as conn:
        segments = {str(r["id"]): r for r in conn.execute("select id, name, weight from segments where campaign_id = %s", (campaign_id,)).fetchall()}
        themes = {str(r["id"]): r["label"] for r in conn.execute("select id, label from themes where campaign_id = %s", (campaign_id,)).fetchall()}
        cells = {(str(r["theme_id"]), str(r["segment_id"]) if r["segment_id"] else None): {"count": r["n"], "severity_sum": r["sev"]}
                 for r in conn.execute(
                     "select theme_id, segment_id, count(*) as n, sum(severity) as sev from insights "
                     "where campaign_id = %s and theme_id is not null group by 1, 2", (campaign_id,)).fetchall()}
    unknown_segments = {str(k) for k in body.segment_weights} | {str(e.segment_id) for e in body.extra_insights if e.segment_id}
    if not unknown_segments <= segments.keys():
        raise HTTPException(422, "Some of those segments are not part of this campaign")
    if not {str(e.theme_id) for e in body.extra_insights} <= themes.keys():
        raise HTTPException(422, "Some of those themes are not part of this campaign")

    result = forecast.what_if(
        cells, {k: float(v["weight"]) for k, v in segments.items()}, themes,
        {str(k): v for k, v in body.segment_weights.items()},
        [{"theme_id": str(e.theme_id), "segment_id": str(e.segment_id) if e.segment_id else None, "count": e.count, "severity": e.severity}
         for e in body.extra_insights],
    )
    assumptions = {
        "segment_weights": [{"segment": segments[str(k)]["name"], "from": float(segments[str(k)]["weight"]), "to": v} for k, v in body.segment_weights.items()],
        "extra_insights": [{"theme": themes[str(e.theme_id)], "segment": segments[str(e.segment_id)]["name"] if e.segment_id else None, "count": e.count}
                           for e in body.extra_insights],
    }
    out = {"estimate": True, "assumptions": assumptions, **result, "narrative": None,
           "note": "A what-if on the stored data: it recalculates Business Impact under your assumptions. It is not a prediction."}
    if body.narrative:
        facts = {"assumptions": assumptions, "top_theme_before": result["top_before"], "top_theme_after": result["top_after"],
                 "themes": [{"theme": r["label"], "impact_before": r["before"]["business_impact"], "impact_after": r["after"]["business_impact"],
                             "rank_before": r["before"]["rank"], "rank_after": r["after"]["rank"]} for r in result["themes"][:6]]}
        out["narrative"] = _narrate(user.id, campaign_id, facts)
    return out
