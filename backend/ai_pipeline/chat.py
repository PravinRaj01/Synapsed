"""Grounded chat: answer only from the retrieved sources, cite them, and refuse otherwise.

The model is asked for JSON: an answer with [n] markers and, for each source it cites, a quote copied
from that source. Nothing it says is trusted blindly:
- a marker that does not match a source number is removed;
- an answer left with no valid marker is treated as a refusal (it is not grounded);
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
- Answer in the same language as the question, concisely.
- For every source you cite, add an entry to "sources" with "n" and a "quote": 1-2 consecutive sentences copied EXACTLY from that source, at most 300 characters, supporting your claim.
- Text such as <PERSON> marks a removed personal name; never invent names.
Reply with ONLY JSON: {"answer": string or null, "sources": [{"n": 1, "quote": "..."}]}"""

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
    messages.append({"role": "user", "content": f"SOURCES:\n{sources}\n\nQUESTION: {question}"})
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
    cited = sorted({int(n) for n in _MARKER.findall(answer)})
    if not cited:
        return ChatResult(None, reason="ungrounded")

    quotes = {}
    for entry in data.get("sources") or []:
        if isinstance(entry, dict) and isinstance(entry.get("quote"), str):
            try:
                quotes.setdefault(int(entry.get("n")), entry["quote"])
            except (TypeError, ValueError):
                continue
    return ChatResult(answer, [_citation(n, hits[n - 1], quotes.get(n)) for n in cited])
