"""The PRD agent: a product requirements document for one roadmap item, grounded in its evidence.

The model writes the prose (context, problem, goals, user stories, acceptance criteria, scope,
metrics) from numbered evidence it is given. The Evidence Traces section is NOT written by the model:
it is built from the stored citations, so every quote in a PRD is a real quote with real offsets.
"""

import json
import logging
from typing import Callable

import psycopg
from pydantic import BaseModel, Field, ValidationError, field_validator

from ai_pipeline.providers import Completion, parse_json_reply

logger = logging.getLogger("synapsed.prd")

MAX_EVIDENCE = 12

SYSTEM_PROMPT = """You are a senior product manager writing a product requirements document (PRD) for one roadmap item.
You are given the item and numbered customer EVIDENCE (pain points with the customer's own words).
Rules:
- Use ONLY the evidence. Do not invent customers, numbers, features already built, or quotes.
- Write in English, plainly and specifically. No filler.
- "user_stories": 2-6 stories. Each has "as_a" (a user type from the evidence), "i_want", "so_that", and "evidence": the evidence numbers that support it (for example [1, 3]).
- "acceptance_criteria": testable statements, each one checkable by QA.
- "out_of_scope": things this item deliberately does not cover.
- "success_metrics": how the team would know it worked (measurable where the evidence allows).

Reply with ONLY JSON:
{"title": str, "context": str, "problem": str, "goals": [str], "user_stories": [{"as_a": str, "i_want": str, "so_that": str, "evidence": [int]}],
 "acceptance_criteria": [str], "out_of_scope": [str], "success_metrics": [str]}"""

RETRY_NOTE = "Your last reply did not match the required JSON shape ({problem}). Reply again with ONLY the corrected JSON object."


class UserStory(BaseModel):
    as_a: str = Field(min_length=2, max_length=200)
    i_want: str = Field(min_length=2, max_length=400)
    so_that: str = Field(min_length=2, max_length=400)
    evidence: list[int] = Field(default_factory=list, max_length=12)


class PrdContent(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    context: str = Field(min_length=10, max_length=2000)
    problem: str = Field(min_length=10, max_length=2000)
    goals: list[str] = Field(min_length=1, max_length=6)
    user_stories: list[UserStory] = Field(min_length=1, max_length=8)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=10)
    out_of_scope: list[str] = Field(default_factory=list, max_length=6)
    success_metrics: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("goals", "acceptance_criteria", "out_of_scope", "success_metrics")
    @classmethod
    def clean_lines(cls, lines: list[str]) -> list[str]:
        cleaned = [" ".join(str(line).split())[:400] for line in lines if str(line).strip()]
        return cleaned


EVIDENCE_SQL = """
    select * from (
        select distinct on (i.id) i.id as insight_id, i.summary_text as summary, i.severity, i.sentiment,
               s.name as segment, coalesce(s.weight, 1) as weight, c.text_snippet as quote, c.resource_id,
               r.title as resource_title, c.start_offset, c.end_offset
        from insights i
        join citations c on c.insight_id = i.id
        join resources r on r.id = c.resource_id
        left join segments s on s.id = i.segment_id
        where i.theme_id = %(theme)s
        order by i.id, c.start_offset
    ) e order by e.severity * e.weight desc, e.summary limit %(n)s
"""


def gather_evidence(conn: psycopg.Connection, theme_id, limit: int = MAX_EVIDENCE) -> list[dict]:
    """The theme's strongest insights, one real quote each, numbered from 1."""
    rows = conn.execute(EVIDENCE_SQL, {"theme": theme_id, "n": limit}).fetchall()
    return [
        {"n": n, "insight_id": str(r["insight_id"]), "summary": r["summary"], "severity": r["severity"],
         "sentiment": r["sentiment"], "segment": r["segment"], "quote": r["quote"],
         "resource_id": str(r["resource_id"]), "resource_title": r["resource_title"],
         "start_offset": r["start_offset"], "end_offset": r["end_offset"]}
        for n, r in enumerate(rows, start=1)
    ]


