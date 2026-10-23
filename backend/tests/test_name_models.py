from types import SimpleNamespace

import pytest

from app.core import name_models as nm


def test_redact_spans_replaces_each_span_and_counts_them():
    text = "Encik Lim met Siti Aminah today"
    spans = [(0, 9), (14, 25)]  # "Encik Lim" and "Siti Aminah"
    assert nm.redact_spans(text, spans) == ("<PERSON> met <PERSON> today", 2)
    assert nm.redact_spans("nothing here", []) == ("nothing here", 0)


def test_trailing_punctuation_stays_outside_the_span():
    text = "Saya Isha, manager di sini."
    assert nm.merge_spans(text, [(5, 10)]) == [(5, 9)]  # "Isha," -> "Isha"
    redacted, _ = nm.redact_spans(text, nm.merge_spans(text, [(5, 10)]))
    assert redacted == "Saya <PERSON>, manager di sini."


def test_adjacent_name_parts_become_one_name():
    text = "Encik Lim dan Puan Siti Aminah"
    #       Encik=0-5 Lim=6-9           Puan=14-18 Siti=19-23 Aminah=24-30
    merged = nm.merge_spans(text, [(0, 5), (6, 9), (14, 18), (19, 23), (24, 30)])
    assert merged == [(0, 9), (14, 30)]  # "dan" keeps the two names apart


def test_names_separated_by_a_comma_are_merged_but_not_across_words():
    text = "Lim, Siti pergi ke pasar"
    assert nm.merge_spans(text, [(0, 4), (5, 9)]) == [(0, 9)]
    assert nm.merge_spans(text, [(0, 3), (15, 20)]) == [(0, 3), (15, 20)]


def test_punctuation_only_spans_are_dropped():
    assert nm.merge_spans("a ... b", [(2, 5)]) == []


def test_spans_grow_to_whole_words():
    text = "பிரியா சுரேஷ் பேசினார்"
    start = text.index("யா")
    assert nm.expand_to_words(text, [(start, start + 2)]) == [(0, len("பிரியா"))]
    grown = nm.expand_to_words(text, [(2, 9)])
    assert text[grown[0][0] : grown[0][1]].count(" ") <= 1 and grown[0][0] == 0


def test_windows_cover_the_text_exactly_and_cut_at_spaces():
    text = " ".join(f"word{i}" for i in range(200))
    pieces = list(nm.windows(text, 100))
    assert "".join(p for _, p in pieces) == text
    assert all(len(p) <= 100 for _, p in pieces)
    assert all(text[o : o + len(p)] == p for o, p in pieces)  # offsets are exact
    assert all(not p.endswith("wor") for _, p in pieces[:-1])  # no word is cut in half


def test_windows_handle_text_without_spaces():
    pieces = list(nm.windows("x" * 250, 100))
    assert [len(p) for _, p in pieces] == [100, 100, 50]


def test_detector_routing_and_the_off_switch(monkeypatch):
    on = SimpleNamespace(pii_malay_model="m", pii_tamil_model="t")
    monkeypatch.setattr(nm, "get_settings", lambda: on)
    assert nm.detector_for("ms")[0] == "Malay" and nm.detector_for("id")[0] == "Malay"
    assert nm.detector_for("ta")[0] == "Tamil"
    assert nm.detector_for("th") is None and nm.detector_for(None) is None

    off = SimpleNamespace(pii_malay_model="", pii_tamil_model="")
    monkeypatch.setattr(nm, "get_settings", lambda: off)
    assert nm.detector_for("ms") is None and nm.detector_for("ta") is None


def test_malay_label_id_is_person():
    assert nm.MALAY_PERSON_LABEL_ID == 4
