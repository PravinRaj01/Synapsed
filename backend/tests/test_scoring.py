import pytest

from ai_pipeline.analysis import scoring as sc


def test_raw_impact_weights_severity_by_segment_and_defaults_missing_segments():
    assert sc.raw_impact([(3.0, 4), (1.0, 2), (None, 5)]) == 3 * 4 + 1 * 2 + 1 * 5
    assert sc.raw_impact([]) == 0


def test_business_impact_is_scaled_to_the_strongest_theme():
    result = sc.business_impacts({"a": 60.0, "b": 30.0, "c": 6.0})
    assert result == {"a": 100.0, "b": 50.0, "c": 10.0}


def test_business_impact_with_no_signal_is_zero_not_a_division_error():
    assert sc.business_impacts({"a": 0.0}) == {"a": 0.0}
    assert sc.business_impacts({}) == {}


def test_a_big_enterprise_theme_outranks_a_frequent_free_one():
    enterprise = sc.raw_impact([(3.0, 5)] * 2)  # two severe enterprise mentions
    free = sc.raw_impact([(0.5, 2)] * 5)  # five minor free-tier mentions
    impacts = sc.business_impacts({"enterprise": enterprise, "free": free})
    assert impacts["enterprise"] == 100.0 and impacts["free"] < 20


@pytest.mark.parametrize("impact,expected", [(0, 1), (4, 1), (45, 5), (100, 10), (96, 10)])
def test_impact_score_is_one_to_ten(impact, expected):
    assert sc.impact_score(impact) == expected


def test_confidence_grows_with_each_kind_of_evidence():
    weak = sc.confidence_score(1, 1, 0.70)
    more_sources = sc.confidence_score(4, 1, 0.70)
    more_mentions = sc.confidence_score(1, 10, 0.70)
    tighter = sc.confidence_score(1, 1, 0.95)
    assert weak < more_sources and weak <= more_mentions and weak < tighter
    assert 1 <= weak and sc.confidence_score(50, 500, 1.0) == 10


def test_confidence_without_a_cohesion_value_and_with_loose_clusters():
    assert sc.confidence_score(2, 3, None) == sc.confidence_score(2, 3, 0.70)
    assert sc.confidence_score(2, 3, 0.40) == sc.confidence_score(2, 3, 0.70)  # never penalised below the floor


def test_ice_is_the_product():
    assert sc.ice(8, 5, 3) == 120


def test_horizons_split_into_terciles():
    result = sc.horizons({f"t{i}": 100 - i for i in range(6)})
    assert [result[f"t{i}"] for i in range(6)] == ["now", "now", "next", "next", "later", "later"]


@pytest.mark.parametrize("n,expected", [
    (1, ["now"]), (2, ["now", "next"]), (3, ["now", "next", "later"]),
    (4, ["now", "now", "next", "later"]), (7, ["now", "now", "now", "next", "next", "later", "later"]),
])
def test_horizons_for_small_counts(n, expected):
    result = sc.horizons({f"t{i}": 100 - i for i in range(n)})
    assert [result[f"t{i}"] for i in range(n)] == expected


def test_horizons_of_nothing():
    assert sc.horizons({}) == {}


@pytest.mark.parametrize("sentiments,label", [
    (["negative"] * 5, "negative"),
    (["positive"] * 3, "positive"),
    (["neutral"] * 5 + ["negative"], "neutral"),
    (["neutral", "neutral", "negative"], "negative"),
    (["negative", "negative", "positive", "positive"], "mixed"),
    (["negative"] * 5 + ["positive"], "negative"),
    ([], "neutral"),
])
def test_theme_sentiment(sentiments, label):
    assert sc.theme_sentiment(sentiments).label == label


def test_theme_sentiment_reports_counts_and_net():
    result = sc.theme_sentiment(["negative", "negative", "positive", "neutral"])
    assert result.counts == {"positive": 1, "neutral": 1, "negative": 2} and result.net == -0.25
