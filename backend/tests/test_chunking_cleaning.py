import pytest

from app.ingestion.chunking import chunk_text
from app.ingestion.cleaning import clean_text, content_hash


def test_clean_text_normalises_whitespace_and_controls():
    raw = "Hello  world \r\n\r\n\r\n\r\nSecond\x00 line\t  here  "
    assert clean_text(raw) == "Hello world\n\nSecond line here"


def test_hash_ignores_case_and_whitespace_but_not_content():
    assert content_hash("Slow  dashboard\n") == content_hash("slow dashboard")
    assert content_hash("slow dashboard") != content_hash("slow checkout")


def test_empty_text_has_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_short_text_is_one_chunk():
    chunks = chunk_text("Just one short note.")
    assert len(chunks) == 1 and chunks[0].start == 0 and chunks[0].content == "Just one short note."


def test_chunk_offsets_always_match_the_text():
    text = "\n\n".join(f"Paragraph {i}. " + "The checkout page is slow. " * 20 for i in range(12))
    chunks = chunk_text(text, size=500, overlap=60)
    assert len(chunks) > 5
    for chunk in chunks:
        assert chunk.content == text[chunk.start : chunk.end]
        assert len(chunk.content) <= 500
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_chunks_cover_the_whole_text_with_overlap():
    text = ("Sentence number one is here. " * 80).strip()
    chunks = chunk_text(text, size=400, overlap=50)
    assert chunks[0].start == 0 and chunks[-1].end == len(text)
    for a, b in zip(chunks, chunks[1:]):
        assert b.start < a.end  # overlapping, so no quote is split without context
        assert b.start > a.start  # always makes progress


def test_prefers_paragraph_breaks():
    text = "A" * 300 + "\n\n" + "B" * 300
    first = chunk_text(text, size=400, overlap=20)[0]
    assert first.content.endswith("\n\n")


def test_unbroken_text_is_hard_split():
    chunks = chunk_text("x" * 1000, size=300, overlap=30)
    assert all(len(c.content) <= 300 for c in chunks) and chunks[-1].end == 1000


def test_size_must_exceed_overlap():
    with pytest.raises(ValueError):
        chunk_text("abc", size=10, overlap=10)
