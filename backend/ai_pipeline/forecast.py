"""Weekly trend forecast (Holt's linear trend) and the what-if on Business Impact.

Everything numeric is computed here, in plain code. The model only writes a short narrative from these
numbers (see narrative.py), and anything it says is an estimate: the forecast carries its method, an 80%
interval and a note, and refuses to forecast from fewer than MIN_WEEKS complete weeks.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

MIN_WEEKS = 4
MAX_HORIZON = 12
ALPHA, BETA = 0.5, 0.3  # smoothing of the level and of the trend
Z80 = 1.2816  # half-width of an 80% interval, in standard deviations
FLAT_BAND = 0.1  # a weekly change under 10% of the average counts as flat
METHOD = "Holt linear trend (weekly)"


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def weekly_series(points: list[tuple[date, float]], today: date) -> list[dict]:
    """(date, value) pairs summed per week from the first week to the current one, gaps filled with 0.

    The current week is included but marked `partial`, because it is not over yet.
    """
    if not points:
        return []
    totals: dict[date, float] = {}
    for day, value in points:
        totals[week_start(day)] = totals.get(week_start(day), 0) + value
    first, last = min(totals), max(max(totals), week_start(today))
    series, current = [], first
    while current <= last:
        series.append({"week": current.isoformat(), "value": round(totals.get(current, 0), 2), "partial": current == week_start(today)})
        current += timedelta(days=7)
    return series


@dataclass
class Forecast:
    values: list[float]
    lower: list[float]
    upper: list[float]
    trend: str  # rising | falling | flat
    weekly_change: float  # estimated change per week


def holt(values: list[float], horizon: int) -> Forecast:
    """Forecast `horizon` weeks ahead. Needs at least MIN_WEEKS values."""
    if len(values) < MIN_WEEKS:
        raise ValueError(f"need at least {MIN_WEEKS} weeks of data")
    span = min(3, len(values) - 1)
    level, trend = values[0], (values[span] - values[0]) / span
    residuals = []
    for y in values[1:]:
        predicted = level + trend
        residuals.append(y - predicted)
        new_level = ALPHA * y + (1 - ALPHA) * predicted
        trend = BETA * (new_level - level) + (1 - BETA) * trend
        level = new_level
    sigma = math.sqrt(sum(e * e for e in residuals) / len(residuals))
    forecast, lower, upper = [], [], []
    for h in range(1, horizon + 1):
        point = max(0.0, level + h * trend)
        half = Z80 * sigma * math.sqrt(h)  # uncertainty grows with distance
        forecast.append(round(point, 2))
        lower.append(round(max(0.0, point - half), 2))
        upper.append(round(point + half, 2))
    mean = sum(values) / len(values)
    change = trend / mean if mean > 0 else 0.0
    label = "rising" if change > FLAT_BAND else "falling" if change < -FLAT_BAND else "flat"
    return Forecast(forecast, lower, upper, label, round(trend, 2))


def forecast_series(series: list[dict], horizon: int) -> dict:
    """Forecast from a weekly series (partial weeks are left out). Returns the forecast block of the API answer."""
    horizon = max(1, min(horizon, MAX_HORIZON))
    complete = [p for p in series if not p["partial"]]
    if len(complete) < MIN_WEEKS:
        return {"forecast": None, "trend": None, "method": METHOD, "weeks_used": len(complete),
                "note": f"A forecast needs at least {MIN_WEEKS} complete weeks of data; there are {len(complete)} so far."}
    result = holt([p["value"] for p in complete], horizon)
    last = date.fromisoformat(complete[-1]["week"])
    # The first forecast week is the one after the last complete week (the current, partial week when there is one).
    points = [{"week": (last + timedelta(days=7 * (h + 1))).isoformat(), "value": result.values[h],
               "lower": result.lower[h], "upper": result.upper[h]} for h in range(horizon)]
    return {"forecast": points, "trend": result.trend, "weekly_change": result.weekly_change, "method": METHOD,
            "weeks_used": len(complete), "interval": "80%",
            "note": "An estimate from past weekly counts only. It does not know about releases, seasons or other changes."}


# ---------------------------------------------------------------- what-if on Business Impact

def _raw(cells: dict[tuple[str, str | None], dict], weights: dict[str | None, float], extra: dict[tuple[str, str | None], tuple[int, float]]):
    """Business Impact inputs per theme: sum of (segment weight x severity), with added insights."""
    raw: dict[str, float] = {}
    freq: dict[str, int] = {}
    for (theme, segment), cell in cells.items():
        raw[theme] = raw.get(theme, 0) + weights.get(segment, 1.0) * cell["severity_sum"]
        freq[theme] = freq.get(theme, 0) + cell["count"]
    for (theme, segment), (count, severity) in extra.items():
        raw[theme] = raw.get(theme, 0) + weights.get(segment, 1.0) * severity * count
        freq[theme] = freq.get(theme, 0) + count
    return raw, freq


def _impacts(raw: dict[str, float]) -> dict[str, float]:
    top = max(raw.values(), default=0.0)
    return {t: round(100 * v / top, 1) if top > 0 else 0.0 for t, v in raw.items()}


def _ranks(impact: dict[str, float]) -> dict[str, int]:
    ordered = sorted(impact, key=lambda t: (-impact[t], t))
    return {t: i + 1 for i, t in enumerate(ordered)}


def what_if(
    cells: dict[tuple[str, str | None], dict], weights: dict[str | None, float], labels: dict[str, str],
    segment_weights: dict[str, float] | None = None, extra_insights: list[dict] | None = None,
) -> dict:
    """Business Impact before and after changing segment weights and/or adding insights.

    `cells` maps (theme_id, segment_id) to {"count", "severity_sum"}. An added insight takes the given
    severity, or the theme's average severity (3 when the theme has none), and counts with the new weight.
    """
    new_weights = {**weights, **(segment_weights or {})}
    extra: dict[tuple[str, str | None], tuple[int, float]] = {}
    for item in extra_insights or []:
        key = (item["theme_id"], item.get("segment_id"))
        theme_cells = [c for (t, _), c in cells.items() if t == item["theme_id"]]
        total = sum(c["count"] for c in theme_cells)
        default = sum(c["severity_sum"] for c in theme_cells) / total if total else 3.0
        count, _ = extra.get(key, (0, 0))
        extra[key] = (count + item["count"], item.get("severity") or default)

    before_raw, before_freq = _raw(cells, weights, {})
    after_raw, after_freq = _raw(cells, new_weights, extra)
    for theme in after_raw:
        before_raw.setdefault(theme, 0.0)
        before_freq.setdefault(theme, 0)
    before, after = _impacts(before_raw), _impacts(after_raw)
    rank_before, rank_after = _ranks(before), _ranks(after)
    rows = [{
        "theme_id": t, "label": labels.get(t, t),
        "before": {"business_impact": before[t], "rank": rank_before[t], "frequency": before_freq[t]},
        "after": {"business_impact": after[t], "rank": rank_after[t], "frequency": after_freq[t]},
        "impact_change": round(after[t] - before[t], 1), "rank_change": rank_before[t] - rank_after[t],  # positive = moved up
    } for t in sorted(after, key=lambda t: rank_after[t])]
    return {"themes": rows, "top_before": min(rows, key=lambda r: r["before"]["rank"])["label"] if rows else None,
            "top_after": rows[0]["label"] if rows else None}
