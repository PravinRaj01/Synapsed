"""Insights Studio: charts from a validated spec, and a prompt-to-spec translator.

The model never writes SQL or code. It picks values from fixed lists (a chart type, a dimension, a
measure, filters); `run_chart` turns a validated spec into a query made only of fixed fragments, and the
filter values travel as parameters. Anything outside the lists fails validation.
"""

import logging
from decimal import Decimal
from typing import Callable, Literal

import psycopg
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from ai_pipeline.providers import Completion, parse_json_reply

logger = logging.getLogger("synapsed.charts")

ChartType = Literal["bar", "stacked_bar", "pie", "line"]
Dimension = Literal["theme", "segment", "sentiment", "use_case", "kind", "severity", "source_type", "language", "week"]
FilterField = Literal["theme", "segment", "sentiment", "use_case", "kind", "severity", "source_type", "language"]
Measure = Literal["insights", "impact", "avg_severity", "resources"]

MEASURE_LABELS = {
    "insights": "Pain points and requests", "impact": "Business Impact (weight x severity)",
    "avg_severity": "Average severity (1-5)", "resources": "Distinct sources",
}
MAX_SERIES = 8
MAX_ROWS = 2000

# Fixed SQL fragments: the only text that ever reaches the query besides parameters.
DIMENSION_SQL = {
    "theme": "coalesce(t.label, 'Unthemed')",
    "segment": "coalesce(s.name, 'No segment')",
    "sentiment": "i.sentiment",
    "use_case": "coalesce(nullif(i.use_case, ''), 'Unspecified')",
    "kind": "i.kind",
    "severity": "i.severity::text",
    "source_type": "coalesce(src.source_type, 'unknown')",
    "language": "coalesce(src.language, 'unknown')",
    "week": "to_char(date_trunc('week', i.created_at at time zone 'utc'), 'YYYY-MM-DD')",
}
MEASURE_SQL = {
    "insights": "count(*)",
    "impact": "round(sum(coalesce(s.weight, 1) * i.severity)::numeric, 1)",
    "avg_severity": "round(avg(i.severity)::numeric, 2)",
    "resources": "count(distinct src.resource_id)",
}
NATURAL_ORDER = {"week", "severity"}  # these read left to right, not by size

QUERY = """
    select {x} as x, {split} as split, {measure} as value
    from insights i
    left join themes t on t.id = i.theme_id
    left join segments s on s.id = i.segment_id
    left join lateral (
        select r.id as resource_id, r.source_type, r.language
        from citations c join resources r on r.id = c.resource_id
        where c.insight_id = i.id order by c.start_offset limit 1
    ) src on true
    where i.campaign_id = %(campaign)s {filters}
    group by 1, 2
    limit {max_rows}
"""


class ChartFilter(BaseModel):
    field: FilterField
    values: list[str] = Field(min_length=1, max_length=10)

    @field_validator("values")
    @classmethod
    def clean(cls, values: list[str]) -> list[str]:
        cleaned = [" ".join(str(v).split())[:100].lower() for v in values if str(v).strip()]
        if not cleaned:
            raise ValueError("a filter needs at least one value")
        return cleaned


class ChartSpec(BaseModel):
    type: ChartType = "bar"
    x: Dimension
    y: Measure = "insights"
    split_by: Dimension | None = None
    filters: list[ChartFilter] = Field(default_factory=list, max_length=5)
    limit: int = Field(12, ge=1, le=30)
    title: str | None = Field(None, max_length=120)

    @model_validator(mode="after")
    def consistent(self) -> "ChartSpec":
        if self.split_by == self.x:
            raise ValueError("split_by must differ from x")
        if self.type == "stacked_bar" and self.split_by is None:
            raise ValueError("a stacked bar needs split_by")
        if self.type == "pie":
            self.split_by = None  # a pie shows one measure across one dimension
        return self


PRESETS: list[tuple[str, ChartSpec]] = [
    ("top_themes", ChartSpec(type="bar", x="theme", y="impact", title="Themes by Business Impact")),
    ("sentiment_by_segment", ChartSpec(type="stacked_bar", x="segment", split_by="sentiment", title="Sentiment by customer segment")),
    ("kinds_by_segment", ChartSpec(type="stacked_bar", x="segment", split_by="kind", title="Pain points vs feature requests by segment")),
    ("over_time", ChartSpec(type="line", x="week", title="New insights per week", limit=30)),
    ("severity", ChartSpec(type="bar", x="severity", title="How severe are the problems?")),
    ("sources", ChartSpec(type="pie", x="source_type", y="resources", title="Where the feedback comes from")),
    ("use_cases", ChartSpec(type="bar", x="use_case", title="Top use cases")),
]


def _number(value) -> float | int:
    return float(value) if isinstance(value, Decimal) else value


