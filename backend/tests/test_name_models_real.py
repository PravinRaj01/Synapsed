"""Runs the real Malay model. Opt in with RUN_MODEL_TESTS=1: the first run downloads
about 140 MB from Hugging Face."""

import os

import pytest

from app.core.pii_shield import scrub_pii

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_MODEL_TESTS") != "1", reason="set RUN_MODEL_TESTS=1 to run the real name models"
)

COLLOQUIAL = (
    "So, kami first of all, saya kenal-kenal saya. Saya Isha, manager untuk Foodie Aging New 12. "
    "So, saya menguruskan 15 slot kedai dekat sini. Lebih kurang 10 ke 25 kg dalam masa sehari. "
    "Okay, yang tu untuk food waste sahaja. Okay, faham."
)
STANDARD = (
    "Pertama sekali, saya Ahmad dari bahagian operasi. Kami menguruskan lima belas kedai di pusat "
    "beli-belah ini. Encik Lim dan Puan Siti Aminah akan datang minggu depan."
)


def test_malay_model_redacts_names_and_keeps_the_rest():
    for text, names, kept in (
        (COLLOQUIAL, ["Isha"], ["first of all", "manager", "kedai", "food waste", "Okay"]),
        (STANDARD, ["Ahmad", "Lim", "Siti", "Aminah"], ["Pertama sekali", "bahagian operasi", "kedai", "minggu depan"]),
    ):
        result = scrub_pii(text)
        assert result.engine == "malay-model", result.notice
        for name in names:
            assert name not in result.text
        for phrase in kept:
            assert phrase in result.text
