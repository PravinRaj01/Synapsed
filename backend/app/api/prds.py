"""PRDs for roadmap items: generate, list, read, export as Markdown, delete, and send to Jira."""

import logging
import re
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from ai_pipeline import prd as prd_logic
from ai_pipeline.providers import AllProvidersFailed, Completion, chain_for, complete
from ai_pipeline.telemetry import record_completion
from app.core.auth import AuthUser, current_user
from app.core.config import get_settings
from app.core.database import user_tx
from app.core.rate_limit import limited
from app.integrations import jira

logger = logging.getLogger("synapsed.prds")

router = APIRouter(prefix="/api/v1", tags=["prds"])

ITEM_SQL = """
    select r.id, r.campaign_id, r.theme_id, r.title, r.description, r.horizon, r.impact_score, r.confidence_score,
           r.ease_score, r.ice_score from roadmap_items r where r.id = %s
"""


class UserStoryOut(BaseModel):
    as_a: str
    i_want: str
    so_that: str
    evidence: list[int]  # numbers of the evidence quotes that back the story


class PrdBodyOut(BaseModel):
    title: str
    context: str
    problem: str
    goals: list[str]
    user_stories: list[UserStoryOut]
    acceptance_criteria: list[str]
    out_of_scope: list[str]
    success_metrics: list[str]


class EvidenceOut(BaseModel):
    n: int
    insight_id: UUID
    summary: str
    severity: int
    sentiment: str
    segment: str | None
    quote: str
    resource_id: UUID
    resource_title: str
    start_offset: int
    end_offset: int


class StoredPrdOut(BaseModel):
    prd: PrdBodyOut
    evidence: list[EvidenceOut]


class PrdOut(BaseModel):
    id: UUID
    roadmap_item_id: UUID
    content: StoredPrdOut
    markdown: str
    jira_issue_key: str | None
    created_at: datetime


class PrdVersionOut(BaseModel):
    id: UUID
    roadmap_item_id: UUID
    title: str | None
    jira_issue_key: str | None
    created_at: datetime


class JiraStatusOut(BaseModel):
    configured: bool
    project_key: str | None


class IntegrationsOut(BaseModel):
    jira: JiraStatusOut


class JiraIssueOut(BaseModel):
    jira_issue_key: str
    url: str


def call_llm(messages: list[dict]) -> Completion:
    """The model call for a PRD (English, structured output); tests replace this."""
    return complete(messages, chain_for("en"), max_tokens=2200)


def _filename(title: str) -> str:
    return (re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower() or "prd")[:60] + ".md"


@router.post("/roadmap/{item_id}/prd", status_code=201, response_model=PrdOut)
def generate_prd(item_id: UUID, user: AuthUser = Depends(limited("prd"))):
    """Write a PRD for the roadmap item from its theme's evidence. Each call stores a new version."""
    with user_tx(user.id) as conn:
        item = conn.execute(ITEM_SQL, (item_id,)).fetchone()
        if item is None:
            raise HTTPException(404, "Roadmap item not found")
        if item["theme_id"] is None:
            raise HTTPException(422, "This item has no theme, so there is no customer evidence to write a PRD from")
        theme = conn.execute("select label, description from themes where id = %s", (item["theme_id"],)).fetchone()
        evidence = prd_logic.gather_evidence(conn, item["theme_id"])
    if not evidence:
        raise HTTPException(422, "This item has no cited evidence yet. Run an analysis first.")

    def record(completion: Completion) -> None:
        try:
            with user_tx(user.id) as conn:
                record_completion(conn, item["campaign_id"], "prd", completion)
        except Exception:
            logger.warning("Could not record telemetry", exc_info=True)

    try:
        content = prd_logic.generate(item, theme, evidence, call_llm, record)
    except AllProvidersFailed as exc:
        logger.warning("PRD generation unavailable: %s", exc)
        raise HTTPException(502, "The PRD writer is unavailable right now. Try again shortly.") from exc
    except ValueError as exc:
        logger.warning("PRD generation failed: %s", exc)
        raise HTTPException(502, "The PRD writer returned something unusable. Try again.") from exc

    markdown = prd_logic.render_markdown(content, evidence, item)
    with user_tx(user.id) as conn:
        row = conn.execute(
            "insert into prds (roadmap_item_id, content, markdown) values (%s, %s, %s) "
            "returning id, roadmap_item_id, content, markdown, jira_issue_key, created_at",
            (item_id, Jsonb(prd_logic.to_stored(content, evidence)), markdown),
        ).fetchone()
    return row


@router.get("/roadmap/{item_id}/prds", response_model=list[PrdVersionOut])
def list_prds(item_id: UUID, user: AuthUser = Depends(current_user)):
    with user_tx(user.id) as conn:
        if conn.execute("select 1 from roadmap_items where id = %s", (item_id,)).fetchone() is None:
            raise HTTPException(404, "Roadmap item not found")
        return conn.execute(
            "select id, roadmap_item_id, content->'prd'->>'title' as title, jira_issue_key, created_at "
            "from prds where roadmap_item_id = %s order by created_at desc",
            (item_id,),
        ).fetchall()


def _get(user_id: UUID, prd_id: UUID) -> dict:
    with user_tx(user_id) as conn:
        row = conn.execute(
            "select id, roadmap_item_id, content, markdown, jira_issue_key, created_at from prds where id = %s", (prd_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "PRD not found")
    return row


@router.get("/prds/{prd_id}", response_model=PrdOut)
def get_prd(prd_id: UUID, user: AuthUser = Depends(current_user)):
    return _get(user.id, prd_id)


@router.get("/prds/{prd_id}/markdown")
def export_markdown(prd_id: UUID, user: AuthUser = Depends(current_user)):
    """The PRD as a downloadable Markdown file."""
    row = _get(user.id, prd_id)
    return PlainTextResponse(
        row["markdown"], media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_filename(row["content"]["prd"]["title"])}"'},
    )


@router.delete("/prds/{prd_id}", status_code=204)
def delete_prd(prd_id: UUID, user: AuthUser = Depends(current_user)) -> None:
    with user_tx(user.id) as conn:
        row = conn.execute("delete from prds where id = %s returning id", (prd_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "PRD not found")


@router.get("/integrations", response_model=IntegrationsOut)
def integrations(user: AuthUser = Depends(current_user)):
    """Which optional integrations the server has configured, so the UI can hide the buttons that would fail."""
    return {"jira": {"configured": jira.configured(get_settings()), "project_key": get_settings().jira_project_key or None}}


@router.post("/prds/{prd_id}/jira", response_model=JiraIssueOut)
def send_to_jira(prd_id: UUID, user: AuthUser = Depends(current_user)):
    """Create a Jira issue from the PRD. A PRD is sent once; its issue key is kept."""
    settings = get_settings()
    if not jira.configured(settings):
        raise HTTPException(503, "Jira is not configured on the server")
    row = _get(user.id, prd_id)
    if row["jira_issue_key"]:
        raise HTTPException(409, f"This PRD was already sent to Jira as {row['jira_issue_key']}")
    try:
        key, url = jira.create_issue(settings, row["content"]["prd"]["title"], row["markdown"])
    except jira.JiraError as exc:
        raise HTTPException(502, str(exc)) from exc
    with user_tx(user.id) as conn:
        conn.execute("update prds set jira_issue_key = %s where id = %s", (key, prd_id))
    return {"jira_issue_key": key, "url": url}