def run_chart(conn: psycopg.Connection, campaign_id, spec: ChartSpec) -> dict:
    """Execute a validated spec. Returns {"x": [labels], "series": [{"name", "values"}], "measure": label}."""
    params: dict = {"campaign": campaign_id}
    clauses = []
    for n, flt in enumerate(spec.filters):
        params[f"f{n}"] = flt.values
        clauses.append(f"and lower({DIMENSION_SQL[flt.field]}) = any(%(f{n})s)")
    sql = QUERY.format(
        x=DIMENSION_SQL[spec.x], split=DIMENSION_SQL[spec.split_by] if spec.split_by else "null::text",
        measure=MEASURE_SQL[spec.y], filters=" ".join(clauses), max_rows=MAX_ROWS,
    )
    rows = conn.execute(sql, params).fetchall()

    totals: dict[str, float] = {}
    for r in rows:
        totals[r["x"]] = totals.get(r["x"], 0) + float(r["value"] or 0)
    order = sorted(totals) if spec.x in NATURAL_ORDER else sorted(totals, key=lambda k: (-totals[k], k))
    labels = order[-spec.limit:] if spec.x == "week" else order[: spec.limit]  # time charts keep the latest weeks

    if spec.split_by is None:
        values = {r["x"]: _number(r["value"]) for r in rows}
        return {"x": labels, "series": [{"name": MEASURE_LABELS[spec.y], "values": [values.get(x, 0) for x in labels]}],
                "measure": MEASURE_LABELS[spec.y]}

    by_series: dict[str, dict[str, float]] = {}
    for r in rows:
        by_series.setdefault(r["split"], {})[r["x"]] = _number(r["value"])
    names = sorted(by_series, key=lambda n: (-sum(by_series[n].values()), n))[:MAX_SERIES]
    if spec.split_by in NATURAL_ORDER:
        names = sorted(names)
    return {"x": labels, "series": [{"name": n, "values": [by_series[n].get(x, 0) for x in labels]} for n in names],
            "measure": MEASURE_LABELS[spec.y]}


# ---------------------------------------------------------------- prompt to spec

SYSTEM_PROMPT = """You turn a product manager's request into a chart specification for customer-feedback data.
Reply with ONLY a JSON object, chosen from these fixed options (anything else is rejected):
- "type": "bar" | "stacked_bar" | "pie" | "line"
- "x": what to group by: "theme" | "segment" | "sentiment" | "use_case" | "kind" (pain_point or feature_request) | "severity" (1-5) | "source_type" | "language" | "week"
- "y": what to measure: "insights" (count of pain points and requests) | "impact" (Business Impact: customer weight x severity) | "avg_severity" | "resources" (distinct sources)
- "split_by": optional, same options as "x" but different from it; required for "stacked_bar"
- "filters": optional list of {"field": theme|segment|sentiment|use_case|kind|severity|source_type|language, "values": [..]}; use the exact names listed below when the request names a theme or segment; sentiment is positive|neutral|negative
- "limit": optional number of groups, 1-30
- "title": a short chart title
Use "week" with "line" for trends over time. Use "pie" only for shares of a whole. "Negative sentiment by segment as a stacked bar" means x=segment, split_by=sentiment, and you may filter sentiment if the request asks for only one.
If the request cannot be answered from this data, reply {"error": "<one short sentence saying why>"}."""

RETRY_NOTE = "That was not a valid chart specification ({problem}). Reply again with ONLY the corrected JSON object."


class ChartRefused(ValueError):
    """The request cannot be charted from this data; the message is safe to show the user."""


def build_messages(prompt: str, themes: list[str], segments: list[str]) -> list[dict]:
    context = f"Themes in this campaign: {', '.join(themes[:30]) or 'none yet'}\nCustomer segments: {', '.join(segments[:20]) or 'none'}"
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": f"{context}\n\nRequest: {prompt}"}]


def _problem(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        return f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}"
    return str(exc)[:150]


def spec_from_prompt(
    prompt: str, themes: list[str], segments: list[str], llm: Callable[[list[dict]], Completion],
    on_completion: Callable[[Completion], None] | None = None,
) -> ChartSpec:
    """Ask the model for a spec and validate it, asking once more if it is invalid.

    Raises ChartRefused when the model says the request cannot be charted or never produces a valid spec.
    """
    messages = build_messages(prompt, themes, segments)
    last: Exception | None = None
    for attempt in range(2):
        completion = llm(messages)
        if on_completion:
            on_completion(completion)
        try:
            data = parse_json_reply(completion.text)
            if isinstance(data, dict) and isinstance(data.get("error"), str) and "x" not in data:
                raise ChartRefused(data["error"][:200])
            return ChartSpec.model_validate(data)
        except ChartRefused:
            raise
        except (ValueError, ValidationError) as exc:
            last = exc
            logger.warning("Chart spec rejected (attempt %s): %s", attempt + 1, _problem(exc))
            messages = messages + [{"role": "assistant", "content": completion.text[:2000]},
                                   {"role": "user", "content": RETRY_NOTE.format(problem=_problem(exc))}]
    raise ChartRefused(f"I could not turn that into a chart ({_problem(last)}). Try rephrasing it.")


# ---------------------------------------------------------------- opportunity matrix

IMPACT_LINE = 50.0
QUADRANTS = {
    (True, True): ("priority", "Frequent and high impact"),
    (True, False): ("high_stakes", "High impact, mentioned less often"),
    (False, True): ("common_annoyance", "Frequent, lower impact"),
    (False, False): ("monitor", "Lower impact, less frequent"),
}


def opportunity_matrix(themes: list[dict]) -> dict:
    """Impact against frequency for each theme. The frequency line is the median, so the split adapts to the data."""
    frequencies = sorted(t["frequency"] for t in themes)
    median = frequencies[len(frequencies) // 2] if frequencies else 0
    frequency_line = max(median, 1)
    points = []
    for t in themes:
        impact = float(t["business_impact"])
        key, label = QUADRANTS[(impact >= IMPACT_LINE, t["frequency"] >= frequency_line and t["frequency"] > 0)]
        points.append({
            "theme_id": t["id"], "label": t["label"], "color": t["color"], "frequency": t["frequency"],
            "business_impact": impact, "ice_score": t.get("ice_score"), "horizon": t.get("horizon"),
            "quadrant": key, "quadrant_label": label,
        })
    return {"impact_line": IMPACT_LINE, "frequency_line": frequency_line, "points": points,
            "quadrants": [{"key": k, "label": lbl} for k, lbl in QUADRANTS.values()]}
