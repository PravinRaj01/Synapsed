"""Editing sources after they are uploaded: rename them and say which customer segment they come from.

The segment matters long after upload: it sets the weight an insight carries in Business Impact, and it is
what personas and the segment charts group by. So changing it on a source that was already analysed also
updates that source's insights and recalculates the scores that depend on it.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from ai_pipeline.analysis.theme_nodes import score_themes
from app.api.common import require_campaign
from app.core.auth import AuthUser, current_user
from app.core.database import user_tx

router = APIRouter(prefix="/api/v1", tags=["sources"])

MAX_BULK = 200

SOURCE_SELECT = """
    select r.id, r.campaign_id, r.title, r.source_type, r.source_url, r.language, r.status, r.segment_id,
           s.name as segment, r.analyzed_at
    from resources r left join segments s on s.id = r.segment_id
"""


class SourcePatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    segment_id: UUID | None = None  # send null to clear it

    @field_validator("title")
    @classmethod
    def tidy_title(cls, value: str | None) -> str | None:
        return " ".join(value.split()) if value else value


class BulkSegment(BaseModel):
    resource_ids: list[UUID] = Field(min_length=1, max_length=MAX_BULK)
    segment_id: UUID | None = None  # null clears the segment


class SourceOut(BaseModel):
    id: UUID
    campaign_id: UUID
    title: str
    source_type: str
    source_url: str | None
    language: str | None
    status: Literal["staged", "approved", "rejected"]
    segment_id: UUID | None
    segment: str | None
    analyzed_at: datetime | None
    rescored: bool  # true when the change moved insights and Business Impact was recalculated


class BulkSegmentOut(BaseModel):
    updated: int
    segment_id: UUID | None
    rescored: bool


def apply_segment(conn, campaign_id, resource_ids: list, segment_id) -> bool:
    """Set the segment on sources, carry it to the insights quoted from them, and recalculate dependent scores.

    Returns True when scores were recalculated (some of the sources had already been analysed).
    """
    conn.execute("update resources set segment_id = %s where id = any(%s::uuid[])", (segment_id, resource_ids))
    moved = conn.execute(
        """update insights set segment_id = %s
           where id in (select insight_id from citations where resource_id = any(%s::uuid[]))""",
        (segment_id, resource_ids),
    ).rowcount
    if not moved:
        return False
    score_themes(conn, campaign_id)
    conn.execute(  # roadmap items follow their theme's impact; confidence, ease and the PM's horizon are left alone
        """update roadmap_items ri set impact_score = greatest(1, least(10, floor(t.business_impact / 10 + 0.5)::int))
           from themes t where ri.theme_id = t.id and ri.campaign_id = %s""",
        (campaign_id,),
    )
    return True


def _check_segment(conn, campaign_id, segment_id) -> None:
    if segment_id is not None and not conn.execute(
        "select 1 from segments where id = %s and campaign_id = %s", (segment_id, campaign_id)
    ).fetchone():
        raise HTTPException(422, "That segment is not part of this campaign")


@router.patch("/resources/{resource_id}", response_model=SourceOut)
def update_source(resource_id: UUID, body: SourcePatch, user: AuthUser = Depends(current_user)):
    """Rename a source and/or set (or clear, with null) its customer segment."""
    changes = body.model_fields_set
    if not changes:
        raise HTTPException(422, "Nothing to change")
    if "title" in changes and body.title is None:
        raise HTTPException(422, "title cannot be empty")
    with user_tx(user.id) as conn:
        row = conn.execute("select campaign_id from resources where id = %s", (resource_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Resource not found")
        rescored = False
        if "segment_id" in changes:
            _check_segment(conn, row["campaign_id"], body.segment_id)
            rescored = apply_segment(conn, row["campaign_id"], [resource_id], body.segment_id)
        if "title" in changes:
            conn.execute("update resources set title = %s where id = %s", (body.title, resource_id))
        return {**conn.execute(SOURCE_SELECT + " where r.id = %s", (resource_id,)).fetchone(), "rescored": rescored}


@router.post("/campaigns/{campaign_id}/resources/segment", response_model=BulkSegmentOut)
def assign_segment(campaign_id: UUID, body: BulkSegment, user: AuthUser = Depends(current_user)):
    """Give many sources the same customer segment (or clear it) in one step."""
    require_campaign(user.id, campaign_id)
    ids = list(dict.fromkeys(body.resource_ids))
    with user_tx(user.id) as conn:
        _check_segment(conn, campaign_id, body.segment_id)
        found = conn.execute(
            "select id from resources where campaign_id = %s and id = any(%s::uuid[])", (campaign_id, ids)
        ).fetchall()
        if len(found) != len(ids):
            raise HTTPException(422, "Some of those sources are not part of this campaign")
        rescored = apply_segment(conn, campaign_id, ids, body.segment_id)
    return {"updated": len(ids), "segment_id": body.segment_id, "rescored": rescored}
