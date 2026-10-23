from dataclasses import dataclass, field

from app.core.language import detect_language
from app.core.pii_shield import scrub_pii
from app.ingestion import parsers
from app.ingestion.cleaning import clean_text, content_hash
from app.ingestion.parsers import IngestError

# Must match the source_type check constraint in schema.sql.
SOURCE_TYPES = {"transcript", "ticket", "survey", "audio", "video", "ocr", "pdf", "web_scrape"}
# What a user may choose to relabel an upload as, per kind of file.
RELABEL = {
    "text": {"transcript", "ticket", "survey"},
    "json": {"transcript", "ticket", "survey"},
    "table": {"survey", "ticket"},
}


@dataclass
class Prepared:
    text: str
    hash: str
    language: str | None
    redactions: dict[str, int] = field(default_factory=dict)
    pii_note: str | None = None  # set when names may remain in the text

    @property
    def pii_redacted(self) -> bool:
        return bool(self.redactions)


@dataclass
class ParsedItem:
    title: str
    text: str
    segment: str | None = None


def prepare(raw: str) -> Prepared:
    """Clean, scrub PII, then hash and tag the language. The result is what gets stored."""
    cleaned = clean_text(raw)
    if not cleaned:
        raise IngestError("The file contains no text")
    scrubbed = scrub_pii(cleaned)
    return Prepared(
        scrubbed.text, content_hash(scrubbed.text), detect_language(scrubbed.text),
        scrubbed.redactions, scrubbed.notice,
    )


def resolve_source_type(kind: str, requested: str | None) -> str:
    default = parsers.default_source_type(kind)
    if not requested:
        return default
    if requested not in RELABEL.get(kind, {default}):
        raise IngestError(f"'{requested}' is not a valid type for this file")
    return requested


def parse_upload(
    data: bytes, filename: str, kind: str, text_column: str | None = None, segment_column: str | None = None
) -> list[ParsedItem]:
    """Extract text from an upload. A spreadsheet can yield several items (one per segment)."""
    if kind == "text":
        return [ParsedItem(filename, parsers.decode_text(data))]
    if kind == "json":
        return [ParsedItem(filename, parsers.parse_json(data))]
    if kind == "pdf":
        return [ParsedItem(filename, parsers.parse_pdf(data))]
    if kind == "image":
        return [ParsedItem(filename, parsers.parse_image(data))]
    if kind in ("audio", "video"):
        from app.ingestion.transcribe import transcribe

        return [ParsedItem(filename, transcribe(data, filename))]
    groups = parsers.parse_table(data, filename, text_column, segment_column)
    return [
        ParsedItem(f"{filename} — {g.segment}" if g.segment else filename, g.text, g.segment) for g in groups
    ]
