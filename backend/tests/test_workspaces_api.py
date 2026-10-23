"""Workspace, campaign and segment endpoints against a real Neon database.

Skipped unless DATABASE_URL and DATABASE_URL_ADMIN are set. Test workspaces are deleted afterwards.
"""

from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core import database
from app.core.auth import AuthUser, current_user
from app.core.config import get_settings
from app.main import app

settings = get_settings()
pytestmark = pytest.mark.skipif(
    not (settings.database_url and settings.database_url_admin),
    reason="DATABASE_URL and DATABASE_URL_ADMIN are not set",
)


@pytest.fixture
def world():
    """A client that acts as `who.id`; switch `who.id` to act as someone else. Cleans up what it created."""
    who = SimpleNamespace(id=uuid4(), workspaces=[])
    app.dependency_overrides[current_user] = lambda: AuthUser(id=who.id)
    with TestClient(app) as client:  # runs the lifespan, which opens the connection pool
        client.who = who
        yield client
    app.dependency_overrides.clear()
    if who.workspaces:
        with psycopg.connect(settings.database_url_admin) as admin:
            admin.execute("delete from workspaces where id = any(%s)", (who.workspaces,))


def workspace(client, name="Acme workspace"):
    r = client.post("/api/v1/workspaces", json={"name": name, "company": "Acme", "industry": "SaaS"})
    assert r.status_code == 201, r.text
    client.who.workspaces.append(r.json()["id"])
    return r.json()


