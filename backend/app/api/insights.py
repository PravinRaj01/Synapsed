"""Insights Studio: the opportunity matrix, preset charts and charts from a plain-language request."""

import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ai_pipeline import charts
from ai_pipeline.providers import AllProvidersFailed, Completion, chain_for, complete
from ai_pipeline.telemetry import record_completion
from app.api.common import require_campaign
from app.core.auth import AuthUser, current_user
from app.core.database import user_tx
from app.core.rate_limit import limited

logger = logging.getLogger("synapsed.insights")

router = APIRouter(prefix="/api/v1", tags=["insights"])


class MatrixPointOut(BaseModel):
    theme_id: UUID
    label: str
    color: str
    frequency: int
    business_impact: float
    ice_score: int | None
    horizon: Literal["now", "next", "later"] | None
    quadrant: Literal["priority", "high_stakes", "common_annoyance", "monitor"]
    quadrant_label: str


class QuadrantOut(BaseModel):
    key: str
    label: str


class OpportunityMatrixOut(BaseModel):
    impact_line: float
    frequency_line: float
    points: list[MatrixPointOut]
    quadrants: list[QuadrantOut]


class ChartSeriesOut(BaseModel):
    name: str
    values: list[float]


class ChartResultOut(BaseModel):
    x: list[str]
    series: list[ChartSeriesOut]
    measure: str


class ChartOut(BaseModel):
    spec: charts.ChartSpec
    result: ChartResultOut


class PresetChartOut(ChartOut):
    key: str
    title: str | None


class PromptChartOut(ChartOut):
    title: str | None
    model: str | None
    tokens: int


class RunChartRequest(BaseModel):
    spec: charts.ChartSpec


class PromptChartRequest(BaseModel):
    prompt: str = Field(min_length=5, max_length=400)


def call_llm(messages: list[dict]) -> Completion:
    """The model call for turning a request into a chart spec; tests replace this."""
    return complete(messages, chain_for("en"), max_tokens=500)


@router.get("/campaigns/{campaign_id}/opportunity-matrix", response_model=OpportunityMatrixOut)
def get_opportunity_matrix(campaign_id: UUID, user: AuthUser = Depends(current_user)):
    """Every theme placed by frequency and Business Impact, with its ICE score when it has a roadmap item."""
    require_campaign(user.id, campaign_id)
    with user_tx(user.id) as conn:
        themes = conn.execute(
            """select t.id, t.label, t.color_code as color, t.frequency, t.business_impact,
                      r.ice_score, r.horizon
               from themes t left join lateral (
                   select ice_score, horizon from roadmap_items where theme_id = t.id order by ice_score desc limit 1
               ) r on true
               where t.campaign_id = %s""",
            (campaign_id,),
        ).fetchall()
    return charts.opportunity_matrix(themes)


@router.get("/campaigns/{campaign_id}/charts/presets", response_model=list[PresetChartOut])
def preset_charts(campaign_id: UUID, user: AuthUser = Depends(current_user)):
    """The standard dashboard: each chart's spec together with its data."""
    require_campaign(user.id, campaign_id)
    with user_tx(user.id) as conn:
        return [
            {"key": key, "title": spec.title, "spec": spec.model_dump(), "result": charts.run_chart(conn, campaign_id, spec)}
            for key, spec in charts.PRESETS
        ]


@router.post("/campaigns/{campaign_id}/charts/run", response_model=ChartOut)
def run_chart(campaign_id: UUID, body: RunChartRequest, user: AuthUser = Depends(current_user)):
    """Run a chart spec (a preset, or one the user edited). Specs are validated against fixed options."""
    require_campaign(user.id, campaign_id)
    with user_tx(user.id) as conn:
        return {"spec": body.spec.model_dump(), "result": charts.run_chart(conn, campaign_id, body.spec)}


@router.post("/campaigns/{campaign_id}/charts", response_model=PromptChartOut)
def chart_from_prompt(campaign_id: UUID, body: PromptChartRequest, user: AuthUser = Depends(limited("charts"))):
    """Turn a request such as "show negative sentiment by segment as a stacked bar" into a chart.

    The model only chooses from fixed options; the server builds and runs the query.
    """
    require_campaign(user.id, campaign_id)
    with user_tx(user.id) as conn:
        themes = [r["label"] for r in conn.execute(
            "select label from themes where campaign_id = %s order by business_impact desc limit 30", (campaign_id,)).fetchall()]
        segments = [r["name"] for r in conn.execute("select name from segments where campaign_id = %s order by name", (campaign_id,)).fetchall()]

    used: list[Completion] = []
    try:
        spec = charts.spec_from_prompt(body.prompt, themes, segments, call_llm, used.append)
    except charts.ChartRefused as exc:
        raise HTTPException(422, str(exc)) from exc
    except AllProvidersFailed as exc:
        logger.warning("Chart service unavailable: %s", exc)
        raise HTTPException(502, "The chart service is unavailable right now. Try again shortly.") from exc

    try:
        with user_tx(user.id) as conn:
            for completion in used:
                record_completion(conn, campaign_id, "chart", completion)
    except Exception:
        logger.warning("Could not record telemetry", exc_info=True)
    with user_tx(user.id) as conn:
        result = charts.run_chart(conn, campaign_id, spec)
    return {"spec": spec.model_dump(), "result": result, "title": spec.title,
            "model": f"{used[-1].provider}:{used[-1].model}" if used else None, "tokens": sum(c.total_tokens for c in used)}
