from app.core import pii_shield
from app.core.pii_shield import scrub_pii


def test_redacts_name_email_and_phone():
    text = "Hi, I'm Sarah Connor. Reach me at sarah.connor@example.com or +60 12-345 6789."
    result = scrub_pii(text)
    assert "Sarah Connor" not in result.text
    assert "sarah.connor@example.com" not in result.text
    assert "345 6789" not in result.text
    assert {"PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"} <= set(result.redactions)
    assert result.engine == "presidio"


def test_ordinary_text_is_untouched():
    text = "The dashboard takes eight seconds to load on the reports page."
    result = scrub_pii(text)
    assert result.text == text
    assert result.total == 0


def test_dates_and_short_numbers_are_not_phone_numbers():
    text = "Shipped on 2026-10-23, build 4521, 128 users affected, ticket 99871."
    assert scrub_pii(text).text == text


def test_regex_fallback_when_presidio_is_unavailable(monkeypatch):
    def broken():
        raise RuntimeError("model missing")

    monkeypatch.setattr(pii_shield, "_engines", broken)
    result = scrub_pii("Mail bob@corp.io or call 0123456789 please")
    assert result.engine == "regex"
    assert "bob@corp.io" not in result.text and "0123456789" not in result.text
    assert result.redactions == {"EMAIL_ADDRESS": 1, "PHONE_NUMBER": 1}


def test_long_text_is_processed_in_blocks(monkeypatch):
    monkeypatch.setattr(pii_shield, "_BLOCK_CHARS", 200)
    text = "\n".join(f"Line {i}: contact user{i}@example.com about billing" for i in range(40))
    result = scrub_pii(text)
    assert "@example.com" not in result.text
    assert result.redactions["EMAIL_ADDRESS"] == 40
    assert result.text.count("\n") == 39  # line structure survives block splitting
