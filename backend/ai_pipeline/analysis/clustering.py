"""Decide which theme a new pain point belongs to.

Clear cases are settled in code from the similarity to the nearest themed pain point: at or above
`join` it joins that theme, below `new` it starts a new one. In between, an LLM agent chooses with
tool calls (search other themes, append, create), for at most `max_steps` turns. Every step is
traced. If the agent runs out of steps or every provider fails, a plain similarity rule decides.

Nothing here touches the database: the caller passes in how to search and how to call the model.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Callable

from ai_pipeline.providers import AllProvidersFailed, Completion

logger = logging.getLogger("synapsed.clustering")

MAX_LABEL_CHARS = 80
MAX_EXAMPLES = 3

TOOLS = [
    {"type": "function", "function": {
        "name": "search_existing_clusters",
        "description": "Look for existing themes that match a short description. Use it when none of the "
                       "candidates fits and you want to check for another theme before creating one.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "append_pain_point",
        "description": "Add the new pain point to an existing theme because it describes the same underlying problem.",
        "parameters": {"type": "object", "properties": {"theme_id": {"type": "string"}}, "required": ["theme_id"]},
    }},
    {"type": "function", "function": {
        "name": "create_new_theme",
        "description": "Start a new theme because no existing theme describes this problem.",
        "parameters": {"type": "object", "properties": {"label": {"type": "string", "description": "2-6 words, English"}},
                       "required": ["label"]},
    }},
]

SYSTEM_PROMPT = """You group customer pain points into themes for a product team.
You get one NEW pain point and the closest existing themes (id, label, similarity, example pain points).
Two pain points belong together only when they share the same underlying problem or need, not just the same area of the product.
- If one candidate is the same problem: call append_pain_point with its theme_id.
- If it is a different problem: call create_new_theme with a short English label (2-6 words).
- If the candidates look wrong and you want to check other themes first: call search_existing_clusters.
Always finish by calling append_pain_point or create_new_theme. Call exactly one function per turn."""

NUDGE = "Call one of the functions: append_pain_point, create_new_theme or search_existing_clusters."


@dataclass
class Candidate:
    theme_id: str
    label: str
    similarity: float
    examples: list[str] = field(default_factory=list)


@dataclass
class Decision:
    action: str  # "join" | "new"
    theme_id: str | None  # set for "join"
    label: str | None  # set for "new" when the agent named it
    method: str  # "threshold" | "agent" | "fallback"
    similarity: float | None  # to the nearest themed pain point (None when there was none)
    steps: int = 0
    note: str | None = None


ToolLlm = Callable[[list[dict], list[dict]], Completion]  # (messages, tools) -> completion
Search = Callable[[str], list[Candidate]]
Trace = Callable[..., None]


def threshold_decision(best: float | None, join: float, new: float) -> str | None:
    """"join", "new", or None when the similarity falls in the grey zone."""
    if best is None or best < new:
        return "new"
    if best >= join:
        return "join"
    return None


def fallback_decision(best: Candidate | None, join: float, new: float) -> Decision:
    """The no-LLM answer for the grey zone: join only when closer to the join line than the new line."""
    similarity = best.similarity if best else None
    if best is not None and best.similarity >= (join + new) / 2:
        return Decision("join", best.theme_id, None, "fallback", similarity)
    return Decision("new", None, None, "fallback", similarity)


def _describe(candidates: list[Candidate]) -> list[dict]:
    return [{"theme_id": c.theme_id, "label": c.label, "similarity": round(c.similarity, 3),
             "examples": c.examples[:MAX_EXAMPLES]} for c in candidates]


def _assistant_turn(completion: Completion, call) -> dict:
    """The assistant message to replay: only the one call we act on, so every call id gets a reply."""
    return {"role": "assistant", "content": completion.text or None, "tool_calls": [{
        "id": call.id, "type": "function", "function": {"name": call.name, "arguments": call.raw_arguments or "{}"},
    }]}


def decide(
    pain_point: str, candidates: list[Candidate], *, join: float, new: float, max_steps: int,
    llm: ToolLlm, search: Search, trace: Trace, on_completion: Callable[[Completion], None] | None = None,
) -> Decision:
    """Decide for one pain point. `candidates` are the nearest themes, best first."""
    best = candidates[0] if candidates else None
    similarity = best.similarity if best else None
    clear = threshold_decision(similarity, join, new)
    if clear == "join":
        return Decision("join", best.theme_id, None, "threshold", similarity)
    if clear == "new":
        return Decision("new", None, None, "threshold", similarity)

    known = {c.theme_id for c in candidates}
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps({"new_pain_point": pain_point, "candidates": _describe(candidates)})},
    ]
    for step in range(1, max_steps + 1):
        try:
            completion = llm(messages, TOOLS)
        except AllProvidersFailed as exc:
            logger.warning("Grey-zone agent unavailable: %s", exc)
            trace("decide", "error", input={"pain_point": pain_point}, output={"error": str(exc)[:300], "step": step})
            decision = fallback_decision(best, join, new)
            decision.steps, decision.note = step - 1, "no provider answered"
            return decision
        if on_completion:
            on_completion(completion)
        model = f"{completion.provider}:{completion.model}"

        if not completion.tool_calls:
            trace("decide", "done", model_used=model, input={"pain_point": pain_point},
                  output={"step": step, "note": "no tool call", "text": completion.text[:300]},
                  tokens=completion.total_tokens, latency_ms=completion.latency_ms)
            messages += [{"role": "assistant", "content": completion.text}, {"role": "user", "content": NUDGE}]
            continue

        call = completion.tool_calls[0]
        args = call.arguments
        result: dict | list
        outcome: Decision | None = None
        if call.name == "append_pain_point":
            theme_id = str(args.get("theme_id", "")).strip()
            if theme_id in known:
                outcome = Decision("join", theme_id, None, "agent", similarity, step)
                result = {"ok": True}
            else:
                result = {"error": f"unknown theme_id '{theme_id[:60]}'; use one of the ids you were given"}
        elif call.name == "create_new_theme":
            label = " ".join(str(args.get("label", "")).split())[:MAX_LABEL_CHARS]
            if label:
                outcome = Decision("new", None, label, "agent", similarity, step)
                result = {"ok": True}
            else:
                result = {"error": "label is required"}
        elif call.name == "search_existing_clusters":
            query = str(args.get("query", "")).strip()
            if query:
                found = search(query)
                known |= {c.theme_id for c in found}
                result = _describe(found)
            else:
                result = {"error": "query is required"}
        else:
            result = {"error": f"unknown function '{call.name[:40]}'"}

        trace("decide", "done", model_used=model, input={"pain_point": pain_point},
              output={"step": step, "tool": call.name, "arguments": args, "result": result if outcome is None else "decided"},
              tokens=completion.total_tokens, latency_ms=completion.latency_ms)
        if outcome:
            return outcome
        messages += [_assistant_turn(completion, call),
                     {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}]

    decision = fallback_decision(best, join, new)
    decision.steps, decision.note = max_steps, "step limit reached"
    trace("decide", "done", input={"pain_point": pain_point},
          output={"note": "step limit reached", "fallback": decision.action})
    return decision
