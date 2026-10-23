"""Graph nodes that turn embedded insights into themes, scores and roadmap items.

cluster -> name_themes -> score -> roadmap. Each node commits its own work, so a failure part-way
leaves valid data: an insight that could not be placed stays unthemed and is simply not counted.
"""

import json
import logging
from collections import Counter, defaultdict

from pgvector import Vector

from ai_pipeline.analysis import scoring
from ai_pipeline.analysis.clustering import Candidate, decide
from ai_pipeline.analysis.nodes import traced
from ai_pipeline.analysis.state import Deps, RunState
from ai_pipeline.providers import AllProvidersFailed, Completion, parse_json_reply
from ai_pipeline.telemetry import record_completion
from app.core.config import get_settings
from app.core.database import user_tx

logger = logging.getLogger("synapsed.themes")

THEME_COLORS = ["#6366f1", "#ec4899", "#f59e0b", "#10b981", "#06b6d4", "#8b5cf6", "#ef4444", "#84cc16", "#f97316", "#14b8a6"]
NEIGHBOURS = 12  # nearest themed pain points looked at per decision
MAX_CANDIDATES = 3
NAME_EXAMPLES = 5
MAX_LABEL = 80
MAX_DESCRIPTION = 300
DEFAULT_EASE = 5

NAMING_PROMPT = """You name themes in customer feedback for a product team. Each theme is a group of similar pain points.
For every theme give a short English "label" (2-6 words, naming the problem, no personal names) and a one-sentence English "description".
If a theme already has a suggested label that fits, keep it.
Reply with ONLY JSON: {"themes": [{"id": ..., "label": ..., "description": ...}]}"""

EASE_PROMPT = """You estimate how easy it would be for a software team to address each problem theme.
"ease" is an integer from 1 (a major redesign or long project) to 10 (a small fix). Judge only from the description; this is a rough estimate.
Reply with ONLY JSON: {"items": [{"id": ..., "ease": ...}]}"""


def _record(state: RunState, action: str):
    def hook(completion: Completion) -> None:
        try:
            with user_tx(state["user_id"]) as conn:
                record_completion(conn, state["campaign_id"], action, completion)
        except Exception:
            logger.warning("Could not record telemetry", exc_info=True)

    return hook


# ---------------------------------------------------------------- cluster

NEAREST_SQL = """
    select i.theme_id, t.label, i.summary_text, 1 - (i.embedding <=> %(vec)s) as similarity
    from insights i join themes t on t.id = i.theme_id
    where i.campaign_id = %(campaign)s and i.id <> %(self)s and i.embedding is not null
    order by i.embedding <=> %(vec)s
    limit %(n)s
"""


def _group(rows: list[dict]) -> list[Candidate]:
    """Nearest pain points -> candidate themes, best first, with a few example pain points each."""
    by_theme: dict[str, Candidate] = {}
    for row in rows:
        key = str(row["theme_id"])
        if key not in by_theme:
            by_theme[key] = Candidate(key, row["label"], float(row["similarity"]), [])
        by_theme[key].examples.append(row["summary_text"])
    return sorted(by_theme.values(), key=lambda c: -c.similarity)[:MAX_CANDIDATES]


def _nearest(conn, campaign_id: str, vector, exclude: str | None) -> list[Candidate]:
    rows = conn.execute(
        NEAREST_SQL, {"vec": vector, "campaign": campaign_id, "self": exclude, "n": NEIGHBOURS}
    ).fetchall()
    return _group(rows)


def _new_theme(conn, campaign_id: str, label: str | None) -> str:
    existing = conn.execute("select count(*) as n from themes where campaign_id = %s", (campaign_id,)).fetchone()["n"]
    return str(conn.execute(
        "insert into themes (campaign_id, label, color_code) values (%s, %s, %s) returning id",
        (campaign_id, label or "Unnamed theme", THEME_COLORS[existing % len(THEME_COLORS)]),
    ).fetchone()["id"])


