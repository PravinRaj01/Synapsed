"""Per-user rate limits: the settings and arithmetic need no database; the counters run on Neon.
Skipped (database parts) unless DATABASE_URL and DATABASE_URL_ADMIN are set."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api import chat as chat_api
from app.core import database, rate_limit as rl
from app.core.auth import AuthUser, current_user
from app.core.config import Settings, get_settings
from app.main import app

settings = get_settings()
needs_db = pytest.mark.skipif(
    not (settings.database_url and settings.database_url_admin),
    reason="DATABASE_URL and DATABASE_URL_ADMIN are not set",
)

T0 = datetime(2026, 10, 24, 14, 30, 10, 500000, tzinfo=timezone.utc)


# ---------------------------------------------------------------- settings and arithmetic (pure)

def test_defaults_cover_every_expensive_bucket_and_are_positive():
    assert {"ingest", "research", "approve", "analyze", "chat", "prd"} <= set(rl.DEFAULTS)
    assert all(m > 0 and d >= m for m, d in rl.DEFAULTS.values())


def test_limits_can_be_overridden_per_bucket_and_bad_overrides_are_ignored():
    assert rl.limits_for("chat", Settings()) == rl.DEFAULTS["chat"]
    assert rl.limits_for("chat", Settings(rate_limits='{"chat": [30, 600]}')) == (30, 600)
    assert rl.limits_for("prd", Settings(rate_limits='{"chat": [30, 600]}')) == rl.DEFAULTS["prd"]
    for bad in ('{"chat": [0, 5]}', '{"chat": [1]}', '{"chat": "many"}', '{"chat": [1.5, 2]}', "not json", "[1, 2]"):
        assert rl.limits_for("chat", Settings(rate_limits=bad)) == rl.DEFAULTS["chat"], bad


def test_seconds_until_a_window_ends():
    assert rl.seconds_left("minute", T0) == 50  # 49.5 s left, rounded up
    assert rl.seconds_left("day", T0) == 9 * 3600 + 29 * 60 + 50
    assert rl.seconds_left("minute", T0.replace(second=59, microsecond=999999)) == 1  # never 0


def test_an_unknown_bucket_is_a_programming_error():
    with pytest.raises(KeyError):
        rl.limited("nope")


# ---------------------------------------------------------------- counters (database)

@pytest.fixture
def user():
    uid = uuid4()
    yield uid
    with psycopg.connect(settings.database_url_admin) as admin:
        admin.execute("delete from rate_limits where user_id = %s", (uid,))


def rows(uid):
    with database.user_tx(uid) as conn:
        return conn.execute("select bucket, window_kind, window_start, hits from rate_limits where user_id = %s order by 1, 2, 3", (uid,)).fetchall()


@pytest.fixture(autouse=True)
def pool():
    if settings.database_url and settings.database_url_admin:
        database.init_pool()
        yield
        database.close_pool()
    else:
        yield


@needs_db
def test_requests_up_to_the_limit_pass_and_the_next_waits_for_the_minute_to_end(user):
    assert [rl.consume(user, "chat", 3, 100, T0) for _ in range(3)] == [None, None, None]
    assert rl.consume(user, "chat", 3, 100, T0) == 50
    assert rl.consume(user, "chat", 3, 100, T0 + timedelta(seconds=45)) == 5  # still inside the same minute window
    assert rl.consume(user, "chat", 3, 100, T0 + timedelta(seconds=50)) is None  # the next minute starts fresh


@needs_db
def test_the_daily_limit_blocks_until_utc_midnight(user):
    for minute in range(4):
        assert rl.consume(user, "chat", 10, 4, T0 + timedelta(minutes=minute)) is None
    wait = rl.consume(user, "chat", 10, 4, T0 + timedelta(minutes=5))
    assert wait == rl.seconds_left("day", T0 + timedelta(minutes=5))
    tomorrow = T0.replace(hour=0, minute=0, second=1) + timedelta(days=1)
    assert rl.consume(user, "chat", 10, 4, tomorrow) is None


@needs_db
def test_a_rejected_request_does_not_use_up_the_daily_allowance(user):
    for _ in range(2):
        rl.consume(user, "chat", 2, 100, T0)
    assert rl.consume(user, "chat", 2, 100, T0) is not None
    assert rl.consume(user, "chat", 2, 100, T0) is not None
    day = next(r for r in rows(user) if r["window_kind"] == "day")
    minute = next(r for r in rows(user) if r["window_kind"] == "minute")
    assert day["hits"] == 2 and minute["hits"] == 4


@needs_db
def test_users_and_buckets_are_counted_separately(user):
    other = uuid4()
    try:
        assert [rl.consume(user, "chat", 1, 10, T0), rl.consume(user, "prd", 1, 10, T0), rl.consume(other, "chat", 1, 10, T0)] == [None] * 3
        assert rl.consume(user, "chat", 1, 10, T0) is not None
    finally:
        with psycopg.connect(settings.database_url_admin) as admin:
            admin.execute("delete from rate_limits where user_id = %s", (other,))


@needs_db
def test_a_user_cannot_see_or_change_another_users_counters(user):
    rl.consume(user, "chat", 5, 50, T0)
    stranger = uuid4()
    assert rows(stranger) == []
    with database.user_tx(stranger) as conn:
        assert conn.execute("update rate_limits set hits = 0 where user_id = %s returning hits", (user,)).fetchall() == []
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("insert into rate_limits (user_id, bucket, window_kind, window_start, hits) "
                         "values (%s, 'chat', 'minute', now(), 1)", (user,))


@needs_db
def test_old_counters_are_cleaned_up_now_and_then(user, monkeypatch):
    long_ago = T0 - timedelta(days=10)
    rl.consume(user, "chat", 5, 50, long_ago)
    assert any(r["window_start"].year == 2026 and r["window_start"].day == 14 for r in rows(user))
    monkeypatch.setattr(rl.random, "randrange", lambda n: 0)
    rl.consume(user, "chat", 5, 50, T0)
    assert all(r["window_start"].day == 24 for r in rows(user))


# ---------------------------------------------------------------- through the API

@pytest.fixture
def api_user(monkeypatch):
    who = SimpleNamespace(id=uuid4())
    app.dependency_overrides[current_user] = lambda: AuthUser(id=who.id)
    monkeypatch.setattr(chat_api, "embed_query", lambda text: [1.0] + [0.0] * 767)
    yield who
    app.dependency_overrides.clear()
    with psycopg.connect(settings.database_url_admin) as admin:
        admin.execute("delete from rate_limits where user_id = %s", (who.id,))
        for ws in getattr(who, "workspaces", []):
            admin.execute("delete from workspaces where id = %s", (ws,))


@needs_db
def test_over_the_limit_the_api_answers_429_with_retry_after(api_user, monkeypatch):
    real = get_settings()
    monkeypatch.setattr(rl, "get_settings", lambda: real.model_copy(update={"rate_limit_enabled": True, "rate_limits": '{"search": [2, 100]}'}))
    with TestClient(app) as client:
        with database.user_tx(api_user.id) as conn:
            ws = conn.execute("select create_workspace('Limit test', 'Acme', 'SaaS') as id").fetchone()["id"]
            cid = conn.execute("insert into campaigns (workspace_id, name) values (%s, 'C') returning id", (ws,)).fetchone()["id"]
        api_user.workspaces = [ws]
        params = {"campaign_id": str(cid), "q": "login"}
        assert [client.get("/api/v1/search", params=params).status_code for _ in range(2)] == [200, 200]
        blocked = client.get("/api/v1/search", params=params)
        assert blocked.status_code == 429 and "Too many requests" in blocked.json()["detail"]
        assert 1 <= int(blocked.headers["retry-after"]) <= 60
        monkeypatch.setattr(rl, "get_settings", lambda: real.model_copy(update={"rate_limit_enabled": False}))
        assert client.get("/api/v1/search", params=params).status_code == 200  # switched off: no counting, no blocking


@needs_db
def test_limits_apply_to_the_expensive_endpoints_and_not_to_cheap_reads(api_user, monkeypatch):
    real = get_settings()
    monkeypatch.setattr(rl, "get_settings", lambda: real.model_copy(update={"rate_limit_enabled": True, "rate_limits": '{"research": [1, 10]}'}))
    monkeypatch.setattr("app.api.ingestion.web.search_web", lambda q, n: [])
    with TestClient(app) as client:
        with database.user_tx(api_user.id) as conn:
            ws = conn.execute("select create_workspace('Limit test 2', 'Acme', 'SaaS') as id").fetchone()["id"]
            cid = conn.execute("insert into campaigns (workspace_id, name) values (%s, 'C') returning id", (ws,)).fetchone()["id"]
        api_user.workspaces = [ws]
        body = {"campaign_id": str(cid), "query": "customer churn"}
        assert client.post("/api/v1/research", json=body).status_code == 200
        assert client.post("/api/v1/research", json=body).status_code == 429
        for _ in range(5):  # listing is not limited
            assert client.get("/api/v1/workspaces").status_code == 200
