import pytest

from app.core import pii_shield
from app.core.pii_shield import scrub_pii


@pytest.fixture(autouse=True)
def no_name_models(monkeypatch):
    """By default no Malay/Tamil model is used, so these tests never download one."""
    monkeypatch.setattr(pii_shield.name_models, "detector_for", lambda _language: None)


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
    monkeypatch.setattr(pii_shield, "detect_language", lambda _t: "en")  # reach the Presidio path
    result = scrub_pii("Mail bob@corp.io or call 0123456789 please")
    assert result.engine == "regex" and "unavailable" in result.notice
    assert "bob@corp.io" not in result.text and "0123456789" not in result.text
    assert result.redactions == {"EMAIL_ADDRESS": 1, "PHONE_NUMBER": 1}


def test_long_text_is_processed_in_blocks(monkeypatch):
    monkeypatch.setattr(pii_shield, "_BLOCK_CHARS", 200)
    monkeypatch.setattr(pii_shield, "detect_language", lambda _t: "en")
    text = "\n".join(f"Line {i}: contact user{i}@example.com about billing" for i in range(40))
    result = scrub_pii(text)
    assert "@example.com" not in result.text
    assert result.redactions["EMAIL_ADDRESS"] == 40
    assert result.text.count("\n") == 39  # line structure survives block splitting


MALAY = (
    "Pertama sekali, saya Ahmad dari bahagian operasi. Kami menguruskan lima belas kedai di pusat "
    "beli-belah ini. Setiap hari kami buang lebih kurang dua puluh kilogram sisa makanan. Okay, jadi "
    "kami ada dua tong, satu hijau untuk sisa makanan dan satu lagi untuk kertas dan plastik. Cabaran "
    "terbesar ialah pekerja tidak mengasingkan sampah dengan betul. Hubungi saya di ahmad@pusat.com.my "
    "atau 012-345 6789 jika ada soalan lanjut."
)
TAMIL = "எங்கள் கடையில் கழிவு மேலாண்மை மிகவும் கடினமாக உள்ளது. தினமும் நிறைய உணவு கழிவு வருகிறது. தொடர்புக்கு: tamil@example.com"


def test_malay_text_keeps_its_words_and_gets_a_notice():
    result = scrub_pii(MALAY)
    assert result.engine == "regex" and "Names were not scrubbed" in result.notice
    assert "<PERSON>" not in result.text
    for word in ("Pertama sekali", "Okay", "operasi", "sisa makanan"):
        assert word in result.text  # the English-only model used to turn these into <PERSON>
    assert "ahmad@pusat.com.my" not in result.text and "345 6789" not in result.text  # regex still works
    assert result.redactions == {"EMAIL_ADDRESS": 1, "PHONE_NUMBER": 1}


def test_tamil_text_is_not_sent_through_the_english_name_model():
    result = scrub_pii(TAMIL)
    assert result.engine == "regex" and result.notice
    assert "tamil@example.com" not in result.text and "கடையில்" in result.text


def test_english_text_has_no_notice():
    assert scrub_pii("Ask Sarah Connor about the export, she owns it.").notice is None


@pytest.mark.parametrize(
    "people, words, unreliable",
    [(25, 150, True), (4, 100, False), (11, 100, True), (10, 100, False), (9, 20, False)],
)
def test_sanity_cap_on_name_detection(people, words, unreliable):
    assert pii_shield.names_look_unreliable(people, words) is unreliable


def test_a_name_model_that_is_guessing_is_discarded(monkeypatch):
    monkeypatch.setattr(pii_shield, "detect_language", lambda _t: "en")

    def guessing(text, counts):
        counts["PERSON"] += 30
        return text.replace("export", "<PERSON>")

    monkeypatch.setattr(pii_shield, "_presidio_scrub", guessing)
    text = ("The export is slow and the export fails often. " * 12) + "Write to dev@acme.io"
    result = scrub_pii(text)
    assert "<PERSON>" not in result.text and "export" in result.text
    assert "unreliable" in result.notice and result.engine == "regex"
    assert result.redactions == {"EMAIL_ADDRESS": 1}


def fake_detector(monkeypatch, label, spans_for, language_filter=None):
    monkeypatch.setattr(
        pii_shield.name_models, "detector_for",
        lambda language: (label, spans_for) if language_filter is None or language in language_filter else None,
    )


def test_malay_uses_the_name_model_when_one_is_available(monkeypatch):
    def spans(text):
        start = text.index("Ahmad")
        return [(start, start + len("Ahmad"))]

    fake_detector(monkeypatch, "Malay", spans)
    result = scrub_pii(MALAY)
    assert "Ahmad" not in result.text and "saya <PERSON> dari" in result.text
    assert "Pertama sekali" in result.text and "operasi" in result.text  # nothing else is touched
    assert result.engine == "malay-model" and result.redactions["PERSON"] == 1
    assert "ahmad@pusat.com.my" not in result.text and "345 6789" not in result.text  # regex still runs
    assert "Malay name model that can miss some names" in result.notice


def test_tamil_uses_its_own_label(monkeypatch):
    def spans(text):
        start = text.index("tamil@")  # any span: only the routing is under test
        return [(start, start + 3)]

    fake_detector(monkeypatch, "Tamil", spans)
    assert scrub_pii(TAMIL).engine == "tamil-model"


def test_a_failing_name_model_falls_back_to_regex(monkeypatch):
    def broken(_text):
        raise OSError("could not download model")

    fake_detector(monkeypatch, "Malay", broken)
    result = scrub_pii(MALAY)
    assert result.engine == "regex" and "name model was unavailable" in result.notice
    assert "ahmad@pusat.com.my" not in result.text and "Pertama sekali" in result.text


def test_a_name_model_that_flags_too_much_is_discarded(monkeypatch):
    everything = lambda text: [(0, len(text))]  # absurd, but proves the cap applies to models too
    long_malay = (MALAY + " ") * 3
    fake_detector(monkeypatch, "Malay", lambda text: [(i, i + 1) for i in range(0, 60, 2)])
    result = scrub_pii(long_malay)
    assert result.engine == "regex" and "unreliable" in result.notice and "<PERSON>" not in result.text


def test_languages_without_a_model_still_get_the_review_notice(monkeypatch):
    fake_detector(monkeypatch, "Malay", lambda text: [], language_filter={"ms", "id"})
    thai = "ฉันต้องการข้อมูลเพิ่มเติมเกี่ยวกับการจัดการขยะในร้านอาหารของเรา กรุณาติดต่อ test@example.com"
    result = scrub_pii(thai)
    assert result.engine == "regex" and "English, Malay and Tamil" in result.notice
