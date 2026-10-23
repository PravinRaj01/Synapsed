"""Local name detectors for Malay and Tamil text (they run on our server, so raw text never
leaves it before scrubbing). Models load lazily on first use and are cached.

- Malay/Indonesian: mesolitica/ner-t5-small-standard-bahasa-cased, a small token classifier.
  It was trained on standard written Malay, so colloquial speech may be missed, and its
  "person" tag also catches some food words ("nasi lemak").
- Tamil: Lokeshwaran/xlm-roberta-base-fintuned-panx-ta-hi (MIT), a community model. It splits
  names across sub-words (handled by expanding to whole words) and does not see Latin-script
  names inside Tamil text.

Both are detectors of names only; the callers keep a review notice on their results.
"""

import re
from functools import lru_cache
from typing import Callable, Iterator

from app.core.config import get_settings

# Malaya's tag order is OTHER, law, location, organization, person, quantity, time, event.
# The model's config only has LABEL_0..LABEL_7; id 4 = person was verified on real text.
MALAY_PERSON_LABEL_ID = 4
MALAY_LANGUAGES = {"ms", "id"}  # langdetect answers "id" for most Malay
MALAY_WINDOW_WORDS = 120
TAMIL_WINDOW_CHARS = 800

Span = tuple[int, int]
_WORD = re.compile(r"\S+")
_EDGE_PUNCT = ".,;:!?()[]{}\"'“”‘’…"


@lru_cache
def _malay():
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    name = get_settings().pii_malay_model
    return AutoTokenizer.from_pretrained(name), AutoModelForTokenClassification.from_pretrained(name).eval()


@lru_cache
def _tamil():
    from transformers import pipeline

    return pipeline(
        "token-classification", model=get_settings().pii_tamil_model, aggregation_strategy="simple"
    )


def _trim(text: str, start: int, end: int) -> Span | None:
    """Drop punctuation at both edges of a span; None if nothing is left."""
    while start < end and text[start] in _EDGE_PUNCT:
        start += 1
    while end > start and text[end - 1] in _EDGE_PUNCT:
        end -= 1
    return (start, end) if end > start else None


def merge_spans(text: str, spans: list[Span]) -> list[Span]:
    """Trim punctuation, then join spans that overlap or are separated only by whitespace
    or a comma, so "Encik Lim" or "Siti Aminah" becomes a single name."""
    trimmed = sorted(s for s in (_trim(text, a, b) for a, b in spans) if s)
    merged: list[Span] = []
    for start, end in trimmed:
        if merged and not text[merged[-1][1] : start].strip(" \t\r\n,"):
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def expand_to_words(text: str, spans: list[Span]) -> list[Span]:
    """Grow each span to the whole whitespace-delimited word at both ends."""
    grown = []
    for start, end in spans:
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        while end < len(text) and not text[end].isspace():
            end += 1
        grown.append((start, end))
    return grown


def redact_spans(text: str, spans: list[Span], token: str = "<PERSON>") -> tuple[str, int]:
    """Replace each span with a token. Returns the new text and how many spans were replaced."""
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + token + text[end:]
    return text, len(spans)


def windows(text: str, size: int) -> Iterator[tuple[int, str]]:
    """(offset, piece) pieces of at most `size` characters, cut at whitespace where possible."""
    pos = 0
    while pos < len(text):
        end = min(pos + size, len(text))
        if end < len(text):
            cut = text.rfind(" ", pos + size // 2, end)
            end = cut + 1 if cut != -1 else end
        yield pos, text[pos:end]
        pos = end


def malay_person_spans(text: str) -> list[Span]:
    import torch

    tokenizer, model = _malay()
    words = [(m.start(), m.end()) for m in _WORD.finditer(text)]
    flagged: list[Span] = []
    for first in range(0, len(words), MALAY_WINDOW_WORDS):
        window = words[first : first + MALAY_WINDOW_WORDS]
        encoded = tokenizer(
            [text[s:e] for s, e in window], is_split_into_words=True, return_tensors="pt",
            truncation=True, max_length=512,
        )
        with torch.no_grad():
            labels = model(**encoded).logits[0].argmax(-1).tolist()
        seen: set[int] = set()
        for index, word_id in enumerate(encoded.word_ids()):
            if word_id is None or word_id in seen:
                continue
            seen.add(word_id)  # a word's label comes from its first sub-word
            if labels[index] == MALAY_PERSON_LABEL_ID:
                flagged.append(window[word_id])
    return merge_spans(text, flagged)


def tamil_person_spans(text: str) -> list[Span]:
    ner = _tamil()
    found: list[Span] = []
    for offset, piece in windows(text, TAMIL_WINDOW_CHARS):
        for entity in ner(piece):
            if entity["entity_group"] == "PER":
                found.append((offset + entity["start"], offset + entity["end"]))
    return merge_spans(text, expand_to_words(text, found))


def detector_for(language: str | None) -> tuple[str, Callable[[str], list[Span]]] | None:
    """(label, function) for a language, or None when it has no model or the model is disabled."""
    settings = get_settings()
    if language in MALAY_LANGUAGES and settings.pii_malay_model:
        return "Malay", malay_person_spans
    if language == "ta" and settings.pii_tamil_model:
        return "Tamil", tamil_person_spans
    return None


def warm_up() -> None:
    """Load the enabled models now, so the first upload does not wait for them."""
    for language in ("ms", "ta"):
        found = detector_for(language)
        if found:
            found[1]("Ahmad" if language == "ms" else "ராஜேஷ்")
