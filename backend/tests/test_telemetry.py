"""Telemetry writes against a real Neon database. Skipped unless DATABASE_URL and DATABASE_URL_ADMIN are set."""

from uuid import uuid4

import psycopg
import pytest

from ai_pipeline.providers import Completion
from ai_pipeline.telemetry import record_completion
from app.core import database
from app.core.config import get_settings

settings = get_settings()
pytestmark = pytest.mark.skipif(
    not (settings.database_url and settings.database_url_admin),
    reason="DATABASE_URL and DATABASE_URL_ADMIN are not set",
)


@pytest.fixture
def campaign():
    database.init_pool()
    user = uuid4()
    with database.user_tx(user) as conn:
        ws = conn.execute("select create_workspace('Telemetry test', 'Acme', 'SaaS') as id").fetchone()["id"]
        cid = conn.execute("insert into campaigns (workspace_id, name) values (%s, 'C') returning id", (ws,)).fetchone()["id"]
    yield user, cid
    with psycopg.connect(settings.database_url_admin) as admin:
        admin.execute("delete from workspaces where id = %s", (ws,))
    database.close_pool()


def test_records_tokens_latency_and_fallbacks(campaign):
    user, cid = campaign
    done = Completion("{}", "gemini", "flash-lite", prompt_tokens=400, completion_tokens=90, latency_ms=1300,
                      failed_before=["groq-fast: HTTP 429", "sealion: not configured"])
    with database.user_tx(user) as conn:
        record_completion(conn, cid, "extraction", done)
    with database.user_tx(user) as conn:
        row = conn.execute("select * from telemetry_logs where campaign_id = %s", (cid,)).fetchone()
    assert row["model_used"] == "gemini:flash-lite" and row["tokens_processed"] == 490
    assert row["latency_ms"] == 1300 and row["action_type"] == "extraction"
    assert row["fallback_from"] == "groq-fast: HTTP 429, sealion: not configured"


def test_no_fallback_is_stored_as_null(campaign):
    user, cid = campaign
    with database.user_tx(user) as conn:
        record_completion(conn, cid, "triage", Completion("{}", "groq-fast", "m", 10, 5, 800))
    with database.user_tx(user) as conn:
        assert conn.execute("select fallback_from from telemetry_logs").fetchone()["fallback_from"] is None


def test_another_user_cannot_see_the_logs(campaign):
    user, cid = campaign
    with database.user_tx(user) as conn:
        record_completion(conn, cid, "triage", Completion("{}", "groq-fast", "m", 10, 5, 800))
    with database.user_tx(uuid4()) as conn:
        assert conn.execute("select count(*) as n from telemetry_logs").fetchone()["n"] == 0
