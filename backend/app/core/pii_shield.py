"""PII scrubbing (the "Enterprise Shield").

Runs before text is stored or sent to any LLM. Presidio (spaCy small model) finds
names, emails and phone numbers; a regex pass then catches anything it missed, and
is also the fallback if Presidio cannot load. Redactions become tokens such as
<PERSON>, so stored text and chunk offsets always refer to the scrubbed text.

Limit: the spaCy model is English-only, so names in Malay or Tamil text are not
detected by the NER step; emails and phone numbers are still caught by regex.
"""

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

logger = logging.getLogger("synapsed.pii")
# Presidio warns on every call about spaCy labels it does not map (CARDINAL, DATE, ...).
logging.getLogger("presidio-analyzer").setLevel(logging.ERROR)

ENTITIES = ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"]
_BLOCK_CHARS = 50_000  # keep each Presidio call well under spaCy's length limit

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\w.])\+?\d[\d\-\s().]{7,}\d(?![\w])")
_DATE_LIKE = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$|^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$")


@dataclass
class ScrubResult:
    text: str
    redactions: dict[str, int] = field(default_factory=dict)
    engine: str = "presidio"

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


def scrub_pii(text: str) -> ScrubResult:
    """Redact names, emails and phone numbers. Never raises: falls back to regex only."""
    counts: Counter = Counter()
    engine = "presidio"
    try:
        text = _presidio_scrub(text, counts)
    except Exception:  # model missing, spaCy error, ...
        logger.warning("Presidio unavailable; using regex-only PII scrubbing", exc_info=True)
        engine = "regex"
    text = _regex_scrub(text, counts)  # catches what NER missed; sole pass in fallback mode
    return ScrubResult(text=text, redactions=dict(counts), engine=engine)
