"""Embeddings with Google gemini-embedding-001, truncated to 768 dimensions.

Truncated embeddings are not unit length, so every vector is L2-normalised; the
pgvector cosine search then behaves consistently.
"""

import math
from functools import lru_cache

from google import genai
from google.genai import errors, types
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import get_settings

DIMENSIONS = 768
BATCH_SIZE = 50


@lru_cache
def _client() -> genai.Client:
    key = get_settings().google_api_key
    if not key:
        raise RuntimeError("GOOGLE_API_KEY is not set")
    return genai.Client(api_key=key)


def _retryable(exc: BaseException) -> bool:
    return isinstance(exc, errors.APIError) and (exc.code == 429 or (exc.code or 0) >= 500)


def normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


@retry(
    retry=retry_if_exception(_retryable),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, max=30),
    reraise=True,
)
def _embed_batch(texts: list[str], task_type: str) -> list[list[float]]:
    response = _client().models.embed_content(
        model=get_settings().gemini_embed_model,
        contents=texts,
        config=types.EmbedContentConfig(output_dimensionality=DIMENSIONS, task_type=task_type),
    )
    return [normalize(list(e.values)) for e in response.embeddings]


def embed_texts(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """Embed texts in batches. Use task_type="RETRIEVAL_QUERY" for search queries."""
    vectors: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        vectors.extend(_embed_batch(texts[i : i + BATCH_SIZE], task_type))
    return vectors
