"""Persona profiles, one per customer segment, written from that segment's own evidence.

The model writes an archetype (never an invented person), goals, frustrations and behaviours from numbered
evidence. The quotes on a persona card are NOT written by the model: it only picks evidence numbers, and the
real quotes (with their source and offsets) are attached in code.
"""

import logging
from typing import Callable

import psycopg
from pydantic import BaseModel, Field, ValidationError, field_validator

from ai_pipeline.providers import Completion, parse_json_reply

logger = logging.getLogger("synapsed.personas")

MAX_EVIDENCE = 10
MIN_INSIGHTS = 2  # fewer than this and a persona would be a guess
MAX_QUOTES = 3

SYSTEM_PROMPT = """You write a persona profile for one customer segment of a software product, from customer research evidence.
You get the segment and numbered EVIDENCE (pain points with the customer's own words).
Rules:
- Base everything on the evidence. Do not invent demographics (age, gender, location, company size) or facts that are not in it.
- "name" is an ARCHETYPE such as "The Month-End Reporter": 2-5 words, describing what this group does or needs. Never a person's name.
- "description": 2-3 sentences on who they are and what they are trying to get done, written in the third person, with no personal names.
- "goals", "frustrations", "behaviours", "typical_use_cases": short phrases (at most 5 each); "frustrations" must come from the evidence.
- "quote_refs": up to 3 evidence numbers whose quotes best represent this group.
Reply with ONLY JSON:
{"name": str, "description": str, "goals": [str], "frustrations": [str], "behaviours": [str], "typical_use_cases": [str], "quote_refs": [int]}"""

RETRY_NOTE = "Your last reply did not match the required JSON shape ({problem}). Reply again with ONLY the corrected JSON object."


class PersonaContent(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    description: str = Field(min_length=20, max_length=700)
    goals: list[str] = Field(min_length=1, max_length=5)
    frustrations: list[str] = Field(min_length=1, max_length=5)
    behaviours: list[str] = Field(default_factory=list, max_length=5)
    typical_use_cases: list[str] = Field(default_factory=list, max_length=5)
    quote_refs: list[int] = Field(default_factory=list, max_length=6)

    @field_validator("goals", "frustrations", "behaviours", "typical_use_cases")
    @classmethod
    def clean_lines(cls, lines: list[str]) -> list[str]:
        return [" ".join(str(line).split())[:200] for line in lines if str(line).strip()]


EVIDENCE_SQL = """
    select * from (
        select distinct on (i.id) i.summary_text as summary, i.severity, i.sentiment, i.use_case,
               t.label as theme, c.text_snippet as quote, c.resource_id, r.title as resource_title,
               c.start_offset, c.end_offset
        from insights i
        join citations c on c.insight_id = i.id
        join resources r on r.id = c.resource_id
        left join themes t on t.id = i.theme_id
        where i.segment_id = %(segment)s
        order by i.id, c.start_offset
    ) e order by e.severity desc, e.summary limit %(n)s
"""


def count_insights(conn: psycopg.Connection, segment_id) -> int:
    return conn.execute("select count(*) as n from insights where segment_id = %s", (segment_id,)).fetchone()["n"]


def gather_evidence(conn: psycopg.Connection, segment_id, limit: int = MAX_EVIDENCE) -> list[dict]:
    rows = conn.execute(EVIDENCE_SQL, {"segment": segment_id, "n": limit}).fetchall()
    return [
        {"n": n, "summary": r["summary"], "severity": r["severity"], "sentiment": r["sentiment"], "use_case": r["use_case"],
         "theme": r["theme"], "quote": r["quote"], "resource_id": str(r["resource_id"]), "resource_title": r["resource_title"],
         "start_offset": r["start_offset"], "end_offset": r["end_offset"]}
        for n, r in enumerate(rows, start=1)
    ]


def build_messages(segment: dict, evidence: list[dict]) -> list[dict]:
    lines = [
        f"[{e['n']}] {e['summary']} (severity {e['severity']}/5, {e['sentiment']}"
        f"{', use case: ' + e['use_case'] if e['use_case'] else ''}{', theme: ' + e['theme'] if e['theme'] else ''})\n"
        f"    customer said: \"{e['quote']}\""
        for e in evidence
    ]
    brief = (
        f"SEGMENT: {segment['name']} (tier: {segment['tier']}, weight {segment['weight']})\n"
        f"{('Description: ' + segment['description']) if segment.get('description') else ''}\n\nEVIDENCE:\n" + "\n".join(lines)
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": brief}]


def _problem(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        return f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}"
    return str(exc)[:150]


def generate(
    segment: dict, evidence: list[dict], llm: Callable[[list[dict]], Completion],
    on_completion: Callable[[Completion], None] | None = None,
) -> PersonaContent:
    """Ask for the persona, validate it, and ask once more if the shape is wrong. Raises ValueError if it stays wrong."""
    messages = build_messages(segment, evidence)
    last: Exception | None = None
    for attempt in range(2):
        completion = llm(messages)
        if on_completion:
            on_completion(completion)
        try:
            persona = PersonaContent.model_validate(parse_json_reply(completion.text))
            break
        except (ValueError, ValidationError) as exc:
            last = exc
            logger.warning("Persona reply rejected (attempt %s): %s", attempt + 1, _problem(exc))
            messages = messages + [{"role": "assistant", "content": completion.text[:2000]},
                                   {"role": "user", "content": RETRY_NOTE.format(problem=_problem(exc))}]
    else:
        raise ValueError(f"the model did not return a usable persona: {_problem(last)}")
    valid = {e["n"] for e in evidence}
    persona.quote_refs = [n for n in dict.fromkeys(persona.quote_refs) if n in valid][:MAX_QUOTES]
    return persona


def attributes(persona: PersonaContent, evidence: list[dict], insight_count: int) -> dict:
    """What is stored in personas.attributes: the model's lists plus the real quotes it picked."""
    picked = persona.quote_refs or [e["n"] for e in evidence[:MAX_QUOTES]]  # a persona without any quote is not credible
    by_number = {e["n"]: e for e in evidence}
    return {
        "generated": True, "goals": persona.goals, "frustrations": persona.frustrations,
        "behaviours": persona.behaviours, "typical_use_cases": persona.typical_use_cases,
        "quotes": [{k: by_number[n][k] for k in ("quote", "summary", "resource_id", "resource_title", "start_offset", "end_offset")}
                   for n in picked[:MAX_QUOTES]],
        "insight_count": insight_count, "evidence_used": len(evidence),
    }
