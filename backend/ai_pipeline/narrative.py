"""A short written summary of numbers that were computed in code.

The model gets the numbers and may only describe them. If its text contains a figure that is not in
the data (a made-up percentage, say), the whole narrative is dropped: the numbers stand on their own.
"""

import json
import logging
import re
from typing import Callable

from ai_pipeline.providers import AllProvidersFailed, Completion, parse_json_reply

logger = logging.getLogger("synapsed.narrative")

SYSTEM_PROMPT = """You explain analysis results to a product manager in 2-3 plain sentences.
You are given the results as JSON. Rules:
- Use ONLY numbers that appear in the JSON. Do not calculate new percentages or totals. Do not add outside facts.
- This is an ESTIMATE, not a fact: say so once, and mention the uncertainty (the interval, or the small amount of data) when it is given.
- Name themes and segments by their labels. In a what-if, "before" and "after" mean before and after the assumed change, not before and after any analysis.
Reply with ONLY JSON: {"narrative": "<2-3 sentences>"}"""

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
TOLERANCE = 0.051  # "4.2" in the data may be written as "4.2" or "4"; not as a different figure


def _numbers(node, out: set[float]) -> None:
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        out.add(abs(float(node)))
    elif isinstance(node, str):
        out.update(float(n) for n in _NUMBER.findall(node))
    elif isinstance(node, dict):
        for v in node.values():
            _numbers(v, out)
    elif isinstance(node, list):
        for v in node:
            _numbers(v, out)


def only_known_numbers(text: str, data) -> bool:
    """True when every figure in `text` appears in `data` (to one decimal, or as a whole number)."""
    allowed: set[float] = set()
    _numbers(data, allowed)
    for token in _NUMBER.findall(text):
        value = float(token)
        if not any(abs(value - a) <= TOLERANCE or abs(value - round(a)) < 1e-9 for a in allowed):
            return False
    return True


def narrate(
    data: dict, llm: Callable[[list[dict]], Completion], on_completion: Callable[[Completion], None] | None = None
) -> str | None:
    """The narrative, or None if the model is unavailable, unreadable, or mentions a figure that is not in the data."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": json.dumps(data, default=str)}]
    try:
        completion = llm(messages)
    except AllProvidersFailed as exc:
        logger.warning("Narrative unavailable: %s", exc)
        return None
    if on_completion:
        on_completion(completion)
    try:
        text = parse_json_reply(completion.text)["narrative"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(text, str) or not text.strip():
        return None
    text = " ".join(text.split())[:700]
    if not only_known_numbers(text, data):
        logger.warning("Narrative dropped: it contains a figure that is not in the data")
        return None
    return text
