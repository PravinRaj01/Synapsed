"""Extraction agent: pain points and feature requests with verifiable quotes.

One LLM call per resource (long ones are split into overlapping windows), because the free
tiers cannot afford per-chunk calls. The model's quotes are checked against the stored text.
"""

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from ai_pipeline.analysis.quotes import locate_quote
from ai_pipeline.providers import Completion, parse_json_reply
from app.ingestion.chunking import chunk_text

logger = logging.getLogger("synapsed.extraction")

MAX_WINDOW_CHARS = 6000  # about 2,000 tokens; keeps one call well inside the free tiers
WINDOW_OVERLAP = 400
MAX_QUOTE_CHARS = 600  # longer than this is cut back to its first part (spoken text has no sentence ends)
KINDS = {"pain_point", "feature_request"}
SENTIMENTS = {"positive", "neutral", "negative"}

SYSTEM_PROMPT = """You analyse customer research (interviews, support tickets, survey answers) for a product team.
Extract what the CUSTOMER says: pain points (problems, frustrations, workarounds) and feature requests.

Rules:
- Only extract what the customer clearly states. Do not infer problems that are not stated. Ignore praise, greetings, small talk and anything the interviewer says.
- "quote": copy one or two short consecutive sentences or clauses from the text EXACTLY, character for character, in the original language, at most 300 characters. Spoken transcripts often have no punctuation: still pick one short stretch (about 200 characters) that states the problem, never a long passage. Never translate, fix or join separate parts.
- Report EVERY distinct pain point or request the customer states, one item each. A long interview usually has several; do not stop after the first.
- "pain_point": one standalone sentence IN ENGLISH describing the problem or request, understandable without the quote, with no personal names (the text contains placeholders such as <PERSON> where names were removed; never invent names).
- "use_case": a short English phrase for what the customer was trying to do (for example "monthly reporting").
- "severity": 1 (minor annoyance) to 5 (blocks their work or risks them leaving).
- "sentiment": the customer's feeling about the problem or situation they describe: negative, neutral or positive. It is not a rating of any product, unless the customer is talking about one.
- "kind": "pain_point" or "feature_request".
- If the text states nothing relevant, return {"items": []}.

Reply with ONLY JSON: {"items": [{"kind": ..., "pain_point": ..., "quote": ..., "use_case": ..., "severity": ..., "sentiment": ...}]}"""

RETRY_NOTE = "Your last reply was not valid JSON. Reply again with ONLY the JSON object described above."

LlmCall = Callable[[list[dict], str | None], Completion]


@dataclass
class Item:
    kind: str
    pain_point: str
    quote: str  # the exact text found in the source, not the model's version
    use_case: str
    severity: int
    sentiment: str
    start: int  # offsets into the full resource text
    end: int
    exact: bool  # the model's quote matched verbatim


@dataclass
class Extraction:
    items: list[Item] = field(default_factory=list)
    dropped: Counter = field(default_factory=Counter)  # reason -> count
    windows: int = 0


def build_messages(text: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"TEXT:\n{text}"},
    ]


def _clean_int(value, default: int = 3) -> int:
    try:
        return min(5, max(1, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def shorten_quote(quote: str) -> str:
    """Cut an over-long quote back to its first part, at a word boundary. The start of a verbatim quote is still verbatim."""
    quote = quote.strip()
    if len(quote) <= MAX_QUOTE_CHARS:
        return quote
    cut = quote[:MAX_QUOTE_CHARS]
    return cut.rsplit(" ", 1)[0] if " " in cut else cut


def validate_items(raw: object, window_text: str, window_start: int, dropped: Counter) -> list[Item]:
    """Turn the model's JSON into items whose quotes are verified against the window text."""
    entries = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        dropped["bad_shape"] += 1
        return []
    items: list[Item] = []
    for entry in entries:
        if not isinstance(entry, dict) or not str(entry.get("pain_point", "")).strip() or not entry.get("quote"):
            dropped["bad_shape"] += 1
            continue
        quote = shorten_quote(str(entry["quote"]))
        match = locate_quote(window_text, quote)
        if match is None:
            dropped["quote_not_found"] += 1
            continue
        kind = str(entry.get("kind", "pain_point")).strip().lower()
        sentiment = str(entry.get("sentiment", "negative")).strip().lower()
        items.append(
            Item(
                kind=kind if kind in KINDS else "pain_point",
                pain_point=str(entry["pain_point"]).strip(),
                quote=window_text[match.start : match.end],
                use_case=str(entry.get("use_case", "")).strip()[:120],
                severity=_clean_int(entry.get("severity")),
                sentiment=sentiment if sentiment in SENTIMENTS else "neutral",
                start=window_start + match.start,
                end=window_start + match.end,
                exact=match.exact,
            )
        )
    return items


def _overlaps(a: Item, b: Item) -> bool:
    shared = min(a.end, b.end) - max(a.start, b.start)
    return shared > 0.5 * min(a.end - a.start, b.end - b.start)


def merge_windows(items: list[Item]) -> list[Item]:
    """Windows overlap, so the same quote can come back twice: keep the first."""
    kept: list[Item] = []
    for item in sorted(items, key=lambda i: i.start):
        if not any(_overlaps(item, other) for other in kept):
            kept.append(item)
    return kept


def _ask(window_text: str, language: str | None, llm: LlmCall, on_completion) -> object:
    messages = build_messages(window_text)
    for attempt in range(2):
        completion = llm(messages, language)
        if on_completion:
            on_completion(completion, messages)
        try:
            return parse_json_reply(completion.text)
        except ValueError:
            logger.warning("Extraction reply from %s was not JSON (attempt %s)", completion.provider, attempt + 1)
            messages = messages + [{"role": "user", "content": RETRY_NOTE}]
    raise ValueError("the model did not return valid JSON after two tries")


def extract_resource(
    text: str, language: str | None, llm: LlmCall, on_completion: Callable[[Completion, list[dict]], None] | None = None
) -> Extraction:
    """Extract and verify items from one resource. Raises AllProvidersFailed or ValueError on failure."""
    result = Extraction()
    windows = chunk_text(text, size=MAX_WINDOW_CHARS, overlap=WINDOW_OVERLAP) if len(text) > MAX_WINDOW_CHARS else None
    pieces = [(w.start, w.content) for w in windows] if windows else [(0, text)]
    gathered: list[Item] = []
    for start, piece in pieces:
        raw = _ask(piece, language, llm, on_completion)
        gathered.extend(validate_items(raw, piece, start, result.dropped))
        result.windows += 1
    result.items = merge_windows(gathered)
    return result