def build_messages(item: dict, theme: dict, evidence: list[dict]) -> list[dict]:
    lines = [
        f"[{e['n']}] {e['summary']} (severity {e['severity']}/5, {e['sentiment']}"
        f"{', segment: ' + e['segment'] if e['segment'] else ''})\n    customer said: \"{e['quote']}\""
        for e in evidence
    ]
    brief = (
        f"ROADMAP ITEM: {item['title']}\nDescription: {item['description']}\n"
        f"Theme: {theme['label']} - {theme.get('description') or ''}\n"
        f"Scores: impact {item['impact_score']}/10, confidence {item['confidence_score']}/10, ease {item['ease_score']}/10, "
        f"horizon {item['horizon']}\n\nEVIDENCE:\n" + "\n".join(lines)
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": brief}]


def _problem(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        return f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}"
    return str(exc)[:150]


def generate(
    item: dict, theme: dict, evidence: list[dict], llm: Callable[[list[dict]], Completion],
    on_completion: Callable[[Completion], None] | None = None,
) -> PrdContent:
    """Ask for the PRD, validate it, and ask once more if the shape is wrong. Raises ValueError if it stays wrong."""
    messages = build_messages(item, theme, evidence)
    last: Exception | None = None
    for attempt in range(2):
        completion = llm(messages)
        if on_completion:
            on_completion(completion)
        try:
            prd = PrdContent.model_validate(parse_json_reply(completion.text))
            break
        except (ValueError, ValidationError) as exc:  # ValidationError is a ValueError too; kept explicit for clarity
            last = exc
            logger.warning("PRD reply rejected (attempt %s): %s", attempt + 1, _problem(exc))
            messages = messages + [{"role": "assistant", "content": completion.text[:3000]},
                                   {"role": "user", "content": RETRY_NOTE.format(problem=_problem(exc))}]
    else:
        raise ValueError(f"the model did not return a usable PRD: {_problem(last)}")
    valid = {e["n"] for e in evidence}
    for story in prd.user_stories:  # references to evidence that was not given are dropped
        story.evidence = sorted({n for n in story.evidence if n in valid})
    return prd


def render_markdown(prd: PrdContent, evidence: list[dict], item: dict) -> str:
    """The PRD as Markdown. The evidence section comes from stored citations, not from the model."""
    def bullets(lines: list[str], mark: str = "-") -> str:
        return "\n".join(f"{mark} {line}" for line in lines)

    stories = "\n".join(
        f"- As a **{s.as_a}**, I want {s.i_want}, so that {s.so_that}."
        + (f" _({', '.join(f'E{n}' for n in s.evidence)})_" if s.evidence else "")
        for s in prd.user_stories
    )
    traces = "\n\n".join(
        f"**E{e['n']}** · {e['summary']} · severity {e['severity']}/5"
        f"{' · ' + e['segment'] if e['segment'] else ''}\n> {e['quote']}\n> — {e['resource_title']}, characters {e['start_offset']}–{e['end_offset']}"
        for e in evidence
    )
    parts = [
        f"# {prd.title}",
        f"_Roadmap: {item['horizon'].title()} · Impact {item['impact_score']}/10 · Confidence {item['confidence_score']}/10 · "
        f"Ease {item['ease_score']}/10 · ICE {item['ice_score']}_",
        f"## Context\n{prd.context}",
        f"## Problem\n{prd.problem}",
        f"## Goals\n{bullets(prd.goals)}",
        f"## User stories\n{stories}",
        f"## Acceptance criteria\n{bullets(prd.acceptance_criteria, '- [ ]')}",
        f"## Out of scope\n{bullets(prd.out_of_scope) if prd.out_of_scope else '- Nothing explicitly excluded.'}",
        f"## Success metrics\n{bullets(prd.success_metrics) if prd.success_metrics else '- To be defined with the team.'}",
        f"## Evidence traces\n{traces}",
    ]
    return "\n\n".join(parts) + "\n"


def to_stored(prd: PrdContent, evidence: list[dict]) -> dict:
    return {"prd": json.loads(prd.model_dump_json()), "evidence": evidence}
