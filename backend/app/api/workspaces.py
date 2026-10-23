"""Workspaces, campaigns and customer segments.

Everything runs under the signed-in user's row-level security: a user only ever sees workspaces they
belong to, so a wrong or foreign id looks like "not found".
"""

from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.api.common import require_campaign
from app.core.auth import AuthUser, current_user
from app.core.database import user_tx

router = APIRouter(prefix="/api/v1", tags=["workspaces"])

Tier = Literal["enterprise", "mid_market", "free", "other"]
MAX_SEGMENTS = 20
MAX_WEIGHT = 20.0


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    company: str = Field(min_length=1, max_length=120)
    industry: str = Field(min_length=1, max_length=120)


class SegmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    tier: Tier = "other"
    weight: float = Field(1.0, gt=0, le=MAX_WEIGHT)  # how much this customer group counts in Business Impact
    description: str | None = Field(None, max_length=300)

    @field_validator("name")
    @classmethod
    def tidy_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("name is required")
        return value

    @field_validator("weight")
    @classmethod
    def one_decimal(cls, value: float) -> float:
        rounded = round(value, 1)
        if rounded <= 0:
            raise ValueError("weight must be at least 0.1")
        return rounded


class SegmentPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    tier: Tier | None = None
    weight: float | None = Field(None, gt=0, le=MAX_WEIGHT)
    description: str | None = Field(None, max_length=300)

    @field_validator("name")
    @classmethod
    def tidy_name(cls, value: str | None) -> str | None:
        return " ".join(value.split()) if value else value

    @field_validator("weight")
    @classmethod
    def one_decimal(cls, value: float | None) -> float | None:
        if value is None:
            return value
        rounded = round(value, 1)
        if rounded <= 0:
            raise ValueError("weight must be at least 0.1")
        return rounded


class CampaignIn(BaseModel):
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=120)
    goal: str | None = Field(None, max_length=500)
    segments: list[SegmentIn] = Field(default_factory=list, max_length=MAX_SEGMENTS)


class CampaignPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    goal: str | None = Field(None, max_length=500)


CAMPAIGN_SELECT = """
    select c.id, c.workspace_id, c.name, c.goal, c.created_at,
           (select count(*) from resources r where r.campaign_id = c.id) as resources,
           (select count(*) from resources r where r.campaign_id = c.id and r.status = 'staged') as staged,
           (select count(*) from insights i where i.campaign_id = c.id) as insights,
           (select count(*) from themes t where t.campaign_id = c.id) as themes
    from campaigns c
"""


def _unique_names(segments: list[SegmentIn]) -> None:
    seen = set()
    for segment in segments:
        key = segment.name.lower()
        if key in seen:
            raise HTTPException(422, f"Segment '{segment.name}' appears twice")
        seen.add(key)


def _insert_segment(conn: psycopg.Connection, campaign_id: UUID, segment: SegmentIn) -> dict:
    if conn.execute(
        "select 1 from segments where campaign_id = %s and lower(name) = lower(%s)", (campaign_id, segment.name)
    ).fetchone():
        raise HTTPException(409, f"This campaign already has a segment named '{segment.name}'")
    return conn.execute(
        """insert into segments (campaign_id, name, tier, weight, description) values (%s, %s, %s, %s, %s)
           returning id, campaign_id, name, tier, weight, description""",
        (campaign_id, segment.name, segment.tier, segment.weight, segment.description),
    ).fetchone()


# ---------------------------------------------------------------- workspaces

@router.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceIn, user: AuthUser = Depends(current_user)):
    with user_tx(user.id) as conn:
        workspace_id = conn.execute(
            "select create_workspace(%s, %s, %s) as id", (body.name, body.company, body.industry)
        ).fetchone()["id"]
    return {"id": workspace_id, **body.model_dump(), "role": "owner", "campaigns": 0}


@router.get("/workspaces")
def list_workspaces(user: AuthUser = Depends(current_user)):
    with user_tx(user.id) as conn:
        return conn.execute(
            """select w.id, w.name, w.company, w.industry, w.created_at, m.role,
                      (select count(*) from campaigns c where c.workspace_id = w.id) as campaigns
               from workspaces w join workspace_members m on m.workspace_id = w.id and m.user_id = %s
               order by w.created_at""",
            (user.id,),
        ).fetchall()


# ---------------------------------------------------------------- campaigns

