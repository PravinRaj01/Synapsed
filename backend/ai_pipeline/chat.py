"""Grounded chat: answer only from the retrieved sources, cite them, and refuse otherwise.

The model is asked for JSON: an answer with [n] markers and, for each source it cites, a quote copied
from that source. Nothing it says is trusted blindly:
- a marker that does not match a source number is removed;
- an answer is grounded if it keeps a valid marker, or if at least one of the quotes the model listed is really
  found in its source (small models often list good quotes but forget the inline markers; the markers are then
  added at the end). An answer with neither is treated as a refusal;
- each quote is located in the source text, and a citation points at the exact words only when the
  quote was really found (otherwise it points at the whole retrieved passage and says so).
"""

import re
from dataclasses import dataclass, field

from ai_pipeline.analysis.quotes import locate_quote
from ai_pipeline.providers import parse_json_reply
from ai_pipeline.retrieval import Hit

MAX_HISTORY_TURNS = 6
MAX_TURN_CHARS = 1500
MAX_SNIPPET = 300
REFUSAL = "I could not find this in your approved sources."

SYSTEM_PROMPT = """You answer questions about customer research using ONLY the numbered sources provided.
Rules:
- Use only facts stated in the sources. If the sources do not answer the question, set "answer" to null. Never guess or use outside knowledge.
- Put the source number in square brackets right after each claim, for example [1] or [2][3]. Use only the numbers given.
- Answer in the language of the QUESTION, even when the sources are in another language (for example an English question about Malay interviews gets an English answer). Be concise. Quotes stay in their original language.
- If the question asks for a judgement the sources do not contain (for example whether a product will solve a problem), do not give one. Say what customers actually said and wanted, and state that they did not evaluate it.
- For every source you cite, add an entry to "sources" with "n" and a "quote": one short stretch (a sentence or two, under 200 characters) copied EXACTLY from that source, character for character, supporting your claim. Spoken transcripts have no punctuation and may look garbled: still copy one short stretch exactly as written, never use "..." or join separate parts, never tidy the words.
- Text such as <PERSON> marks a removed personal name; never invent names.
Reply with ONLY JSON: {"answer": string or null, "sources": [{"n": 1, "quote": "..."}]}"""

RETRY_NOTE = (
    "Some of your quotes were not found exactly in the sources. Reply again in the same JSON format. Each quote must be one "
    "short stretch (under 200 characters) copied character for character, with no \"...\" and no tidying of the words."
)

_MARKER = re.compile(r"\[(\d+)\]")


@dataclass
class Citation:
    n: int
    resource_id: str
    resource_title: str
    chunk_id: str
    start_offset: int
    end_offset: int
    snippet: str
    verified: bool  # the offsets point at the quoted words, not just the retrieved passage


@dataclass
class ChatResult:
    answer: str | None
    citations: list[Citation] = field(default_factory=list)
    reason: str | None = None  # why it refused

    @property
    def refused(self) -> bool:
        return self.answer is None


def build_messages(question: str, hits: list[Hit], history: list[dict] | None = None) -> list[dict]:
    """System prompt, recent turns, then the numbered sources and the question."""
    sources = "\n\n".join(f"[{n}] ({hit.resource_title})\n{hit.content}" for n, hit in enumerate(hits, start=1))
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    usable = [t for t in (history or []) if t.get("role") in ("user", "assistant") and str(t.get("content", "")).strip()]
    for turn in usable[-MAX_HISTORY_TURNS:]:
        messages.append({"role": turn["role"], "content": str(turn["content"])[:MAX_TURN_CHARS]})
    messages.append({"role": "user", "content": f"SOURCES:\n{sources}\n\nReply in the language of the question, not the language of the sources.\nQUESTION: {question}"})
    return messages


def _citation(n: int, hit: Hit, quote: str | None) -> Citation:
    match = locate_quote(hit.content, quote) if quote else None
    if match:
        return Citation(n, str(hit.resource_id), hit.resource_title, str(hit.chunk_id),
                        hit.start_offset + match.start, hit.start_offset + match.end,
                        hit.content[match.start : match.end], True)
    return Citation(n, str(hit.resource_id), hit.resource_title, str(hit.chunk_id),
                    hit.start_offset, hit.end_offset, hit.content[:MAX_SNIPPET], False)


def parse_answer(reply: str, hits: list[Hit]) -> ChatResult:
    """Turn the model's reply into a checked answer, or a refusal."""
    try:
        data = parse_json_reply(reply)
    except ValueError:
        return ChatResult(None, reason="unreadable_reply")
    if not isinstance(data, dict):
        return ChatResult(None, reason="unreadable_reply")
    answer = data.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return ChatResult(None, reason="not_in_sources")

    valid = set(range(1, len(hits) + 1))
    answer = _MARKER.sub(lambda m: m.group(0) if int(m.group(1)) in valid else "", answer)
    answer = re.sub(r"[ \t]{2,}", " ", answer).strip()
    quotes = {}
    for entry in data.get("sources") or []:
        if isinstance(entry, dict) and isinstance(entry.get("quote"), str):
            try:
                quotes.setdefault(int(entry.get("n")), entry["quote"])
            except (TypeError, ValueError):
                continue

    cited = sorted({int(n) for n in _MARKER.findall(answer)})
    if not cited:
        cited = sorted(n for n, quote in quotes.items() if n in valid and locate_quote(hits[n - 1].content, quote))
        if not cited:
            return ChatResult(None, reason="ungrounded")
        answer = f"{answer} {''.join(f'[{n}]' for n in cited)}"
    return ChatResult(answer, [_citation(n, hits[n - 1], quotes.get(n)) for n in cited])
