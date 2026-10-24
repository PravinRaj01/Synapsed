"""Per-user rate limits for the endpoints that spend shared free-tier quota.

Counters live in the `rate_limits` table (fixed minute and day windows), not in memory, because the
server runs as several instances and each would otherwise count on its own. A request over its limit
gets a 429 with a Retry-After header. Rejected requests do not touch the day counter.
"""

import json
import logging
import random
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException

from app.core.auth import AuthUser, current_user
from app.core.config import Settings, get_settings
from app.core.database import user_tx

logger = logging.getLogger("synapsed.ratelimit")

# bucket: (requests per minute, requests per day)
DEFAULTS: dict[str, tuple[int, int]] = {
    "ingest": (10, 200),     # parsing, scrubbing and possibly Whisper transcription
    "research": (4, 40),     # a web search plus up to 10 page fetches
    "approve": (30, 500),    # spends embedding quota
    "analyze": (3, 60),      # many model calls per run
    "chat": (20, 400),
    "search": (60, 1500),    # one embedding call
    "prd": (4, 60),
    "charts": (15, 300),
    "personas": (3, 30),
    "forecast": (10, 200),
}
CLEANUP_ODDS = 50  # one request in this many removes the user's expired counters
KEEP_DAYS = 3

UPSERT = """
    insert into rate_limits (user_id, bucket, window_kind, window_start, hits)
    values (%s, %s, %s, date_trunc(%s, %s at time zone 'utc'), 1)
    on conflict (user_id, bucket, window_kind, window_start) do update set hits = rate_limits.hits + 1
    returning hits
"""


def limits_for(bucket: str, settings: Settings) -> tuple[int, int]:
    """The (per minute, per day) limits, with any overrides from the RATE_LIMITS setting, e.g. {"chat": [30, 600]}."""
    limits = DEFAULTS[bucket]
    if settings.rate_limits:
        try:
            override = json.loads(settings.rate_limits).get(bucket)
            if isinstance(override, list) and len(override) == 2 and all(isinstance(n, int) and n > 0 for n in override):
                limits = (override[0], override[1])
        except (ValueError, AttributeError):
            logger.warning("RATE_LIMITS is not valid JSON; using the defaults")
    return limits


def seconds_left(kind: str, now: datetime) -> int:
    """Whole seconds until the current minute or UTC day ends (at least 1)."""
    if kind == "minute":
        end = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    else:
        end = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return max(1, int((end - now).total_seconds() + 0.999))


def consume(user_id, bucket: str, per_minute: int, per_day: int, now: datetime | None = None) -> int | None:
    """Count one request. Returns None when allowed, or the seconds to wait when over a limit."""
    now = now or datetime.now(timezone.utc)
    with user_tx(user_id) as conn:
        minute_hits = conn.execute(UPSERT, (user_id, bucket, "minute", "minute", now)).fetchone()["hits"]
        if minute_hits > per_minute:
            return seconds_left("minute", now)
        day_hits = conn.execute(UPSERT, (user_id, bucket, "day", "day", now)).fetchone()["hits"]
        if day_hits > per_day:
            return seconds_left("day", now)
        if random.randrange(CLEANUP_ODDS) == 0:
            conn.execute("delete from rate_limits where window_start < (%s at time zone 'utc') - make_interval(days => %s)", (now, KEEP_DAYS))
    return None


def limited(bucket: str):
    """A FastAPI dependency: the signed-in user, after counting this request against `bucket`."""
    if bucket not in DEFAULTS:
        raise KeyError(f"unknown rate limit bucket '{bucket}'")

    def dependency(user: AuthUser = Depends(current_user)) -> AuthUser:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return user
        per_minute, per_day = limits_for(bucket, settings)
        wait = consume(user.id, bucket, per_minute, per_day)
        if wait is not None:
            raise HTTPException(
                429, f"Too many requests. Try again in {wait} seconds.", headers={"Retry-After": str(wait)}
            )
        return user

    return dependency
