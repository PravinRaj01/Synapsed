"""PII scrubbing (the "Enterprise Shield").

Runs before text is stored or sent to any LLM. Presidio (spaCy small model) finds
names, emails and phone numbers; a regex pass then catches anything it missed, and
is also the fallback when the name detector cannot be trusted. Redactions become
tokens such as <PERSON>, so stored text and chunk offsets refer to the scrubbed text.

The name detector is an English-only model. On other languages it guesses, and it
turns ordinary words into <PERSON> (a Malay interview lost 1 word in 6), which
ruins the text for analysis. So names are only detected in English text. Anywhere
else only emails and phone numbers are scrubbed, and the result carries a notice so
the user can review the text before approving it.
"""

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

from app.core.language import detect_language

logger = logging.getLogger("synapsed.pii")
# Presidio warns on every call about spaCy labels it does not map (CARDINAL, DATE, ...).
logging.getLogger("presidio-analyzer").setLevel(logging.ERROR)

ENTITIES = ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"]
NER_LANGUAGES = {"en"}
MAX_PERSON_RATE = 0.10  # if more than 10% of the words are "names", the model is guessing
MIN_WORDS_FOR_RATE = 40
_BLOCK_CHARS = 50_000  # keep each Presidio call well under spaCy's length limit

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\w.])\+?\d[\d\-\s().]{7,}\d(?![\w])")
_DATE_LIKE = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$|^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$")


@dataclass
class ScrubResult:
    text: str
    redactions: dict[str, int] = field(default_factory=dict)
    engine: str = "presidio"  # "regex" when names were not detected
    notice: str | None = None  # set when names may remain in the text

    @property
    def total(self) -> int:
        return sum(self.redactions.values())


@lru_cache
def _engines():
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_anonymizer import AnonymizerEngine

    nlp = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }
    ).create_engine()
    analyzer = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
    return analyzer, AnonymizerEngine()


def _blocks(text: str) -> list[str]:
    """Split on line breaks into pieces of at most _BLOCK_CHARS (joined back losslessly)."""
    if len(text) <= _BLOCK_CHARS:
        return [text]
    pieces, current = [], ""
    for line in text.splitlines(keepends=True):
        if current and len(current) + len(line) > _BLOCK_CHARS:
            pieces.append(current)
            current = ""
        while len(line) > _BLOCK_CHARS:  # a single enormous line
            pieces.append(line[:_BLOCK_CHARS])
            line = line[_BLOCK_CHARS:]
        current += line
    if current:
        pieces.append(current)
    return pieces


def _presidio_scrub(text: str, counts: Counter) -> str:
    from presidio_anonymizer.entities import OperatorConfig

    analyzer, anonymizer = _engines()
    operators = {e: OperatorConfig("replace", {"new_value": f"<{e}>"}) for e in ENTITIES}
    out = []
    for block in _blocks(text):
        found = analyzer.analyze(text=block, entities=ENTITIES, language="en", score_threshold=0.5)
        counts.update(r.entity_type for r in found)
        out.append(anonymizer.anonymize(text=block, analyzer_results=found, operators=operators).text)
    return "".join(out)


def _phone_sub(counts: Counter):
    def repl(m: re.Match) -> str:
        raw = m.group(0)
        digits = sum(c.isdigit() for c in raw)
        if not 9 <= digits <= 15 or _DATE_LIKE.match(raw.strip()):
            return raw
        counts["PHONE_NUMBER"] += 1
        return "<PHONE_NUMBER>"

    return repl


def _regex_scrub(text: str, counts: Counter) -> str:
    def email(_m: re.Match) -> str:
        counts["EMAIL_ADDRESS"] += 1
        return "<EMAIL_ADDRESS>"

    text = _EMAIL.sub(email, text)
    return _PHONE.sub(_phone_sub(counts), text)


def names_look_unreliable(person_count: int, word_count: int) -> bool:
    """True when so many words were tagged as names that the detector must be guessing."""
    return word_count >= MIN_WORDS_FOR_RATE and person_count / word_count > MAX_PERSON_RATE


def _regex_only(text: str, notice: str) -> ScrubResult:
    counts: Counter = Counter()
    return ScrubResult(_regex_scrub(text, counts), dict(counts), engine="regex", notice=notice)


def scrub_pii(text: str) -> ScrubResult:
    """Redact names, emails and phone numbers. Never raises: falls back to regex only."""
    language = detect_language(text)
    if language is not None and language not in NER_LANGUAGES:
        return _regex_only(
            text,
            f"Names were not scrubbed: the text looks like '{language}' and name detection only "
            "supports English. Emails and phone numbers were scrubbed. Review before approving.",
        )

    counts: Counter = Counter()
    try:
        scrubbed = _presidio_scrub(text, counts)
    except Exception:  # model missing, spaCy error, ...
        logger.warning("Presidio unavailable; using regex-only PII scrubbing", exc_info=True)
        return _regex_only(
            text, "Names were not scrubbed: name detection was unavailable. Review before approving."
        )

    if names_look_unreliable(counts.get("PERSON", 0), len(text.split())):
        logger.warning("Name detection tagged %s words as names; discarding it", counts["PERSON"])
        return _regex_only(
            text,
            "Names were not scrubbed: name detection looked unreliable on this text and was "
            "skipped. Emails and phone numbers were scrubbed. Review before approving.",
        )

    scrubbed = _regex_scrub(scrubbed, counts)  # catches what NER missed
    return ScrubResult(text=scrubbed, redactions=dict(counts))
