"""Find a model's quote inside the source text.

Models copy quotes verbatim only 75-100% of the time (measured), and citations must
point at the exact words, so every quote is located in the stored text and the match
gives the offsets. A quote that cannot be found is dropped, never trusted.
"""

from dataclasses import dataclass

MIN_QUOTE_CHARS = 8
_EDGE = " \t\r\n\"'“”‘’`"
_UNIFY = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


@dataclass(frozen=True)
class QuoteMatch:
    start: int
    end: int
    exact: bool  # False when only whitespace, case or quote-style differences were forgiven


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
    and quote/dash style. None when it is too short to be meaningful or cannot be found."""
    quote = quote.strip(_EDGE)
    if len(quote) < MIN_QUOTE_CHARS:
        return None
    position = text.find(quote)
    if position != -1:
        return QuoteMatch(position, position + len(quote), True)

    normalized_text, origin = _normalize(text)
    normalized_quote, _ = _normalize(quote)
    normalized_quote = normalized_quote.strip()
    if len(normalized_quote) < MIN_QUOTE_CHARS:
        return None
    position = normalized_text.find(normalized_quote)
    if position == -1:
        return None
    start = origin[position]
    end = origin[position + len(normalized_quote) - 1] + 1
    return QuoteMatch(start, end, False)
