"""Find a model's quote inside the source text.

Models copy quotes verbatim only 75-100% of the time (measured), and citations must
point at the exact words, so every quote is located in the stored text and the match
gives the offsets. A quote that cannot be found is dropped, never trusted.
"""

import re
from dataclasses import dataclass

MIN_QUOTE_CHARS = 8
_EDGE = " \t\r\n\"'“”‘’`"
_ELLIPSIS = re.compile(r"\s*(?:\.{3,}|…)\s*")  # models shorten long quotes with "..."
_UNIFY = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


@dataclass(frozen=True)
class QuoteMatch:
    start: int
    end: int
    exact: bool  # False when only whitespace, case or quote-style differences were forgiven


def _normalized_floor(origin: list[int], floor: int) -> int:
    """The first normalised index that comes from original index `floor` or later."""
    return next((i for i, o in enumerate(origin) if o >= floor), len(origin))


def _normalize(text: str) -> tuple[str, list[int]]:
    """Casefold, unify quotes and dashes, collapse whitespace.

    Returns the normalised text and, for each of its characters, the index of the
    original character it came from.
    """
    out: list[str] = []
    origin: list[int] = []
    pending_space = False
    for i, char in enumerate(text):
        char = char.translate(_UNIFY)
        if char.isspace():
            pending_space = bool(out)  # leading whitespace is dropped
            if pending_space:
                space_at = i
            continue
        if pending_space:
            out.append(" ")
            origin.append(space_at)
            pending_space = False
        for piece in char.casefold():
            out.append(piece)
            origin.append(i)
    return "".join(out), origin


def locate_quote(text: str, quote: str) -> QuoteMatch | None:
    """Offsets of `quote` in `text`: an exact match, else one that ignores case, whitespace
    and quote/dash style. None when it is too short to be meaningful or cannot be found.

    A quote shortened with "..." is accepted only if every piece is found, in order; the match is the first piece."""
    match = _locate(text, quote)
    if match is not None or not _ELLIPSIS.search(quote):
        return match
    pieces = [p for p in _ELLIPSIS.split(quote) if p.strip(_EDGE)]
    first, floor = None, 0
    for piece in pieces:
        found = _locate(text, piece, floor)
        if found is None:
            return None
        first, floor = first or found, found.end
    return first


def _locate(text: str, quote: str, floor: int = 0) -> QuoteMatch | None:
    quote = quote.strip(_EDGE)
    if len(quote) < MIN_QUOTE_CHARS:
        return None
    position = text.find(quote, floor)
    if position != -1:
        return QuoteMatch(position, position + len(quote), True)

    normalized_text, origin = _normalize(text)
    normalized_quote, _ = _normalize(quote)
    normalized_quote = normalized_quote.strip()
    if len(normalized_quote) < MIN_QUOTE_CHARS:
        return None
    position = normalized_text.find(normalized_quote, _normalized_floor(origin, floor))
    if position == -1:
        return None
    start = origin[position]
    end = origin[position + len(normalized_quote) - 1] + 1
    return QuoteMatch(start, end, False)