@traced("cluster")
def cluster_node(state: RunState, deps: Deps) -> dict:
    """Place each new insight in a theme: by similarity in code, by the agent in the grey zone."""
    settings = get_settings()
    campaign_id, user_id = state["campaign_id"], state["user_id"]
    on_completion = _record(state, "clustering")
    new_themes: list[dict] = []
    methods: Counter = Counter()
    errors: list[dict] = []
    placed = 0

    def search(query: str) -> list[Candidate]:
        vector = Vector(deps.embed([query])[0])
        with user_tx(user_id) as conn:
            return _nearest(conn, campaign_id, vector, None)

    for insight_id in state.get("insight_ids", []):
        try:
            with user_tx(user_id) as conn:
                row = conn.execute(
                    "select summary_text, embedding from insights where id = %s", (insight_id,)
                ).fetchone()
                candidates = _nearest(conn, campaign_id, row["embedding"], insight_id)
            decision = decide(
                row["summary_text"], candidates, join=settings.cluster_join_similarity,
                new=settings.cluster_new_similarity, max_steps=settings.cluster_agent_max_steps,
                llm=deps.llm_tools, search=search, trace=deps.trace, on_completion=on_completion,
            )
            with user_tx(user_id) as conn:
                if decision.action == "join":
                    theme_id = decision.theme_id
                else:
                    theme_id = _new_theme(conn, campaign_id, decision.label)
                    new_themes.append({"id": theme_id, "label": decision.label})
                conn.execute("update insights set theme_id = %s where id = %s", (theme_id, insight_id))
            methods[decision.method] += 1
            placed += 1
        except Exception as exc:
            logger.warning("Could not place insight %s: %s", insight_id, exc)
            errors.append({"resource_id": None, "stage": "cluster", "error": f"insight {insight_id}: {str(exc)[:250]}"})
    return {"new_themes": new_themes, "themed_insights": placed, "cluster_methods": dict(methods), "errors": errors}


# ---------------------------------------------------------------- name_themes

def _fallback_label(example: str) -> str:
    words = example.split()
    return " ".join(words[:6]).rstrip(".,;:")[:MAX_LABEL] or "Unnamed theme"


@traced("name_themes")
def name_themes_node(state: RunState, deps: Deps) -> dict:
    """Name and describe the themes created in this run with one batched call."""
    themes = state.get("new_themes", [])
    if not themes:
        return {}
    with user_tx(state["user_id"]) as conn:
        payload = []
        for theme in themes:
            examples = conn.execute(
                "select summary_text from insights where theme_id = %s order by created_at limit %s",
                (theme["id"], NAME_EXAMPLES),
            ).fetchall()
            payload.append({"id": theme["id"], "suggested_label": theme["label"],
                            "pain_points": [e["summary_text"] for e in examples]})
    named: dict[str, dict] = {}
    try:
        completion = deps.llm(
            [{"role": "system", "content": NAMING_PROMPT}, {"role": "user", "content": json.dumps({"themes": payload})}], None
        )
        _record(state, "theme_naming")(completion)
        for entry in parse_json_reply(completion.text).get("themes", []):
            if isinstance(entry, dict) and str(entry.get("id")) in {t["id"] for t in themes}:
                label = " ".join(str(entry.get("label", "")).split())[:MAX_LABEL]
                if label:
                    named[str(entry["id"])] = {
                        "label": label, "description": " ".join(str(entry.get("description", "")).split())[:MAX_DESCRIPTION] or None,
                    }
    except (AllProvidersFailed, ValueError, AttributeError) as exc:
        logger.warning("Theme naming failed, using fallback labels: %s", exc)
        deps.trace("name_themes", "error", output={"error": str(exc)[:300]})
    with user_tx(state["user_id"]) as conn:
        for theme, entry in zip(themes, payload):
            result = named.get(theme["id"])
            label = (result or {}).get("label") or theme["label"] or _fallback_label(entry["pain_points"][0] if entry["pain_points"] else "")
            conn.execute(
                "update themes set label = %s, description = %s where id = %s",
                (label, (result or {}).get("description"), theme["id"]),
            )
    return {"new_themes": [{**t, "label": (named.get(t["id"]) or {}).get("label") or t["label"]} for t in themes]}


# ---------------------------------------------------------------- score

THEME_STATS_SQL = """
    select t.id,
           (select count(*) from insights i where i.theme_id = t.id) as frequency,
           coalesce((select sum(coalesce(s.weight, %(default_weight)s) * i.severity)
                     from insights i left join segments s on s.id = i.segment_id where i.theme_id = t.id), 0) as raw
    from themes t where t.campaign_id = %(campaign)s
"""


