from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.schemas import Insight, RoadmapItem, Segment, Theme

NOW = datetime.now(timezone.utc)


def insight(**overrides):
    base = dict(
        id=uuid4(), campaign_id=uuid4(), summary_text="Dashboard is slow", created_at=NOW
    )
    return Insight(**{**base, **overrides})


def roadmap_item(**overrides):
    base = dict(
        id=uuid4(), campaign_id=uuid4(), title="Fix latency", description="d",
        horizon="now", impact_score=8, confidence_score=7, ease_score=5,
        ice_score=280, created_at=NOW,
    )
    return RoadmapItem(**{**base, **overrides})


def test_insight_defaults():
    i = insight()
    assert (i.severity, i.sentiment, i.kind) == (3, "neutral", "pain_point")


@pytest.mark.parametrize("severity", [0, 6])
def test_insight_severity_bounds(severity):
    with pytest.raises(ValidationError):
        insight(severity=severity)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_insight_confidence_bounds(confidence):
    with pytest.raises(ValidationError):
        insight(confidence_score=confidence)


def test_insight_rejects_unknown_sentiment():
    with pytest.raises(ValidationError):
        insight(sentiment="angry")


def test_embedding_must_be_768_dimensions():
    assert insight(embedding=[0.0] * 768).embedding is not None
    with pytest.raises(ValidationError):
        insight(embedding=[0.0] * 767)


@pytest.mark.parametrize("field", ["impact_score", "confidence_score", "ease_score"])
@pytest.mark.parametrize("value", [0, 11])
def test_roadmap_scores_bounds(field, value):
    with pytest.raises(ValidationError):
        roadmap_item(**{field: value})


def test_roadmap_horizon_values():
    with pytest.raises(ValidationError):
        roadmap_item(horizon="soon")


def test_segment_weight_must_be_positive():
    with pytest.raises(ValidationError):
        Segment(id=uuid4(), campaign_id=uuid4(), name="Free", tier="free", weight=0)


def test_theme_impact_bounds():
    with pytest.raises(ValidationError):
        Theme(id=uuid4(), campaign_id=uuid4(), label="x", color_code="#fff",
              business_impact=101, created_at=NOW)
