"""Reads and edits behind the Problem Space Report, the resource viewer, the roadmap and the dashboard.

Everything runs under the signed-in user's row-level security, so a foreign id is "not found".
"""

from collections import Counter, defaultdict
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from ai_pipeline.analysis.scoring import theme_sentiment
from app.api.common import require_campaign
from app.api.runs import RUN_NODE, _status
from app.core.auth import AuthUser, current_user
from app.core.database import user_tx

router = APIRouter(prefix="/api/v1", tags=["report"])

TOP_USE_CASES = 5
TOP_THEMES = 5
RECENT = 5
TREND_DAYS = 7
MAX_THEME_INSIGHTS = 200


# ---------------------------------------------------------------- themes (the Problem Space Report)

def build_theme_rows(themes: list[dict], insights: list[dict], sources: dict[str, int], segments: dict[str, dict]) -> list[dict]:
    """One report row per theme, strongest first. Pure: the caller supplies the rows from the database."""
    by_theme: dict[str, list[dict]] = defaultdict(list)
    for insight in insights:
        by_theme[str(insight["theme_id"])].append(insight)

    rows = []
    for theme in themes:
        mine = by_theme.get(str(theme["id"]), [])
        sentiment = theme_sentiment([i["sentiment"] for i in mine])
        per_segment = Counter(str(i["segment_id"]) if i["segment_id"] else None for i in mine)
        use_cases = Counter(i["use_case"] for i in mine if i["use_case"])
        rows.append({
            "id": theme["id"], "label": theme["label"], "description": theme["description"],
            "color": theme["color_code"], "frequency": theme["frequency"], "business_impact": theme["business_impact"],
            "sentiment": sentiment.label, "sentiment_counts": sentiment.counts, "sentiment_net": sentiment.net,
            "average_severity": round(sum(i["severity"] for i in mine) / len(mine), 1) if mine else None,
            "kinds": dict(Counter(i["kind"] for i in mine)),
            "sources": sources.get(str(theme["id"]), 0),
            "segments": [
                {"segment_id": key, "name": segments[key]["name"] if key else "No segment",
                 "tier": segments[key]["tier"] if key else None, "insights": count}
                for key, count in per_segment.most_common() if key is None or key in segments
            ],
            "use_cases": [{"use_case": name, "insights": count} for name, count in use_cases.most_common(TOP_USE_CASES)],
        })
    return sorted(rows, key=lambda r: (-float(r["business_impact"]), -r["frequency"], r["label"]))


@router.get("/campaigns/{campaign_id}/themes")
def list_themes(campaign_id: UUID, user: AuthUser = Depends(current_user)):
    """The Problem Space Report: themes with frequency, Business Impact, sentiment, segments and use cases."""
    require_campaign(user.id, campaign_id)
    with user_tx(user.id) as conn:
        themes = conn.execute(
            "select id, label, description, color_code, frequency, business_impact from themes where campaign_id = %s",
            (campaign_id,),
        ).fetchall()
        insights = conn.execute(
            "select theme_id, segment_id, use_case, sentiment, severity, kind from insights "
            "where campaign_id = %s and theme_id is not null",
            (campaign_id,),
        ).fetchall()
        sources = {
            str(r["theme_id"]): r["n"]
            for r in conn.execute(
                """select i.theme_id, count(distinct c.resource_id) as n from citations c
                   join insights i on i.id = c.insight_id where i.campaign_id = %s and i.theme_id is not null
                   group by i.theme_id""",
                (campaign_id,),
            ).fetchall()
        }
        segments = {
            str(r["id"]): r
            for r in conn.execute("select id, name, tier from segments where campaign_id = %s", (campaign_id,)).fetchall()
        }
    return build_theme_rows(themes, insights, sources, segments)