def campaign(client, ws, **extra):
    r = client.post("/api/v1/campaigns", json={"workspace_id": ws["id"], "name": "Q4 research", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_and_list_workspaces(world):
    ws = workspace(world)
    assert ws["role"] == "owner" and ws["campaigns"] == 0
    listed = world.get("/api/v1/workspaces").json()
    assert [w["id"] for w in listed] == [ws["id"]] and listed[0]["company"] == "Acme" and listed[0]["role"] == "owner"


def test_workspace_needs_all_fields(world):
    assert world.post("/api/v1/workspaces", json={"name": "x", "company": "", "industry": "SaaS"}).status_code == 422
    assert world.post("/api/v1/workspaces", json={"name": "x"}).status_code == 422


def test_campaign_with_starting_segments_and_counts(world):
    ws = workspace(world)
    c = campaign(world, ws, goal="Why do enterprise users churn?", segments=[
        {"name": "Enterprise", "tier": "enterprise", "weight": 3}, {"name": "  Free   tier ", "tier": "free", "weight": 0.5}])
    assert c["goal"].startswith("Why") and (c["resources"], c["staged"], c["insights"], c["themes"]) == (0, 0, 0, 0)
    assert sorted((s["name"], s["tier"], float(s["weight"])) for s in c["segments"]) == [
        ("Enterprise", "enterprise", 3.0), ("Free tier", "free", 0.5)]
    fetched = world.get(f"/api/v1/campaigns/{c['id']}").json()
    assert len(fetched["segments"]) == 2 and fetched["name"] == "Q4 research"
    assert world.get("/api/v1/campaigns", params={"workspace_id": ws["id"]}).json()[0]["id"] == c["id"]
    assert world.get("/api/v1/workspaces").json()[0]["campaigns"] == 1


def test_duplicate_starting_segments_are_rejected_before_anything_is_created(world):
    ws = workspace(world)
    r = world.post("/api/v1/campaigns", json={"workspace_id": ws["id"], "name": "C", "segments": [
        {"name": "Enterprise"}, {"name": "enterprise"}]})
    assert r.status_code == 422
    assert world.get("/api/v1/campaigns").json() == []


def test_campaign_counts_follow_the_data(world):
    ws = workspace(world)
    c = campaign(world, ws)
    with database.user_tx(world.who.id) as conn:
        conn.execute(
            "insert into resources (campaign_id, title, source_type, content, content_hash, status) "
            "values (%s, 't', 'transcript', 'x', 'h1', 'staged'), (%s, 't2', 'transcript', 'y', 'h2', 'approved')",
            (c["id"], c["id"]),
        )
    got = world.get(f"/api/v1/campaigns/{c['id']}").json()
    assert (got["resources"], got["staged"]) == (2, 1)


def test_update_campaign(world):
    c = campaign(world, workspace(world))
    r = world.patch(f"/api/v1/campaigns/{c['id']}", json={"name": "Renamed", "goal": None})
    assert r.status_code == 200 and r.json()["name"] == "Renamed" and r.json()["goal"] is None
    assert world.patch(f"/api/v1/campaigns/{c['id']}", json={"goal": "New goal"}).json()["name"] == "Renamed"
    assert world.patch(f"/api/v1/campaigns/{c['id']}", json={}).status_code == 422
    assert world.patch(f"/api/v1/campaigns/{c['id']}", json={"name": None}).status_code == 422


def test_segment_crud(world):
    c = campaign(world, workspace(world))
    cid = c["id"]
    made = world.post(f"/api/v1/campaigns/{cid}/segments", json={"name": "Mid market", "tier": "mid_market", "weight": 1.56})
    assert made.status_code == 201 and float(made.json()["weight"]) == 1.6  # stored with one decimal
    sid = made.json()["id"]
    assert world.post(f"/api/v1/campaigns/{cid}/segments", json={"name": "MID MARKET"}).status_code == 409

    patched = world.patch(f"/api/v1/segments/{sid}", json={"weight": 2, "description": "50-500 seats"})
    assert patched.status_code == 200 and float(patched.json()["weight"]) == 2.0 and patched.json()["name"] == "Mid market"
    other = world.post(f"/api/v1/campaigns/{cid}/segments", json={"name": "Free", "tier": "free"}).json()
    assert world.patch(f"/api/v1/segments/{other['id']}", json={"name": "mid market"}).status_code == 409
    assert world.patch(f"/api/v1/segments/{other['id']}", json={"name": "Free"}).status_code == 200  # renaming to itself is fine

    listed = world.get(f"/api/v1/campaigns/{cid}/segments").json()
    assert [s["name"] for s in listed] == ["Free", "Mid market"] and listed[0]["resources"] == 0

    assert world.delete(f"/api/v1/segments/{sid}").status_code == 204
    assert world.delete(f"/api/v1/segments/{sid}").status_code == 404
    assert [s["name"] for s in world.get(f"/api/v1/campaigns/{cid}/segments").json()] == ["Free"]


@pytest.mark.parametrize("body", [
    {"name": "x", "weight": 0}, {"name": "x", "weight": -1}, {"name": "x", "weight": 21},
    {"name": "x", "weight": 0.04}, {"name": "x", "tier": "vip"}, {"name": "   "}, {"name": ""},
])
def test_bad_segments_are_rejected(world, body):
    c = campaign(world, workspace(world))
    assert world.post(f"/api/v1/campaigns/{c['id']}/segments", json=body).status_code == 422


@pytest.mark.parametrize("body", [{"weight": 0}, {"tier": "vip"}, {"name": None}, {"weight": None}, {}])
def test_bad_segment_changes_are_rejected(world, body):
    c = campaign(world, workspace(world, "bad changes"))
    sid = world.post(f"/api/v1/campaigns/{c['id']}/segments", json={"name": "Keep"}).json()["id"]
    assert world.patch(f"/api/v1/segments/{sid}", json=body).status_code == 422


def test_deleting_a_segment_keeps_its_insights_and_resources(world):
    c = campaign(world, workspace(world))
    sid = world.post(f"/api/v1/campaigns/{c['id']}/segments", json={"name": "Enterprise", "weight": 3}).json()["id"]
    with database.user_tx(world.who.id) as conn:
        rid = conn.execute(
            "insert into resources (campaign_id, title, source_type, content, content_hash, segment_id) "
            "values (%s, 't', 'transcript', 'x', 'h', %s) returning id", (c["id"], sid)).fetchone()["id"]
    assert world.get(f"/api/v1/campaigns/{c['id']}/segments").json()[0]["resources"] == 1
    assert world.delete(f"/api/v1/segments/{sid}").status_code == 204
    with database.user_tx(world.who.id) as conn:
        assert conn.execute("select segment_id from resources where id = %s", (rid,)).fetchone()["segment_id"] is None


def test_segment_limit(world):
    c = campaign(world, workspace(world), segments=[{"name": f"S{i}"} for i in range(20)])
    assert world.post(f"/api/v1/campaigns/{c['id']}/segments", json={"name": "One too many"}).status_code == 409


def test_users_cannot_see_or_touch_each_others_data(world):
    ws = workspace(world)
    c = campaign(world, ws, segments=[{"name": "Enterprise"}])
    sid = c["segments"][0]["id"]

    world.who.id = uuid4()  # someone else
    assert world.get("/api/v1/workspaces").json() == []
    assert world.get("/api/v1/campaigns").json() == []
    assert world.get(f"/api/v1/campaigns/{c['id']}").status_code == 404
    assert world.patch(f"/api/v1/campaigns/{c['id']}", json={"name": "Hijacked"}).status_code == 404
    assert world.get(f"/api/v1/campaigns/{c['id']}/segments").status_code == 404
    assert world.post(f"/api/v1/campaigns/{c['id']}/segments", json={"name": "Spy"}).status_code == 404
    assert world.patch(f"/api/v1/segments/{sid}", json={"weight": 9}).status_code == 404
    assert world.delete(f"/api/v1/segments/{sid}").status_code == 404
    assert world.post("/api/v1/campaigns", json={"workspace_id": ws["id"], "name": "Intruder"}).status_code == 404


# ---------------------------------------------------------------- deletion

from app.api import workspaces as ws_api  # noqa: E402


@pytest.fixture
def stored_files(monkeypatch):
    removed = []
    monkeypatch.setattr(ws_api.storage, "delete_object", lambda key: removed.append(key))
    return removed


def add_member(workspace_id, user_id, role):
    with psycopg.connect(settings.database_url_admin) as admin:
        admin.execute("insert into workspace_members (workspace_id, user_id, role) values (%s, %s, %s)", (workspace_id, user_id, role))


def fill(world, campaign_id):
    """Resources (two sharing one stored file), an insight, a theme and a roadmap item."""
    with database.user_tx(world.who.id) as conn:
        for n, path in enumerate(("c/a/one.txt", "c/a/one.txt", "c/b/two.txt", None)):
            conn.execute(
                "insert into resources (campaign_id, title, source_type, content, content_hash, storage_path) "
                "values (%s, %s, 'transcript', 'x', %s, %s)", (campaign_id, f"r{n}", f"h{n}", path))
        theme = conn.execute("insert into themes (campaign_id, label, color_code) values (%s, 'T', '#000') returning id", (campaign_id,)).fetchone()["id"]
        conn.execute("insert into insights (campaign_id, theme_id, summary_text) values (%s, %s, 'pain')", (campaign_id, theme))
        conn.execute("insert into roadmap_items (campaign_id, theme_id, title, description, horizon, impact_score, confidence_score, ease_score) "
                     "values (%s, %s, 'item', 'd', 'now', 5, 5, 5)", (campaign_id, theme))


def counts(world, campaign_id):
    with database.user_tx(world.who.id) as conn:
        return {t: conn.execute(f"select count(*) as n from {t} where campaign_id = %s", (campaign_id,)).fetchone()["n"]
                for t in ("resources", "insights", "themes", "roadmap_items")}


def test_deleting_a_campaign_removes_everything_in_it_and_its_files_once(world, stored_files):
    ws = workspace(world)
    doomed, kept = campaign(world, ws, segments=[{"name": "Enterprise"}]), campaign(world, ws)
    fill(world, doomed["id"]), fill(world, kept["id"])
    assert counts(world, doomed["id"]) == {"resources": 4, "insights": 1, "themes": 1, "roadmap_items": 1}

    assert world.delete(f"/api/v1/campaigns/{doomed['id']}").status_code == 204
    assert sorted(stored_files) == ["c/a/one.txt", "c/b/two.txt"]  # each file once, rows without a file skipped
    assert counts(world, doomed["id"]) == {"resources": 0, "insights": 0, "themes": 0, "roadmap_items": 0}
    assert counts(world, kept["id"])["resources"] == 4  # the other campaign is untouched
    assert world.get(f"/api/v1/campaigns/{doomed['id']}").status_code == 404
    assert world.delete(f"/api/v1/campaigns/{doomed['id']}").status_code == 404
    assert [c["id"] for c in world.get("/api/v1/campaigns").json()] == [kept["id"]]


def test_a_storage_failure_does_not_undo_the_delete(world, monkeypatch):
    c = campaign(world, workspace(world))
    fill(world, c["id"])

    def broken(key):
        raise RuntimeError("storage down")

    monkeypatch.setattr(ws_api.storage, "delete_object", broken)
    assert world.delete(f"/api/v1/campaigns/{c['id']}").status_code == 204
    assert world.get(f"/api/v1/campaigns/{c['id']}").status_code == 404


def test_only_owners_and_pms_may_delete_a_campaign(world, stored_files):
    ws = workspace(world)
    c = campaign(world, ws)
    owner = world.who.id
    viewer, pm, stranger = uuid4(), uuid4(), uuid4()
    add_member(ws["id"], viewer, "viewer")
    add_member(ws["id"], pm, "pm")

    world.who.id = viewer
    assert world.delete(f"/api/v1/campaigns/{c['id']}").status_code == 403
    world.who.id = stranger
    assert world.delete(f"/api/v1/campaigns/{c['id']}").status_code == 404
    world.who.id = owner
    assert world.get(f"/api/v1/campaigns/{c['id']}").status_code == 200 and stored_files == []
    world.who.id = pm
    assert world.delete(f"/api/v1/campaigns/{c['id']}").status_code == 204


def test_deleting_a_workspace_removes_its_campaigns_and_files_and_needs_the_owner(world, stored_files):
    ws = workspace(world)
    first, second = campaign(world, ws), campaign(world, ws)
    fill(world, first["id"]), fill(world, second["id"])
    owner, pm = world.who.id, uuid4()
    add_member(ws["id"], pm, "pm")

    world.who.id = pm
    assert world.delete(f"/api/v1/workspaces/{ws['id']}").status_code == 403
    world.who.id = uuid4()
    assert world.delete(f"/api/v1/workspaces/{ws['id']}").status_code == 404
    world.who.id = owner
    assert world.get(f"/api/v1/campaigns/{first['id']}").status_code == 200 and stored_files == []

    assert world.delete(f"/api/v1/workspaces/{ws['id']}").status_code == 204
    assert sorted(set(stored_files)) == ["c/a/one.txt", "c/b/two.txt"]
    assert world.get("/api/v1/workspaces").json() == [] and world.get("/api/v1/campaigns").json() == []
    assert world.delete(f"/api/v1/workspaces/{ws['id']}").status_code == 404
