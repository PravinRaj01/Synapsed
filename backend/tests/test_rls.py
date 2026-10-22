"""Row-level security against a real Neon database.

Skipped unless DATABASE_URL (app role) and DATABASE_URL_ADMIN (owner role) are set.
Every workspace it creates is deleted at the end.
"""

from uuid import uuid4

import psycopg
import pytest

from app.core import database
from app.core.config import get_settings

settings = get_settings()
pytestmark = pytest.mark.skipif(
    not (settings.database_url and settings.database_url_admin),
    reason="DATABASE_URL and DATABASE_URL_ADMIN are not set",
)


@pytest.fixture
def pool():
    database.init_pool()
    yield database.get_pool()
    database.close_pool()


@pytest.fixture
def workspace(pool):
    """A workspace owned by user A, removed afterwards through the owner role."""
    user_a = uuid4()
    with database.user_tx(user_a) as conn:
        ws = conn.execute(
            "select create_workspace(%s, %s, %s) as id", ("RLS test", "Acme", "SaaS")
        ).fetchone()["id"]
    yield user_a, ws
    with psycopg.connect(settings.database_url_admin) as admin:
        admin.execute("delete from workspaces where id = %s", (ws,))


def visible_workspaces(user, ws):
    with database.user_tx(user) as conn:
        return conn.execute(
            "select count(*) as n from workspaces where id = %s", (ws,)
        ).fetchone()["n"]


def test_owner_sees_own_workspace(workspace):
    user_a, ws = workspace
    assert visible_workspaces(user_a, ws) == 1


def test_other_user_sees_nothing(workspace):
    _, ws = workspace
    assert visible_workspaces(uuid4(), ws) == 0


def test_other_user_cannot_write_into_workspace(workspace):
    _, ws = workspace
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with database.user_tx(uuid4()) as conn:
            conn.execute(
                "insert into campaigns (workspace_id, name) values (%s, 'intruder')", (ws,)
            )


def test_audit_log_records_the_acting_user(workspace):
    user_a, ws = workspace
    with database.user_tx(user_a) as conn:
        campaign = conn.execute(
            "insert into campaigns (workspace_id, name) values (%s, 'C1') returning id", (ws,)
        ).fetchone()["id"]
        conn.execute(
            "insert into resources (campaign_id, title, source_type, content, content_hash) "
            "values (%s, 't', 'transcript', 'hello', %s)", (campaign, uuid4().hex),
        )
        actors = conn.execute(
            "select actor from audit_logs where workspace_id = %s", (ws,)
        ).fetchall()
    assert actors and all(a["actor"] == str(user_a) for a in actors)


def test_no_user_set_means_no_rows(pool):
    with pool.connection() as conn:  # deliberately skips user_tx
        assert conn.execute("select count(*) as n from workspaces").fetchone()["n"] == 0


def test_user_tx_rejects_non_uuid(pool):
    with pytest.raises(ValueError):
        with database.user_tx("x'; drop table workspaces; --"):
            pass