@router.get("/themes/{theme_id}")
def get_theme(theme_id: UUID, user: AuthUser = Depends(current_user)):
    """A theme with its insights and, for each, the quotes that back it up."""
    with user_tx(user.id) as conn:
        theme = conn.execute(
            "select id, campaign_id, label, description, color_code as color, frequency, business_impact "
            "from themes where id = %s",
            (theme_id,),
        ).fetchone()
        if theme is None:
            raise HTTPException(404, "Theme not found")
        insights = conn.execute(
            """select i.id, i.summary_text, i.use_case, i.severity, i.sentiment, i.kind, i.confidence_score,
                      i.segment_id, s.name as segment, i.created_at
               from insights i left join segments s on s.id = i.segment_id
               where i.theme_id = %s order by i.severity desc, i.created_at limit %s""",
            (theme_id, MAX_THEME_INSIGHTS),
        ).fetchall()
        citations = conn.execute(
            """select c.insight_id, c.resource_id, r.title as resource_title, c.chunk_id, c.text_snippet,
                      c.start_offset, c.end_offset
               from citations c join resources r on r.id = c.resource_id
               where c.insight_id = any(%s::uuid[]) order by c.start_offset""",
            ([i["id"] for i in insights],),
        ).fetchall()
    quotes: dict[UUID, list[dict]] = defaultdict(list)
    for c in citations:
        quotes[c["insight_id"]].append({k: v for k, v in c.items() if k != "insight_id"})
    return {**theme, "insights": [{**i, "citations": quotes.get(i["id"], [])} for i in insights]}


# ---------------------------------------------------------------- resource viewer

@router.get("/resources/{resource_id}")
def get_resource(resource_id: UUID, user: AuthUser = Depends(current_user)):
    """A resource's text with every quote to highlight in it, coloured by theme."""
    with user_tx(user.id) as conn:
        resource = conn.execute(
            """select r.id, r.campaign_id, r.title, r.source_type, r.source_url, r.language, r.status, r.content,
                      r.summary, r.pii_redacted, r.pii_note, r.segment_id, s.name as segment, r.analyzed_at, r.created_at
               from resources r left join segments s on s.id = r.segment_id where r.id = %s""",
            (resource_id,),
        ).fetchone()
        if resource is None:
            raise HTTPException(404, "Resource not found")
        highlights = conn.execute(
            """select c.id as citation_id, c.insight_id, c.start_offset, c.end_offset, c.text_snippet,
                      i.summary_text as insight, i.theme_id, t.label as theme, t.color_code as color
               from citations c join insights i on i.id = c.insight_id left join themes t on t.id = i.theme_id
               where c.resource_id = %s order by c.start_offset""",
            (resource_id,),
        ).fetchall()
    return {**resource, "highlights": highlights}


# ---------------------------------------------------------------- roadmap

Horizon = Literal["now", "next", "later"]


def score_field():
    return Field(None, ge=1, le=10)

ROADMAP_SELECT = """
    select r.id, r.campaign_id, r.theme_id, t.label as theme, t.color_code as color, r.insight_id, r.title,
           r.description, r.horizon, r.impact_score, r.confidence_score, r.ease_score, r.ice_score, r.created_at
    from roadmap_items r left join themes t on t.id = r.theme_id
"""


class RoadmapPatch(BaseModel):
    horizon: Horizon | None = None
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, min_length=1, max_length=2000)
    impact_score: int | None = score_field()
    confidence_score: int | None = score_field()
    ease_score: int | None = score_field()

    @field_validator("title")
    @classmethod
    def tidy_title(cls, value: str | None) -> str | None:
        return " ".join(value.split()) if value else value


@router.get("/campaigns/{campaign_id}/roadmap")
def list_roadmap(campaign_id: UUID, user: AuthUser = Depends(current_user)):
    """The board: every item with its ICE score, highest first. The client groups them by horizon."""
    require_campaign(user.id, campaign_id)
    with user_tx(user.id) as conn:
        return conn.execute(ROADMAP_SELECT + " where r.campaign_id = %s order by r.ice_score desc, r.title", (campaign_id,)).fetchall()


