"""Hybrid search over approved sources: vectors find paraphrases, keywords find exact terms.

Embeddings blur feature names, error codes and short Malay words ("SSO", "eksport"), so the same
query also runs as a keyword search (Postgres full text, the `simple` configuration so no English
stemming gets in the way). The two ranked lists are merged with Reciprocal Rank Fusion, which
needs no score calibration between them.
"""

import re
from dataclasses import dataclass
from uuid import UUID

import psycopg
from pgvector import Vector

RRF_K = 60
CANDIDATES = 12  # taken from each list before fusing
MAX_KEYWORDS = 12
MAX_KEYWORD_CHARS = 40

# Words that match nearly every chunk: dropped from the keyword query so real terms decide the ranking.
STOPWORDS = {
    "the", "and", "are", "was", "were", "what", "which", "who", "whom", "when", "where", "why", "how", "does",
    "did", "for", "with", "that", "this", "these", "those", "from", "have", "has", "had", "about", "they",
    "their", "there", "been", "would", "could", "should", "can", "any", "all", "our", "your", "you", "not",
    "yang", "dan", "untuk", "dengan", "apa", "ini", "itu", "adalah", "kepada", "dalam", "pada", "tidak",
    "saya", "kami", "anda", "ada", "atau", "dari", "ke", "di",
}
_WORD = re.compile(r"\w+", re.UNICODE)

VECTOR_SQL = """
    select c.id as chunk_id, c.resource_id, r.title as resource_title, c.content, c.start_offset, c.end_offset,
           1 - (c.embedding <=> %(vector)s) as similarity
    from resource_chunks c join resources r on r.id = c.resource_id
    where r.campaign_id = %(campaign)s and r.status = 'approved'
      and (%(only)s::uuid[] is null or r.id = any(%(only)s::uuid[]))
    order by c.embedding <=> %(vector)s
    limit %(n)s
"""

KEYWORD_SQL = """
    select c.id as chunk_id, c.resource_id, r.title as resource_title, c.content, c.start_offset, c.end_offset,
           ts_rank(to_tsvector('simple', c.content), q) as rank
    from resource_chunks c join resources r on r.id = c.resource_id, to_tsquery('simple', %(query)s) q
    where r.campaign_id = %(campaign)s and r.status = 'approved'
      and (%(only)s::uuid[] is null or r.id = any(%(only)s::uuid[]))
      and to_tsvector('simple', c.content) @@ q
    order by rank desc
    limit %(n)s
"""


@dataclass
class Hit:
    chunk_id: UUID
    resource_id: UUID
    resource_title: str
    content: str
    start_offset: int
    end_offset: int
    score: float = 0.0  # reciprocal rank fusion
    similarity: float | None = None  # cosine similarity when the vector search found it
    vector_rank: int | None = None  # 1-based position in each list, None when absent
    keyword_rank: int | None = None


def keyword_query(text: str) -> str | None:
    """A safe to_tsquery string (terms OR-ed together), or None when nothing searchable is left.

    Only word characters survive, so user text can never inject tsquery syntax.
    """
    seen: dict[str, None] = {}
    for word in _WORD.findall(text.lower()):
        if len(word) >= 3 and word not in STOPWORDS and not word.isdigit() and len(word) <= MAX_KEYWORD_CHARS and "_" not in word:
            seen.setdefault(word)
    terms = list(seen)[:MAX_KEYWORDS]
    return " | ".join(terms) if terms else None


def fuse(vector_hits: list[Hit], keyword_hits: list[Hit], limit: int) -> list[Hit]:
    """Merge two ranked lists. A chunk found by both rises above chunks found by only one."""
    merged: dict[UUID, Hit] = {}
    for rank, hit in enumerate(vector_hits, start=1):
        hit.vector_rank = rank
        hit.score += 1 / (RRF_K + rank)
        merged[hit.chunk_id] = hit
    for rank, hit in enumerate(keyword_hits, start=1):
        existing = merged.get(hit.chunk_id)
        if existing is None:
            merged[hit.chunk_id] = existing = hit
        existing.keyword_rank = rank
        existing.score += 1 / (RRF_K + rank)
    return sorted(merged.values(), key=lambda h: (-h.score, h.vector_rank or 999, h.keyword_rank or 999))[:limit]


def _hit(row: dict, similarity: float | None = None) -> Hit:
    return Hit(row["chunk_id"], row["resource_id"], row["resource_title"], row["content"],
               row["start_offset"], row["end_offset"], similarity=similarity)


def hybrid_search(
    conn: psycopg.Connection, campaign_id: UUID | str, text: str, vector, *, limit: int = 8,
    resource_ids: list[UUID | str] | None = None,
) -> list[Hit]:
    """Approved chunks of the campaign (optionally only from some resources), best first."""
    params = {"campaign": campaign_id, "only": [str(r) for r in resource_ids] if resource_ids else None, "n": CANDIDATES}
    vector_hits = [_hit(r, float(r["similarity"])) for r in conn.execute(VECTOR_SQL, {**params, "vector": Vector(vector)}).fetchall()]
    query = keyword_query(text)
    keyword_hits = [_hit(r) for r in conn.execute(KEYWORD_SQL, {**params, "query": query}).fetchall()] if query else []
    return fuse(vector_hits, keyword_hits, limit)