@router.post("/campaigns", status_code=201)
def create_campaign(body: CampaignIn, user: AuthUser = Depends(current_user)):
    """Create a campaign, optionally with its starting customer segments."""
    _unique_names(body.segments)
    with user_tx(user.id) as conn:
        if not conn.execute("select 1 from workspaces where id = %s", (body.workspace_id,)).fetchone():
            raise HTTPException(404, "Workspace not found")
        campaign_id = conn.execute(
            "insert into campaigns (workspace_id, name, goal) values (%s, %s, %s) returning id",
            (body.workspace_id, body.name.strip(), body.goal),
        ).fetchone()["id"]
        segments = [_insert_segment(conn, campaign_id, s) for s in body.segments]
        campaign = conn.execute(CAMPAIGN_SELECT + " where c.id = %s", (campaign_id,)).fetchone()
    return {**campaign, "segments": segments}


@router.get("/campaigns")
def list_campaigns(workspace_id: UUID | None = None, user: AuthUser = Depends(current_user)):
    with user_tx(user.id) as conn:
        return conn.execute(
            CAMPAIGN_SELECT + " where (%s::uuid is null or c.workspace_id = %s) order by c.created_at desc",
            (workspace_id, workspace_id),
        ).fetchall()


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: UUID, user: AuthUser = Depends(current_user)):
    with user_tx(user.id) as conn:
        campaign = conn.execute(CAMPAIGN_SELECT + " where c.id = %s", (campaign_id,)).fetchone()
        if campaign is None:
            raise HTTPException(404, "Campaign not found")
        segments = conn.execute(
            "select id, campaign_id, name, tier, weight, description from segments where campaign_id = %s order by name",
            (campaign_id,),
        ).fetchall()
    return {**campaign, "segments": segments}


@router.patch("/campaigns/{campaign_id}")
def update_campaign(campaign_id: UUID, body: CampaignPatch, user: AuthUser = Depends(current_user)):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "Nothing to change")
    if "name" in changes and changes["name"] is None:
        raise HTTPException(422, "name cannot be empty")
    with user_tx(user.id) as conn:
        row = conn.execute(
            "update campaigns set name = coalesce(%s, name), goal = case when %s then %s else goal end "
            "where id = %s returning id",
            (changes.get("name"), "goal" in changes, changes.get("goal"), campaign_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Campaign not found")
        return conn.execute(CAMPAIGN_SELECT + " where c.id = %s", (campaign_id,)).fetchone()


# ---------------------------------------------------------------- segments

@router.get("/campaigns/{campaign_id}/segments")
def list_segments(campaign_id: UUID, user: AuthUser = Depends(current_user)):
    require_campaign(user.id, campaign_id)
    with user_tx(user.id) as conn:
        return conn.execute(
            """select s.id, s.campaign_id, s.name, s.tier, s.weight, s.description,
                      (select count(*) from resources r where r.segment_id = s.id) as resources,
                      (select count(*) from insights i where i.segment_id = s.id) as insights
               from segments s where s.campaign_id = %s order by s.name""",
            (campaign_id,),
        ).fetchall()


@router.post("/campaigns/{campaign_id}/segments", status_code=201)
def create_segment(campaign_id: UUID, body: SegmentIn, user: AuthUser = Depends(current_user)):
    require_campaign(user.id, campaign_id)
    with user_tx(user.id) as conn:
        count = conn.execute("select count(*) as n from segments where campaign_id = %s", (campaign_id,)).fetchone()["n"]
        if count >= MAX_SEGMENTS:
            raise HTTPException(409, f"A campaign can have at most {MAX_SEGMENTS} segments")
        return _insert_segment(conn, campaign_id, body)


@router.patch("/segments/{segment_id}")
def update_segment(segment_id: UUID, body: SegmentPatch, user: AuthUser = Depends(current_user)):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "Nothing to change")
    if any(changes.get(k, 0) is None for k in ("name", "tier", "weight")):
        raise HTTPException(422, "name, tier and weight cannot be empty")
    with user_tx(user.id) as conn:
        current = conn.execute("select campaign_id, name from segments where id = %s", (segment_id,)).fetchone()
        if current is None:
            raise HTTPException(404, "Segment not found")
        if "name" in changes and conn.execute(
            "select 1 from segments where campaign_id = %s and lower(name) = lower(%s) and id <> %s",
            (current["campaign_id"], changes["name"], segment_id),
        ).fetchone():
            raise HTTPException(409, f"This campaign already has a segment named '{changes['name']}'")
        sets = ", ".join(f"{column} = %s" for column in changes)  # column names come from the model, never from the client
        return conn.execute(
            f"update segments set {sets} where id = %s returning id, campaign_id, name, tier, weight, description",
            (*changes.values(), segment_id),
        ).fetchone()


@router.delete("/segments/{segment_id}", status_code=204)
def delete_segment(segment_id: UUID, user: AuthUser = Depends(current_user)) -> None:
    """Resources and insights tagged with the segment keep existing; they just lose the tag."""
    with user_tx(user.id) as conn:
        row = conn.execute("delete from segments where id = %s returning id", (segment_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Segment not found")
