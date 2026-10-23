from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    index: int
    start: int  # character offsets into the text that was chunked
    end: int
    content: str  # always text[start:end]


def _break_point(text: str, start: int, hard_end: int, min_end: int) -> int:
    """Prefer ending on a paragraph break, then a line break, then a sentence end."""
    for marker in ("\n\n", "\n", ". ", "? ", "! "):
        pos = text.rfind(marker, min_end, hard_end)
        if pos != -1:
            return pos + len(marker)
    return hard_end


def chunk_text(text: str, size: int = 1200, overlap: int = 150) -> list[Chunk]:
    """Split text into overlapping chunks with exact character offsets.

    The offsets let a citation point back to the quote in the stored resource text.
    """
    if size <= overlap:
        raise ValueError("size must be larger than overlap")
    text_len = len(text)
    chunks: list[Chunk] = []
    start = 0
    while start < text_len:
        hard_end = min(start + size, text_len)
        end = hard_end if hard_end == text_len else _break_point(text, start, hard_end, start + size // 2)
        if text[start:end].strip():
            chunks.append(Chunk(len(chunks), start, end, text[start:end]))
        if end >= text_len:
            break
        start = max(end - overlap, start + 1)
    return chunks
