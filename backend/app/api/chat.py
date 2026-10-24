"""Chat with the approved sources, and search across them."""

import logging
from dataclasses import asdict
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ai_pipeline import chat as chat_logic
from ai_pipeline.embedder import embed_texts
from ai_pipeline.providers import AllProvidersFailed, Completion, chain_for, complete
from ai_pipeline.retrieval import Hit, hybrid_search
from ai_pipeline.telemetry import record_completion
from app.api.common import require_campaign
from app.core.auth import AuthUser, current_user
from app.core.database import user_tx
from app.core.rate_limit import limited
from app.core.language import detect_language

logger = logging.getLogger("synapsed.chat")

router = APIRouter(prefix="/api/v1", tags=["chat"])

CONTEXT_CHUNKS = 6  # passages sent to the model
SNIPPET_CHARS = 300
MIN_CHARS_TO_DETECT_LANGUAGE = 60  # language detection on a short question is a coin toss ("Why does login fail?" reads as Welsh)


def question_language(question: str) -> str | None:
    """The question's language for choosing a provider chain, or None (the default chain) when too short to tell."""
    return detect_language(question) if len(question) >= MIN_CHARS_TO_DETECT_LANGUAGE else None


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    campaign_id: UUID
    question: str = Field(min_length=3, max_length=1000)
    source_ids: list[UUID] | None = Field(None, max_length=50)  # the context checklist; default: every approved source
    history: list[Turn] = Field(default_factory=list, max_length=12)


def embed_query(text: str) -> list[float]:
    """Embedding of a question; tests replace this."""
    return embed_texts([text], task_type="RETRIEVAL_QUERY")[0]


def call_llm(messages: list[dict], language: str | None) -> Completion:
    """The model call for a chat turn; tests replace this."""
    return complete(messages, chain_for(language), max_tokens=900)


def _retrieve(user_id: UUID, campaign_id: UUID, text: str, source_ids, limit: int) -> list[Hit]:
    try:
        vector = embed_query(text)
    except Exception as exc:
        logger.warning("Query embedding failed: %s", exc)
        raise HTTPException(502, "Search is unavailable right now. Try again shortly.") from exc
    with user_tx(user_id) as conn:
        return hybrid_search(conn, campaign_id, text, vector, limit=limit, resource_ids=source_ids)


def _describe(n: int, hit: Hit) -> dict:
    return {"n": n, "resource_id": hit.resource_id, "resource_title": hit.resource_title, "chunk_id": hit.chunk_id,
            "similarity": None if hit.similarity is None else round(hit.similarity, 3),
            "vector_rank": hit.vector_rank, "keyword_rank": hit.keyword_rank}


class RetrievedOut(BaseModel):
    n: int
    resource_id: UUID
    resource_title: str
    chunk_id: UUID
    similarity: float | None
    vector_rank: int | None
    keyword_rank: int | None


class CitationOut(BaseModel):
    n: int
    resource_id: UUID
    resource_title: str
    chunk_id: UUID
    start_offset: int
    end_offset: int
    snippet: str
    verified: bool  # the offsets point at the quoted words, not just the retrieved passage


class ChatOut(BaseModel):
    answer: str | None
    refused: bool
    reason: str | None  # no_sources | not_in_sources | ungrounded | unreadable_reply
    message: str | None  # the plain refusal text to show when refused
    citations: list[CitationOut]
    retrieved: list[RetrievedOut]
    model: str | None
    tokens: int


class SearchHitOut(BaseModel):
    chunk_id: UUID
    resource_id: UUID
    resource_title: str
    snippet: str
    start_offset: int
    end_offset: int
    score: float
    similarity: float | None
    matched_by: list[Literal["meaning", "keywords"]]


@router.post("/chat", response_model=ChatOut)
def chat(req: ChatRequest, user: AuthUser = Depends(limited("chat"))):
    """Answer from the approved sources with [n] citations, or refuse when they do not support an answer."""
    require_campaign(user.id, req.campaign_id)
    hits = _retrieve(user.id, req.campaign_id, req.question, req.source_ids, CONTEXT_CHUNKS)
    base = {"retrieved": [_describe(n, h) for n, h in enumerate(hits, start=1)], "model": None, "tokens": 0}
    if not hits:
        return {**base, "answer": None, "refused": True, "reason": "no_sources", "message": chat_logic.REFUSAL, "citations": []}

    messages = chat_logic.build_messages(req.question, hits, [t.model_dump() for t in req.history])
    try:
        completion = call_llm(messages, question_language(req.question))
    except AllProvidersFailed as exc:
        logger.warning("Chat unavailable: %s", exc)
        raise HTTPException(502, "The answer service is unavailable right now. Try again shortly.") from exc
    try:
        with user_tx(user.id) as conn:
            record_completion(conn, req.campaign_id, "chat", completion)
    except Exception:
        logger.warning("Could not record telemetry", exc_info=True)

    result = chat_logic.parse_answer(completion.text, hits)
    return {
        **base, "model": f"{completion.provider}:{completion.model}", "tokens": completion.total_tokens,
        "answer": result.answer, "refused": result.refused, "reason": result.reason,
        "message": chat_logic.REFUSAL if result.refused else None,
        "citations": [asdict(c) for c in result.citations],
    }


@router.get("/search", response_model=list[SearchHitOut])
def search(
    campaign_id: UUID, q: str = Query(min_length=2, max_length=300), limit: int = Query(10, ge=1, le=20),
    source_ids: list[UUID] | None = Query(None, max_length=50), user: AuthUser = Depends(limited("search")),
):
    """Hybrid search over approved sources: passages that match by meaning or by exact words."""
    require_campaign(user.id, campaign_id)
    hits = _retrieve(user.id, campaign_id, q, source_ids, limit)
    return [{
        "chunk_id": h.chunk_id, "resource_id": h.resource_id, "resource_title": h.resource_title,
        "snippet": h.content[:SNIPPET_CHARS], "start_offset": h.start_offset, "end_offset": h.end_offset,
        "score": round(h.score, 5), "similarity": None if h.similarity is None else round(h.similarity, 3),
        "matched_by": [name for name, rank in (("meaning", h.vector_rank), ("keywords", h.keyword_rank)) if rank],
    } for h in hits]
