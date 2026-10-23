from uuid import UUID

from fastapi import HTTPException

from app.core.database import user_tx


def require_campaign(user_id: UUID, campaign_id: UUID) -> None:
    """404 unless the campaign exists and belongs to one of the user's workspaces (RLS)."""
    with user_tx(user_id) as conn:
        if not conn.execute("select 1 from campaigns where id = %s", (campaign_id,)).fetchone():
            raise HTTPException(404, "Campaign not found")
