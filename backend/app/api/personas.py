"""Persona profiles: generate one per segment from its evidence, list, edit and delete."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from ai_pipeline import personas as logic
from ai_pipeline.providers import AllProvidersFailed, Completion, chain_for, complete
from ai_pipeline.telemetry import record_completion
from app.api.common import require_campaign
from app.core.auth import AuthUser, current_user
from app.core.database import user_tx
from app.core.rate_limit import limited

logger = logging.getLogger("synapsed.personas")

router = APIRouter(prefix="/api/v1", tags=["personas"])

MAX_SEGMENTS_PER_RUN = 10

PERSONA_SELECT = """
    select p.id, p.campaign_id, p.segment_id, s.name as segment, s.tier, p.name, p.description, p.attributes
    from personas p left join segments s on s.id = p.segment_id
"""


class GenerateRequest(BaseModel):
    segment_ids: list[UUID] | None = Field(None, max_length=MAX_SEGMENTS_PER_RUN)  # default: every segment with enough insights


class PersonaIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=700)
    segment_id: UUID | None = None


class PersonaPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    description: str | None = Field(None, min_length=1, max_length=700)


def call_llm(messages: list[dict]) -> Completion:
    """The model call for a persona (English, structured output); tests replace this."""
    return complete(messages, chain_for("en"), max_tokens=900)


@router.get("/campaigns/{campaign_id}/personas")
def list_personas(campaign_id: UUID, user: AuthUser = Depends(current_user)):
    require_campaign(user.id, campaign_id)
    with user_tx(user.id) as conn:
        return conn.execute(PERSONA_SELECT + " where p.campaign_id = %s order by s.name nulls last, p.name", (campaign_id,)).fetchall()


@router.post("/campaigns/{campaign_id}/personas", status_code=201)
def create_persona(campaign_id: UUID, body: PersonaIn, user: AuthUser = Depends(current_user)):
    """Add a persona by hand (the PM knows something the data does not)."""
    require_campaign(user.id, campaign_id)
    with user_tx(user.id) as conn:
        if body.segment_id and not conn.execute(
            "select 1 from segments where id = %s and campaign_id = %s", (body.segment_id, campaign_id)
        ).fetchone():
            raise HTTPException(422, "That segment is not part of this campaign")
        persona_id = conn.execute(
            "insert into personas (campaign_id, segment_id, name, description, attributes) values (%s, %s, %s, %s, %s) returning id",
            (campaign_id, body.segment_id, " ".join(body.name.split()), body.description.strip(), Jsonb({"generated": False})),
        ).fetchone()["id"]
        return conn.execute(PERSONA_SELECT + " where p.id = %s", (persona_id,)).fetchone()


@router.post("/campaigns/{campaign_id}/personas/generate")
def generate_personas(campaign_id: UUID, body: GenerateRequest | None = None, user: AuthUser = Depends(limited("personas"))):
    """Write a persona for each segment that has enough insights, replacing the previously generated one.

    Personas added by hand are never touched. One segment failing does not stop the others.
    """
    require_campaign(user.id, campaign_id)
    wanted = body.segment_ids if body else None
    with user_tx(user.id) as conn:
        segments = conn.execute(
            "select id, name, tier, weight, description from segments where campaign_id = %s "
            "and (%s::uuid[] is null or id = any(%s::uuid[])) order by name",
            (campaign_id, wanted, wanted),
        ).fetchall()
    if wanted and len(segments) != len(set(wanted)):
        raise HTTPException(422, "Some of those segments are not part of this campaign")

    def record(completion: Completion) -> None:
        try:
            with user_tx(user.id) as conn:
                record_completion(conn, campaign_id, "persona", completion)
        except Exception:
            logger.warning("Could not record telemetry", exc_info=True)

    created, skipped, failed = [], [], []
    for segment in segments[:MAX_SEGMENTS_PER_RUN]:
        with user_tx(user.id) as conn:
            insight_count = logic.count_insights(conn, segment["id"])
            evidence = logic.gather_evidence(conn, segment["id"]) if insight_count >= logic.MIN_INSIGHTS else []
        if not evidence:
            skipped.append({"segment": segment["name"], "reason": f"needs at least {logic.MIN_INSIGHTS} analysed insights with quotes"})
            continue
        try:
            content = logic.generate(segment, evidence, call_llm, record)
        except (AllProvidersFailed, ValueError) as exc:
            logger.warning("Persona for segment %s failed: %s", segment["name"], exc)
            failed.append({"segment": segment["name"], "error": "The persona writer is unavailable or returned something unusable. Try again."})
            continue
        with user_tx(user.id) as conn:
            conn.execute(
                "delete from personas where segment_id = %s and attributes->>'generated' = 'true'", (segment["id"],)
            )
            persona_id = conn.execute(
                "insert into personas (campaign_id, segment_id, name, description, attributes) values (%s, %s, %s, %s, %s) returning id",
                (campaign_id, segment["id"], content.name, content.description,
                 Jsonb(logic.attributes(content, evidence, insight_count))),
            ).fetchone()["id"]
            created.append(conn.execute(PERSONA_SELECT + " where p.id = %s", (persona_id,)).fetchone())
    return {"personas": created, "skipped": skipped, "failed": failed}


@router.patch("/personas/{persona_id}")
def update_persona(persona_id: UUID, body: PersonaPatch, user: AuthUser = Depends(current_user)):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "Nothing to change")
    if any(v is None for v in changes.values()):
        raise HTTPException(422, "Fields cannot be set to null")
    sets = ", ".join(f"{column} = %s" for column in changes)  # column names come from the model, never from the client
    with user_tx(user.id) as conn:
        row = conn.execute(f"update personas set {sets} where id = %s returning id", (*[v.strip() for v in changes.values()], persona_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Persona not found")
        return conn.execute(PERSONA_SELECT + " where p.id = %s", (persona_id,)).fetchone()


@router.delete("/personas/{persona_id}", status_code=204)
def delete_persona(persona_id: UUID, user: AuthUser = Depends(current_user)) -> None:
    with user_tx(user.id) as conn:
        row = conn.execute("delete from personas where id = %s returning id", (persona_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Persona not found")
