import io
import json
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from app.ingestion import parsers
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


def test_pdf_without_text_explains_what_to_do():
    blank = minimal_pdf("").replace(b"BT /F1 12 Tf 10 50 Td () Tj ET", b"")
    with pytest.raises(IngestError, match="scanned"):
        parsers.parse_pdf(blank)


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


def test_image_ocr_requires_tesseract(monkeypatch):
    monkeypatch.setattr(parsers, "find_tesseract", lambda: None)
    with pytest.raises(ToolMissing):
        parsers.parse_image(b"irrelevant")


def test_find_tesseract_prefers_the_configured_path(monkeypatch, tmp_path):
    fake = tmp_path / "tesseract.exe"
    fake.write_text("")
    monkeypatch.setattr(parsers, "get_settings", lambda: SimpleNamespace(tesseract_cmd=str(fake)))
    assert parsers.find_tesseract() == str(fake)


def test_find_tesseract_falls_back_to_the_windows_install_folder(monkeypatch, tmp_path):
    fake = tmp_path / "tesseract.exe"
    fake.write_text("")
    monkeypatch.setattr(parsers, "get_settings", lambda: SimpleNamespace(tesseract_cmd=""))
    monkeypatch.setattr(parsers.shutil, "which", lambda _n: None)  # not on PATH
    monkeypatch.setattr(parsers, "_WINDOWS_TESSERACT", str(fake))
    assert parsers.find_tesseract() == str(fake)
    monkeypatch.setattr(parsers, "_WINDOWS_TESSERACT", str(tmp_path / "missing.exe"))
    assert parsers.find_tesseract() is None


def test_ocr_languages_use_only_installed_packs():
    assert parsers.ocr_languages(["eng", "osd"]) == "eng"
    assert parsers.ocr_languages(["tam", "eng", "msa", "osd"]) == "eng+msa+tam"
    assert parsers.ocr_languages(["osd"]) == "eng"  # always a valid default


@pytest.mark.skipif(parsers.find_tesseract() is None, reason="Tesseract is not installed")
def test_image_ocr_reads_text():
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (500, 120), "white")
    ImageDraw.Draw(img).text((10, 40), "Checkout is slow", fill="black", font=ImageFont.load_default(size=36))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    assert "slow" in parsers.parse_image(buf.getvalue()).lower()


def test_prepare_scrubs_hashes_and_tags_language():
    prepared = prepare("Contact jane.doe@example.com   about the   billing page being slow for our team.")
    assert "jane.doe@example.com" not in prepared.text and prepared.pii_redacted
    assert prepared.language == "en"
    assert prepared.hash == prepare("contact jane.doe@example.com about the billing page being slow for our team.").hash


def test_prepare_rejects_empty_text():
    with pytest.raises(IngestError):
        prepare("  \n\x00 ")


def test_source_type_relabelling_rules():
    assert resolve_source_type("text", None) == "transcript"
    assert resolve_source_type("table", "ticket") == "ticket"
    assert resolve_source_type("audio", None) == "audio"
    with pytest.raises(IngestError):
        resolve_source_type("audio", "survey")
    with pytest.raises(IngestError):
        resolve_source_type("table", "transcript")
