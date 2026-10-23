import hashlib
import re
import unicodedata

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BLANK_RUNS = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t ]+")


def clean_text(text: str) -> str:
    """Normalise unicode and whitespace so equal content compares and hashes equal."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANK_RUNS.sub("\n\n", "\n".join(lines)).strip()


def content_hash(text: str) -> str:
    """sha256 over a whitespace- and case-insensitive form, for exact de-duplication."""
    folded = " ".join(text.lower().split())
    return hashlib.sha256(folded.encode("utf-8")).hexdigest()