@router.patch("/roadmap/{item_id}")
def update_roadmap_item(item_id: UUID, body: RoadmapPatch, user: AuthUser = Depends(current_user)):
    """Move a card or correct a score. ICE is recomputed by the database."""
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "Nothing to change")
    if any(value is None for value in changes.values()):
        raise HTTPException(422, "Fields cannot be set to null")
    sets = ", ".join(f"{column} = %s" for column in changes)  # column names come from the model, never from the client
    with user_tx(user.id) as conn:
        row = conn.execute(f"update roadmap_items set {sets} where id = %s returning id", (*changes.values(), item_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Roadmap item not found")
        return conn.execute(ROADMAP_SELECT + " where r.id = %s", (item_id,)).fetchone()


# ---------------------------------------------------------------- dashboard

@router.get("/campaigns/{campaign_id}/overview")
def overview(campaign_id: UUID, user: AuthUser = Depends(current_user)):
    """Everything the dashboard shows in one call."""
    require_campaign(user.id, campaign_id)
    with user_tx(user.id) as conn:
        resource_counts = {r["status"]: r["n"] for r in conn.execute(
            "select status, count(*) as n from resources where campaign_id = %s group by status", (campaign_id,)).fetchall()}
        waiting = conn.execute(
            "select count(*) as n from resources where campaign_id = %s and status = 'approved' and analyzed_at is null",
            (campaign_id,)).fetchone()["n"]
        sentiment = {r["sentiment"]: r["n"] for r in conn.execute(
            "select sentiment, count(*) as n from insights where campaign_id = %s group by sentiment", (campaign_id,)).fetchall()}
        top_themes = conn.execute(
            "select id, label, color_code as color, frequency, business_impact from themes where campaign_id = %s "
            "order by business_impact desc, frequency desc limit %s", (campaign_id, TOP_THEMES)).fetchall()
        totals = conn.execute(
            """select (select count(*) from insights where campaign_id = %(c)s) as insights,
                      (select count(*) from themes where campaign_id = %(c)s) as themes,
                      (select count(*) from roadmap_items where campaign_id = %(c)s) as roadmap_items,
                      (select count(*) from segments where campaign_id = %(c)s) as segments""", {"c": campaign_id}).fetchone()
        trend = conn.execute(
            """select table_name, count(*) filter (where created_at >= now() - make_interval(days => %(d)s)) as current,
                      count(*) filter (where created_at < now() - make_interval(days => %(d)s)
                                         and created_at >= now() - make_interval(days => 2 * %(d)s)) as previous
               from (select 'resources' as table_name, created_at from resources where campaign_id = %(c)s
                     union all select 'insights', created_at from insights where campaign_id = %(c)s
                     union all select 'themes', created_at from themes where campaign_id = %(c)s) t
               group by table_name""", {"c": campaign_id, "d": TREND_DAYS}).fetchall()
        recent = conn.execute(
            "select id, title, source_type, status, language, created_at from resources where campaign_id = %s "
            "order by created_at desc limit %s", (campaign_id, RECENT)).fetchall()
        last_run = conn.execute(
            """select run_id, min(created_at) as started_at,
                      (array_agg(status order by created_at desc) filter (where node = %s))[1] as run_status,
                      extract(epoch from (now() - max(created_at))) / 60 as idle_minutes
               from agent_runs where campaign_id = %s group by run_id order by min(created_at) desc limit 1""",
            (RUN_NODE, campaign_id)).fetchone()
        telemetry = conn.execute(
            """select model_used, count(*) as calls, coalesce(sum(tokens_processed), 0) as tokens,
                      count(fallback_from) as fallbacks
               from telemetry_logs where campaign_id = %s group by model_used order by calls desc""", (campaign_id,)).fetchall()
    return {
        "resources": {"total": sum(resource_counts.values()), "staged": resource_counts.get("staged", 0),
                      "approved": resource_counts.get("approved", 0), "rejected": resource_counts.get("rejected", 0),
                      "waiting_for_analysis": waiting},
        **totals,
        "sentiment": {s: sentiment.get(s, 0) for s in ("positive", "neutral", "negative")},
        # How many were added in the last TREND_DAYS days against the TREND_DAYS before, so KPI cards can show % change.
        "trend": {"days": TREND_DAYS, **{name: {"current": 0, "previous": 0} for name in ("resources", "insights", "themes")},
                  **{t["table_name"]: {"current": t["current"], "previous": t["previous"]} for t in trend}},
        "top_themes": top_themes,
        "recent_resources": recent,
        "last_run": None if last_run is None else {
            "run_id": last_run["run_id"], "started_at": last_run["started_at"],
            "status": _status(last_run["run_status"], float(last_run["idle_minutes"]))},
        "telemetry": {
            "calls": sum(t["calls"] for t in telemetry), "tokens": sum(t["tokens"] for t in telemetry),
            "fallbacks": sum(t["fallbacks"] for t in telemetry), "by_model": telemetry},
    }
