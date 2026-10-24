"""The demo sandbox: a small, finished campaign loaded from files, with no LLM calls.

data/demo/demo.json holds invented interviews, tickets and surveys (English and Malay) with the pain points, themes and
roadmap an analysis run would produce. data/demo/embeddings.json.gz holds their vectors, built once by
scripts/build_demo_embeddings.py, so search and chat work on the demo as on real data. Text without a stored vector is
loaded without one: it simply does not turn up in similarity search.
"""

import gzip
import hashlib
import json
from pathlib import Path

from pgvector import Vector

from ai_pipeline.analysis import scoring
from ai_pipeline.analysis.theme_nodes import EVIDENCE_SQL, score_themes
from app.ingestion.chunking import chunk_text
from app.ingestion.cleaning import content_hash

DATA = Path(__file__).resolve().parent.parent / "data" / "demo"
SUMMARY_CHARS = 200
DAY_SPREAD = 1.2  # days between demo sources, so the dashboard has a recent past to compare


class DemoError(Exception):
    """The campaign cannot take the demo (it already has data)."""


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def load_definition() -> dict:
    return json.loads((DATA / "demo.json").read_text(encoding="utf-8"))


def load_embeddings() -> dict[str, list[float]]:
    path = DATA / "embeddings.json.gz"
    if not path.exists():
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def embedded_texts(definition: dict) -> list[str]:
    """Every text that gets a vector: resource chunks and insight summaries, in a stable order."""
    texts: list[str] = []
    for resource in definition["resources"]:
        texts.extend(chunk.content for chunk in chunk_text(resource["content"]))
    texts.extend(insight["summary"] for insight in definition["insights"])
    return list(dict.fromkeys(texts))


def _summary(text: str) -> str:
    flat = " ".join(text.split())
    if len(flat) <= SUMMARY_CHARS:
        return flat
    return flat[:SUMMARY_CHARS].rsplit(" ", 1)[0] + "..."


def _vector(vectors: dict[str, list[float]], text: str):
    found = vectors.get(text_key(text))
    return Vector(found) if found else None


