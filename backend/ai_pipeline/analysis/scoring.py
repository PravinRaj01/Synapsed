"""Scores for themes and roadmap items. Pure functions: no database, no LLM.

Business Impact (0-100): raw = sum(segment weight x severity) over a theme's insights, scaled so the
strongest theme in the campaign scores 100. Frequency is built in, and valuable customer groups
count more. ICE: Impact x Confidence x Ease, each 1-10.
"""

import math
from collections import Counter
from dataclasses import dataclass

DEFAULT_SEGMENT_WEIGHT = 1.0  # insights without a segment
COSINE_FLOOR = 0.70  # cohesion at or below this adds nothing to confidence (unrelated text scores 0.71-0.82)


def clamp_score(value: float) -> int:
    return max(1, min(10, math.floor(value + 0.5)))  # round half up; Python's round() goes to even


def raw_impact(insights: list[tuple[float | None, int]]) -> float:
    """Sum of segment weight x severity for (weight, severity) pairs."""
    return sum((DEFAULT_SEGMENT_WEIGHT if weight is None else float(weight)) * severity for weight, severity in insights)


def business_impacts(raw: dict[str, float]) -> dict[str, float]:
    """Raw impacts scaled to 0-100 against the campaign's strongest theme."""
    top = max(raw.values(), default=0.0)
    if top <= 0:
        return {key: 0.0 for key in raw}
    return {key: round(100 * value / top, 2) for key, value in raw.items()}


def impact_score(business_impact: float) -> int:
    return clamp_score(business_impact / 10)


def confidence_score(distinct_resources: int, insight_count: int, cohesion: float | None) -> int:
    """1-10 from the evidence: more sources, more mentions and a tighter cluster all raise it.

    Up to 4 points for sources (5 or more distinct resources is the maximum), 3 for mentions (10 or more),
    3 for cohesion (the mean cosine similarity of members to the theme's centre, 0.70 to 1.00).
    """
    sources = 4 * min(distinct_resources, 5) / 5
    mentions = 3 * min(insight_count, 10) / 10
    tight = 3 * max(0.0, min(1.0, ((cohesion if cohesion is not None else COSINE_FLOOR) - COSINE_FLOOR) / (1 - COSINE_FLOOR)))
    return clamp_score(sources + mentions + tight)


def ice(impact: int, confidence: int, ease: int) -> int:
    return impact * confidence * ease


def horizons(ice_by_item: dict[str, int]) -> dict[str, str]:
    """Now / Next / Later by tercile of ICE (highest first); ties keep their input order."""
    ranked = sorted(ice_by_item, key=lambda key: -ice_by_item[key])
    total = len(ranked)
    now_end, next_end = math.ceil(total / 3), math.ceil(2 * total / 3)
    return {
        key: "now" if rank < now_end else "next" if rank < next_end else "later"
        for rank, key in enumerate(ranked)
    }


@dataclass
class SentimentSummary:
    label: str  # positive | neutral | negative | mixed
    counts: dict[str, int]
    net: float  # (positive - negative) / total, from -1 to 1


def theme_sentiment(sentiments: list[str]) -> SentimentSummary:
    """Roll up per-insight sentiment: a clear lean wins, a real split is "mixed"."""
    counts = Counter(sentiments)
    total = sum(counts.values())
    if total == 0:
        return SentimentSummary("neutral", {"positive": 0, "neutral": 0, "negative": 0}, 0.0)
    positive, negative = counts["positive"], counts["negative"]
    net = (positive - negative) / total
    if positive and negative and min(positive, negative) / total >= 0.25 and abs(net) < 0.5:
        label = "mixed"
    elif net >= 0.2:
        label = "positive"
    elif net <= -0.2:
        label = "negative"
    else:
        label = "neutral"
    return SentimentSummary(label, {s: counts[s] for s in ("positive", "neutral", "negative")}, round(net, 2))
