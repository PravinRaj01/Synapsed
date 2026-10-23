"""The graph's nodes. Each takes the run state and the injected Deps and returns a state update."""

import logging
from collections import defaultdict
from dataclasses import asdict

from pgvector import Vector

from ai_pipeline.analysis.extraction import extract_resource
from ai_pipeline.analysis.state import Deps, RunState
from ai_pipeline.providers import AllProvidersFailed, Completion
from ai_pipeline.telemetry import record_completion
from app.core.database import user_tx

logger = logging.getLogger("synapsed.analysis")

MAX_RESOURCES_PER_RUN = 200


def traced(name: str):
    """Report a node's start, result or failure through deps.trace."""

    def decorate(fn):
        # No functools.wraps: it sets __wrapped__, and LangGraph then reads the inner
        # function's signature, finds no `config` parameter and does not pass one.
        def node(state: RunState, config) -> dict:
            deps: Deps = config["configurable"]["deps"]
            deps.trace(name, "running")
            try:
                update = fn(state, deps)
            except Exception as exc:
                deps.trace(name, "error", output={"error": str(exc)[:500]})
                raise
            deps.trace(name, "done", output={k: len(v) if isinstance(v, (list, dict)) else v for k, v in update.items()})
            return update

        node.__name__ = fn.__name__
        node.__doc__ = fn.__doc__
        return node

    return decorate


@traced("select")
def select_node(state: RunState, deps: Deps) -> dict:
    """Approved resources in the campaign that have not been analysed yet."""
    only = state.get("only_resources")
    with user_tx(state["user_id"]) as conn:
        rows = conn.execute(
            """select id from resources
               where campaign_id = %s and status = 'approved' and analyzed_at is null
                 and (%s::uuid[] is null or id = any(%s::uuid[]))
               order by created_at limit %s""",
            (state["campaign_id"], only, only, min(MAX_RESOURCES_PER_RUN, state.get("max_resources") or MAX_RESOURCES_PER_RUN)),
        ).fetchall()
    return {"resource_ids": [str(r["id"]) for r in rows]}


@traced("extract")
def extract_node(state: RunState, deps: Deps) -> dict:
    """One LLM call per resource (more for long ones). A failed resource is skipped, not fatal."""
    items: list[dict] = []
    extracted: list[str] = []
    errors: list[dict] = []

    def on_completion(completion: Completion, messages: list[dict]) -> None:
        try:
            with user_tx(state["user_id"]) as conn:
                record_completion(conn, state["campaign_id"], "extraction", completion)
        except Exception:
            logger.warning("Could not record telemetry", exc_info=True)
        deps.trace(
            "extract", "done", model_used=f"{completion.provider}:{completion.model}",
            prompt=messages[-1]["content"], output=completion.text,
            tokens=completion.total_tokens, latency_ms=completion.latency_ms,
        )

    for resource_id in state["resource_ids"]:
        with user_tx(state["user_id"]) as conn:
            row = conn.execute(
                "select content, language, segment_id from resources where id = %s", (resource_id,)
            ).fetchone()
        try:
            result = extract_resource(row["content"], row["language"], deps.llm, on_completion)
        except (AllProvidersFailed, ValueError) as exc:
            logger.warning("Extraction failed for resource %s: %s", resource_id, exc)
            errors.append({"resource_id": resource_id, "stage": "extract", "error": str(exc)[:300]})
            continue
        extracted.append(resource_id)
        for item in result.items:
            items.append({**asdict(item), "resource_id": resource_id,
                          "segment_id": str(row["segment_id"]) if row["segment_id"] else None})
        if result.dropped:
            logger.info("Resource %s: dropped %s", resource_id, dict(result.dropped))
    return {"items": items, "extracted_resources": extracted, "errors": errors}


def _chunk_for(chunks: list[dict], start: int, end: int) -> str | None:
    """The chunk that holds the whole quote if there is one, else the one covering most of it."""
    for chunk in chunks:
        if chunk["start_offset"] <= start and end <= chunk["end_offset"]:
            return chunk["id"]
    best_id, best_overlap = None, 0
    for chunk in chunks:
        overlap = min(end, chunk["end_offset"]) - max(start, chunk["start_offset"])
        if overlap > best_overlap:
            best_id, best_overlap = chunk["id"], overlap
    return best_id


@traced("embed")
def embed_node(state: RunState, deps: Deps) -> dict:
    """Embed each pain point and store insights with their citations; mark the resource analysed.

    Everything for one resource is written in one transaction, so a failure leaves it unanalysed
    and eligible for the next run.
    """
    by_resource: dict[str, list[dict]] = defaultdict(list)
    for item in state.get("items", []):
        by_resource[item["resource_id"]].append(item)

    insight_ids: list[str] = []
    errors: list[dict] = []
    for resource_id in state.get("extracted_resources", []):
        items = by_resource.get(resource_id, [])
        try:
            vectors = deps.embed([i["pain_point"] for i in items]) if items else []
            with user_tx(state["user_id"]) as conn:
                chunks = conn.execute(
                    "select id, start_offset, end_offset from resource_chunks where resource_id = %s order by chunk_index",
                    (resource_id,),
                ).fetchall()
                for item, vector in zip(items, vectors):
                    insight_id = conn.execute(
                        """insert into insights (campaign_id, segment_id, use_case, summary_text, severity,
                                                 sentiment, kind, confidence_score, embedding)
                           values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
                        (state["campaign_id"], item["segment_id"], item["use_case"] or None, item["pain_point"],
                         item["severity"], item["sentiment"], item["kind"],
                         1.00 if item["exact"] else 0.90,  # how sure we are the quote is the customer's words
                         Vector(vector)),
                    ).fetchone()["id"]
                    conn.execute(
                        """insert into citations (insight_id, resource_id, chunk_id, text_snippet, start_offset, end_offset)
                           values (%s, %s, %s, %s, %s, %s)""",
                        (insight_id, resource_id, _chunk_for(chunks, item["start"], item["end"]),
                         item["quote"], item["start"], item["end"]),
                    )
                    insight_ids.append(str(insight_id))
                conn.execute("update resources set analyzed_at = now() where id = %s", (resource_id,))
        except Exception as exc:
            logger.warning("Could not store insights for resource %s: %s", resource_id, exc)
            errors.append({"resource_id": resource_id, "stage": "embed", "error": str(exc)[:300]})
    return {"insight_ids": insight_ids, "errors": errors}
