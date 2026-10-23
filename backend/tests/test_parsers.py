import io
import json
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from app.ingestion import ocr, parsers
from app.ingestion.parsers import IngestError, ToolMissing
from app.ingestion.pipeline import prepare, resolve_source_type


def test_detect_kind():
    assert parsers.detect_kind("Interview 3.TXT") == "text"
    assert parsers.detect_kind("calls.mp4") == "video"
    assert parsers.detect_kind("scan.JPG") == "image"
    assert parsers.detect_kind("survey.xlsx") == "table"
    with pytest.raises(IngestError):
        parsers.detect_kind("archive.zip")


def test_decode_text_handles_bom_and_latin1():
    assert parsers.decode_text("﻿hello".encode("utf-8")) == "hello"
    assert parsers.decode_text("café".encode("latin-1")) == "café"
    assert parsers.decode_text("héllo wörld".encode("utf-16")) == "héllo wörld"


def test_json_transcript_turns_and_plain_strings():
    data = json.dumps({"turns": [
        {"speaker": "PM", "text": "What slows you down?"},
        {"speaker": "User", "text": "The export is painfully slow."},
    ], "notes": ["Follow up on billing"]}).encode()
    assert parsers.parse_json(data).splitlines() == [
        "PM: What slows you down?", "User: The export is painfully slow.", "Follow up on billing",
    ]


def test_invalid_json_is_a_user_error():
    with pytest.raises(IngestError):
        parsers.parse_json(b"{not json")


def minimal_pdf(text: str) -> bytes:
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        None,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = f"BT /F1 12 Tf 10 50 Td ({text}) Tj ET"
    objects[3] = f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def test_pdf_text_extraction():
    assert "checkout is slow" in parsers.parse_pdf(minimal_pdf("The checkout is slow"))


def test_pdf_without_text_is_read_by_gemini(monkeypatch):
    blank = minimal_pdf("").replace(b"BT /F1 12 Tf 10 50 Td () Tj ET", b"")
    calls = []
    monkeypatch.setattr(ocr, "read_text", lambda data, mime: calls.append(mime) or "scanned words")
    assert parsers.parse_pdf(blank) == "scanned words"
    assert calls == ["application/pdf"]


def test_garbage_pdf_is_a_user_error():
    with pytest.raises(IngestError):
        parsers.parse_pdf(b"definitely not a pdf")


CSV = (
    "id,plan,comment\n"
    "1,Enterprise,The export is painfully slow\n"
    "2,Free,I cannot find the settings page\n"
    "3,Enterprise,SSO login keeps failing\n"
    "4,Free,\n"
).encode()


def test_csv_auto_detects_the_text_column_and_groups_by_segment():
    groups = {g.segment: g.text for g in parsers.parse_table(CSV, "survey.csv", None, "plan")}
    assert set(groups) == {"Enterprise", "Free"}
    assert groups["Enterprise"].splitlines() == [
        "Row 2: The export is painfully slow", "Row 4: SSO login keeps failing",
    ]
    assert groups["Free"] == "Row 3: I cannot find the settings page"  # the empty row is skipped


def test_csv_without_segment_column_is_one_group():
    groups = parsers.parse_table(CSV, "survey.csv", "comment")
    assert len(groups) == 1 and groups[0].segment is None and groups[0].text.count("Row ") == 3


def test_csv_semicolon_delimiter():
    data = b"id;feedback\n1;Too many clicks to export\n2;Love the new layout\n"
    assert len(parsers.parse_table(data, "x.csv", "feedback")[0].text.splitlines()) == 2


def test_unknown_column_lists_the_available_ones():
    with pytest.raises(IngestError, match="comment"):
        parsers.parse_table(CSV, "survey.csv", "nope")


def test_xlsx_survey():
    wb = Workbook()
    ws = wb.active
    ws.append(["tier", "response"])
    ws.append(["Enterprise", "Reports time out on large accounts"])
    ws.append(["Free", "Onboarding was confusing"])
    buf = io.BytesIO()
    wb.save(buf)
    groups = parsers.parse_table(buf.getvalue(), "s.xlsx", "response", "tier")
    assert {g.segment for g in groups} == {"Enterprise", "Free"}


def test_table_needs_data_rows():
    with pytest.raises(IngestError):
        parsers.parse_table(b"only,a,header\n", "x.csv")


def test_image_is_sent_to_gemini_with_its_mime_type(monkeypatch):
    calls = []
    monkeypatch.setattr(ocr, "read_text", lambda data, mime: calls.append((data, mime)) or "Checkout is slow")
    assert parsers.parse_image(b"bytes", "Scan.JPG") == "Checkout is slow"
    assert calls == [(b"bytes", "image/jpeg")]


def test_unknown_image_type_is_rejected():
    with pytest.raises(IngestError):
        parsers.parse_image(b"x", "scan.gif")


def fake_gemini(monkeypatch, reply=None, error=None, key="k"):
    sent = {}

    class Models:
        def generate_content(self, **kwargs):
            sent.update(kwargs)
            if error:
                raise error
            return SimpleNamespace(text=reply)

    monkeypatch.setattr(ocr, "get_settings", lambda: SimpleNamespace(google_api_key=key, gemini_model="m"))
    monkeypatch.setattr(ocr, "_client", lambda: SimpleNamespace(models=Models()))
    return sent


def test_gemini_reply_is_returned_trimmed(monkeypatch):
    sent = fake_gemini(monkeypatch, reply="  Hello Selamat pagi  ")
    assert ocr.read_text(b"img", "image/png") == "Hello Selamat pagi"
    assert sent["model"] == "m" and ocr.PROMPT in sent["contents"]


@pytest.mark.parametrize("reply", ["", "   ", None, "NO_TEXT"])
def test_empty_gemini_reply_means_no_text(monkeypatch, reply):
    fake_gemini(monkeypatch, reply=reply)
    with pytest.raises(IngestError, match="No text"):
        ocr.read_text(b"img", "image/png")


def test_missing_google_key_is_a_tool_error(monkeypatch):
    fake_gemini(monkeypatch, reply="x", key="")
    with pytest.raises(ToolMissing):
        ocr.read_text(b"img", "image/png")


def test_oversized_file_is_refused_before_calling_gemini(monkeypatch):
    sent = fake_gemini(monkeypatch, reply="x")
    with pytest.raises(IngestError, match="too large"):
        ocr.read_text(b"x" * (ocr.INLINE_LIMIT + 1), "application/pdf")
    assert not sent


def test_gemini_errors_become_user_messages(monkeypatch):
    from google.genai import errors

    fake_gemini(monkeypatch, error=errors.ClientError(400, {"error": {"message": "bad"}}))
    with pytest.raises(IngestError, match="could not read"):
        ocr.read_text(b"img", "image/png")
    fake_gemini(monkeypatch, error=errors.ServerError(503, {"error": {"message": "down"}}))
    with pytest.raises(IngestError, match="unavailable"):
        ocr.read_text(b"img", "image/png")