def load_demo(conn, campaign_id) -> dict:
    """Fill an empty campaign with the demo and return the counts. Runs inside the caller's transaction."""
    taken = conn.execute(
        "select (select count(*) from resources where campaign_id = %(c)s) + (select count(*) from insights where campaign_id = %(c)s)"
        " + (select count(*) from themes where campaign_id = %(c)s) as n", {"c": campaign_id}).fetchone()["n"]
    if taken:
        raise DemoError("The demo can only be loaded into a campaign that has no sources yet")

    definition = load_definition()
    vectors = load_embeddings()

    segments: dict[str, str] = {
        row["name"].lower(): row["id"]
        for row in conn.execute("select id, name from segments where campaign_id = %s", (campaign_id,)).fetchall()
    }
    for segment in definition["segments"]:
        if segment["name"].lower() not in segments:
            segments[segment["name"].lower()] = conn.execute(
                "insert into segments (campaign_id, name, tier, weight, description) values (%s, %s, %s, %s, %s) returning id",
                (campaign_id, segment["name"], segment["tier"], segment["weight"], segment["description"]),
            ).fetchone()["id"]

    count = len(definition["resources"])
    resources: dict[str, dict] = {}
    for position, resource in enumerate(definition["resources"]):
        segment_id = segments.get(resource["segment"].lower()) if resource["segment"] else None
        age_days = (count - position) * DAY_SPREAD
        text = resource["content"]
        resource_id = conn.execute(
            """insert into resources (campaign_id, title, source_type, content, summary, language, segment_id, content_hash,
                                      pii_redacted, status, analyzed_at, created_at)
               values (%(c)s, %(title)s, %(type)s, %(content)s, %(summary)s, %(lang)s, %(seg)s, %(hash)s, true, 'approved',
                       now(), now() - make_interval(secs => %(age)s))
               returning id""",
            {"c": campaign_id, "title": resource["title"], "type": resource["source_type"], "content": text,
             "summary": _summary(text), "lang": resource["language"], "seg": segment_id, "hash": content_hash(text),
             "age": age_days * 86400},
        ).fetchone()["id"]
        chunk_rows = []
        for chunk in chunk_text(text):
            chunk_id = conn.execute(
                """insert into resource_chunks (resource_id, chunk_index, content, start_offset, end_offset, embedding)
                   values (%s, %s, %s, %s, %s, %s) returning id""",
                (resource_id, chunk.index, chunk.content, chunk.start, chunk.end, _vector(vectors, chunk.content)),
            ).fetchone()["id"]
            chunk_rows.append((chunk_id, chunk.start, chunk.end))
        resources[resource["key"]] = {"id": resource_id, "text": text, "chunks": chunk_rows, "age": age_days}

    themes: dict[str, str] = {}
    for theme in definition["themes"]:
        themes[theme["key"]] = conn.execute(
            "insert into themes (campaign_id, label, description, color_code) values (%s, %s, %s, %s) returning id",
            (campaign_id, theme["label"], theme["description"], theme["color"]),
        ).fetchone()["id"]

    for insight in definition["insights"]:
        source = resources[insight["resource"]]
        segment_id = segments.get(insight["segment"].lower()) if insight["segment"] else None
        insight_id = conn.execute(
            """insert into insights (campaign_id, theme_id, segment_id, use_case, summary_text, severity, sentiment, kind,
                                     confidence_score, embedding, created_at)
               values (%(c)s, %(theme)s, %(seg)s, %(use)s, %(summary)s, %(sev)s, %(sent)s, %(kind)s, %(conf)s, %(emb)s,
                       now() - make_interval(secs => %(age)s))
               returning id""",
            {"c": campaign_id, "theme": themes[insight["theme"]], "seg": segment_id, "use": insight["use_case"],
             "summary": insight["summary"], "sev": insight["severity"], "sent": insight["sentiment"], "kind": insight["kind"],
             "conf": 0.9, "emb": _vector(vectors, insight["summary"]), "age": source["age"] * 86400},
        ).fetchone()["id"]
        start = source["text"].index(insight["quote"])  # a quote that is not in the text is a bug in demo.json
        end = start + len(insight["quote"])
        chunk_id = next((cid for cid, s, e in source["chunks"] if s <= start and end <= e), None)
        conn.execute(
            "insert into citations (insight_id, resource_id, chunk_id, text_snippet, start_offset, end_offset) values (%s, %s, %s, %s, %s, %s)",
            (insight_id, source["id"], chunk_id, insight["quote"], start, end),
        )

    score_themes(conn, campaign_id)
    roadmap = _build_roadmap(conn, campaign_id, definition, themes)
    return {"resources": count, "insights": len(definition["insights"]), "themes": len(themes), "roadmap_items": roadmap}


def _build_roadmap(conn, campaign_id, definition: dict, themes: dict[str, str]) -> int:
    """One roadmap item per problem theme, scored with the same formulas the analysis run uses."""
    plans = {themes[t["key"]]: t for t in definition["themes"] if t.get("roadmap", True)}
    scored: dict[str, dict] = {}
    for row in conn.execute(EVIDENCE_SQL, (campaign_id,)).fetchall():
        plan = plans.get(row["id"])
        if plan is None or not row["mentions"]:
            continue
        impact = scoring.impact_score(float(row["business_impact"]))
        confidence = scoring.confidence_score(row["sources"], row["mentions"], float(row["cohesion"]) if row["cohesion"] is not None else None)
        scored[str(row["id"])] = {"plan": plan, "impact": impact, "confidence": confidence, "ease": plan["ease"],
                                  "ice": scoring.ice(impact, confidence, plan["ease"])}
    horizon = scoring.horizons({tid: s["ice"] for tid, s in scored.items()})
    for tid, s in scored.items():
        conn.execute(
            """insert into roadmap_items (campaign_id, theme_id, title, description, horizon, impact_score, confidence_score, ease_score)
               values (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (campaign_id, tid, s["plan"]["title"], s["plan"]["plan"], horizon[tid], s["impact"], s["confidence"], s["ease"]),
        )
    return len(scored)
