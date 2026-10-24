"""Load the demo sandbox into a campaign."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.common import require_campaign
from app.core.auth import AuthUser, current_user
from app.core.database import user_tx
from app.demo import DemoError, load_demo

router = APIRouter(prefix="/api/v1", tags=["demo"])


class DemoLoadedOut(BaseModel):
    resources: int
    insights: int
    themes: int
    roadmap_items: int


@router.post("/campaigns/{campaign_id}/demo", status_code=201, response_model=DemoLoadedOut)
def load_demo_sandbox(campaign_id: UUID, user: AuthUser = Depends(current_user)):
    """Fill an empty campaign with invented sources, pain points, themes and a roadmap (no LLM calls).

    Missing demo segments (Enterprise, Mid-Market, Free) are added; segments the campaign already has are kept.
    """
    require_campaign(user.id, campaign_id)
    try:
        with user_tx(user.id) as conn:
            return load_demo(conn, campaign_id)
    except DemoError as exc:
        raise HTTPException(409, str(exc)) from exc