@traced("score")
def score_node(state: RunState, deps: Deps) -> dict:
    """Frequency and Business Impact for every theme in the campaign (impact is relative to the top theme)."""
    with user_tx(state["user_id"]) as conn:
        rows = conn.execute(
            THEME_STATS_SQL, {"campaign": state["campaign_id"], "default_weight": scoring.DEFAULT_SEGMENT_WEIGHT}
        ).fetchall()
        impacts = scoring.business_impacts({str(r["id"]): float(r["raw"]) for r in rows})
        for r in rows:
            conn.execute(
                "update themes set frequency = %s, business_impact = %s where id = %s",
                (r["frequency"], impacts[str(r["id"])], r["id"]),
            )
    return {"scored_themes": len(rows)}


# ---------------------------------------------------------------- roadmap

EVIDENCE_SQL = """
    select t.id, t.label, t.description, t.business_impact,
           (select count(distinct c.resource_id) from citations c join insights i on i.id = c.insight_id
             where i.theme_id = t.id) as sources,
           (select count(*) from insights i where i.theme_id = t.id) as mentions,
           (select avg(1 - (i.embedding <=> cen.v)) from insights i,
                   (select avg(embedding) as v from insights where theme_id = t.id) cen
             where i.theme_id = t.id) as cohesion
    from themes t where t.campaign_id = %s
"""


def _estimate_ease(state: RunState, deps: Deps, themes: list[dict]) -> dict[str, int]:
    """One batched call for the themes that have no roadmap item yet; failures give the default."""
    if not themes:
        return {}
    payload = [{"id": t["id"], "theme": t["label"], "description": t["description"]} for t in themes]
    try:
        completion = deps.llm(
            [{"role": "system", "content": EASE_PROMPT}, {"role": "user", "content": json.dumps({"themes": payload})}], None
        )
        _record(state, "roadmap_ease")(completion)
        eases = {}
        for entry in parse_json_reply(completion.text).get("items", []):
            try:
                eases[str(entry["id"])] = scoring.clamp_score(float(entry["ease"]))
            except (KeyError, TypeError, ValueError):
                continue
        return eases
    except (AllProvidersFailed, ValueError, AttributeError) as exc:
        logger.warning("Ease estimate failed, using %s: %s", DEFAULT_EASE, exc)
        deps.trace("roadmap", "error", output={"error": str(exc)[:300]})
        return {}


@traced("roadmap")
def roadmap_node(state: RunState, deps: Deps) -> dict:
    """One roadmap item per theme: ICE from impact, evidence and an estimated ease.

    New items are placed Now / Next / Later by tercile of ICE across the campaign. Items that already
    exist keep their horizon and ease (the PM may have moved them) and only get fresh impact and confidence.
    """
    with user_tx(state["user_id"]) as conn:
        themes = [dict(r, id=str(r["id"])) for r in conn.execute(EVIDENCE_SQL, (state["campaign_id"],)).fetchall() if r["mentions"]]
        existing = {
            str(r["theme_id"]): r
            for r in conn.execute(
                "select id, theme_id, ease_score from roadmap_items where campaign_id = %s and theme_id is not null",
                (state["campaign_id"],),
            ).fetchall()
        }
    eases = _estimate_ease(state, deps, [t for t in themes if t["id"] not in existing])

    scored: dict[str, dict] = {}
    for t in themes:
        impact = scoring.impact_score(float(t["business_impact"]))
        confidence = scoring.confidence_score(t["sources"], t["mentions"], float(t["cohesion"]) if t["cohesion"] is not None else None)
        ease = existing[t["id"]]["ease_score"] if t["id"] in existing else eases.get(t["id"], DEFAULT_EASE)
        scored[t["id"]] = {"impact": impact, "confidence": confidence, "ease": ease, "ice": scoring.ice(impact, confidence, ease)}
    horizon = scoring.horizons({tid: s["ice"] for tid, s in scored.items()})

    created = updated = 0
    with user_tx(state["user_id"]) as conn:
        for t in themes:
            s = scored[t["id"]]
            if t["id"] in existing:
                conn.execute(
                    "update roadmap_items set impact_score = %s, confidence_score = %s where id = %s",
                    (s["impact"], s["confidence"], existing[t["id"]]["id"]),
                )
                updated += 1
            else:
                conn.execute(
                    """insert into roadmap_items (campaign_id, theme_id, title, description, horizon,
                                                  impact_score, confidence_score, ease_score)
                       values (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (state["campaign_id"], t["id"], t["label"], t["description"] or t["label"], horizon[t["id"]],
                     s["impact"], s["confidence"], s["ease"]),
                )
                created += 1
    return {"roadmap_created": created, "roadmap_updated": updated}
